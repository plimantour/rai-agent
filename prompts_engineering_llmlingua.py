
# Philippe Limantour - March 2024
# This file contains the prompts for drafting a Responsible AI Assessment from a solution description

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.keyvault.secrets import SecretClient
from helpers.docs_utils import docx_find_replace_text, docx_find_replace_text_bydict, docx_delete_all_between_searched_texts
from llmlingua import PromptCompressor
import random
import time
import openai
import os
import json
import re
import ast
from pprint import pprint
from helpers.cache_completions import save_completion_to_cache, load_answer_from_completion_cache, delete_cache_entry
from helpers.completion_pricing import get_completion_pricing_from_usage
from termcolor import colored

from prompts.rai_prompts_llmlingua import SYSTEM_PROMPT, TARGET_LANGUAGE_PLACEHOLDER, SOLUTION_DESCRIPTION_PLACEHOLDER, SOLUTION_DESCRIPTION_SECURITY_ANALYSIS_PROMPT
from prompts.rai_prompts_llmlingua import INTENDED_USES_PLACEHOLDER, INTENDED_USES_STAKEHOLDERS_PLACEHOLDER, FITNESS_FOR_PURPOSE_PROMPT
from prompts.rai_prompts_llmlingua import STAKEHOLDERS_PROMPT, GOALS_A5_T3_PROMPT, GOALS_FAIRNESS_PROMPT, SOLUTION_SCOPE_PROMPT, SOLUTION_INFORMATION_PROMPT
from prompts.rai_prompts_llmlingua import INTENDED_USES_PROMPT, RISK_OF_USE_PROMPT, IMPACT_ON_STAKEHOLDERS_PROMPT, HARMS_ASSESMENT_PROMPT
from prompts.rai_prompts_llmlingua import SOLUTION_INTENDEDUSE_ASSESSMENT_PROMPT, DISCLOSURE_OF_AI_INTERACTION_PROMPT, SOLUTION_DESCRIPTION_ANALYSIS_PROMPT

try:
    from termcolor import colored
except ImportError:
    def colored(x, *args, **kwargs):
        return x

# Method to segment the llmlingua prompt
def segment_llmlingua_prompt(context, global_rate=0.33):
    new_context, context_segs, context_segs_rate, context_segs_compress = (
            [],
            [],
            [],
            [],
        )
    for text in context:
        if not text.startswith("<llmlingua"):
            text = "<llmlingua>" + text
        if not text.endswith("</llmlingua>"):
            text = text + "</llmlingua>"

        # Regular expression to match <llmlingua, rate=x, compress=y>content</llmlingua>, allowing rate and compress in any order
        pattern = r"<llmlingua\s*(?:,\s*rate\s*=\s*([\d\.]+))?\s*(?:,\s*compress\s*=\s*(True|False))?\s*(?:,\s*rate\s*=\s*([\d\.]+))?\s*(?:,\s*compress\s*=\s*(True|False))?\s*>([^<]+)</llmlingua>"
        matches = re.findall(pattern, text)

        # Extracting segment contents
        segments = [match[4] for match in matches]

        # Extracting rate and compress, considering their possible positions
        segs_rate = [
            float(match[0]) if match[0] else (float(match[2]) if match[2] else None)
            for match in matches
        ]
        segs_compress = [
            (
                match[1] == "True"
                if match[1]
                else (match[3] == "True" if match[3] else None)
            )
            for match in matches
        ]

        segs_compress = [
            compress if compress is not None else True for compress in segs_compress
        ]
        segs_rate = [
            rate if rate else (global_rate if compress else 1.0)
            for rate, compress in zip(segs_rate, segs_compress)
        ]
        assert (
            len(segments) == len(segs_rate) == len(segs_compress)
        ), "The number of segments, rates, and compress flags should be the same."
        assert all(
            seg_rate <= 1.0 for seg_rate in segs_rate
        ), "Error: 'rate' must not exceed 1.0. The value of 'rate' indicates compression rate and must be within the range [0, 1]."

        new_context.append("".join(segments))
        context_segs.append(segments)
        context_segs_rate.append(segs_rate)
        context_segs_compress.append(segs_compress)

    return new_context, context_segs, context_segs_rate, context_segs_compress

# Method to process the llmlingua prompt
def process_llmlingua_prompt(prompt, global_rate=0.33, rebuildCache=False, verbose=False):
    new_context, context_segs, context_segs_rate, context_segs_compress = segment_llmlingua_prompt([prompt])
    if verbose:
        print(colored(f"new_context: {new_context}", "green"))
        print('='*80)
        print(colored(f"context_segs: {context_segs}", "green"))
        print('='*80)
        print(colored(f"context_segs_rate: {context_segs_rate}", "green"))
        print('='*80)
        print(colored(f"context_segs_compress: {context_segs_compress}", "green"))
        print('='*80)
    compressed_prompt = {"compressed_prompt": "", "compressed_tokens": 0, "origin_tokens": 0}
    for i, context_seg in enumerate(context_segs[0]):
        if not context_segs_compress[0][i]:
            compressed_prompt['compressed_prompt'] += context_seg
        else:
            # cached_data = None
            # if not rebuildCache:
            #     cached_data, cached_key = load_answer_from_completion_cache(f'{str(rate=context_segs_rate[0][i])}_{context_seg})
            # if not rebuildCache and cached_data:
            #     compressed_seg = cached_data
            compressed_seg = llm_lingua.compress_prompt(
                context_seg,
                rate=context_segs_rate[0][i],
                rank_method="longllmlingua",
                force_tokens=["!", ".", "?", ":", "\n"],
                drop_consecutive=True
            )
            if verbose:
                print(colored(f"Compressed Prompt: {compressed_seg['compressed_prompt']}\n{compressed_seg['compressed_tokens']} tokens Vs {compressed_seg['origin_tokens']} tokens", "blue"))
            compressed_prompt['compressed_prompt'] += compressed_seg["compressed_prompt"]
            compressed_prompt['compressed_tokens'] += compressed_seg["compressed_tokens"]
            compressed_prompt['origin_tokens'] += compressed_seg["origin_tokens"]

    return compressed_prompt

# Method to print a message to the console or to the UI through a hook
def uiprint(msg, ui_hook=None, color='white'):
    if ui_hook:
        ui_hook(msg)
        print(colored(msg, color))
    else:
        print(colored(msg, color))

## Configure Azure OpenAI settings

load_dotenv()  # take environment variables from .env. - Use an Azure KeyVault in production

completion_model: str = None

def initialize_ai_models():
    global completion_model

    # Create a DefaultAzureCredential object to authenticate with Azure
    credential = DefaultAzureCredential()
    # managed_identity = os.getenv("AZURE_CONTAINER_MANAGED_IDENTITY", None)
    # credential = DefaultAzureCredential(managed_identity_client_id=managed_identity)

    if credential is None:
        print(colored("Failed to authenticate with Azure.", "red"))
        print(colored("Logging in to Azure OpenAI - execute once an 'az login' for your session from command prompt before calling this method", "cyan"))
        exit(1)

    print(colored("Using Azure Entra ID", "cyan"))

    # Specify the Azure Key Vault URL
    key_vault_url = os.getenv("AZURE_KEYVAULT_URL", None)

    azure_ad_token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

    if not azure_ad_token_provider:
        print(colored("Failed to get the Azure AD token provider.", "red"))
        exit(1)

    # Check if the key vault URL is set
    if key_vault_url:

        # key_vault_url = "https://your-key-vault-name.vault.azure.net"

        # Create a SecretClient object
        secret_client = SecretClient(vault_url=key_vault_url, credential=credential)

        print(colored("Using an Azure key vault...", "cyan"))

        # Retrieve the openai secrets from the key vault
        openai.api_type = os.getenv("AZURE_OPENAI_API_TYPE")
        if openai.api_type == 'azure':
            # openai.api_key = secret_client.get_secret('AZURE-OPENAI-API-KEY').value
            openai.azure_ad_token_provider = azure_ad_token_provider
            openai.azure_endpoint = secret_client.get_secret('AZURE-OPENAI-ENDPOINT').value
            openai.api_version = os.getenv("AZURE_OPENAI_API_VERSION")
            completion_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")
            print(f'Using Azure OpenAI API with model {completion_model}\n')
            print(f'keyless - azure_endpoint {openai.azure_endpoint}\n')
        else:
            from openai import OpenAI
            mistral_url = secret_client.get_secret('MISTRAL-OPENAI-ENDPOINT').value
            mistral_key = secret_client.get_secret('MISTRAL-OPENAI-API-KEY').value
            mistral = OpenAI(base_url=mistral_url, api_key=mistral_key)
            completion_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")

    # If the key vault URL is not set, use the environment variables
    else:
        openai.api_type = os.getenv("AZURE_OPENAI_API_TYPE")
        if openai.api_type == 'azure':
            # openai.api_key = os.getenv("AZURE_OPENAI_API_KEY")
            openai.azure_ad_token_provider = azure_ad_token_provider
            openai.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            openai.api_version = os.getenv("AZURE_OPENAI_API_VERSION")
            completion_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")
            print(f'Using Azure OpenAI API with model {completion_model}\n')
            print(f'Calling Azure with {"Mistral Large" if completion_model == "azureai" else completion_model} model\n')
        else:
            from openai import OpenAI
            mistral_url = os.getenv("AZURE_OPENAI_ENDPOINT")
            mistral_key = os.getenv("AZURE_OPENAI_API_KEY") 
            mistral = OpenAI(base_url=mistral_url, api_key=mistral_key)
            completion_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT")
            print(f'Calling Azure with {"Mistral Large" if completion_model == "azureai" else completion_model} model\n')

    # Set up a llmlingua 2 Prompt Compressor
    llm_lingua = PromptCompressor(
        # model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank", # Use the XLM-RoBERTa model, out of space of azure web app plan B2
        model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        device_map="cpu",
        use_llmlingua2=True,
    )

# Method to extract a string from a content
def extract_string_content(content):
    regex = r'"(.*?)"'
    value = re.search(regex, content)
    if value:
        return value.group(1), value.start(), value.end()
    return None, -1, -1


# ## Method to ask a prompt to LLM (best with GPT-4)
def get_azure_openai_completion_nocache(prompt, system_prompt, model=None):
    try:
        if model is None:
            model = completion_model
        if openai.api_type == 'azure':
            # Calling Azure OpenAI model
            response = openai.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                    ],
                temperature=0.0
            )
        else:
            # Calling Azure Mistral Large As a Service
            response = mistral.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                    ],
                temperature=0.0
            )
    except Exception as e:
        print(e)
        print(colored("Failed to generate the completion.", "red"))
        return ""

    # Extract the answer from the response
    if response.choices and len(response.choices) > 0 and response.choices[0].message and response.choices[0].message.content:
        answer = response.choices[0].message.content
        return answer
    else:
        print(colored("Failed to extract the answer from the response.", "red"))
        return ""


# ## Method to ask a prompt to LLM (best with GPT-4-32k)
def get_azure_openai_completion(prompt, system_prompt, model=None, json_mode="text", temperature=0.0, language="English", min_sleep=0, max_sleep=0, rebuildCache=False, compress=False, verbose=False):

    if model is None:
        model = completion_model

    if '32-k' or 'mistral' in model.lower():
        json_mode = "text"  # GPT-4-32k does not support JSON output API parameter

    if not compress:
        system_prompt = system_prompt.replace('<llmlingua, compress=False>', '').replace('<llmlingua, rate=0.5>', '').replace('<llmlingua, rate=0.8>', '').replace('</llmlingua>', '')
        prompt = prompt.replace('<llmlingua, compress=False>', '').replace('<llmlingua, rate=0.5>', '').replace('<llmlingua, rate=0.8>', '').replace('</llmlingua>', '')

    cached_data, cached_key = load_answer_from_completion_cache(model + '_' + language + '_' + prompt + '_' + str(temperature) + '_' + str(compress), verbose=verbose)
    cached_model, cached_language, cached_input_cost, cached_output_cost, cached_response = cached_data[0:5] if cached_data else [None, None, None, None, None]
    # generate a random seconds between min_sleep and max_sleep seconds
    sleep_time = random.randint(min_sleep, max_sleep)
    response = None
    if not rebuildCache:
        action_text = f'Using cached response {cached_key} - waiting {sleep_time} seconds' if cached_response else "No cache found - Calling LLM"
    else:
        action_text = "Found cached response but forced to rebuild cache" if cached_response else "Calling LLM"
 
    if cached_response and not rebuildCache:
        print(colored(action_text, "green"))
        time.sleep(sleep_time)
        cached_completion_cost = (cached_input_cost + cached_output_cost) # Using the cached pricing - for information but cost occured once the first time
        return cached_response, cached_completion_cost, 0, 0, cached_key
    else:
        print(colored(action_text, "cyan"))

    # Use llmlingua 2 to compress the prompt
    if compress:
        # print(colored(f"System Prompt: {system_prompt}", "green"))
        compressed_system_prompt = process_llmlingua_prompt(system_prompt, global_rate=0.33, rebuildCache=rebuildCache)
        if verbose:
            print(colored(f"Compressed System Prompt: {compressed_system_prompt['compressed_prompt']}\n{compressed_system_prompt['compressed_tokens']} tokens Vs {compressed_system_prompt['origin_tokens']} tokens", "cyan"))
        else:
            print(colored(f"Compressed System Prompt: {compressed_system_prompt['compressed_tokens']} tokens Vs {compressed_system_prompt['origin_tokens']} tokens", "cyan"))
        use_system_prompt = compressed_system_prompt["compressed_prompt"]
        
        # print(colored(f"Prompt: {prompt}", "green"))
        compressed_prompt = process_llmlingua_prompt(prompt, global_rate=0.33)
        if verbose:
            print(colored(f"Compressed Prompt: {compressed_prompt['compressed_prompt']}\n{compressed_prompt['compressed_tokens']} tokens Vs {compressed_prompt['origin_tokens']} tokens", "cyan"))
        else:
            print(colored(f"Compressed Prompt: {compressed_system_prompt['compressed_tokens']} tokens Vs {compressed_system_prompt['origin_tokens']} tokens", "cyan"))
        use_prompt = compressed_prompt["compressed_prompt"]
    else:
        use_system_prompt = system_prompt
        use_prompt = prompt

    try:
        process_completion = True
        while process_completion:
            if openai.api_type == 'azure':
                response = openai.chat.completions.create(
                    model=model,
                    response_format={ "type": "json_object" } if json_mode == "json" else { "type": "text" },
                    messages=[
                        {"role": "system", "content": use_system_prompt},
                        {"role": "user", "content": use_prompt},
                        ],
                    temperature=temperature,
                )
            else:
                print(colored(f'Calling Azure with {"Mistral Large" if completion_model == "azureai" else completion_model} model', "green"))
                response = mistral.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": use_system_prompt},
                        {"role": "user", "content": use_prompt},
                        ],
                    temperature=0.0,
                )

            finish_reason = response.choices[0].finish_reason if response and response.choices and len(response.choices) > 0 else "unknown"
            print(colored(f"Completion's finish reason ({finish_reason}).", "red" if finish_reason == "length" else "yellow"))

            model_called_first = None
            if finish_reason == "length":
                if '32-k' not in model.lower():
                    print(colored("Completion failed due to length. Retrying with a GPT-4-32k", "yellow"))
                    model_called_first = model
                    model = "gpt-4-32k"
                else:
                    process_completion = False
            else:
                process_completion = False

    except Exception as e:
        print(e)
        finish_reason = response.choices[0].finish_reason if response and response.choices and len(response.choices) > 0 else "unknown"
        content_filter_result = response.choices[0].content_filter_results if response and response.choices and len(response.choices) > 0 else None
        print(colored(f"Failed to generate the completion ({finish_reason}).", "red"))
        # Access the individual categories and details
        if content_filter_result:
            for category, details in content_filter_result.items():
                print(colored(f"{category}:\n filtered={details['filtered']}\n severity={details['severity']}", "red"))
        return "", 0, 0, 0, ""

    if response and response.usage:
        input_cost, output_cost = get_completion_pricing_from_usage(
            model,
            response.usage.prompt_tokens,
            response.usage.completion_tokens
        )
    else:
        input_cost, output_cost = 0, 0
    completion_cost = input_cost + output_cost
    print(colored(f"Cost: {completion_cost:.2f} - Input: {input_cost:.2f} - Output: {output_cost:.2f}", "yellow"))

    answer = response.choices[0].message.content if response and response.choices and len(response.choices) > 0 and response.choices[0].message.content else ""
    cached_key_list = []
    if answer != "":
        if model_called_first:  # Save the completion to the cache with the model called first if it was changed to use gpt-4-32k due to length
            cached_key = save_completion_to_cache(model_called_first + '_' + language + '_' + prompt + '_' + str(temperature) + '_' + str(compress), [model_called_first, language, input_cost, output_cost, answer])
            cached_key_list.append(cached_key)
        cached_key = save_completion_to_cache(model + '_' + language + '_' + prompt + '_' + str(temperature) + '_' + str(compress), [model, language, input_cost, output_cost, answer])
        cached_key_list.append(cached_key)

    return answer, completion_cost, response.usage.prompt_tokens, response.usage.completion_tokens, cached_key_list


# Method to get only the JSON information from the answer if the LLM outputs text before or after the json structure
def get_json_from_answer(answer, main_json= '', verbose=False):

    def has_nested_structures(answer_json):
        if isinstance(answer_json, dict):
            for value in answer_json.values():
                if isinstance(value, dict):
                    return True
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            return True
        return False
    try:
        answer = answer.strip()
        if verbose:
            print('ANSWER:\n', answer)
        if answer[0] == '[':    # If the answer is a list, convert it to a dictionary of lists
            answer_json = {
                main_json: ast.literal_eval(answer) # Get a list from the string
            }
            if verbose:
                print(f'\n===>\n {answer_json}')
        else:
            json_answer = _get_only_json_from_answer(answer) # We expect only a JSON structure as the answer - remove any text before or after it
            # Convert text to JSON
            try:
                answer_json = json.loads(json_answer)
                try:
                    if main_json not in answer_json.keys():   # If the main_json is not in the answer, we expect only a JSON structure as the answer
                        print(colored(f"Expected {main_json} in the JSON answer, but got {answer_json.keys()}", "yellow"))
                        if not has_nested_structures(answer_json):
                            answer_json = {
                                main_json: answer_json
                            }
                        else:
                            # Assuming 'jsond' is your dictionary and 'newKeyName' is the new key name
                            oldKeyName = list(answer_json.keys())[0]  # Get the first key name
                            print(colored(f'Replacing {oldKeyName} with {main_json} ({answer_json.keys()})', 'yellow'))
                            answer_json[main_json] = answer_json.pop(oldKeyName)  # Rename key to main_json
                        if verbose:
                            print(f'\n===>\n {answer_json}')
                except Exception as e:
                    print(e)
                    print(colored(f"Failed to convert the JSON to the expected dictionary.\n{answer}", "red"))
                    return {}
            except Exception as e:
                print(e)
                print(colored(f"Failed to convert the JSON to a dictionary.\n{answer}\n------\n{json_answer}", "red"))
                return {}
        if verbose:
            print('='*80)
            print(answer_json)
            print('='*80)
        return answer_json

    except Exception as e:
        print(e)
        print(colored(f"Failed to convert the JSON answer.\n{answer}\n------\n{json_answer}", "red"))
        return {}

# Method to extract the JSON information from the answer if the LLM outputs text before or after the json structure
def _get_only_json_from_answer(answer):
    try:
        # Extract the JSON information from the answer
        match = re.search(r'\{(.*)\}', answer, re.DOTALL)
        if match:
            json_answer = '{' + match.group(1) + '}'
        else:
            print(colored("Failed to extract the JSON information from the answer.", "red"))
            return {}
    except Exception as e:
        print(e)
        print(colored("Failed to parse the JSON information.", "red"))
        return {}
    return json_answer

# Method to process the risks of bias or prompt injections in the user provided solution description
def process_solution_risks_assessment(answer, verbose=False):
    json_answer = get_json_from_answer(answer, main_json='solutionassessment', verbose=verbose)

    try:
        solution_assessment = json_answer['solutionassessment']

        identified_bias = solution_assessment['identified_bias']
        identified_prompt_commands = solution_assessment['identified_prompt_commands']
        rewritten_solution_description = solution_assessment['rewritten_solution_description']

        return identified_bias, identified_prompt_commands, rewritten_solution_description

    except Exception as e:
        print(e)
        print(colored(f"Failed to process risks of bias or prompt injections.\n{answer}\n------\n{json_answer}", "red"))
        return [], [], ""

# Method to process the intended uses section
def process_intended_uses(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, verbose=False):
    json_answer = get_json_from_answer(answer, main_json='intendeduses', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        intended_use_list = json_answer['intendeduses'].copy()
        for intended_use_number in range(1, nbintendeduses+1):
            intended_use_number_str = str(intended_use_number).zfill(2)
            intended_use = intended_use_list.pop(0) if len(intended_use_list) > 0 else None
            if intended_use is not None:
                search_for.append("##INTENDED_USE_NAME_" + intended_use_number_str)
                replace_by.append(intended_use['name'])
                search_for.append("##INTENDED_USE_" + intended_use_number_str)
                replace_by.append(intended_use['name'])
                search_for.append("##INTENDED_USE_DESCRIPTION_" + intended_use_number_str)
                replace_by.append(intended_use['description'])
            else:
                search_for.append("##INTENDED_USE_NAME_" + intended_use_number_str)
                replace_by.append('')
                search_for.append("##INTENDED_USE_" + intended_use_number_str)
                replace_by.append('')
                search_for.append("##INTENDED_USE_DESCRIPTION_" + intended_use_number_str)
                replace_by.append('')

        intended_use_list = json_answer['intendeduses'].copy()   ## Keep a copy for the next prompt for sections (one section per intended use)
        for intended_use_number, intended_use in enumerate(intended_use_list):
            intended_use_number_str = str(intended_use_number+1).zfill(2)
            intended_use['id'] = intended_use_number_str
        if len(intended_use_list) > 10:
            intended_use_list = intended_use_list[:10]
        return json_answer, intended_use_list, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process intended uses.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], [], []

# Method to process the fitness for purpose section
def process_fitness_for_purpose(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='fitnessforpurpose', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        fitness_for_purpose_list = json_answer['fitnessforpurpose'].copy()
        for intended_use_number in range(1, nbintendeduses+1):
            intended_use_number_str = str(intended_use_number).zfill(2)
            fitness_for_purpose = fitness_for_purpose_list.pop(0) if len(fitness_for_purpose_list) > 0 else None
            if verbose:
                print(f'Processing fitness for purpose for intended use {intended_use_number_str} - {fitness_for_purpose}')
            if fitness_for_purpose is not None:
                search_for.append(f"##ASSESSMENT_OF_FITNESS_FOR_PURPOSE_IU{intended_use_number_str}")
                replace_by.append(fitness_for_purpose['fitness_for_purpose'])
            else:
                search_for.append(f"##ASSESSMENT_OF_FITNESS_FOR_PURPOSE_IU{intended_use_number_str}")
                replace_by.append('')

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process fitness for purpose.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the stakeholders section
def process_stakeholders(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='intendeduse_stakeholder', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        intendeduses_stakeholders = {}
        intended_use_stakeholders_list = json_answer['intendeduse_stakeholder'].copy()

        for intended_use_number in range(1, nbintendeduses+1):
            intended_use_number_str = str(intended_use_number).zfill(2)
            stakeholders_list = None
            for stakeholder in intended_use_stakeholders_list:
                if stakeholder["intendeduse_id"] == intended_use_number_str:
                    stakeholders_list = stakeholder["StakeHolders"]
                    break

            if stakeholders_list:
                stakeholders_names = [stakeholder['name'] for stakeholder in stakeholders_list]
                intendeduses_stakeholders.update({f'intended_use_{intended_use_number_str}': stakeholders_names})
            
            for stakeholder_id in range(1, 11):
                stakeholder_id_str = str(stakeholder_id).zfill(2)
                if stakeholders_list:
                    stakeholder = stakeholders_list[stakeholder_id-1] if stakeholders_list and len(stakeholders_list) >= stakeholder_id else None
                else:
                    stakeholder = None
                if stakeholder is not None:
                    if verbose:
                        print(f'Processing stakeholders for intended use {intended_use_number_str} - {stakeholder_id_str}')
                    search_for.append(f"##STAKEHOLDER_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append(stakeholder['name'])
                    search_for.append(f"##STAKEHOLDER_BENEFITS_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append(stakeholder['potential_solution_benefits'])
                    search_for.append(f"##STAKEHOLDER_HARMS_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append(stakeholder['potential_solution_harms'])
                else:
                    search_for.append(f"##STAKEHOLDER_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append('')
                    search_for.append(f"##STAKEHOLDER_BENEFITS_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append('')
                    search_for.append(f"##STAKEHOLDER_HARMS_{stakeholder_id_str}_IU{intended_use_number_str}")
                    replace_by.append('')

        return json_answer, intendeduses_stakeholders, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process stakeholders.\n{answer}\n------\n{json_answer}", "red"))
        return {}, {}, [], []

# Method to process the goals A5 and T3 section
def process_goals_a5_t3(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='intendeduse_answers' ,verbose=verbose)
    try:
        search_for = []
        replace_by = []
        goal_tag_mapping = {
            "GOAL_A5_Q1": "##HUMAN_OVERSIGHT_IU",
            "GOAL_A5_Q2": "##HUMAN_RESPONSIBILITIES_IU",
            "GOAL_T1_Q1": "##DECISIONMAKING_OUTPUTS_IU",
            "GOAL_T1_Q2": "##DECISIONMAKING_MADE_IU",
            "GOAL_T2_Q1": "##DECISIONMAKING_STAKEHOLDERS_IU",
            "GOAL_T2_Q2": "##DEVELOPDEPLOY_SOLUTION_IU",
            "GOAL_T3_Q1": "##DISCLOSURE_AND_AI_INTERACTION_IU"
        }
        main_key = 'intendeduse_answers'
        alternative_key = 'inteduse_answers'    # Mistral Large has a typo in the response
        if main_key in json_answer:
            intendeduse_answers_list = json_answer[main_key].copy()
        elif alternative_key in json_answer:
            intendeduse_answers_list = json_answer[alternative_key].copy()
        elif json_answer and json_answer.keys() and len(json_answer.keys()) > 0:
            oldKeyName = list(json_answer.keys())[0]  # Get the first key name
            print(colored(f'Replacing {oldKeyName} with {main_key} ({json_answer.keys()})', 'yellow'))
            json_answer[main_key] = json_answer.pop(oldKeyName)  # Rename key to main_json
            intendeduse_answers_list = json_answer[main_key].copy()
        else:
            print(colored(f"Failed to process goals A5, T2 and T3 main key.", "red"))
            return {}, [], []

        for intended_use_number in range(1, nbintendeduses+1):
            intended_use_number_str = str(intended_use_number).zfill(2)
            answers_list = None
            for answers in intendeduse_answers_list:
                answers_id_key = 'intendeduse_id' if 'intendeduse_id' in answers.keys() else 'inteduse_id' # Mistral Large has a typo in the response
                if answers[answers_id_key] == intended_use_number_str:
                    answers_list = answers["answers"]
                    break
            for goal_id in goal_tag_mapping.keys():
                if answers_list:
                    answer = next((answer['detailed_answer'] for answer in answers_list if answer['question_id'] == goal_id), None)
                else:
                    answer = None
                if answer is not None:
                    if verbose:
                        print(f'Processing goal {goal_id} for intended use {intended_use_number_str} and {goal_tag_mapping[goal_id]}{intended_use_number_str}')
                    search_for.append(f"{goal_tag_mapping[goal_id]}{intended_use_number_str}")
                    replace_by.append(answer)
                else:
                    search_for.append(f"{goal_tag_mapping[goal_id]}{intended_use_number_str}")
                    replace_by.append('')

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process goals A5, T1, T2 and T3.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the fairness goals F1, F2, F3 section
def process_fairness_goals(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='intendeduse_fairness_answers' ,verbose=verbose)
    try:
        search_for = []
        replace_by = []
        goal_tag_mapping = {
            "GOAL_F1_Q1": "##QUALITYOFSERVICE_STAKEHOLDERS_IU",
            "GOAL_F1_Q2": "##QUALITYOFSERVICE_PIORITIZED_IU",
            "GOAL_F1_Q3": "##QUALITYOFSERVICE_AFFECTED_IU",
            "GOAL_F2_Q1": "##ALLOCATION_STAKEHOLDERS_IU",
            "GOAL_F2_Q2": "##ALLOCATION_PRIORITIZED_IU",
            "GOAL_F2_Q3": "##ALLOCATION_AFFECTED_IU",
            "GOAL_F3_Q1": "##MINIMIZATION_STAKEHOLDERS_IU",
            "GOAL_F3_Q2": "##MINIMIZATION_PRIORITIZED_IU",
            "GOAL_F3_Q3": "##MINIMIZATION_AFFECTED_IU"
        }
        main_key = 'intendeduse_fairness_answers'
        alternative_key = 'inteduse_fairness_answers'    # Mistral Large has a typo in the response
        if main_key in json_answer:
            intendeduse_answers_list = json_answer[main_key].copy()
        elif alternative_key in json_answer:
            intendeduse_answers_list = json_answer[alternative_key].copy()
        elif json_answer and json_answer.keys() and len(json_answer.keys()) > 0:
            oldKeyName = list(json_answer.keys())[0]  # Get the first key name
            print(colored(f'Replacing {oldKeyName} with {main_key} ({json_answer.keys()})', 'yellow'))
            json_answer[main_key] = json_answer.pop(oldKeyName)  # Rename key to main_json
            intendeduse_answers_list = json_answer[main_key].copy()
        else:
            print(colored(f"Failed to process fairness goals F1, F2 and F3 main key.", "red"))
            return {}, [], []

        for intended_use_number in range(1, nbintendeduses+1):
            intended_use_number_str = str(intended_use_number).zfill(2)
            answers_list = None
            for answers in intendeduse_answers_list:
                answers_id_key = 'intendeduse_id' if 'intendeduse_id' in answers.keys() else 'inteduse_id' # Mistral Large has a typo in the response
                if answers[answers_id_key] == intended_use_number_str:
                    answers_list = answers["answers"]
                    break
            for goal_id in goal_tag_mapping.keys():
                if answers_list:
                    answer = next((answer['detailed_answer'] for answer in answers_list if answer['question_id'] == goal_id), None)
                else:
                    answer = None
                if answer is not None:
                    if verbose:
                        print(f'Processing goal {goal_id} for intended use {intended_use_number_str} and {goal_tag_mapping[goal_id]}{intended_use_number_str}')
                    search_for.append(f"{goal_tag_mapping[goal_id]}{intended_use_number_str}")
                    replace_by.append(answer)
                else:
                    search_for.append(f"{goal_tag_mapping[goal_id]}{intended_use_number_str}")
                    replace_by.append('N/A')

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process fairness goals F1, F2 and F3.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the solution scope section
def process_solution_scope(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='solutionscope', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        solution_scope = json_answer['solutionscope']
        search_for.append("##CURRENT_DEPLOYMENT_LOCATION")
        replace_by.append(solution_scope['current_deployment_location'])
        search_for.append("##UPCOMING_RELEASE_DEPLOYMENT_LOCATIONS")
        replace_by.append(solution_scope['upcoming_release_deployment_locations'])
        search_for.append("##FUTURE_DEPLOYMENT_LOCATIONS")
        replace_by.append(solution_scope['future_deployment_locations'])
        search_for.append("##CURRENT_SUPPORTED_LANGUAGES")
        replace_by.append(solution_scope['current_supported_languages'])
        search_for.append("##UPCOMING_RELEASE_SUPPORTED_LANGUAGES")
        replace_by.append(solution_scope['upcoming_release_supported_languages'])
        search_for.append("##FUTURE_SUPPORTED_LANGUAGES")
        replace_by.append(solution_scope['future_supported_languages'])
        search_for.append("##CURRENT_SOLUTION_DEPLOYMENT_METHOD")
        replace_by.append(solution_scope['current_solution_deployment_method'])
        search_for.append("##UPCOMING_RELEASE_SOLUTION_DEPLOYMENT_METHOD")
        replace_by.append(solution_scope['upcoming_release_solution_deployment_method'])
        search_for.append("##CLOUD_PLATFORM")
        replace_by.append(solution_scope['cloud_platform'])
        search_for.append("##DATA_REQUIREMENTS")
        replace_by.append(solution_scope['data_requirements'])
        search_for.append("##EXISTING_DATA_SETS")
        replace_by.append(solution_scope['existing_data_sets'])

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process solution scope.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the solution information section
def process_solution_assessment(answer, doc, rai_filepath, rai_public_filepath, intended_uses_list=[], nbintendeduses=10, verbose=False):

    def get_selected_id(assessment_answer):
        best_selection_id = assessment_answer.split('_')[-1]
        return str(best_selection_id).zfill(2)

    json_answer = get_json_from_answer(answer, main_json='intendeduse_assessment', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        intended_use_assessment_list = json_answer['intendeduse_assessment'].copy()

        for assessment in intended_use_assessment_list:
            intended_use_number_str = assessment["intendeduse_id"]
            assessment_list = assessment["assessment"]

            if not isinstance(assessment_list, list):
                assessment_list = [assessment_list]
            
            if verbose:
                print(f'Processing solution assessment for intended use {intended_use_number_str}')

            if len(assessment_list) > 0:
                assessment = assessment_list[0]
                technology_readiness_id = get_selected_id(assessment['technology_readiness_id'])
                task_complexity_id = get_selected_id(assessment['task_complexity_id'])
                role_of_humans_id = get_selected_id(assessment['role_of_humans_id'])
                deployment_environment_complexity_id = get_selected_id(assessment['deployment_environment_complexity_id'])
            else:
                technology_readiness_id = ''
                task_complexity_id = ''
                role_of_humans_id = ''
                deployment_environment_complexity_id = ''

            if verbose:
                if technology_readiness_id != '':
                    print(f"Technology readiness: {technology_readiness_id}")
                if task_complexity_id != '':
                    print(f"Task complexity: {task_complexity_id}")
                if role_of_humans_id != '':
                    print(f"Role of humans: {role_of_humans_id}")
                if deployment_environment_complexity_id != '':
                    print(f"Deployment environment complexity: {deployment_environment_complexity_id}")

            for id in range(1, 6):
                str_id = str(id).zfill(2)
                search_for.append(f"##TECH_ASSESSMENT_{str_id}_IU{intended_use_number_str}")
                answer_str = 'X' if str_id == technology_readiness_id else ''
                replace_by.append(answer_str)

            for id in range(1,4):
                str_id = str(id).zfill(2)
                search_for.append(f"##TASK_COMPLEXITY_{str_id}_IU{intended_use_number_str}")
                answer_str = 'X' if str_id == task_complexity_id else ''
                replace_by.append(answer_str)
            
            for id in range(1,6):
                str_id = str(id).zfill(2)
                search_for.append(f"##ROLE_OF_HUMAN_{str_id}_IU{intended_use_number_str}")
                answer_str = 'X' if str_id == role_of_humans_id else ''
                replace_by.append(answer_str)
            
            for id in range(1,4):
                str_id = str(id).zfill(2)
                search_for.append(f"##DEPLOYMENT_COMPLEXITY_{str_id}_IU{intended_use_number_str}")
                answer_str = 'X' if str_id == deployment_environment_complexity_id else ''
                replace_by.append(answer_str)

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process assessment.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the risk of use section
def process_risk_of_use(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='risksofuse', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        risk_of_use = json_answer['risksofuse']

        search_for.append("##RESTRICTED_USES")
        restricted_uses = risk_of_use['restricted_uses']
        if isinstance(restricted_uses, list):
            restricted_uses = '\n'.join(restricted_uses) + '\n'
        replace_by.append(restricted_uses)
        search_for.append("##UNSUPPORTED_USES")
        unsupported_uses = risk_of_use['unsupported_uses']
        if isinstance(unsupported_uses, list):
            unsupported_uses = '\n'.join(unsupported_uses) + '\n'
        replace_by.append(unsupported_uses)
        search_for.append("##KNOWN_LIMITATIONS")
        replace_by.append(risk_of_use['known_limitations'])
        search_for.append("##FAILURE_ON_STAKEHOLDERS")
        replace_by.append(f"{risk_of_use['potential_impact_of_failure_on_stakeholders']}\n\n##FAILURE_ON_STAKEHOLDERS")
        search_for.append("##MISUSE_ON_STAKEHOLDERS")
        replace_by.append(f"{risk_of_use['potential_impact_of_misuse_on_stakeholders']}\n\n##MISUSE_ON_STAKEHOLDERS")
        search_for.append("##SENSITIVE_USE_01")
        replace_by.append('  Yes' if risk_of_use['sensitive_use_1'] else '  No')
        search_for.append("##SENSITIVE_USE_02")
        replace_by.append('  Yes' if risk_of_use['sensitive_use_2'] else '  No')
        search_for.append("##SENSITIVE_USE_03")
        replace_by.append('  Yes' if risk_of_use['sensitive_use_3'] else '  No')

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process risk of use.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to get how to mitigate the identified harm
def get_harm_mitigation(harm_assessment_id):
    if harm_assessment_id == "01":
        return """Goal A2: Oversight of significant adverse impacts
Harms that result from Sensitive Uses must be mitigated by guidance received from the Office of Responsible AI’s Sensitive Uses team. Please report your system as a Sensitive Use. For Restricted Uses, see guidance.
"""
    elif harm_assessment_id == "02":
        return """Goal A3: Fit for purpose
This harm is mitigated by assessing whether the system is fit for purpose for this intended use by providing evidence, recognizing that there may be many valid ways in which to solve the problem.
        """
    elif harm_assessment_id == "03":
        return """Goal A4: Data governance and management
This harm is mitigated by ensuring that data used to train the system is correctly processed and appropriate based on the intended use, stakeholders, and geographic areas.
        """
    elif harm_assessment_id == "04":
        return """Goal A5: Human oversight and control
This harm can be mitigated by modifying system elements (like system UX, features, educational materials, etc.) so that the relevant stakeholders can effectively understand and fulfill their oversight responsibilities.
        """
    elif harm_assessment_id == "05":
        return """Goal T1: System intelligibility for decision making
This Goal applies to all AI systems when the intended use of the generated outputs is to inform decision making by or about people. 
This harm is mitigated by modifying system elements (like system UX, features, educational materials, etc.) so that the affected stakeholders can interpret system behavior effectively.
        """
    elif harm_assessment_id == "06":
        return """Goal T2: Communication to stakeholders
This harm is mitigated by providing stakeholders with relevant information about the system to inform decisions about when to employ the system or platform.
        """
    elif harm_assessment_id == "07":
        return """Goal T3:  Disclosure of AI interaction
This Goal applies to AI systems that impersonate interactions with humans, unless it is obvious from the circumstances or context of use that an AI system is in use; and AI systems that generate or manipulate image, audio, or video content that could falsely appear to be authentic.
This harm is mitigated by modifying system elements (like system UX, features, educational materials, etc.) so that the relevant stakeholders will understand the type of AI system they are interacting with or that the content they are exposed to is AI-generated.
        """
    elif harm_assessment_id == "08":
        return """Goal F1: Quality of Service
This Goal applies to AI systems when system users or people impacted by the system with different demographic characteristics might experience differences in quality of service that Microsoft can remedy by building the system differently.
This harm is mitigated by evaluating the data sets and the system then modifying the system to improve system performance for affected demographic groups while minimizing performance differences between identified demographic groups.
        """
    elif harm_assessment_id == "09":
        return """Goal F2: Allocation of resources and opportunities
This Goal applies to AI systems that generate outputs that directly affect the allocation of resources or opportunities relating to finance, education, employment, healthcare, housing, insurance, or social welfare.
This harm is mitigated by evaluating the data sets and the system then modifying the system to minimize differences in the allocation of resources and opportunities between identified demographic groups.
        """
    elif harm_assessment_id == "10":
        return """Goal F3:  Minimization of stereotyping, demeaning, and erasing outputs
This Goal applies to AI systems when system outputs include descriptions, depictions, or other representations of people, cultures, or society.
This harm is mitigated by a rigorous understanding of how different demographic groups are represented within the AI system and modifying the system to minimize harmful outputs.
        """
    elif harm_assessment_id == "11":
        return """Goal RS1: Reliability and safety guidance
This harm is mitigated by defining safe and reliable behavior for the system, ensuring that datasets include representation of key intended uses, defining operational factors and ranges that are important for safe & reliable behavior for the system, and communicating information about reliability and safety to stakeholders.
        """
    elif harm_assessment_id == "12":
        return """Goal RS2: Failures and remediations
This harm is mitigated by establishing failure management approaches for each predictable failure.
        """
    elif harm_assessment_id == "13":
        return """Goal RS3: Ongoing monitoring, feedback, and evaluation
This harm is mitigated by establishing system monitoring methods that allow the team to identify and review new uses, identify and troubleshoot issues, manage and maintain the system, and improve the system over time.
        """
    else:
        return ''

# Method to process the harms assessment section
def process_harms_assessment(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='harms_assessment', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        harms_assessment = json_answer['harms_assessment']
        for harm_id in range(1, 11):
            harm_id_str = str(harm_id).zfill(2)
            harm = harms_assessment.pop(0) if len(harms_assessment) > 0 else None
            if harm is not None:
                search_for.append(f"##HARM_{harm_id_str}")
                replace_by.append(harm['identified_harm'])
                search_for.append(f"##HARM_{harm_id_str}_GOAL")
                replace_by.append(harm['corresponding_goals'])
                mitigation_methods = []
                assessment = harm['assessment']
                for id in range(1, 14):
                    str_id = str(id).zfill(2)
                    if assessment[f'Q{id}']:
                        mitigation = get_harm_mitigation(str_id)
                        if mitigation:
                            mitigation_methods.append(mitigation)
                if mitigation_methods:
                    search_for.append(f"##HARM_{harm_id_str}_MITIGATION")
                    replace_by.append('------------------------\n'.join(mitigation_methods))
                else:
                    search_for.append(f"##HARM_{harm_id_str}_MITIGATION")
                    replace_by.append('')
            else:
                search_for.append(f"##HARM_{harm_id_str}")
                replace_by.append('')
                search_for.append(f"##HARM_{harm_id_str}_GOAL")
                replace_by.append('')
                search_for.append(f"##HARM_{harm_id_str}_MITIGATION")
                replace_by.append('')

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process harms assessment.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# Method to process the impact on stakeholders section
def process_impact_on_stakeholders(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='intendeduse_impactonstakeholders', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        impact_of_failure_text = ''
        impact_of_misuse_text = ''
        impact_on_stakeholders = json_answer['intendeduse_impactonstakeholders']

        for impact in impact_on_stakeholders:
            intendeduse_id = impact['intendeduse_id']
            if '_' in intendeduse_id:
                intendeduse_id = intendeduse_id.split('_')[-1]
            intended_use_number_str = str(intendeduse_id).zfill(2)
            intended_use_name = next((item['name'] for item in intended_uses_list if item['id'] == intended_use_number_str), None)
            impact_on_failure = impact['impact_on_stakeholders'][0]['potential_impact_of_failure_on_stakeholders']
            impact_on_misuse = impact['impact_on_stakeholders'][0]['potential_impact_of_misuse_on_stakeholders']
            impact_of_failure_text += f"{intended_use_name}:\n{impact_on_failure}\n\n"
            impact_of_misuse_text += f"{intended_use_name}:\n{impact_on_misuse}\n\n"

        impact_of_failure_text = impact_of_failure_text[:-2]    # remove last \n\n
        impact_of_misuse_text = impact_of_misuse_text[:-2]      # remove last \n\n
        search_for.append("##FAILURE_ON_STAKEHOLDERS")
        replace_by.append(impact_of_failure_text)
        search_for.append("##MISUSE_ON_STAKEHOLDERS")
        replace_by.append(impact_of_misuse_text)

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process impact on stakeholders.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []


# Method to process the disclosure of AI interaction section
def process_disclosure_of_ai_interaction(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='disclosureofaiinteraction', verbose=verbose)
    try:
        search_for = []
        replace_by = []
        disclosure_of_ai_interaction = json_answer['disclosureofaiinteraction']
        search_for.append("##DISCLOSURE_OF_AI_INTERACTION")
        replace_by.append('  Yes' if disclosure_of_ai_interaction['disclosure_of_ai_interaction_applies'] else '  No')
        search_for.append("##DISCLOSURE_OF_AI_INTERACTION_EXPLANATION")
        replace_by.append(disclosure_of_ai_interaction['explanation'])
        
        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process disclosure of AI interaction.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []

# {'solution_information': {'solution_name': 'AI-Powered Job Matching Platform', 'supplementary_informations': [{'name': 'Solution Demo', 'link': 'https://www.example.com/solution_demo'}, {'name': 'Solution Architecture Diagram', 'link': 'https://www.example.com/solution_architecture'}], 'existing_features': ['Voice-to-text transcription for candidate profile and job offer capture', 'AI-powered structuring of candidate profiles and job offers using Azure OpenAI GPT-4', 'Candidate and job offeror review and modification of AI-structured data', "Job matching using existing client's non-AI matching engine"], 'upcoming_features': ['Integration with additional languages', 'AI-powered job matching engine'], 'solution_relations': "The solution uses Azure OpenAI GPT-4 for AI-powered structuring of data and integrates with an existing client's non-AI matching engine for job matching."}}

# Method to process the solution information section
def process_solution_information(answer, doc, rai_filepath, rai_public_filepath, nbintendeduses=10, intended_uses_list=[], verbose=False):
    json_answer = get_json_from_answer(answer, main_json='solution_information', verbose=verbose)
    try:
        search_for = []
        replace_by = []

        solution_information = json_answer['solution_information']
        search_for.append("##SOLUTION_NAME")
        replace_by.append(solution_information['solution_name'])

        search_for.append("##SOLUTION_PURPOSE")     # This is used only by the Microsoft Public RAI template
        replace_by.append(solution_information['solution_purpose'])

        for id in range(1, 6):
            str_id = str(id).zfill(2)
            if id < len(solution_information['supplementary_informations']) + 1:
                if verbose:
                    print(f'Processing supplementary information {id}')
                search_for.append(f"##SUPPLEMENTARY_INFORMATION_{str_id}")
                replace_by.append(solution_information['supplementary_informations'][id-1]['name'])
                search_for.append(f"##SUPPLEMENTARY_INFORMATION_LINK_{str_id}")
                replace_by.append(solution_information['supplementary_informations'][id-1]['link'])
            else:
                search_for.append(f"##SUPPLEMENTARY_INFORMATION_{str_id}")
                replace_by.append('' if id > 1 or (id == 1 and len(solution_information['supplementary_informations']) > 0) else 'None')
                search_for.append(f"##SUPPLEMENTARY_INFORMATION_LINK_{str_id}")
                replace_by.append('' if id > 1 or (id == 1 and len(solution_information['supplementary_informations']) > 0) else 'None')

        for id in range(1, 11):
            str_id = str(id).zfill(2)
            if id < len(solution_information['existing_features']) + 1:
                if verbose:
                    print(f'Processing existing feature {id}')
                search_for.append(f"##EXISTING_FEATURE_{str_id}")
                replace_by.append(solution_information['existing_features'][id-1])
            else:
                search_for.append(f"##EXISTING_FEATURE_{str_id}")
                replace_by.append('' if id > 1 or (id == 1 and len(solution_information['supplementary_informations']) > 0) else 'None')

        for id in range(1, 11):
            str_id = str(id).zfill(2)
            if id < len(solution_information['upcoming_features']) + 1:
                if verbose:
                    print(f'Processing upcoming feature {id}')
                search_for.append(f"##UPCOMING_FEATURE_{str_id}")
                replace_by.append(solution_information['upcoming_features'][id-1])
            else:
                search_for.append(f"##UPCOMING_FEATURE_{str_id}")
                replace_by.append('' if id > 1 or (id == 1 and len(solution_information['supplementary_informations']) > 0) else 'None')

        search_for.append("##RELATION_TO_OTHER_FEATURES")
        replace_by.append(solution_information['solution_relations'])

        return json_answer, search_for, replace_by
    except Exception as e:
        print(e)
        print(colored(f"Failed to process solution information.\n{answer}\n------\n{json_answer}", "red"))
        return {}, [], []


# Method to process the solution description audit to detect bias or risks
def process_solution_description_security_analysis(solution_description, language='English', model=None, ui_hook=None, rebuildCache=False, min_sleep=0, max_sleep=0, verbose=False):
    total_completion_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    rewritten_solution_description = ""
    bias_or_risks_analysis = ""
    
    if model is None:
        model = completion_model

    # Update SYSTEM_PROMPT to include the language
    system_prompt = SYSTEM_PROMPT.replace(TARGET_LANGUAGE_PLACEHOLDER, language)

    prompt = SOLUTION_DESCRIPTION_SECURITY_ANALYSIS_PROMPT
    filled_prompt = prompt.replace(SOLUTION_DESCRIPTION_PLACEHOLDER, solution_description).replace(TARGET_LANGUAGE_PLACEHOLDER, language)

    uiprint(f'Auditing the Solution Description Bias or Risks with {"Mistral Large" if completion_model == "azureai" else completion_model} model', ui_hook=ui_hook)

    try:
        answer, completion_cost, input_tokens_number, output_tokens_number, cached_key_list = get_azure_openai_completion(
            filled_prompt,
            system_prompt,
            model=model,
            temperature=0.1,
            json_mode="text",
            rebuildCache=rebuildCache,
            min_sleep=min_sleep,
            max_sleep=max_sleep,
            compress=False,
            verbose=verbose
            )
        total_completion_cost += completion_cost
        total_input_tokens += input_tokens_number
        total_output_tokens += output_tokens_number

        identified_bias, identified_prompt_commands, rewritten_solution_description = process_solution_risks_assessment(answer, verbose=verbose)
    except Exception as e:
        print(e)
        print(colored("Failed to audit the solution description bias or risks.", 'red'))
        identified_bias = []
        identified_prompt_commands = []
        rewritten_solution_description = solution_description

    try:
        if identified_bias != []:
            bias_risks_analysis = "### Potential Bias in the solution description:\n"
            for bias in identified_bias:
                bias_risks_analysis += f"\n- {bias}"
            bias_or_risks_analysis += bias_risks_analysis
            bias_or_risks_analysis += "\n\n"
            
        if identified_prompt_commands != []:
            injection_risks_analysis = "### Potential Risks in the solution description:\n "
            for risk in identified_prompt_commands:
                injection_risks_analysis += f"\n- {risk}"
            bias_or_risks_analysis += injection_risks_analysis
            bias_or_risks_analysis += "\n\n"

        return bias_or_risks_analysis, total_completion_cost, rewritten_solution_description

    except Exception as e:
        print(e)
        print(colored("Failed to process the identified bias or risks.", 'red'))
        return '', 0, ''


# Method to process the solution description audit to provide feedback for enhancement
def process_solution_description_analysis(solution_description, language='English', model=None, ui_hook=None, rebuildCache=False, min_sleep=0, max_sleep=0, verbose=False):
    
    if model is None:
        model = completion_model

    # Update SYSTEM_PROMPT to include the language
    system_prompt = SYSTEM_PROMPT.replace(TARGET_LANGUAGE_PLACEHOLDER, language)
    prompt = SOLUTION_DESCRIPTION_ANALYSIS_PROMPT
    filled_prompt = prompt.replace(SOLUTION_DESCRIPTION_PLACEHOLDER, solution_description).replace(TARGET_LANGUAGE_PLACEHOLDER, language)
    
    uiprint(f'Auditing the Solution Description with {"Mistral Large" if completion_model == "azureai" else completion_model} model', ui_hook=ui_hook)

    try:
        answer, completion_cost, input_tokens_number, output_tokens_number, cached_key_list = get_azure_openai_completion(
            filled_prompt,
            system_prompt,
            model=model,
            temperature=0.4,
            json_mode="text",
            rebuildCache=rebuildCache,
            min_sleep=min_sleep,
            max_sleep=max_sleep,
            compress=False,
            verbose=verbose
            )
        total_completion_cost = completion_cost
        total_input_tokens = input_tokens_number
        total_output_tokens = output_tokens_number

        return answer, total_completion_cost
    except Exception as e:
        print(e)
        print(colored("Failed to audit the solution description.", 'red'))
        return '', 0


# Method to update the RAI Impact Assessment template tailored to the solution description
def update_rai_assessment_template(solution_description, rai_filepath, rai_public_filepath, language='English', model=None, ui_hook=None, rebuildCache=False, update_steps=False, min_sleep=0, max_sleep=0, compress=False, verbose=False):

    if model is None:
        model = completion_model

    sections = []
    total_completion_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    search_list = []
    replace_list = []
    search_replace_dict = {}

    doc = None
    doc_public = None
    uiprint(f'Preparing the RAI Assessment document', ui_hook=ui_hook)
    if update_steps:
        doc = docx_find_replace_text(rai_filepath, search_text_list=['##SOLUTION_DESCRIPTION'], replace_text_list=[solution_description], doc=doc, verbose=verbose)
        doc_public = docx_find_replace_text(rai_public_filepath, search_text_list=['##SOLUTION_DESCRIPTION'], replace_text_list=[solution_description], doc=doc_public, verbose=verbose)

    search_list += ['##SOLUTION_DESCRIPTION']
    replace_list += [solution_description]
    search_replace_dict['##SOLUTION_DESCRIPTION'] = solution_description

    # Update SYSTEM_PROMPT to include the language
    system_prompt = SYSTEM_PROMPT.replace(TARGET_LANGUAGE_PLACEHOLDER, language)

    step = 0
    intended_use_list = []
    intendeduses_stakeholders = {}

    steps = [
        ("intended Uses", INTENDED_USES_PROMPT, 0.1, "json", process_intended_uses),       # must be run first
        ("Solution Scope", SOLUTION_SCOPE_PROMPT, 0.1, "json", process_solution_scope),
        ("Solution Information",SOLUTION_INFORMATION_PROMPT, 0.1, "json", process_solution_information),
        ("Fitness for Purpose", FITNESS_FOR_PURPOSE_PROMPT, 0.2, "json", process_fitness_for_purpose),
        ("Stakeholders", STAKEHOLDERS_PROMPT, 0.4, "json", process_stakeholders),
        ("Goals A5 and T3", GOALS_A5_T3_PROMPT, 0.2, "json", process_goals_a5_t3),
        ("Fitness Goals", GOALS_FAIRNESS_PROMPT, 0.1, "json", process_fairness_goals),
        ("Solution Assessment", SOLUTION_INTENDEDUSE_ASSESSMENT_PROMPT, 0.1, "json", process_solution_assessment),
        ("Risks of Use", RISK_OF_USE_PROMPT, 0.1, "json", process_risk_of_use),
        ("Impact on Stakeholders", IMPACT_ON_STAKEHOLDERS_PROMPT, 0.3, "json", process_impact_on_stakeholders), # must be after RISK_OF_USE_PROMPT
        ("Harms Assessment", HARMS_ASSESMENT_PROMPT, 0.1, "json", process_harms_assessment),
        ("Disclosure of AI Interaction", DISCLOSURE_OF_AI_INTERACTION_PROMPT, 0.1, "json", process_disclosure_of_ai_interaction)
        ]

    for step_name, prompt, temperature, json_or_text, processor in steps:
        if  prompt == INTENDED_USES_PROMPT or (intended_use_list and prompt != INTENDED_USES_PROMPT):
            cached_key_list = []
            filled_prompt = prompt.replace(SOLUTION_DESCRIPTION_PLACEHOLDER, solution_description).replace(TARGET_LANGUAGE_PLACEHOLDER, language)
            filled_prompt = filled_prompt.replace(INTENDED_USES_PLACEHOLDER, json.dumps(intended_use_list))
            filled_prompt = filled_prompt.replace(INTENDED_USES_STAKEHOLDERS_PLACEHOLDER, json.dumps(intendeduses_stakeholders))
            try:
                step_message = f'\nStep {step+1} / {len(steps)}: Generating "{step_name}" with {"Mistral Large" if model == "azureai" else model}{" using llmlingua v2 compression" if compress else ""}'
                uiprint(step_message, ui_hook=ui_hook)
                answer, completion_cost, input_tokens_number, output_tokens_number, cached_key_list = get_azure_openai_completion(
                    filled_prompt,
                    system_prompt,
                    model=model,
                    temperature=temperature,
                    json_mode=json_or_text,
                    rebuildCache=rebuildCache,
                    min_sleep=min_sleep,
                    max_sleep=max_sleep,
                    compress=compress,
                    verbose=verbose
                    )
                total_completion_cost += completion_cost
                total_input_tokens += input_tokens_number
                total_output_tokens += output_tokens_number
            except Exception as e:
                print(e)
                print(colored("Failed to generate the model completion.", 'red'))
                delete_cache_entry(cached_key_list, verbose=True)
                return {}

            try:
                uiprint(f'Analyzing and Processing AI outputs', ui_hook=ui_hook, color='cyan')
                if prompt == INTENDED_USES_PROMPT:
                    json_answer, intended_use_list, search_for, replace_by = processor(answer, doc, rai_filepath, rai_public_filepath, verbose=verbose)

                    # Remove template pages with unusued intended uses
                    doc = docx_delete_all_between_searched_texts(rai_filepath, f'Intended use #{len(intended_use_list)+1}', 'Section 3: Adverse Impact', doc=doc, verbose=verbose)
                    doc_public = docx_delete_all_between_searched_texts(rai_public_filepath, f'Intended use #{len(intended_use_list)+1}', 'Section 3: Adverse impact', doc=doc_public, verbose=verbose)
                    if verbose:
                        pprint(intended_use_list)
                elif prompt == STAKEHOLDERS_PROMPT:
                    json_answer, intendeduses_stakeholders, search_for, replace_by = processor(answer, doc, rai_filepath, rai_public_filepath, verbose=verbose)
                else:
                    json_answer, search_for, replace_by = processor(answer, doc, rai_filepath, rai_public_filepath, intended_uses_list=intended_use_list, verbose=verbose)

                search_list += search_for
                replace_list += replace_by
                search_replace_dict.update(dict(zip(search_for, replace_by)))
                sections.append(json_answer)

                if update_steps:
                    step_search_replace_dict = dict(zip(search_for, replace_by))
                    doc = docx_find_replace_text_bydict(rai_filepath, search_replace_dict=step_search_replace_dict.copy(), search_prefix='##', doc=doc, verbose=verbose)
                    doc_public = docx_find_replace_text_bydict(rai_public_filepath, search_replace_dict=step_search_replace_dict.copy(), search_prefix='##', doc=doc_public, verbose=verbose)

            except Exception as e:
                print(e)
                print(colored(f"Failed to process {step_name}.", 'red'))
                delete_cache_entry(cached_key_list, verbose=True)
                return {}
        step += 1

    # Update the RAI Assessment document
    if not update_steps:
        print('\n')
        uiprint(f'Updating the RAI Assessment draft document ({len(search_list)} substitutions)', ui_hook=ui_hook, color='cyan')
        doc = docx_find_replace_text_bydict(rai_filepath, search_replace_dict=search_replace_dict.copy(), search_prefix='##', doc=doc, verbose=verbose)
        doc_public = docx_find_replace_text_bydict(rai_public_filepath, search_replace_dict=search_replace_dict.copy(), search_prefix='##', doc=doc_public, verbose=verbose)

    final_json = {}
    for section in sections:
        if section and section.keys():
            mainkey = list(section.keys())[0]
            if mainkey in final_json.keys():
                final_json[mainkey].update(section[mainkey])
            else:
                final_json[mainkey] = section[mainkey]
        else:
            print(colored(f"Section is empty or does not have a main key.\n{section}", 'red'))
    
    print('\n')
    uiprint(f'Total completion cost: {total_completion_cost:.4f} €', ui_hook=ui_hook, color='yellow')
    print(f'Total input tokens: {total_input_tokens}')
    print(f'Total output tokens: {total_output_tokens}')

    # print('='*80)
    # print(colored(f"Final JSON\n{final_json}", 'green'))

    return final_json
