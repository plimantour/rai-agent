"""HTMX-powered web UI for the RAI Assessment Copilot.

This module exposes a FastAPI application that mirrors the Streamlit experience
while keeping business logic in the shared helpers/prompts modules. Operators
can launch it with:

    uvicorn htmx_ui_main:app --host 0.0.0.0 --port 8001

The app expects the same Azure configuration (Key Vault, OpenAI deployments,
Blob Storage) used by the Streamlit UI.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import markdown
import requests
from fastapi import (BackgroundTasks, FastAPI, File,
                     HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from helpers.blob_cache import append_log_to_blob, get_from_keyvault, read_logs_blob_content
from helpers.docs_utils import (extract_text_from_input, generate_unique_identifier,
                                save_text_to_docx)
from helpers.logging_setup import get_logger, init_logging, set_log_level
from helpers.completion_pricing import is_reasoning_model, model_pricing_euros
from prompts.prompts_engineering_llmlingua import (get_last_reasoning_summary,
                                                   initialize_ai_models,
                                                   last_reasoning_fallback_used,
                                                   last_reasoning_summary_status,
                                                   last_used_responses_api,
                                                   process_solution_description_analysis,
                                                   set_reasoning_verbosity,
                                                   update_rai_assessment_template)

init_logging()
log = get_logger(__name__)

app = FastAPI(title="RAI Assessment Copilot (HTMX Edition)")

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ---------------------------------------------------------------------------
# Session & user management
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def _default_show_reasoning_summary() -> Optional[bool]:
    if "SHOW_REASONING_SUMMARY_DEFAULT" in os.environ:
        return _env_bool("SHOW_REASONING_SUMMARY_DEFAULT", True)
    return True


@dataclass
class AnalysisResult:
    html: str
    cost: float
    file_path: str
    reasoning_summary: Optional[str] = None


@dataclass
class GenerationResult:
    internal_path: str
    public_path: str
    zip_path: str
    cost: Optional[float] = None
    message: str = ""
    reasoning_summary: Optional[str] = None


@dataclass
class SessionState:
    use_cache: bool = True
    use_prompt_compression: bool = False
    show_reasoning_summary: Optional[bool] = field(default_factory=_default_show_reasoning_summary)
    selected_model: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-4o"))
    reasoning_level: str = "medium"
    reasoning_verbosity: str = "low"
    log_level: str = "None"
    analysis_result: Optional[AnalysisResult] = None
    generation_result: Optional[GenerationResult] = None
    messages: List[str] = field(default_factory=list)
    user_info: str = ""
    has_logged_access: bool = False
    cached_user: Optional['UserContext'] = None

    @property
    def reasoning_levels(self) -> List[str]:
        levels = ["low", "medium", "high"]
        if self.selected_model.lower().startswith("gpt-5"):
            levels.insert(0, "minimal")
        return levels


@dataclass
class UserContext:
    user_id: str
    display_name: str
    preferred_username: Optional[str]
    authorized: bool
    is_admin: bool


SESSION_STORE: Dict[str, SessionState] = {}
SESSION_LOCK = threading.Lock()
MODELS_INITIALIZED = False
MODELS_LOCK = threading.Lock()
ALLOW_LIST_CACHE: Dict[str, object] = {"value": set(), "timestamp": 0.0}
ALLOW_LIST_TTL = 300.0  # seconds
ADMIN_USERS = [name.strip() for name in os.getenv(
    "RAI_ADMIN_USERS",
    "Philippe Limantour;Philippe Limantour (NTO/NSO);Philippe Beraud"
).split(";") if name.strip()]


class LoginRequest(BaseModel):
    accessToken: str


def ensure_session(request: Request) -> Tuple[str, SessionState, bool]:
    session_id = request.cookies.get("rai_session")
    created = False
    with SESSION_LOCK:
        if not session_id or session_id not in SESSION_STORE:
            session_id = uuid.uuid4().hex
            SESSION_STORE[session_id] = SessionState()
            created = True
        session = SESSION_STORE[session_id]
    return session_id, session, created


def ensure_models_loaded() -> None:
    global MODELS_INITIALIZED
    if MODELS_INITIALIZED:
        return
    with MODELS_LOCK:
        if MODELS_INITIALIZED:
            return
        log.info("Initializing Azure OpenAI clients for HTMX UI")
        initialize_ai_models()
        MODELS_INITIALIZED = True


def _decode_principal(encoded: str) -> Optional[dict]:
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:  # pragma: no cover - depends on hosting platform
        log.warning("Failed to decode client principal: %s", exc)
        return None


def load_allow_list() -> List[str]:
    now = time.time()
    cached = ALLOW_LIST_CACHE["value"]
    if cached and now - ALLOW_LIST_CACHE["timestamp"] < ALLOW_LIST_TTL:
        return list(cached)
    entries: List[str] = []
    try:
        result = get_from_keyvault(['RAI-ASSESSMENT-USERS'])
        if result and 'RAI-ASSESSMENT-USERS' in result:
            entries = [item.strip() for item in result['RAI-ASSESSMENT-USERS'].split(';') if item.strip()]
    except Exception as exc:
        log.warning("Unable to retrieve allow list from Key Vault: %s", exc)
    if not entries:
        fallback = os.getenv("HTMX_FALLBACK_ALLOW_LIST", "")
        entries = [item.strip() for item in fallback.split(';') if item.strip()]
    ALLOW_LIST_CACHE["value"] = set(entries)
    ALLOW_LIST_CACHE["timestamp"] = now
    return entries


async def resolve_user(request: Request, session: SessionState) -> UserContext:
    principal_header = request.headers.get("x-ms-client-principal") or request.headers.get("X-MS-CLIENT-PRINCIPAL")
    payload = _decode_principal(principal_header) if principal_header else None

    user_id = None
    display_name = None
    preferred_username = None
    if payload:
        user_id = payload.get("userId") or payload.get("oid")
        display_name = payload.get("name") or payload.get("userDetails")
        preferred_username = payload.get("userPrincipalName")
    elif session.cached_user:
        return session.cached_user

    allow_dev_bypass = _env_bool("HTMX_ALLOW_DEV_BYPASS", False)
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", "") if client else ""
    is_local_request = client_host in {"127.0.0.1", "::1", "localhost"}

    # Local development fallback (explicit opt-in + local-only)
    if allow_dev_bypass and is_local_request and not user_id:
        user_id = os.getenv("HTMX_DEV_USER_ID")
        display_name = display_name or os.getenv("HTMX_DEV_USER_NAME")
        preferred_username = preferred_username or os.getenv("HTMX_DEV_USER_UPN")

    if allow_dev_bypass and not is_local_request and not user_id:
        log.warning("Dev auth bypass refused for non-local request from %s", client_host)

    if not user_id or not display_name:
        return UserContext(user_id="", display_name="", preferred_username=None, authorized=False, is_admin=False)

    allow_list = load_allow_list()
    authorized = display_name in allow_list or preferred_username in allow_list or user_id in allow_list
    is_admin = display_name in ADMIN_USERS
    user = UserContext(
        user_id=user_id,
        display_name=display_name,
        preferred_username=preferred_username,
        authorized=authorized,
        is_admin=is_admin,
    )
    session.cached_user = user
    return user


def pop_messages(session: SessionState, extra: Optional[List[str]] = None) -> List[str]:
    messages = list(session.messages)
    session.messages.clear()
    if extra:
        messages.extend(extra)
    return messages


def model_options_for_template(selected: str) -> List[dict]:
    options = []
    for name, pricing in model_pricing_euros.items():
        label = name
        try:
            label = f"{name} (in {pricing['Input']:.5f}€ / out {pricing['Output']:.5f}€)"
        except Exception:
            pass
        options.append({"name": name, "label": label})
    options.sort(key=lambda item: item["name"].lower())
    return options


def collect_system_log_files() -> List[Path]:
    log_dir = Path(os.getenv("APP_LOG_DIR", "./logs"))
    if not log_dir.exists():
        return []
    log_files = []
    for pattern in ("app.log", "app.log.*", "*.log"):
        log_files.extend(log_dir.glob(pattern))
    dedup = []
    seen = set()
    for item in log_files:
        try:
            resolved = item.resolve()
        except Exception:
            resolved = item
        if resolved in seen or not item.is_file():
            continue
        seen.add(resolved)
        dedup.append(item)
    return dedup


def build_system_logs_zip(files: List[Path]) -> Optional[bytes]:
    if not files:
        return None
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            try:
                zf.write(file_path, arcname=file_path.name)
            except Exception as exc:
                log.debug("Skipping log file %s: %s", file_path, exc)
    buffer.seek(0)
    return buffer.getvalue()


def render_dashboard(request: Request, session: SessionState, user: UserContext, *, partial: bool = False, extra_messages: Optional[List[str]] = None) -> HTMLResponse:
    messages = pop_messages(session, extra_messages)
    context = {
        "request": request,
        "session": session,
        "user": user,
        "model_options": model_options_for_template(session.selected_model),
        "analysis_result": session.analysis_result,
        "generation_result": session.generation_result,
        "messages": messages,
        "admin_downloads": {
            "system_logs": bool(collect_system_log_files()),
        },
        "current_year": time.gmtime().tm_year,
    }
    template_name = "htmx/partials/dashboard.html" if partial else "htmx/index.html"
    return TEMPLATES.TemplateResponse(template_name, context)


def render_login(request: Request, session: SessionState) -> HTMLResponse:
    messages = pop_messages(session)
    msal_config = {
        "clientId": os.getenv("AZURE_APP_REGISTRATION_CLIENT_ID", ""),
        "tenantId": os.getenv("AZURE_TENANT_ID", ""),
        "redirectUri": os.getenv("AZURE_REDIRECT_URI") or str(request.url_for("home")),
    }
    context = {
        "request": request,
        "session": session,
        "user": None,
        "messages": messages,
        "msal_config_json": json.dumps(msal_config),
        "current_year": time.gmtime().tm_year,
    }
    return TEMPLATES.TemplateResponse("htmx/login.html", context)


def _cookie_secure() -> bool:
    return _env_bool("HTMX_COOKIE_SECURE", True)


def register_access(session: SessionState, user: UserContext) -> None:
    if session.has_logged_access:
        return
    session.user_info = f"{user.display_name} - {user.user_id}"
    try:
        append_log_to_blob(f"{session.user_info} : Access granted (htmx)")
    except Exception as exc:
        log.debug("Failed to append access log: %s", exc)
    session.has_logged_access = True


class ProgressCollector:
    def __init__(self) -> None:
        self.messages: List[str] = []

    def hook(self, msg: str) -> None:
        self.messages.append(msg)


def extract_cost_from_messages(messages: List[str]) -> Optional[float]:
    pattern = re.compile(r"Total completion cost:\s*([0-9]+\.[0-9]+)")
    for message in reversed(messages):
        match = pattern.search(message)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def remove_file_safe(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as exc:
        log.debug("Failed to remove %s: %s", path, exc)


async def get_session_and_user(request: Request) -> Tuple[str, SessionState, bool, UserContext]:
    session_id, session, created = ensure_session(request)
    user = await resolve_user(request, session)
    return session_id, session, created, user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/auth/session")
async def establish_session(request: Request, payload: LoginRequest):
    session_id, session, created = ensure_session(request)
    access_token = (payload.accessToken or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="Missing access token")

    try:
        graph_response = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.RequestException as exc:
        log.warning("Graph profile lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="Failed to validate access token") from exc

    if graph_response.status_code >= 400:
        log.warning("Graph profile lookup returned %s", graph_response.status_code)
        raise HTTPException(status_code=401, detail="Invalid access token")

    profile = graph_response.json() or {}
    user_id = profile.get("id")
    display_name = profile.get("displayName")
    preferred_username = profile.get("userPrincipalName") or profile.get("mail")

    if not user_id or not display_name:
        raise HTTPException(status_code=401, detail="Incomplete profile information")

    allow_list = load_allow_list()
    authorized = display_name in allow_list or (preferred_username in allow_list if preferred_username else False) or user_id in allow_list
    is_admin = display_name in ADMIN_USERS
    user = UserContext(
        user_id=user_id,
        display_name=display_name,
        preferred_username=preferred_username,
        authorized=authorized,
        is_admin=is_admin,
    )

    session.cached_user = user
    session.user_info = f"{display_name} - {user_id}"
    session.has_logged_access = False

    messages = []
    if authorized:
        register_access(session, user)
        messages.append(f"Signed in as {display_name}.")
    else:
        messages.append("Sign-in succeeded, but your account is not on the allow list.")
    session.messages.extend(messages)

    response = JSONResponse({
        "authorized": authorized,
        "displayName": display_name,
        "preferredUsername": preferred_username,
    }, status_code=200 if authorized else 403)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized:
        if not user.user_id:
            response = render_login(request, session)
        else:
            context = {
                "request": request,
                "user": user,
                "current_year": time.gmtime().tm_year,
                "messages": pop_messages(session),
            }
            response = TEMPLATES.TemplateResponse("htmx/unauthorized.html", context)
        if created:
            response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
        return response

    ensure_models_loaded()
    register_access(session, user)
    set_reasoning_verbosity(session.reasoning_verbosity)

    response = render_dashboard(request, session, user, partial=False)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


@app.post("/options/general", response_class=HTMLResponse)
async def update_general_options(request: Request):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")
    form = await request.form()
    session.use_cache = "use_cache" in form
    session.use_prompt_compression = "use_prompt_compression" in form
    if session.show_reasoning_summary is not None:
        session.show_reasoning_summary = "show_reasoning_summary" in form
    session.messages.append("Options updated.")
    response = render_dashboard(request, session, user, partial=True)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


@app.post("/options/model", response_class=HTMLResponse)
async def update_model_options(request: Request):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    form = await request.form()
    selected_model = form.get("selected_model") or session.selected_model
    if selected_model not in model_pricing_euros:
        raise HTTPException(status_code=400, detail="Unknown model")
    messages: List[str] = []
    if selected_model != session.selected_model:
        session.selected_model = selected_model
        messages.append(f"Model set to {selected_model}.")
        try:
            append_log_to_blob(f"{session.user_info or user.display_name} : Changed LLM model to {selected_model}")
        except Exception as exc:
            log.debug("Unable to log model change: %s", exc)
    reasoning_level = form.get("reasoning_level") or session.reasoning_level
    if reasoning_level not in session.reasoning_levels:
        reasoning_level = session.reasoning_levels[0]
    if reasoning_level != session.reasoning_level:
        session.reasoning_level = reasoning_level
        messages.append(f"Reasoning effort set to {reasoning_level}.")
        try:
            append_log_to_blob(f"{session.user_info or user.display_name} : Changed reasoning effort to {reasoning_level}")
        except Exception:
            pass
    reasoning_verbosity = form.get("reasoning_verbosity") or session.reasoning_verbosity
    if reasoning_verbosity not in ("low", "medium", "high"):
        reasoning_verbosity = "low"
    if reasoning_verbosity != session.reasoning_verbosity:
        session.reasoning_verbosity = reasoning_verbosity
        set_reasoning_verbosity(reasoning_verbosity)
        messages.append(f"Reasoning verbosity set to {reasoning_verbosity}.")
        try:
            append_log_to_blob(f"{session.user_info or user.display_name} : Changed reasoning verbosity to {reasoning_verbosity}")
        except Exception:
            pass
    log_level = form.get("log_level") or "None"
    if log_level != session.log_level:
        session.log_level = log_level
        if log_level != "None":
            changed = set_log_level(log_level)
            messages.append(f"Log level changed to {log_level}{' (applied)' if changed else ''}.")
            try:
                append_log_to_blob(f"{session.user_info or user.display_name} : Changed log level to {log_level} (applied={changed})")
            except Exception:
                pass
        else:
            messages.append("Log level unchanged (None).")
    response = render_dashboard(request, session, user, partial=True, extra_messages=messages)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


def _write_temp_upload(upload: UploadFile) -> Path:
    upload.file.seek(0)
    data = upload.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    suffix = Path(upload.filename or "upload").suffix or ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def _extract_text_from_upload(upload: UploadFile) -> Tuple[str, str]:
    temp_path = _write_temp_upload(upload)
    try:
        filename_root, text = extract_text_from_input(str(temp_path))
    finally:
        remove_file_safe(str(temp_path))
    if not text:
        raise HTTPException(status_code=400, detail="Unable to read uploaded document")
    return filename_root, text


@app.post("/analysis", response_class=HTMLResponse)
async def analyze_solution(request: Request, file: UploadFile = File(...)):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")
    ensure_models_loaded()
    filename_root, text = _extract_text_from_upload(file)

    progress = ProgressCollector()
    rebuild_cache = not session.use_cache
    reasoning_effort = session.reasoning_level if is_reasoning_model(session.selected_model) else None
    try:
        append_log_to_blob(f"{session.user_info or user.display_name} : Analyze the solution description - {file.filename}")
    except Exception:
        pass

    analysis_text, completion_cost = process_solution_description_analysis(
        solution_description=text,
        model=session.selected_model,
        reasoning_effort=reasoning_effort,
        ui_hook=progress.hook,
        rebuildCache=rebuild_cache,
        min_sleep=1,
        max_sleep=2,
        verbose=False,
    )

    html_content = markdown.markdown(analysis_text or "", extensions=["fenced_code", "tables"]) if analysis_text else "<p>No analysis generated.</p>"
    output_dir = BASE_DIR / "rai-assessment-output"
    output_dir.mkdir(exist_ok=True)
    identifier = generate_unique_identifier()
    analysis_path = output_dir / f"{filename_root}_analysis_{identifier}.docx"
    saved = save_text_to_docx(analysis_text or "", str(analysis_path))
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save analysis result")

    reasoning_summary = None
    if session.show_reasoning_summary and is_reasoning_model(session.selected_model):
        reasoning_summary = get_last_reasoning_summary() or None
        if not reasoning_summary and last_reasoning_summary_status() == "empty":
            reasoning_summary = "Reasoning summary not returned for this request."

    session.analysis_result = AnalysisResult(
        html=html_content,
        cost=completion_cost,
        file_path=str(analysis_path),
        reasoning_summary=reasoning_summary,
    )
    session.messages.extend(progress.messages)
    response = render_dashboard(request, session, user, partial=True)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


@app.post("/generate", response_class=HTMLResponse)
async def generate_assessment(request: Request, file: UploadFile = File(...)):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")
    ensure_models_loaded()
    filename_root, text = _extract_text_from_upload(file)

    output_dir = BASE_DIR / "rai-assessment-output"
    output_dir.mkdir(exist_ok=True)
    identifier = generate_unique_identifier()

    masterfolder = BASE_DIR / "rai-template"
    rai_master_internal = masterfolder / "RAI Impact Assessment for RAIS for Custom Solutions - MASTER.docx"
    rai_master_public = masterfolder / "Microsoft-RAI-Impact-Assessment-Public-MASTER.docx"
    if not rai_master_internal.exists() or not rai_master_public.exists():
        raise HTTPException(status_code=500, detail="RAI template files are missing")

    internal_path = output_dir / f"{filename_root}_draftRAI_MsInternal_{identifier}.docx"
    public_path = output_dir / f"{filename_root}_draftRAI_{identifier}.docx"

    internal_path.write_bytes(rai_master_internal.read_bytes())
    public_path.write_bytes(rai_master_public.read_bytes())

    progress = ProgressCollector()
    rebuild_cache = not session.use_cache
    reasoning_effort = session.reasoning_level if is_reasoning_model(session.selected_model) else None
    compress_mode = session.use_prompt_compression

    try:
        append_log_to_blob(f"{session.user_info or user.display_name} : Generate draft RAI assessment - {file.filename}")
    except Exception:
        pass

    try:
        update_rai_assessment_template(
            solution_description=text,
            rai_filepath=str(internal_path),
            rai_public_filepath=str(public_path),
            model=session.selected_model,
            reasoning_effort=reasoning_effort,
            ui_hook=progress.hook,
            rebuildCache=rebuild_cache,
            min_sleep=1,
            max_sleep=2,
            compress=compress_mode,
            verbose=False,
        )
    except Exception as exc:
        log.exception("Generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(internal_path, arcname=internal_path.name)
        archive.write(public_path, arcname=public_path.name)
    zip_buffer.seek(0)
    zip_path = output_dir / f"{filename_root}_draftRAI_{identifier}.zip"
    zip_path.write_bytes(zip_buffer.read())

    reasoning_summary = None
    if session.show_reasoning_summary and is_reasoning_model(session.selected_model):
        summary = get_last_reasoning_summary()
        if summary:
            reasoning_summary = summary
        elif last_reasoning_summary_status() == "empty":
            reasoning_summary = "Reasoning summary not returned for this request."
    cost = extract_cost_from_messages(progress.messages)
    message = "Draft RAI Assessment generated successfully."
    session.generation_result = GenerationResult(
        internal_path=str(internal_path),
        public_path=str(public_path),
        zip_path=str(zip_path),
        cost=cost,
        message=message,
        reasoning_summary=reasoning_summary,
    )
    session.messages.extend(progress.messages)
    response = render_dashboard(request, session, user, partial=True)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


# ---------------------------------------------------------------------------
# Download & admin routes
# ---------------------------------------------------------------------------


def _prepare_download(session: SessionState, path: Optional[str], label: str) -> Path:
    if not path:
        raise HTTPException(status_code=404, detail=f"No {label} available for download")
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{label} not found on server")
    return file_path


@app.get("/download/analysis")
async def download_analysis(request: Request, background_tasks: BackgroundTasks):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not session.analysis_result:
        raise HTTPException(status_code=403, detail="Unauthorized")
    file_path = _prepare_download(session, session.analysis_result.file_path, "analysis document")
    filename = file_path.name
    background_tasks.add_task(remove_file_safe, str(file_path))
    session.analysis_result = None
    return FileResponse(str(file_path), filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/download/rai-internal")
async def download_internal(request: Request, background_tasks: BackgroundTasks):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not session.generation_result:
        raise HTTPException(status_code=403, detail="Unauthorized")
    file_path = _prepare_download(session, session.generation_result.internal_path, "internal draft")
    filename = file_path.name
    background_tasks.add_task(remove_file_safe, str(file_path))
    session.generation_result.internal_path = ""
    return FileResponse(str(file_path), filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/download/rai-public")
async def download_public(request: Request, background_tasks: BackgroundTasks):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not session.generation_result:
        raise HTTPException(status_code=403, detail="Unauthorized")
    file_path = _prepare_download(session, session.generation_result.public_path, "public draft")
    filename = file_path.name
    background_tasks.add_task(remove_file_safe, str(file_path))
    session.generation_result.public_path = ""
    return FileResponse(str(file_path), filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/download/rai-zip")
async def download_zip(request: Request, background_tasks: BackgroundTasks):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not session.generation_result:
        raise HTTPException(status_code=403, detail="Unauthorized")
    file_path = _prepare_download(session, session.generation_result.zip_path, "zip archive")
    filename = file_path.name
    background_tasks.add_task(remove_file_safe, str(file_path))
    session.generation_result.zip_path = ""
    return FileResponse(str(file_path), filename=filename, media_type="application/zip")


@app.get("/admin/download/logs")
async def download_logs(request: Request):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    logs = read_logs_blob_content() or ""
    response = PlainTextResponse(logs)
    response.headers["Content-Disposition"] = "attachment; filename=rai_logs.txt"
    return response


@app.get("/admin/download/system")
async def download_system_logs(request: Request):
    _, session, _, user = await get_session_and_user(request)
    if not user.authorized or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    files = collect_system_log_files()
    content = build_system_logs_zip(files)
    if not content:
        raise HTTPException(status_code=404, detail="No system logs available")
    stream = io.BytesIO(content)
    headers = {"Content-Disposition": "attachment; filename=system_logs.zip"}
    return StreamingResponse(stream, media_type="application/zip", headers=headers)


@app.post("/admin/cache/clear", response_class=HTMLResponse)
async def clear_cache(request: Request):
    session_id, session, created, user = await get_session_and_user(request)
    if not user.authorized or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    cache_path = BASE_DIR / "cache" / "completions_cache.pkl"
    if cache_path.exists():
        remove_file_safe(str(cache_path))
        session.messages.append("Cache cleared.")
        try:
            append_log_to_blob(f"{session.user_info or user.display_name} : Cleared cache")
        except Exception:
            pass
    else:
        session.messages.append("Cache file not found.")
    response = render_dashboard(request, session, user, partial=True)
    if created:
        response.set_cookie("rai_session", session_id, httponly=True, secure=_cookie_secure(), samesite="lax")
    return response


@app.get("/healthz", response_class=PlainTextResponse)
async def healthcheck():
    return PlainTextResponse("ok")


if __name__ == "__main__":
    import uvicorn  # type: ignore

    uvicorn.run("htmx_ui_main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8001")), reload=_env_bool("UVICORN_RELOAD", False))
