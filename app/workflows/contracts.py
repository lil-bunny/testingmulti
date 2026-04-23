from typing import Dict, List

from pydantic import BaseModel, Field, model_validator


class RouterDefinition(BaseModel):
    router: str
    map: Dict[str, str] = Field(default_factory=dict)


class GraphDefinition(BaseModel):
    entry: str
    exit: str
    nodes: List[str] = Field(default_factory=list)
    edges: List[List[str]] = Field(default_factory=list)
    routers: Dict[str, RouterDefinition] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self):
        node_set = set(self.nodes)
        if self.entry not in node_set:
            raise ValueError(f"Entry node '{self.entry}' must be in nodes list")
        if self.exit not in node_set:
            raise ValueError(f"Exit node '{self.exit}' must be in nodes list")

        for edge in self.edges:
            if len(edge) != 2:
                raise ValueError(f"Each edge must contain [src, dst], got: {edge}")
            src, dst = edge
            if src not in node_set or dst not in node_set:
                raise ValueError(f"Edge references unknown nodes: {edge}")

        for router_node, router in self.routers.items():
            if router_node not in node_set:
                raise ValueError(f"Router source node not in nodes: {router_node}")
            for _route_key, target in router.map.items():
                if target not in node_set:
                    raise ValueError(f"Router target '{target}' not in nodes")
        return self


class TenantWorkflowOverlay(BaseModel):
    replace: Dict[str, str] = Field(default_factory=dict)
    add_edges: List[List[str]] = Field(default_factory=list)
    remove_edges: List[List[str]] = Field(default_factory=list)
    disable_nodes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_overlay(self):
        for edge in self.add_edges + self.remove_edges:
            if len(edge) != 2:
                raise ValueError(f"Overlay edge must be [src, dst], got {edge}")
        return self


class WorkflowTemplateContract(BaseModel):
    workflow_name: str
    operation: str
    version: str
    description: str
    event_types: List[str] = Field(default_factory=list)
    required_state_keys: List[str] = Field(default_factory=list)
    optional_state_keys: List[str] = Field(default_factory=list)
