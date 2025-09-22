from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from termcolor import colored
from dotenv import load_dotenv
import os

load_dotenv()  # take environment variables from .env. - Use an Azure KeyVault in production

# Method to get the storage credential
def get_storage_credential():
    """
    Retrieves the storage credential based on the application run mode.

    Returns:
        The storage credential object based on the application run mode.
    """

    # Create a DefaultAzureCredential object to authenticate with Azure
    credential = DefaultAzureCredential()
    # managed_identity = os.getenv("AZURE_CONTAINER_MANAGED_IDENTITY", None)
    # credential = DefaultAzureCredential(managed_identity_client_id=managed_identity)

    if credential is None:
        print(colored("Azure credential not available", "red"))
        print(colored("Logging in to Azure OpenAI - execute once an 'az login' for your session from command prompt before calling this method", "cyan"))
        exit(1)

    print(f"Storage credential: {credential}")
    
    return credential

def get_from_keyvault(retrieveList=['RAI-ASSESSMENT-USERS']):
    """
    Retrieves the secrets from the Azure Key Vault.
    """
    if isinstance(retrieveList, str):
        retrieveList = [retrieveList]
    if not isinstance(retrieveList, list):  # Check if the retrieveList parameter is a list, apart from a string
        print(colored("The retrieveList parameter must be a list of strings", "red"))
        return None
    # Specify the Azure Key Vault URL
    key_vault_url = os.getenv("AZURE_KEYVAULT_URL", None)
    credential = get_storage_credential()

    # Check if the key vault URL is set
    if key_vault_url and credential:
        # key_vault_url = "https://your-key-vault-name.vault.azure.net"

        # Create a SecretClient object
        secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

        retrievedDict = {}

        # Retrieve the secrets from the key vault
        for retrieve in retrieveList:
            # Retrieve the secrets from the key vault
            for retrieve in retrieveList:
                if not isinstance(retrieve, str):
                    retrieve = str(retrieve)
                secret = secret_client.get_secret(retrieve).value
                retrievedDict[retrieve] = secret
        
        return retrievedDict
    else:
        print(colored(f"Key Vault {key_vault_url} cannot be accessed", "red"))
        return None

if __name__ == "__main__":
    # Retrieve the secrets from the Azure Key Vault
    secrets = get_from_keyvault()
    print(secrets)