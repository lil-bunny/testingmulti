import copy
from app.workflows.contracts import GraphDefinition, TenantWorkflowOverlay
from app.workflows.validators import validate_overlay_targets_exist


def compile_graph(base_graph: dict, tenant_config: dict):
    base = GraphDefinition.model_validate(base_graph)
    overlay = TenantWorkflowOverlay.model_validate(tenant_config)
    validate_overlay_targets_exist(base, overlay)

    graph = copy.deepcopy(base.model_dump())

    replace = overlay.replace
    disable_nodes = set(overlay.disable_nodes)

    def replaced(node_name: str) -> str:
        return replace.get(node_name, node_name)

    graph["nodes"] = [replaced(n) for n in graph["nodes"] if n not in disable_nodes]

    graph["entry"] = replaced(graph["entry"])
    graph["exit"] = replaced(graph["exit"])

    graph["edges"] = [
        [replaced(src), replaced(dst)]
        for src, dst in graph["edges"]
        if src not in disable_nodes and dst not in disable_nodes
    ]

    graph["edges"].extend(overlay.add_edges)

    remove_edges = overlay.remove_edges
    graph["edges"] = [
        e for e in graph["edges"] if e not in remove_edges
    ]

    compiled_routers = {}
    for node_name, router_def in graph.get("routers", {}).items():
        if node_name in disable_nodes:
            continue
        new_node_name = replaced(node_name)
        compiled_routers[new_node_name] = {
            **router_def,
            "map": {
                route_key: replaced(target)
                for route_key, target in router_def.get("map", {}).items()
                if target not in disable_nodes
            },
        }
    graph["routers"] = compiled_routers

    compiled = GraphDefinition.model_validate(graph)
    return compiled.model_dump()