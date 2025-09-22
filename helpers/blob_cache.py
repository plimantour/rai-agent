# Philippe Limantour - June 2024
# This file contains the functions to save and load data to aa azure blob cache

import os
import time
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.keyvault.secrets import SecretClient
from termcolor import colored

try:
    from termcolor import colored
except ImportError:
    def colored(x, *args, **kwargs):
        return x


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


# Method to list all containers in the storage account
def list_containers(blob_service_client):
    """
    Lists all the containers in the storage account and prints their names and metadata.

    Args:
        blob_service_client: The BlobServiceClient object used to interact with the storage account.

    Raises:
        Exception: If there is an error listing the containers.

    Returns:
        None
    """
    try:
        # List the containers in the storage account
        container_list = blob_service_client.list_containers()

        # Print the list of containers
        print(colored("Containers:", "blue"))
        for container in container_list:
            print(f"Container Name: {container['name']}, Metadata: {container['metadata']}")
        
            # Create a ContainerClient
            container_client = blob_service_client.get_container_client(container['name'])
            
            # List all blobs in the container
            print(f"\tBlobs in the container {container['name']}:")
            blob_list = container_client.list_blobs()
            for blob in blob_list:
                print(f"\t\t {blob.name}")

    except Exception as e:
        print(colored(f"Error listing containers: {e}", "red"))

# Method to connect to the blob service
def connect_to_blob_service():
    """
    Connects to the Azure Blob storage service and returns a BlobServiceClient object.

    Returns:
        BlobServiceClient: The BlobServiceClient object used to interact with the Azure Blob storage service.

    Raises:
        Exception: If there is an error connecting to the blob service.
    """
    try:
        # Create a BlobServiceClient object using the connection string
        azure_storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", None)
        azure_storage_url = "https://" + azure_storage_account_name + ".blob.core.windows.net/"
        print(colored(f"Azure Storage URL: {azure_storage_url}", "cyan"))
        credential = DefaultAzureCredential()
        # managed_identity = os.getenv("AZURE_CONTAINER_MANAGED_IDENTITY", None)
        # credential = DefaultAzureCredential(managed_identity_client_id=managed_identity)
        blob_service_client = BlobServiceClient(account_url=azure_storage_url, credential=credential)

        if not blob_service_client:
            print(colored("Blob service client not created", "red"))

        # Return the BlobServiceClient object
        return blob_service_client

    except Exception as e:
        print(colored(f"Error connecting to blob service: {e}", "red"))
        return None

# Method to connect to a container
def connect_to_container(blob_service_client, container_name):
    """
    Connects to a container in Azure Blob Storage.

    Args:
        blob_service_client (BlobServiceClient): The BlobServiceClient object used to connect to the storage account.
        container_name (str): The name of the container to connect to.

    Returns:
        ContainerClient: The ContainerClient object for the specified container.

    Raises:
        Exception: If there is an error connecting to the container.
    """
    try:
        # Create a ContainerClient object for the specified container
        container_client = blob_service_client.get_container_client(container_name)

        # Return the ContainerClient object
        return container_client

    except Exception as e:
        print(colored(f"Error connecting to container: {e}", "red"))
        return None

# Method to upload or update a blob
def upload_update_blob(container_client, blob_name, newdata):
    """
    Uploads or updates a blob in the specified container.

    Args:
        container_client (azure.storage.blob.ContainerClient): The container client object.
        blob_name (str): The name of the blob.
        newdata (str): The new data to be added to the blob.

    Raises:
        Exception: If there is an error uploading the blob.

    Returns:
        None
    """
    try:
        # Create or Get a reference to the blob as a BlobClient object
        blob_client = container_client.get_blob_client(blob_name)
        blob_exists = blob_client.exists()
        if blob_exists:
            print(colored("Blob already exists, updating.", "yellow"))
            # Download the blob to a string
            data = blob_client.download_blob().readall().decode('utf-8')

            # Add a new line to the data
            data += newdata
        else:
            print(colored("Blob does not exist, creating.", "yellow"))
            data = newdata

        # Upload the updated data to the blob
        blob_client.upload_blob(data, overwrite=True)

        # Print a success message
        print(colored("Blob uploaded successfully.", "green"))

    except Exception as e:
        print(colored(f"Error uploading blob: {e}", "red"))

# Method to read the content of a blob
def read_blob(container_client, blob_name):
    """
    Reads the contents of a blob from the specified container.

    Args:
        container_client (azure.storage.blob.ContainerClient): The container client object.
        blob_name (str): The name of the blob to read.

    Returns:
        str: The contents of the blob as a string, decoded using UTF-8.

    Raises:
        Exception: If there is an error reading the blob.
    """
    try:
        # Create or Get a reference to the blob as a BlobClient object
        data = None
        blob_client = container_client.get_blob_client(blob_name)
        blob_exists = blob_client.exists()
        if blob_exists:
            # Download the blob to a string
            data = blob_client.download_blob().readall().decode('utf-8')
        else:
            print(colored("Blob does not exist.", "yellow"))

        return data

    except Exception as e:
        print(colored(f"Error reading blob: {e}", "red"))


# Method to read the content of a log file
def read_logs_blob_content(container_name="assessments-apps-data", blob_name="rai_assessment_logs.txt"):
    """
    Reads the content of a blob file from the specified container.

    Args:
        container_name (str): The name of the container where the blob file is located. 
            Defaults to "assessments-apps-data".
        blob_name (str): The name of the blob file to read. Defaults to "rai_assessment_logs.txt".

    Returns:
        str: The content of the blob file.

    """
    blob_service_client = connect_to_blob_service()
    container_client = connect_to_container(blob_service_client, container_name)
    logs = read_blob(container_client, blob_name)
    return logs

# Method to append a log to a file
def append_log_to_blob(log, container_name="assessments-apps-data", blob_name="rai_assessment_logs.txt"):
    """
    Appends a log entry to a blob in Azure Blob Storage.

    Args:
        log (str): The log entry to be appended.
        container_name (str, optional): The name of the container in Azure Blob Storage. Defaults to "assessments-apps-data".
        blob_name (str, optional): The name of the blob in Azure Blob Storage. Defaults to "rai_assessment_logs.txt".
    """
    blob_service_client = connect_to_blob_service()
    container_client = connect_to_container(blob_service_client, container_name)

    timestamp = time.strftime("%Y%m%d-%H:%M:%S")
    log = f'{timestamp} - {log}\n'

    upload_update_blob(container_client, blob_name, log)


def main():

    blob_service_client = connect_to_blob_service()
    # list_containers(blob_service_client)
    container_name = "assessments-apps-data"
    
    blob_name = "users.txt"
    container_client = connect_to_container(blob_service_client, container_name)

    data = read_blob(container_client, blob_name)
    print(colored(f"\nData in {blob_name}:\n{data}", "cyan"))

    # data = "\nCeci est une nouvelle ligne; test de la fonction upload_update_blob."
    # upload_update_blob(container_client, blob_name, data)

    blob_name = "rai_assessment_logs.txt"
    data = read_blob(container_client, blob_name)
    print(colored(f"\nData in {blob_name}:\n{data}", "cyan"))

    retrievedDict = get_from_keyvault(['RAI-ASSESSMENT-USERS'])
    if retrievedDict and 'RAI-ASSESSMENT-USERS' in retrievedDict:
        users_list = retrievedDict['RAI-ASSESSMENT-USERS'].split(';')
    else:
        users_list = []
        print(f"Retrieved dictionary: {retrievedDict}")
    print(colored(f"\nUsers list:\n{users_list}", "cyan"))

    # Save the users from the list to a text file, one user per line
    users = "\n".join(users_list)
    with open("users.txt", "w") as f:
        f.write(users)

if __name__ == "__main__":
    main()

