from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.configs.workflow_template_contracts import WORKFLOW_TEMPLATE_CONTRACTS
from copy import deepcopy
from app.workflows.validators import validate_graph_definition


class WorkflowRepository:

    def get(self, workflow_name: str):
        graph = WORKFLOW_CONFIGS.get(workflow_name)

        if not graph:
            raise Exception(f"Workflow not found: {workflow_name}")

        if workflow_name not in WORKFLOW_TEMPLATE_CONTRACTS:
            raise Exception(f"Workflow template contract missing: {workflow_name}")

        validated_graph = validate_graph_definition(graph)
        return deepcopy(validated_graph.model_dump())