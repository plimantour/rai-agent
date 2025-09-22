## 🚀 Installation - code démonstratif à adapter et sécuriser pour un usage en production

Create a virtual environment with python >= 3.11

* pip install -r requirements
* cp .env.template .env
* Modifier le .env avec vos informations Azure OpenAI

## 🏃 Exécution

az login
az acr login --name YOURdockerregistry
./docker_build_image.sh
Push your docker image to your registry, linked with a hook to your azure web app

There are mainly 3 ways of installing this solution - With Azure Container Apps, With Docker, Without Docker. Using Azure Container Apps is highly recommended.

### Getting Started with Azure Container Apps (Recommended)

1. Create an EntraID app registration, allow tokens,  user_impersonation and access to user data
2. look at /azure-container-apps shell scripts

#### Génération locale - lit solution_description.docx dans le dossier passé en paramètre
```python
 cp 'your-solution-description.docx' 'rai-solution/solution_description.docx'
 python main.py -i rai-solution
```

#### Arguments optionels
-v verbose mode
-s update step by step (e.g., updates the docx at each step, saving at each step - for debug purpose if a step fails)

#### Utilisation de l'interface utilisateur - peut être déployé en Azure Web App
```python
 python -m streamlit run streamlit_ui_main.py --server.port 8000 --server.address 0.0.0.0
```