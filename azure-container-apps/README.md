# Azure Container Apps Deployment

This folder contains helper scripts and configuration artifacts for deploying the RAI Assessment Copilot to Azure Container Apps.

## Prerequisites

- Azure CLI 2.58.0 or later (`az version`)
- Logged in to the correct subscription (`az login`)
- Resource providers registered once per subscription:
  ```bash
  az provider register --namespace Microsoft.App
  az provider register --namespace Microsoft.OperationalInsights
  ```
- Container Apps extension installed:
  ```bash
  az extension add --name containerapp --upgrade
  ```

## `1-setup_app-raiassessment.sh`

This script provisions (or reuses) the core infrastructure required to run the container app:

- Resource group
- Log Analytics workspace
- Container Apps environment
- Container App instance
- Managed identity role assignments (ACR pull, Azure OpenAI, Key Vault, Storage)

The script is **idempotent**. Before creating any resource it checks whether an instance already exists and reuses it when found. This includes reusing an existing Log Analytics workspace so deployment runs do not proliferate workspaces.

### Key configuration variables

| Variable | Description |
| --- | --- |
| `CONTAINER_APP_NAME` | Name of the Container App resource. |
| `RESOURCE_GROUP` | Resource group for the Container App and environment. |
| `LOCATION` | Azure region where resources are deployed. |
| `AZURE_OPENAI_RESOURCE` / `AZURE_OPENAI_RESOURCE_GROUP` | Existing Azure OpenAI resource and its resource group. |
| `DOCKER_REGISTRY` / `DOCKER_IMAGE` | Azure Container Registry login server and image tag to deploy. |
| `STORAGE_ACCOUNT_NAME` / `STORAGE_RESOURCE_GROUP` | Storage account used for logs and artifacts. |
| `KEYVAULT_NAME` / `KEYVAULT_RESOURCE_GROUP` | Key Vault that stores application secrets. Defaults to the OpenAI resource group. |
| `LOG_ANALYTICS_WORKSPACE_NAME` / `LOG_ANALYTICS_RESOURCE_GROUP` | (Optional) Override the Log Analytics workspace to reuse. Defaults to `<CONTAINER_APP_NAME>-logs` in the app resource group. |
| `TARGET_PORT` | Container port exposed via ingress. |

Adjust these variables at the top of the script before executing it.

### Running the script

```bash
cd azure-container-apps
chmod +x 1-setup_app-raiassessment.sh
./1-setup_app-raiassessment.sh
```

The script enables strict bash options (`set -euo pipefail`) so it halts on the first error. It also validates that the Azure CLI is available before running.

### Idempotent behaviour details

- **Resource group**: Uses `az group exists` to skip creation if the group already exists.
- **Log Analytics**: If `LOG_ANALYTICS_WORKSPACE_NAME` exists, its customer ID (GUID) and shared key are reused during Container Apps environment creation; otherwise a workspace is created once and cached for future runs.
- **Container Apps environment**: `az containerapp env show` is used to detect existing environments and avoid recreation.
- **Container App**: If the app exists, `az containerapp update` runs with the latest image and a fresh timestamp env var so each execution triggers a new revision; otherwise it is created once.
- **Role assignments**: Each role assignment is checked with `az role assignment list` before being created, preventing duplicate assignments.
- **Key Vault policies**: If the vault has RBAC enabled (`enableRbacAuthorization=true`), the script skips `az keyvault set-policy` and relies solely on the role assignments.

## Additional scripts

- `rebuild_app-raiassessment.sh`: helper for redeploying the container image (see script for details).
- `tests/`: placeholder for future automated checks.

## Troubleshooting

- If the script stops due to `set -euo pipefail`, fix the reported issue and re-run; existing resources will be reused.
- To point to an already provisioned Log Analytics workspace in a different resource group, set `LOG_ANALYTICS_WORKSPACE_NAME` and `LOG_ANALYTICS_RESOURCE_GROUP` before executing the script.
- Ensure your Azure account has permissions to assign roles and modify the specified resources.
