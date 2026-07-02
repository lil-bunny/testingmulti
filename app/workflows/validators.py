from app.workflows.contracts import GraphDefinition, TenantWorkflowOverlay


def validate_graph_definition(graph_def: dict) -> GraphDefinition:
    return GraphDefinition.model_validate(graph_def)


def validate_router_static_edge_conflict(graph_def: dict) -> None:
    """Reject static edges from nodes that already have a conditional router."""
    routers = graph_def.get("routers") or {}
    for src, dst in graph_def.get("edges") or []:
        if src in routers:
            raise ValueError(
                f"Node {src!r} has a router and a static edge to {dst!r}; "
                "use the router map only"
            )


def validate_tenant_overlay(overlay: dict) -> TenantWorkflowOverlay:
    return TenantWorkflowOverlay.model_validate(overlay)


def validate_overlay_targets_exist(graph_def: GraphDefinition, overlay: TenantWorkflowOverlay):
    node_set = set(graph_def.nodes)

    for node in overlay.disable_nodes:
        if node not in node_set:
            raise ValueError(f"disable_nodes references unknown node: {node}")

    for src, dst in overlay.add_edges + overlay.remove_edges:
        if src not in node_set and src not in overlay.replace.values():
            raise ValueError(f"Overlay edge source unknown: {src}")
        if dst not in node_set and dst not in overlay.replace.values():
            raise ValueError(f"Overlay edge destination unknown: {dst}")

    for src, dst in overlay.replace.items():
        if src not in node_set:
            raise ValueError(f"Overlay replace source unknown: {src}")
        if dst not in node_set and dst not in overlay.replace.values():
            # Allows chain replacement values for tenant-specific aliases.
            continue
