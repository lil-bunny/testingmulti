from pydantic import BaseModel, Field
from typing import Dict, Any


class WorkflowState(BaseModel):
    tenant_id: str
    execution_id: str

    data: Dict[str, Any] = Field(default_factory=dict)