# Philippe Limantour - March 2024
# This file contains the functions to retrieve the user information from the Azure App Service authentication endpoint.

import streamlit as st
# from streamlit.web.server.websocket_headers import _get_websocket_headers
from streamlit_javascript import st_javascript
import requests
import base64
import json

# Function to get the headers for the websocket connection
def get_headers():
    # headers = _get_websocket_headers()
    headers = st.context.headers
    return headers

# Function to get the current URL
def get_current_url():
    url = st_javascript("await fetch('').then(r => window.parent.location.href)")
    return url

# Function to get the authentication information from the Azure App Service authentication endpoint
def get_auth_info(webapp_url="https://app-raiassessment.redmushroom-417ab9d2.swedencentral.azurecontainerapps.io/", verbose=False):
    try:
        webapp_url = get_current_url()
        headers = get_headers()
        cookies = headers["Cookie"].split("; ")
        auth_cookie = None
        for cookie in cookies:
            cookie = cookie.split('=', 1)
            if cookie[0]=="AppServiceAuthSession":
                auth_cookie = {"AppServiceAuthSession": cookie[1]}
        if auth_cookie:
            if verbose:
                print(f"Auth Cookie found")
            me = requests.get(f"{webapp_url}/.auth/me", cookies=auth_cookie)
            return me.json()
        else:
            if verbose:
                print(f"No Auth Cookie found - cookies = {cookies}")
            return {}
    except Exception as e:
        print(f"Error: {e}")
        return {}

# Function to get the user information from the Azure App Service authentication endpoint
def get_user_info(verbose=False):
    auth_info = get_auth_info()
    if auth_info and auth_info != {}:
        for item in auth_info:
            user_id = item.get('user_id')
            name = None
            preferred_username = None

            for claim in item.get('user_claims', []):
                if claim.get('typ') == 'name':
                    name = claim.get('val')
                elif claim.get('typ') == 'preferred_username':
                    preferred_username = claim.get('val')

            if verbose:
                print(f'User ID: {user_id}, Name: {name}, Preferred Username: {preferred_username}')
    else:
        user_id = None
        name = None
        preferred_username = None

    return auth_info, user_id, name, preferred_username

# Function to get the client principal from the Azure App Service authentication endpoint
def get_client_principal(url="https://rai-assessment.azurewebsites.net"):
    response = requests.get(url)
    header = response.headers.get('x-ms-client-principal')

    if header is not None:
        decoded = base64.b64decode(header).decode('ascii')
        client_principal = json.loads(decoded)
        return client_principal

    return None