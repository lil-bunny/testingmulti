from functools import wraps

from langgraph.graph import StateGraph
from app.domain.error_catalog import has_workflow_error
from app.workflows.registry import NODE_REGISTRY
from app.domain.state import WorkflowState
from app.workflows.contracts import GraphDefinition
from app.workflows.checkpoint import get_checkpointer

ERROR_NODE = "record_workflow_failure"
ERROR_ROUTE = "__error__"
OK_ROUTE = "__ok__"


def check_workflow_error(state: WorkflowState) -> str:
    return ERROR_ROUTE if has_workflow_error(state.data) else OK_ROUTE


def _wrap_router(router_fn):
    @wraps(router_fn)
    def router_with_error_check(state: WorkflowState):
        if has_workflow_error(state.data):
            return ERROR_ROUTE
        return router_fn(state)

    return router_with_error_check


def build_graph(graph_def: dict, router_registry: dict):
    graph_def = GraphDefinition.model_validate(graph_def).model_dump()
    graph = StateGraph(WorkflowState)

    for node in graph_def["nodes"]:
        if node not in NODE_REGISTRY:
            raise Exception(f"Node not registered: {node}")

    for node in graph_def["nodes"]:
        graph.add_node(node, NODE_REGISTRY[node])

    if ERROR_NODE not in graph_def["nodes"]:
        if ERROR_NODE not in NODE_REGISTRY:
            raise Exception(f"Node not registered: {ERROR_NODE}")
        graph.add_node(ERROR_NODE, NODE_REGISTRY[ERROR_NODE])

    for src, dst in graph_def["edges"]:
        graph.add_conditional_edges(
            src,
            check_workflow_error,
            {ERROR_ROUTE: ERROR_NODE, OK_ROUTE: dst},
        )

    for node, router_def in graph_def.get("routers", {}).items():
        if router_def["router"] not in router_registry:
            raise Exception(f"Router not registered: {router_def['router']}")
        router_fn = router_registry[router_def["router"]]

        route_map = {**router_def["map"], ERROR_ROUTE: ERROR_NODE}
        graph.add_conditional_edges(
            node,
            _wrap_router(router_fn),
            route_map,
        )

    graph.add_edge(ERROR_NODE, graph_def["exit"])
    graph.set_entry_point(graph_def["entry"])
    graph.set_finish_point(graph_def["exit"])

    return graph.compile(checkpointer=get_checkpointer())