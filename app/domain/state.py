from pydantic import BaseModel, Field
from typing import Dict, Any


class WorkflowState(BaseModel):
    tenant_id: str       # tenants.id (UUID)
    tenant_slug: str     # tenants.slug / TENANT_CONFIGS key
    execution_id: str

    data: Dict[str, Any] = Field(default_factory=dict)