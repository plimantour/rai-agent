# Install Azure CLI
# sudo apt remove azure-cli
# curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
# az login


# az provider register --namespace Microsoft.App
# az provider register --namespace Microsoft.OperationalInsights
# az extension add --name containerapp --upgrade

set -euo pipefail

if ! command -v az >/dev/null 2>&1; then
    echo "Azure CLI is required but not found in PATH." >&2
    exit 1
fi

CONTAINER_APP_NAME=app-raiassessment
RESOURCE_GROUP=cto-containers-raiassessment-rg
LOCATION=swedencentral
AZURE_OPENAI_RESOURCE=cto-openai-swedencentral
AZURE_OPENAI_RESOURCE_GROUP=cto-resources-rg
DOCKER_REGISTRY=ctodockerregistry.azurecr.io
DOCKER_IMAGE=rai:latest
STORAGE_ACCOUNT_NAME=ctodatastorage
STORAGE_RESOURCE_GROUP=cto-resources-rg
KEYVAULT_NAME=ctosecuredkeyvault
# STORAGE_SHARE_NAME=backend-dbstore
# STORAGE_MOUNT_NAME=backend-dbstore
TARGET_PORT=80
CONTAINER_ENV_NAME=${CONTAINER_APP_NAME}-env
LOG_ANALYTICS_WORKSPACE_NAME=${LOG_ANALYTICS_WORKSPACE_NAME:-${CONTAINER_APP_NAME}-logs}
LOG_ANALYTICS_RESOURCE_GROUP=${LOG_ANALYTICS_RESOURCE_GROUP:-$RESOURCE_GROUP}
KEYVAULT_RESOURCE_GROUP=${KEYVAULT_RESOURCE_GROUP:-$AZURE_OPENAI_RESOURCE_GROUP}
AZURE_CONTENT_SAFETY_RESOURCE=${AZURE_CONTENT_SAFETY_RESOURCE:-cto-contentsafety-swedencentral}
AZURE_CONTENT_SAFETY_RESOURCE_GROUP=${AZURE_CONTENT_SAFETY_RESOURCE_GROUP:-$AZURE_OPENAI_RESOURCE_GROUP}
CONTENT_SAFETY_LOCATION=${CONTENT_SAFETY_LOCATION:-$LOCATION}
CONTENT_SAFETY_SKU=${CONTENT_SAFETY_SKU:-S0}
AZURE_LANGUAGE_RESOURCE=${AZURE_LANGUAGE_RESOURCE:-cto-language-swedencentral}
AZURE_LANGUAGE_RESOURCE_GROUP=${AZURE_LANGUAGE_RESOURCE_GROUP:-$AZURE_OPENAI_RESOURCE_GROUP}
LANGUAGE_LOCATION=${LANGUAGE_LOCATION:-$LOCATION}
LANGUAGE_SKU=${LANGUAGE_SKU:-S0}
LANGUAGE_KIND=${LANGUAGE_KIND:-CognitiveServices}

log_section() {
    printf '\n=== %s ===\n' "$1"
}

ensure_resource_group() {
    if [ "$(az group exists --name "$RESOURCE_GROUP")" = "true" ]; then
        echo "Resource group $RESOURCE_GROUP already exists. Skipping creation."
    else
        az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --tags project=rai-assessment >/dev/null
        echo "Resource group $RESOURCE_GROUP created."
    fi
}

ensure_log_analytics_workspace() {
    if az monitor log-analytics workspace show \
        --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
        --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
        --query id --output tsv >/dev/null 2>&1; then
        LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID=$(az monitor log-analytics workspace show \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
            --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
            --query customerId --output tsv)
        LOG_ANALYTICS_SHARED_KEY=$(az monitor log-analytics workspace get-shared-keys \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
            --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
            --query primarySharedKey --output tsv)
        echo "Reusing Log Analytics workspace $LOG_ANALYTICS_WORKSPACE_NAME."
    else
        echo "Creating Log Analytics workspace $LOG_ANALYTICS_WORKSPACE_NAME..."
        az monitor log-analytics workspace create \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
            --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
            --location "$LOCATION" >/dev/null
        LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID=$(az monitor log-analytics workspace show \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
            --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
            --query customerId --output tsv)
        LOG_ANALYTICS_SHARED_KEY=$(az monitor log-analytics workspace get-shared-keys \
            --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
            --resource-group "$LOG_ANALYTICS_RESOURCE_GROUP" \
            --query primarySharedKey --output tsv)
    fi

    if [ -z "$LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID" ] || [ -z "$LOG_ANALYTICS_SHARED_KEY" ]; then
        echo "Failed to resolve Log Analytics workspace credentials; check permissions." >&2
        exit 1
    fi
}

ensure_container_environment() {
    if az containerapp env show \
        --name "$CONTAINER_ENV_NAME" \
        --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
        echo "Container Apps environment $CONTAINER_ENV_NAME already exists."
    else
        echo "Creating container app environment $CONTAINER_ENV_NAME..."
        az containerapp env create \
            --name "$CONTAINER_ENV_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --location "$LOCATION" \
            --logs-workspace-id "$LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID" \
            --logs-workspace-key "$LOG_ANALYTICS_SHARED_KEY" >/dev/null
    fi
}

ensure_container_app() {
    if az containerapp show \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
        echo "Container app $CONTAINER_APP_NAME already exists. Updating to create new revision..."
        local container_name
        container_name=$(az containerapp show \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --query "properties.template.containers[0].name" \
            --output tsv)
        if [ -z "$container_name" ]; then
            echo "Failed to resolve container name for $CONTAINER_APP_NAME." >&2
            exit 1
        fi
        az containerapp update \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --container-name "$container_name" \
            --image "$DOCKER_REGISTRY/$DOCKER_IMAGE" \
            --set-env-vars DEPLOY_TIME_IN_SECONDS_SINCE_EPOCH="$(date +%s)" >/dev/null
        echo "Container app updated and new revision triggered."
    else
        echo "Creating container app $CONTAINER_APP_NAME..."
        az containerapp create \
            --name "$CONTAINER_APP_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --environment "$CONTAINER_ENV_NAME" \
            --image "$DOCKER_REGISTRY/$DOCKER_IMAGE" \
            --system-assigned \
            --query properties.configuration.ingress.fqdn \
            --ingress external \
            --target-port "$TARGET_PORT" \
            --cpu 2 \
            --memory 4Gi \
            --registry-server "$DOCKER_REGISTRY" \
            --min-replicas 1 \
            --max-replicas 5 \
            --env-vars DEPLOY_TIME_IN_SECONDS_SINCE_EPOCH="$(date +%s)"
    fi
}

ensure_role_assignment() {
    local role="$1"
    local scope="$2"
    if az role assignment list \
        --assignee "$MANAGED_IDENTITY_CLIENT_ID" \
        --scope "$scope" \
        --role "$role" \
        --query '[].id' --output tsv | grep -q .; then
        echo "Role $role already assigned on $scope."
    else
        az role assignment create \
            --assignee "$MANAGED_IDENTITY_CLIENT_ID" \
            --role "$role" \
            --scope "$scope" >/dev/null
        echo "Assigned role $role on $scope."
    fi
}

ensure_content_safety_account() {
    if az cognitiveservices account show \
        --name "$AZURE_CONTENT_SAFETY_RESOURCE" \
        --resource-group "$AZURE_CONTENT_SAFETY_RESOURCE_GROUP" >/dev/null 2>&1; then
        echo "Azure Content Safety account $AZURE_CONTENT_SAFETY_RESOURCE already exists."
    else
        echo "Creating Azure Content Safety account $AZURE_CONTENT_SAFETY_RESOURCE..."
        az cognitiveservices account create \
            --name "$AZURE_CONTENT_SAFETY_RESOURCE" \
            --resource-group "$AZURE_CONTENT_SAFETY_RESOURCE_GROUP" \
            --kind ContentSafety \
            --sku "$CONTENT_SAFETY_SKU" \
            --location "$CONTENT_SAFETY_LOCATION" \
            --yes \
            --tags project=rai-assessment >/dev/null
        echo "Azure Content Safety account $AZURE_CONTENT_SAFETY_RESOURCE created."
    fi
}

ensure_content_safety_custom_domain() {
    local expected_domain current_domain
    expected_domain="$AZURE_CONTENT_SAFETY_RESOURCE"
    current_domain=$(az cognitiveservices account show \
        --name "$AZURE_CONTENT_SAFETY_RESOURCE" \
        --resource-group "$AZURE_CONTENT_SAFETY_RESOURCE_GROUP" \
        --query "properties.customSubDomainName" \
        --output tsv 2>/dev/null || true)
    if [ "$current_domain" = "$expected_domain" ]; then
        echo "Content Safety custom domain $expected_domain already configured."
    else
        echo "Configuring Content Safety custom domain $expected_domain..."
        az cognitiveservices account update \
            --name "$AZURE_CONTENT_SAFETY_RESOURCE" \
            --resource-group "$AZURE_CONTENT_SAFETY_RESOURCE_GROUP" \
            --custom-domain "$expected_domain" >/dev/null
    fi
}

ensure_language_account() {
    if az cognitiveservices account show \
        --name "$AZURE_LANGUAGE_RESOURCE" \
        --resource-group "$AZURE_LANGUAGE_RESOURCE_GROUP" >/dev/null 2>&1; then
        echo "Azure AI Language account $AZURE_LANGUAGE_RESOURCE already exists."
    else
        echo "Creating Azure AI Language account $AZURE_LANGUAGE_RESOURCE..."
        az cognitiveservices account create \
            --name "$AZURE_LANGUAGE_RESOURCE" \
            --resource-group "$AZURE_LANGUAGE_RESOURCE_GROUP" \
            --kind "$LANGUAGE_KIND" \
            --sku "$LANGUAGE_SKU" \
            --location "$LANGUAGE_LOCATION" \
            --yes \
            --tags project=rai-assessment >/dev/null
        echo "Azure AI Language account $AZURE_LANGUAGE_RESOURCE created."
    fi
}

ensure_language_custom_domain() {
    local expected_domain current_domain
    expected_domain="$AZURE_LANGUAGE_RESOURCE"
    current_domain=$(az cognitiveservices account show \
        --name "$AZURE_LANGUAGE_RESOURCE" \
        --resource-group "$AZURE_LANGUAGE_RESOURCE_GROUP" \
        --query "properties.customSubDomainName" \
        --output tsv 2>/dev/null || true)
    if [ "$current_domain" = "$expected_domain" ]; then
        echo "Language custom domain $expected_domain already configured."
    else
        echo "Configuring Language custom domain $expected_domain..."
        az cognitiveservices account update \
            --name "$AZURE_LANGUAGE_RESOURCE" \
            --resource-group "$AZURE_LANGUAGE_RESOURCE_GROUP" \
            --custom-domain "$expected_domain" >/dev/null
    fi
}

log_section "Resource group"
ensure_resource_group

log_section "Log Analytics workspace"
ensure_log_analytics_workspace

log_section "Azure Content Safety account"
ensure_content_safety_account
ensure_content_safety_custom_domain

log_section "Azure AI Language account"
ensure_language_account
ensure_language_custom_domain

log_section "Container Apps environment"
ensure_container_environment

log_section "Container app"
ensure_container_app

# https://www.programonaut.com/how-to-set-up-volumes-for-azure-container-apps-step-by-step/

log_section "Managed identity role assignments"

MANAGED_IDENTITY_CLIENT_ID=$(az containerapp show \
    --name "$CONTAINER_APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query identity.principalId \
    --output tsv)

if [ -z "$MANAGED_IDENTITY_CLIENT_ID" ]; then
    echo "Unable to determine managed identity principal ID for $CONTAINER_APP_NAME." >&2
    exit 1
fi

ACR_NAME=${DOCKER_REGISTRY%%.*}
ACR_SCOPE=$(az acr show --name "$ACR_NAME" --query id --output tsv)
ensure_role_assignment "acrpull" "$ACR_SCOPE"

OPENAI_SCOPE=$(az cognitiveservices account show \
    --name "$AZURE_OPENAI_RESOURCE" \
    --resource-group "$AZURE_OPENAI_RESOURCE_GROUP" \
    --query id --output tsv)
ensure_role_assignment "Cognitive Services OpenAI User" "$OPENAI_SCOPE"

CONTENT_SAFETY_SCOPE=$(az cognitiveservices account show \
    --name "$AZURE_CONTENT_SAFETY_RESOURCE" \
    --resource-group "$AZURE_CONTENT_SAFETY_RESOURCE_GROUP" \
    --query id --output tsv)
ensure_role_assignment "Cognitive Services User" "$CONTENT_SAFETY_SCOPE"

LANGUAGE_SCOPE=$(az cognitiveservices account show \
    --name "$AZURE_LANGUAGE_RESOURCE" \
    --resource-group "$AZURE_LANGUAGE_RESOURCE_GROUP" \
    --query id --output tsv)
ensure_role_assignment "Cognitive Services Language Reader" "$LANGUAGE_SCOPE"

KEYVAULT_SCOPE=$(az keyvault show \
    --name "$KEYVAULT_NAME" \
    --resource-group "$KEYVAULT_RESOURCE_GROUP" \
    --query id --output tsv)
ensure_role_assignment "Key Vault Secrets User" "$KEYVAULT_SCOPE"

KEYVAULT_RBAC_ENABLED=$(az keyvault show \
    --name "$KEYVAULT_NAME" \
    --resource-group "$KEYVAULT_RESOURCE_GROUP" \
    --query properties.enableRbacAuthorization --output tsv)

if [ "$KEYVAULT_RBAC_ENABLED" = "true" ]; then
    echo "Key Vault $KEYVAULT_NAME uses RBAC; skipping set-policy (use role assignments instead)."
else
    az keyvault set-policy \
        --name "$KEYVAULT_NAME" \
        --object-id "$MANAGED_IDENTITY_CLIENT_ID" \
        --secret-permissions get >/dev/null
fi

STORAGE_SCOPE=$(az storage account show \
    --name "$STORAGE_ACCOUNT_NAME" \
    --resource-group "$STORAGE_RESOURCE_GROUP" \
    --query id --output tsv)
ensure_role_assignment "Storage Account Contributor" "$STORAGE_SCOPE"
ensure_role_assignment "Storage Blob Data Contributor" "$STORAGE_SCOPE"

echo "Environment Name: $CONTAINER_ENV_NAME"


# ============= KEEP This section which can be used for 1st deployment to setup storage mount ==============

# # Create a storage account
# az storage account create \
#   --name $STORAGE_ACCOUNT_NAME \
#   --resource-group $RESOURCE_GROUP \
#   --location $LOCATION \
#   --sku Standard_LRS \
#   --kind StorageV2

# # Create a storage share inside the storage account
# az storage share-rm create \
#     --resource-group $RESOURCE_GROUP \
#     --storage-account $STORAGE_ACCOUNT_NAME \
#     --name $STORAGE_SHARE_NAME \
#     --quota 1024 \
#     --enabled-protocols SMB \
#     --output table 

# # Get the storage account key
# STORAGE_ACCOUNT_KEY=$(az storage account keys list \
#     --resource-group $RESOURCE_GROUP \
#     --account-name $STORAGE_ACCOUNT_NAME \
#     --query "[0].value" --output tsv)

# # Create a storage mount named in the specified environment
# az containerapp env storage set \
#     --access-mode ReadWrite \
#     --azure-file-account-name $STORAGE_ACCOUNT_NAME \
#     --azure-file-account-key $STORAGE_ACCOUNT_KEY \
#     --azure-file-share-name $STORAGE_SHARE_NAME \
#     --storage-name $STORAGE_MOUNT_NAME \
#     --name $CONTAINER_ENV_NAME \
#     --resource-group $RESOURCE_GROUP \
#     --output table

az containerapp show \
    --name $CONTAINER_APP_NAME \
    --resource-group $RESOURCE_GROUP \
    --output yaml > ${CONTAINER_APP_NAME}.yaml


# az containerapp update \
#     --name $CONTAINER_APP_NAME \
#     --resource-group $RESOURCE_GROUP \
#     --yaml ${CONTAINER_APP_NAME}.yaml \
#     --output table
