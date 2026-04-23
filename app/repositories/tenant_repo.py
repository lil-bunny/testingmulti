from copy import deepcopy

from app.configs.tenant_configs import TENANT_CONFIGS
from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.workflows.validators import validate_tenant_overlay


class TenantRepository:
    def get_config(self, tenant_id: str) -> dict:
        raw_config = deepcopy(TENANT_CONFIGS.get(tenant_id, {}))
        validated = {}
        for workflow_name, overlay in raw_config.items():
            if workflow_name not in WORKFLOW_CONFIGS:
                raise Exception(
                    f"Tenant '{tenant_id}' contains unknown workflow override: {workflow_name}"
                )
            validated[workflow_name] = validate_tenant_overlay(overlay).model_dump()
        return validated
