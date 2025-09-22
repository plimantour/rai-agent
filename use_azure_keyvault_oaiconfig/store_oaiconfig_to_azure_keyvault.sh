#!/bin/bash

echo "If az login fails from wsl2 try sudo apt remove xdg-utils"
echo

# Check if jq is installed, if not, install it
if ! command -v jq &> /dev/null
then
    echo "jq could not be found, installing..."
    sudo apt-get install jq
fi

# Check if Azure CLI is installed, if not, install it
if ! command -v az &> /dev/null
then
    echo "Azure CLI could not be found, installing..."
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi

# Variables
subscription_id="<subscription-id>"
resource_group_name="<resource-group-name>"
keyvault_name="AutogenKeyVault"
location="<location>"
config_file="./OAI_CONFIG_LIST" # Create one from the OAI_CONFIG_LIST_temaplate file

# Login to Azure
az login

# Set the subscription
az account set --subscription $subscription_id

# Check if the Key Vault exists
if ! az keyvault show --name $keyvault_name --resource-group $resource_group_name > /dev/null 2>&1; then
    # If the Key Vault does not exist, create it
    az keyvault create --name $keyvault_name --resource-group $resource_group_name --location $location
fi

# Check if Azure CLI is installed, if not, install it
if ! command -v az &> /dev/null
then
    echo "Azure CLI could not be found, installing..."
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi

# Convert the JSON file to a string
json_string=$(jq -c . $config_file)

# Add or replace the secret in the Key Vault
az keyvault secret set --vault-name $keyvault_name --name OAI-CONFIG-LIST --value "$json_string"
