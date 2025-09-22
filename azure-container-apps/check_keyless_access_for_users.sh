#!/bin/bash

# This script checks if users have access to the Azure Cognitive Services OpenAI resource.
# If the user does not have access, the script can assign the "Cognitive Services OpenAI User" role to the user.
# The list of users to check is read from a file named "users.txt" in the same directory as this script.
# The script requires the Azure CLI to be installed and logged in.
# launch the script with the following command:
# ./check_keyless_access_for_users.sh to check access for users
# ./check_keyless_access_for_users.sh true to check and assign role to users

# Variables
AZURE_OPENAI_RESOURCE=cto-openai-swedencentral
AZURE_OPENAI_RESOURCE_GROUP=cto-resources-rg

ASSIGN_ROLE=${1:-false}

# Retrieve all users with the "Cognitive Services OpenAI User" role assigned
assigned_users=$(az role assignment list \
  --role "Cognitive Services OpenAI User" \
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$AZURE_OPENAI_RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AZURE_OPENAI_RESOURCE" \
  --query "[].principalName" -o tsv)

# Print the list of assigned users
echo ""
echo "Assigned users:"
echo "$assigned_users"
echo ""

# Transform the list of assigned users to a list of full names
assigned_fullname_users=""
for user in $assigned_users; do
  full_name=$(az ad user show --id "$user" --query "displayName" -o tsv)
  if [ -z "$full_name" ]; then
    echo "Warning: Full name for user $user not found."
  else
    assigned_fullname_users+="$full_name"$'\n'
  fi
done

# Print the list of assigned full names
echo ""
echo "Assigned full name users:"
echo "$assigned_fullname_users"

echo ""
echo "Checking access for users..."

# Read users from users.txt
while IFS= read -r user || [ -n "$user" ]; do
  echo ""
  echo "Checking access for user: $user"
  
  # Check if the user is in the list of assigned full name users
  if echo "$assigned_fullname_users" | grep -q "$user"; then
    echo -e "\e[32mUser $user has access.\e[0m"  # Green
  else
    echo -e "\e[36mUser $user does NOT have access.\e[0m"  # Cyan
    if [ "$ASSIGN_ROLE" = true ]; then
      echo "Retrieving user ID..."
      user_id=$(az ad user list --query "[?displayName=='$user'].userPrincipalName" -o tsv)
      if [ -n "$user_id" ]; then
        echo "Assigning role to user... $user_id"
        az role assignment create --assignee "$user_id" --role "Cognitive Services OpenAI User" --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$AZURE_OPENAI_RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$AZURE_OPENAI_RESOURCE"
        echo -e "\e[33mRole assigned to user $user.\e[0m"  # Yellow
      else
        echo -e "\e[31mUser ID for $user not found.\e[0m"  # Red
      fi
    fi
  fi
done < "./users.txt"

echo ""