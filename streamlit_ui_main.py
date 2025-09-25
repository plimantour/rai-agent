# Philippe Limantour - March 2024 - June 2024

import streamlit as st
from streamlit_javascript import st_javascript
from msallogin_stcomponent import component_msal_login
import os
from helpers.logging_setup import init_logging, get_logger, set_log_level, get_current_log_level
# from prompts_engineering import update_rai_assessment_template, process_solution_description_analysis
from prompts.prompts_engineering_llmlingua import (
    update_rai_assessment_template,
    process_solution_description_analysis,
    initialize_ai_models,
    get_last_reasoning_summary,
    last_used_responses_api,
    set_reasoning_verbosity,
    last_reasoning_fallback_used,
    last_reasoning_summary_status,
)
from helpers.completion_pricing import model_pricing_euros, is_reasoning_model
from helpers.docs_utils import extract_text_from_upload, save_text_to_docx, generate_unique_identifier, generate_unique_identifier, get_filename_and_extension
from helpers.blob_cache import read_logs_blob_content, append_log_to_blob, get_from_keyvault
from helpers.user_auth import get_user_info, get_auth_info
from jinja2 import Environment, FileSystemLoader
import shutil
import io
import zipfile
from pathlib import Path
from datetime import datetime

MAX_STEPS = 23

build_time = os.getenv('BUILD_TIME')    # Get the build time from the environment variable set when creating the image with docker cmd
if build_time is not None:
    build_version = build_time
else:
    build_version = "21/06/2024 16h00"

class Progress:
    """Progress bar and Status update."""
    def __init__(self, number_of_steps: int):
        self.n = number_of_steps
        self.bar = st.progress(0)
        self.progress = 1
        self.message = ""
        self.message_container = st.empty()

    def display_progress(self, msg):
        if msg[:8] == 'Updating':
            previous_message = self.message
            self.message = f"{previous_message}   -   {msg}"
        else:
            self.message = f"{msg}"
        self.message_container.info(self.message)
        progress_percentage = min(self.progress / self.n, 1.0)
        self.bar.progress(progress_percentage)
        self.progress += 1
        if self.progress >= self.n:
            self.bar.empty()
            # Uncomment this line to remove the message container after completion
            # self.message_container.empty()    # We keep last message which displays total cost completion


# Method to display messages in the UI
def ui_hook(msg):
    st.toast(msg, icon='✔️')
    progress.display_progress(msg)
    

# Define a function to download the Draft RAI DOCX file
def download_docx():
    if st.session_state.rai_assessment_filepath != '':
        with open(st.session_state.rai_assessment_filepath, "rb") as file:
            rai_filename = os.path.basename(st.session_state.rai_assessment_filepath)
            append_log_to_blob(f'{st.session_state.user_info} : Downloading the AI-generated draft RAI Impact Assessment - {rai_filename}')
            st.markdown('<p>⚠️ Warning: <span style="color:orange;">This is an AI-generated draft RAI Impact Assessment</span><br/>⚠️ Warning: <span style="color:orange;">Please review and update the document as necessary before submission</span></p>', unsafe_allow_html=True)
            st.download_button("Download Microsoft Internal Draft RAI Impact Assessment", data=file.read(), file_name=rai_filename, key="download_doc_button", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", on_click=download_docx)
            if st.session_state.rai_assessment_filepath != '':
                if os.path.exists(st.session_state.rai_assessment_filepath):
                    os.remove(st.session_state.rai_assessment_filepath)
            st.session_state.rai_assessment_filepath = ''

def download_public_docx():
    if st.session_state.rai_assessment_public_filepath != '':
        with open(st.session_state.rai_assessment_public_filepath, "rb") as file:
            rai_public_filename = os.path.basename(st.session_state.rai_assessment_public_filepath)
            append_log_to_blob(f'{st.session_state.user_info} : Downloading the AI-generated draft RAI Impact Assessment - {rai_public_filename}')
            st.markdown('<p>⚠️ Warning: <span style="color:orange;">This is an AI-generated draft RAI Impact Assessment</span><br/>⚠️ Warning: <span style="color:orange;">Please review and update the document as necessary before submission</span></p>', unsafe_allow_html=True)
            st.download_button("Download Draft RAI Impact Assessment", data=file.read(), file_name=rai_public_filename, key="download_public_doc_button", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", on_click=download_public_docx)
            if st.session_state.rai_assessment_public_filepath != '':
                if os.path.exists(st.session_state.rai_assessment_public_filepath):
                    os.remove(st.session_state.rai_assessment_public_filepath)
            st.session_state.rai_assessment_public_filepath = ''

def download_docx_as_zip():
    filepaths_to_add = [st.session_state.rai_assessment_filepath, st.session_state.rai_assessment_public_filepath]

     # Create an in-memory byte stream
    zip_buffer = io.BytesIO()

    # Create a zip file in the byte stream
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filepath in filepaths_to_add:
            if filepath and os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    zip_file.writestr(os.path.basename(filepath), f.read())
    
    # Seek to the beginning of the stream
    zip_buffer.seek(0)
    
    rai_public_filename = os.path.basename(st.session_state.rai_assessment_public_filepath)
    rai_MSInternal_filename = os.path.basename(st.session_state.rai_assessment_filepath)
    append_log_to_blob(f'{st.session_state.user_info} : Downloading the AI-generated draft RAI Impact Assessments as a zip file - {rai_MSInternal_filename} and {rai_public_filename}')
    st.markdown('<p>⚠️ Warning: <span style="color:orange;">This is an AI-generated draft RAI Impact Assessment</span><br/>⚠️ Warning: <span style="color:orange;">Please review and update the document as necessary before submission</span></p>', unsafe_allow_html=True)

    # Use the byte stream as the data parameter for the download button
    st.download_button(
        label="Download Draft Microsot and Public RAI Assessments as ZIP",
        data=zip_buffer,
        file_name="draft_rai_assessments.zip",
        key="download_zip_button",
        mime="application/zip",
        on_click=download_docx_as_zip
    )



# Define a function to download the Analysis DOCX file
def download_analysis_docx():
    if st.session_state.rai_analysis_filepath != '':
        with open(st.session_state.rai_analysis_filepath, "rb") as file:
            rai_anaysis_filename = os.path.basename(st.session_state.rai_analysis_filepath)
            append_log_to_blob(f'{st.session_state.user_info} : Downloading the AI-generated Analysis ofthe solution description - {rai_anaysis_filename}')
            st.markdown('<p>⚠️ Warning: <span style="color:orange;">This is an AI-generated Anaysis of the solution description</span><br/>⚠️ Warning: <span style="color:orange;">Please review and update the document as necessary before submission</span></p>', unsafe_allow_html=True)
            st.download_button("Download Solution Description Analysis", data=file.read(), file_name=rai_anaysis_filename, key="download_analysis_button", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", on_click=download_analysis_docx)
            if st.session_state.rai_analysis_filepath != '':
                if os.path.exists(st.session_state.rai_analysis_filepath):
                    os.remove(st.session_state.rai_analysis_filepath)
            st.session_state.rai_analysis_filepath = ''

def log_parameter_change(param):
    append_log_to_blob(f'{st.session_state.user_info} : Changed parameter {param} to {st.session_state[param]}')

if __name__ == '__main__':

    # Initialize structured logging once
    init_logging()
    log = get_logger(__name__)
    log.info("Streamlit UI starting (build_version=%s)", build_version)

    st.set_page_config(
        page_title="Draft RAI Assessment",
        page_icon=":clipboard:",
        layout="wide",
        initial_sidebar_state="collapsed",  # Change the initial_sidebar_state to "collapsed"
    )

    # Get or create the session state
    if 'rai_assessment_filepath' not in st.session_state:
        st.session_state.rai_assessment_filepath = ''
    if 'rai_assessment_public_filepath' not in st.session_state:
        st.session_state.rai_assessment_public_filepath = ''
    if 'rai_analysis_filepath' not in st.session_state:
        st.session_state.rai_analysis_filepath = ''
    # if 'logs_file_path' not in st.session_state:
    #     st.session_state.logs_file_path = ''
    if 'user_info' not in st.session_state:
        st.session_state.user_info = ''
    if 'user_name' not in st.session_state:
        st.session_state.user_name = ''
    if 'first_run' not in st.session_state:
        st.session_state.first_run = True
    if 'users_list' not in st.session_state:
        st.session_state.users_list = ['wait for msal login']
    if 'app_initialized' not in st.session_state:
        st.session_state.app_initialized = False
    if 'selected_model' not in st.session_state:
        # Default to environment deployment or fallback to existing completion model (set after initialize_ai_models)
        st.session_state.selected_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-4o")
    if 'reasoning_level' not in st.session_state:
        st.session_state.reasoning_level = 'medium'
    if 'log_level_selection' not in st.session_state:
        st.session_state.log_level_selection = 'None'
    if 'show_reasoning_summary' not in st.session_state:
        # Default from env variable (SHOW_REASONING_SUMMARY_DEFAULT=true/false)
        env_default = os.getenv("SHOW_REASONING_SUMMARY_DEFAULT", "true").lower() in ("1","true","yes","on")
        st.session_state.show_reasoning_summary = env_default

    msal_config = {
        "clientId": os.getenv("AZURE_APP_REGISTRATION_CLIENT_ID"),
        "tenantId": os.getenv("AZURE_TENANT_ID"),
        "redirectUri": os.getenv("AZURE_REDIRECT_URI"),
    }
    # print(f"msal_config: {msal_config}")

    # Check the initialization status
    if not st.session_state.app_initialized:
        # The app is still loading, display a loading message or prevent certain actions
        st.error("Loading... Please wait until the app is fully loaded.")
    
    def run_component(props):
        value = component_msal_login(key='msal_login', **props)
        return value
    def handle_event(value):
        # st.header('Streamlit')
        # st.write('Received from component_msal_login: ', value)
        if value and 'userInfo' in value:
            if value['userInfo'] is not None:
                displayName = value['userInfo']['displayName'] if "displayName" in value['userInfo'] else "Unknown"
                givenName = value['userInfo']['givenName'] if "givenName" in value['userInfo'] else "Unknown"
                user_id = value['userInfo']['id'] if "id" in value['userInfo'] else "Unknown"
                authInfo = value['userInfo']
                st.session_state.user_info = f'{displayName} - {user_id}'
                st.session_state.user_name = displayName
                st.write(f"Welcome, {displayName}! - Please wait while the app is loading...")
                return displayName
            else:
                st.write("Authentication failed")
                return ''
        return ''

    # auth_info, user_id, name, preferred_username = get_user_info(verbose=True)
    auth_info = get_auth_info(verbose=False)

    name = st.session_state.user_name

    # st.write(f"name: {st.session_state.user_name}")
    # st.write(f"users_list: {st.session_state.users_list}")
    # st.write(f"app_initialized: {st.session_state.app_initialized}")

    if st.session_state.app_initialized:

        if st.session_state.user_name not in st.session_state.users_list:

            st.session_state.user_name = handle_event(run_component(msal_config)) # Call the component to display the login page
            if st.session_state.user_name:
                retrievedDict = get_from_keyvault(['RAI-ASSESSMENT-USERS'])
                st.session_state.users_list = retrievedDict['RAI-ASSESSMENT-USERS'].split(';')
                initialize_ai_models()

            if st.session_state.user_name in st.session_state.users_list:
                # reload the page to display the app
                st.rerun()

        else:

            if st.session_state.first_run:
                st.session_state.first_run = False
                st.session_state.user_info = st.session_state.user_info
                append_log_to_blob(f'{st.session_state.user_info} : Access granted')

            # Information displayed on the collapsable side bar
            with st.sidebar:

                if st.session_state.user_name is not None:
                    st.session_state.user_info = st.session_state.user_info
                    st.markdown(f"<br/><b><small>Welcome {st.session_state.user_name}</small></b><br/>", unsafe_allow_html=True)

                use_cache = st.radio(
                    "Choose to use cached answers",
                    ("Use cached answers", "Do not use cached answers"),
                    on_change=log_parameter_change, args=("use_cache",),
                    key="use_cache"
                )

                use_prompt_compression = st.radio(
                    "Choose to use prompt compression",
                    ("Do not use prompt compression", "Use prompt compression"),
                    on_change=log_parameter_change, args=("use_prompt_compression",),
                    key="use_prompt_compression"
                )

                st.markdown(f"<br/><small><i>Developed by Philippe Limantour - March 2024<br>Version {build_version}</i></small>", unsafe_allow_html=True)

                if st.session_state.user_name in ["Philippe Limantour", "Philippe Limantour (NTO/NSO)", "Philippe Beraud"]:
                    st.markdown(f'<b><i><span style="color:orange;"><small>Admin access - version {build_version}</small></span></i></b>', unsafe_allow_html=True)

                    # Admin model selector
                    # Build a concise label with pricing info (input/output per 1K) for quick comparison
                    def _format_model_option(m, meta):
                        try:
                            return f"{m} (in {meta['Input']:.5f}€ / out {meta['Output']:.5f}€)"
                        except Exception:
                            return m
                    model_options = list(model_pricing_euros.keys())
                    # Keep current selection if still valid
                    if st.session_state.selected_model not in model_options:
                        st.session_state.selected_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", model_options[0])

                    formatted_options = { _format_model_option(m, model_pricing_euros[m]): m for m in model_options }
                    selected_label = next((lbl for lbl, mdl in formatted_options.items() if mdl == st.session_state.selected_model), None)
                    new_label = st.selectbox(
                        "AI model (admin)",
                        options=list(formatted_options.keys()),
                        index=list(formatted_options.keys()).index(selected_label) if selected_label else 0,
                        help="Select the Azure OpenAI (or compatible) deployment model to use for new generations. Pricing shown per 1K tokens (input/output).",
                        key="selected_model_label"
                    )
                    # Map back to raw model name
                    new_model = formatted_options[new_label]
                    if new_model != st.session_state.selected_model:
                        st.session_state.selected_model = new_model
                        msg = f"{st.session_state.user_info} : Changed LLM model to {new_model}"
                        append_log_to_blob(msg)
                        log.info(msg)
                        st.toast(f"Model set to {new_model}", icon="🤖")

                    # Reasoning effort submenu (only when reasoning-capable model selected)
                    if is_reasoning_model(st.session_state.selected_model):
                        # GPT-5 family supports 'minimal' in addition to low/medium/high
                        if st.session_state.selected_model.startswith("gpt-5"):
                            effort_options = ["minimal", "low", "medium", "high"]
                        else:
                            effort_options = ["low", "medium", "high"]
                        if st.session_state.reasoning_level not in effort_options:
                            # Reset to medium if previous value invalid under new model
                            st.session_state.reasoning_level = "medium"
                        reasoning_choice = st.selectbox(
                            "Reasoning effort",
                            options=effort_options,
                            index=effort_options.index(st.session_state.reasoning_level),
                            help="Effort for reasoning models (higher = more reasoning tokens, cost & latency). GPT-5 adds 'minimal'.",
                            key="reasoning_effort_select"
                        )
                        if reasoning_choice != st.session_state.reasoning_level:
                            st.session_state.reasoning_level = reasoning_choice
                            msg = f"{st.session_state.user_info} : Changed reasoning effort to {reasoning_choice}"
                            append_log_to_blob(msg)
                            log.info(msg)
                            st.toast(f"Reasoning effort: {reasoning_choice}", icon="🧠")

                        # Reasoning verbosity (always available for reasoning models)
                        if 'reasoning_verbosity' not in st.session_state:
                            st.session_state.reasoning_verbosity = 'low'
                        verbosity_choice = st.selectbox(
                            "Reasoning verbosity",
                            options=["low", "medium", "high"],
                            index=["low", "medium", "high"].index(st.session_state.reasoning_verbosity),
                            help="Controls conciseness of final answer for reasoning models (higher = more verbose output).",
                            key="reasoning_verbosity_select"
                        )
                        if verbosity_choice != st.session_state.reasoning_verbosity:
                            st.session_state.reasoning_verbosity = verbosity_choice
                            set_reasoning_verbosity(verbosity_choice)
                            msg = f"{st.session_state.user_info} : Changed reasoning verbosity to {verbosity_choice}"
                            append_log_to_blob(msg)
                            log.info(msg)
                            st.toast(f"Reasoning verbosity: {verbosity_choice}", icon="🗣️")
                        else:
                            # Ensure prompts module remains in sync
                            set_reasoning_verbosity(st.session_state.reasoning_verbosity)

                    # Dynamic log level selection
                    log_levels = ["None", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                    selected_level = st.selectbox(
                        "Log level (admin)",
                        options=log_levels,
                        index=log_levels.index(st.session_state.log_level_selection) if st.session_state.log_level_selection in log_levels else 0,
                        help="Select a log level to apply immediately. 'None' keeps current level.",
                        key="log_level_select"
                    )
                    if selected_level != st.session_state.log_level_selection and selected_level != "None":
                        changed = set_log_level(selected_level)
                        st.session_state.log_level_selection = selected_level
                        msg = f"{st.session_state.user_info} : Changed log level to {selected_level} (applied={changed})"
                        append_log_to_blob(msg)
                        log.info(msg)
                        st.toast(f"Log level: {selected_level}", icon="🪵")
                    st.caption(f"Current effective log level: {get_current_log_level()}")

                    # System Logs (lazy zip creation on click)
                    def build_system_logs_zip() -> tuple[bytes | None, str | None]:
                        try:
                            log_dir = os.getenv("APP_LOG_DIR", "./logs")
                            syslog_files = []
                            if Path(log_dir).is_dir():
                                for pattern in ["app.log", "app.log.*", "*.log"]:
                                    syslog_files.extend([p for p in Path(log_dir).glob(pattern) if p.is_file()])
                            # Deduplicate while preserving order
                            seen = set()
                            dedup_files = []
                            for f in syslog_files:
                                try:
                                    resolved = f.resolve()
                                except Exception:
                                    resolved = f
                                if resolved not in seen:
                                    seen.add(resolved)
                                    dedup_files.append(f)
                            if not dedup_files:
                                return None, "No system logs found."
                            buf = io.BytesIO()
                            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                                for lf in dedup_files:
                                    try:
                                        zf.write(lf, arcname=lf.name)
                                    except Exception as ie:
                                        log.debug("Skip log file %s: %s", lf, ie)
                            buf.seek(0)
                            return buf.getvalue(), None
                        except Exception as e:
                            return None, f"System log packaging error: {e}"

                    # Single-click timestamped system logs download (generate zip just-in-time)
                    _zip_bytes, _zip_msg = build_system_logs_zip()
                    if _zip_bytes:
                        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                        st.sidebar.download_button(
                            "Download System Logs",
                            data=_zip_bytes,
                            file_name=f"system_logs_{ts}.zip",
                            key="download_system_logs_zip",
                            mime="application/zip"
                        )
                    else:
                        st.sidebar.caption(_zip_msg or "No system logs available.")

                    # Existing access / blob logs (inline like before)
                    st.sidebar.download_button("Download Access Logs", data=read_logs_blob_content(), file_name="rai_logs.txt", key="download_logs", mime="application/txt")

                    # Reasoning summary display toggle (admin)
                    reasoning_toggle = st.checkbox(
                        "Show reasoning summary (admin)",
                        value=st.session_state.show_reasoning_summary,
                        help="Display truncated reasoning steps (if provided by reasoning models). Non-admin users inherit this setting.",
                        key="show_reasoning_summary_checkbox"
                    )
                    if reasoning_toggle != st.session_state.show_reasoning_summary:
                        st.session_state.show_reasoning_summary = reasoning_toggle
                        msg = f"{st.session_state.user_info} : Toggled reasoning summary display to {reasoning_toggle}"
                        append_log_to_blob(msg)
                        log.info(msg)

                if st.session_state.user_name in ["Philippe Limantour", "Philippe Limantour (NTO/NSO)"]:
                    if st.button("Clear cache"):
                        try:
                            os.remove('./cache/completions_cache.pkl')
                            st.success("Cache cleared")
                            append_log_to_blob(f'{st.session_state.user_info} : Cleared Cache')
                        except Exception as e:
                            st.error(f"Error clearing cache: {e}")


            st.markdown(
                f"""
                # Responsible AI Assessment for Custom Solutions
                """,
                unsafe_allow_html=True,
            )
            st.markdown("Upload the solution description document to generate a draft version of the RAI Impact Assessment for RAIS for Custom Solutions")
            st.markdown("Generate and Download an AI-generated RAI impact analysis draft. It may take 10 to 15 minutes to generate the draft.")
            st.warning("This draft will be generated by an AI: please review and update the document as necessary before submission.")

            verbose = False


            uploaded_file = st.file_uploader("Choose a file", type=['docx'])

            if uploaded_file is not None:

                # Get text from the uploaded input file
                try:
                    text, uploaded_filename = extract_text_from_upload(uploaded_file)
                    uploaded_filename_root, _ = get_filename_and_extension(uploaded_filename)
                except Exception as e:
                    if 'zip' in e:
                        st.error(f"Error reading input file: {e}. Check if file is not encrypted.")
                    text = None

                if not text:
                    st.error("Could not read input file")

                if st.button('Analyze the solution description'):     # Button to trigger the audit of the solution description
                    append_log_to_blob(f'{st.session_state.user_info} : Analyze the solution description - {uploaded_filename}')
                    log.info("Analyze triggered model=%s reasoning=%s file=%s", st.session_state.get('selected_model'), st.session_state.get('reasoning_level'), uploaded_filename)
                    progress = Progress(number_of_steps=1)  # Progress bar and status update
                    rebuildCache = True if use_cache == "Do not use cached answers" else False
                    audit_feedback, completion_cost = process_solution_description_analysis(
                        solution_description=text,
                        model=st.session_state.get('selected_model'),
                        reasoning_effort=st.session_state.get('reasoning_level'),
                        ui_hook=ui_hook,
                        rebuildCache=rebuildCache,
                        min_sleep=1,
                        max_sleep=2,
                        verbose=verbose)
                    st.write("")
                    st.markdown(audit_feedback)
                    st.markdown(f"<small><i>Total cost of completion: {completion_cost:.4f} €</i></small><br/>", unsafe_allow_html=True)
                    # Show reasoning summary if enabled and model is reasoning
                    if st.session_state.show_reasoning_summary and is_reasoning_model(st.session_state.get('selected_model')):
                        reasoning_summary = get_last_reasoning_summary()
                        label_suffix = " (Responses API)" if last_used_responses_api() else ""
                        status = last_reasoning_summary_status()
                        fallback_used = last_reasoning_fallback_used()
                        status_suffix = ""
                        if fallback_used and not reasoning_summary:
                            status_suffix = " (fallback detailed retry)"
                        header = f"Reasoning Summary{label_suffix}{status_suffix}"
                        with st.expander(header):
                            if reasoning_summary:
                                st.markdown(f"```text\n{reasoning_summary}\n```")
                            else:
                                if status == 'empty':
                                    st.write("Reasoning part present but summary array was empty (service returned no condensed reasoning).")
                                else:
                                    st.write("No reasoning summary returned (auto + detailed). Not guaranteed every request.")
                    st.warning("This is an AI-generated analysis: please review and update the solution description document as necessary before generating the draft RAI Impact Assessment.")
                    st.markdown("<br/>", unsafe_allow_html=True)

                    # Generate the unique identifier using MD5 hash to allow multiple users to generate RAI Impact Assessments at the same time
                    identifier = generate_unique_identifier()
                    analysis_doc_file_path = os.path.join(os.getcwd(), 'rai-assessment-output', f'{uploaded_filename_root}_analysis_{identifier}.docx')
                    saved = save_text_to_docx(audit_feedback, analysis_doc_file_path)
                    if saved:
                        st.session_state.rai_analysis_filepath = analysis_doc_file_path
                        download_analysis_docx()
                    else:
                        st.error("Error saving analysis to docx file")

                if st.button('Generate RAI Impact Assessment'):     # Button to trigger the RAI Impact Assessment generation

                    progress = Progress(number_of_steps=MAX_STEPS)  # Progress bar and status update
                    
                    # Prepare output folder
                    masterfolder = os.path.join(os.getcwd(), 'rai-template')
                    inputoutputfolder = os.path.join(os.getcwd(), 'rai-assessment-output')
                    if not os.path.exists(inputoutputfolder):
                        os.makedirs(inputoutputfolder)

                    # Generate the unique identifier using MD5 hash to allow multiple users to generate RAI Impact Assessments at the same time
                    identifier = generate_unique_identifier()
                    
                    # Copy the RAI template to the output folder
                    rai_master_filepath = os.path.join(masterfolder, 'RAI Impact Assessment for RAIS for Custom Solutions - MASTER.docx')
                    rai_filepath = os.path.join(inputoutputfolder, f'{uploaded_filename_root}_draftRAI_MsInternal_{identifier}.docx')
                    st.session_state.rai_assessment_filepath = rai_filepath
                    try:
                        shutil.copy(rai_master_filepath, rai_filepath)  # Copy the master RAI file template to the output folder
                    except Exception as e:
                        st.error(f"Error copying master rai file: {e}")

                    # Copy the public (customer approved) RAI template to the output folder
                    rai_master_filepath = os.path.join(masterfolder, 'Microsoft-RAI-Impact-Assessment-Public-MASTER.docx')
                    rai_public_filepath = os.path.join(inputoutputfolder, f'{uploaded_filename_root}_draftRAI_{identifier}.docx')
                    st.session_state.rai_assessment_public_filepath = rai_public_filepath
                    try:
                        shutil.copy(rai_master_filepath, rai_public_filepath)  # Copy the public (customer approved) master RAI file template to the output folder
                    except Exception as e:
                        st.error(f"Error copying public master rai file: {e}")

                    if not text:
                        st.error("Error reading input file")
                    else:
                        append_log_to_blob(f'{st.session_state.user_info} : Generate draft RAI assessment - {uploaded_filename}')
                        log.info("Generation triggered model=%s reasoning=%s file=%s", st.session_state.get('selected_model'), st.session_state.get('reasoning_level'), uploaded_filename)
                        st.session_state.rai_analysis_filepath = ''
                        # Get the completion from Azure OpenAI to update the RAI template
                        rebuildCache = True if use_cache == "Do not use cached answers" else False
                        compressMode = True if use_prompt_compression == "Use prompt compression" else False
                        json = update_rai_assessment_template(
                            solution_description=text,
                            rai_filepath=rai_filepath,
                            rai_public_filepath=rai_public_filepath,
                            model=st.session_state.get('selected_model'),
                            reasoning_effort=st.session_state.get('reasoning_level'),
                            ui_hook=ui_hook,
                            rebuildCache=rebuildCache,
                            min_sleep=1,
                            max_sleep=2,
                            compress=compressMode,
                            verbose=verbose)

                        st.write("RAI Impact Assessment for RAIS for Custom Solutions generated successfully")

                        download_docx_as_zip()  # Call the function to display the download button for both RAI Impact Assessments as a zip file
                        # Show reasoning summary after full generation (final step reasoning often most informative)
                        if st.session_state.show_reasoning_summary and is_reasoning_model(st.session_state.get('selected_model')):
                            reasoning_summary = get_last_reasoning_summary()
                            label_suffix = " (Responses API)" if last_used_responses_api() else ""
                            status = last_reasoning_summary_status()
                            fallback_used = last_reasoning_fallback_used()
                            status_suffix = ""
                            if fallback_used and not reasoning_summary:
                                status_suffix = " (fallback detailed retry)"
                            header = f"Reasoning Summary{label_suffix}{status_suffix}"
                            with st.expander(header):
                                if reasoning_summary:
                                    st.markdown(f"```text\n{reasoning_summary}\n```")
                                else:
                                    if status == 'empty':
                                        st.write("Reasoning part present but summary array was empty (service returned no condensed reasoning).")
                                    else:
                                        st.write("No reasoning summary returned (auto + detailed). Not guaranteed every request.")

    st.session_state.app_initialized = True