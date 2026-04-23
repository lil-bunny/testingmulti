from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import WorkflowService


def get_workflow_service() -> WorkflowService:
    return WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
