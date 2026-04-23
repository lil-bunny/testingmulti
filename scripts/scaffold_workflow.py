"""
Scaffold a new workflow template entry with sane defaults.

Usage:
    python3 scripts/scaffold_workflow.py --workflow load_tendering_request --operation load_tendering
"""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_CONFIG_PATH = ROOT / "app" / "configs" / "workflow_configs.py"
TENANT_CONFIG_PATH = ROOT / "app" / "configs" / "tenant_configs.py"
CONTRACTS_PATH = ROOT / "app" / "configs" / "workflow_template_contracts.py"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", required=True, help="Workflow name (snake_case).")
    parser.add_argument("--operation", required=True, help="Business operation group.")
    args = parser.parse_args()

    workflow_name = args.workflow.strip()
    operation = args.operation.strip()

    print("Scaffold guidance (manual patch):")
    print(f"1) Add workflow '{workflow_name}' in {WORKFLOW_CONFIG_PATH}")
    print(
        "   Base graph template:",
        json.dumps(
            {
                workflow_name: {
                    "entry": "start",
                    "exit": "end",
                    "nodes": ["start", "end"],
                    "edges": [["start", "end"]],
                    "routers": {},
                }
            },
            indent=2,
        ),
    )
    print(f"2) Add contract in {CONTRACTS_PATH}")
    print(
        "   Contract template:",
        json.dumps(
            {
                workflow_name: {
                    "workflow_name": workflow_name,
                    "operation": operation,
                    "version": "1.0.0",
                    "required_state_keys": [],
                    "event_types": [],
                }
            },
            indent=2,
        ),
    )
    print(
        f"3) Add per-tenant overlay in {TENANT_CONFIG_PATH} for existing tenants "
        f"with empty replace/add_edges/remove_edges/disable_nodes"
    )
    print("4) Implement required node handlers and register them in NODE_REGISTRY.")


if __name__ == "__main__":
    main()
