from langgraph.graph import StateGraph
from app.workflows.registry import NODE_REGISTRY
from app.domain.state import WorkflowState
from app.workflows.contracts import GraphDefinition
from app.workflows.checkpoint import get_checkpointer


def build_graph(graph_def: dict, router_registry: dict):
    graph_def = GraphDefinition.model_validate(graph_def).model_dump()
    graph = StateGraph(WorkflowState)

    for node in graph_def["nodes"]:
        if node not in NODE_REGISTRY:
            raise Exception(f"Node not registered: {node}")

    for node in graph_def["nodes"]:
        graph.add_node(node, NODE_REGISTRY[node])

    for src, dst in graph_def["edges"]:
        graph.add_edge(src, dst)

    for node, router_def in graph_def.get("routers", {}).items():
        if router_def["router"] not in router_registry:
            raise Exception(f"Router not registered: {router_def['router']}")
        router_fn = router_registry[router_def["router"]]

        graph.add_conditional_edges(
            node,
            router_fn,
            router_def["map"]
        )

    graph.set_entry_point(graph_def["entry"])
    graph.set_finish_point(graph_def["exit"])

    return graph.compile(checkpointer=get_checkpointer())