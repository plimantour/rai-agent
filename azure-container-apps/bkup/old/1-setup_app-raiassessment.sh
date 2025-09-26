# Install Azure CLI
# sudo apt remove azure-cli
# curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
# az login


# az provider register --namespace Microsoft.App
# az provider register --namespace Microsoft.OperationalInsights
# az extension add --name containerapp --upgrade

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

# Create a resource group
echo "Creating resource group..."
az group create --name $RESOURCE_GROUP --location $LOCATION
echo "Resource group created."

# Deploy containers

echo "Creating container app..."
az containerapp env create \
    --name ${CONTAINER_APP_NAME}-env \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION

az containerapp create \
    --name ${CONTAINER_APP_NAME} \
    --resource-group $RESOURCE_GROUP \
    --environment ${CONTAINER_APP_NAME}-env \
    --image $DOCKER_REGISTRY/$DOCKER_IMAGE \
    --system-assigned \
    --query properties.configuration.ingress.fqdn \
    --ingress external \
    --target-port $TARGET_PORT \
    --cpu 2 \
    --memory 4Gi \
    --registry-server $DOCKER_REGISTRY \
    --min-replicas 1 \
    --max-replicas 5 \
    --env-vars DEPLOY_TIME_IN_SECONDS_SINCE_EPOCH=$(date +%s)

echo "Container app created."

# https://www.programonaut.com/how-to-set-up-volumes-for-azure-container-apps-step-by-step/

echo "Assigning roles to the managed identity..."

# Get the managed identity client ID
MANAGED_IDENTITY_CLIENT_ID=$(az containerapp show \
    --name ${CONTAINER_APP_NAME} \
    --resource-group $RESOURCE_GROUP \
    --query identity.principalId \
    --output tsv)

# Assign the 'acrpull' role to the managed identity
az role assignment create \
    --assignee $MANAGED_IDENTITY_CLIENT_ID \
    --role acrpull \
    --scope $(az acr show --name $(echo $DOCKER_REGISTRY | cut -d'.' -f1) --query id --output tsv)

# Assign the 'Cognitive Services OpenAI User' role to the managed identity
az role assignment create \
    --assignee $MANAGED_IDENTITY_CLIENT_ID \
    --role "Cognitive Services OpenAI User" \
    --scope $(az cognitiveservices account show \
                --name $AZURE_OPENAI_RESOURCE \
                --resource-group $AZURE_OPENAI_RESOURCE_GROUP \
                --query id --output tsv)

# Assign the 'Key Vault Secrets User' role to the managed identity
az role assignment create \
    --assignee $MANAGED_IDENTITY_CLIENT_ID \
    --role "Key Vault Secrets User" \
    --scope $(az keyvault show \
                --name $KEYVAULT_NAME \
                --query id --output tsv)

# Add access policy for getting secrets from Key Vault
az keyvault set-policy \
    --name $KEYVAULT_NAME \
    --object-id $MANAGED_IDENTITY_CLIENT_ID \
    --secret-permissions get

az role assignment create \
    --assignee $MANAGED_IDENTITY_CLIENT_ID \
    --role "Storage Account Contributor" \
    --scope $(az storage account show \
                --name $STORAGE_ACCOUNT_NAME \
                --resource-group $STORAGE_RESOURCE_GROUP \
                --query id --output tsv)

# Add read/write role to azure storage account and blobs
az role assignment create \
    --assignee $MANAGED_IDENTITY_CLIENT_ID \
    --role "Storage Blob Data Contributor" \
    --scope $(az storage account show \
                --name $STORAGE_ACCOUNT_NAME \
                --resource-group $STORAGE_RESOURCE_GROUP \
                --query id --output tsv)

# Get the environment name and assign it to the ENVIRONMENT_NAME variable
CONTAINER_ENV_NAME=$(az containerapp env list \
    --resource-group $RESOURCE_GROUP \
    --query '[].name' \
    --output tsv)

# Ensure the environment name is retrieved correctly
echo "Environment Name: $CONTAINER_ENV_NAME"

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
