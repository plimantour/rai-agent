
# Philippe Limantour - March 2024
# This file contains the prompts for drafting a Responsible AI Assessment from a solution description

try:  # Optional dependency (python-dotenv)
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # Graceful fallback so tests don't skip solely due to missing optional dependency
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        try:
            print("[warn] python-dotenv not installed; proceeding without loading .env file")
        except Exception:
            pass
        return False

"""
NOTE ON IMPORT STRATEGY
-----------------------
Heavy / environment-specific dependencies (Azure identity & Key Vault) are imported lazily
inside initialize_ai_models() so that simply importing this module for lightweight operations
(e.g., unit tests that mock network calls) does not require the Azure SDK stack to be present.

If you need Azure functionality, ensure 'azure-identity' and 'azure-keyvault-secrets' are
installed before calling initialize_ai_models().
"""

# Docs / docx utilities import (optional for reasoning path). Provide no-op stubs if unavailable.
try:
    from helpers.docs_utils import docx_find_replace_text, docx_find_replace_text_bydict, docx_delete_all_between_searched_texts
except Exception:  # pragma: no cover
    def docx_find_replace_text(*_a, **_k):
        return 0
    def docx_find_replace_text_bydict(*_a, **_k):
        return 0
    def docx_delete_all_between_searched_texts(*_a, **_k):
        return 0

# llmlingua is only needed if prompt compression is enabled; provide a lightweight stub if missing
try:
    from llmlingua import PromptCompressor  # type: ignore
except ImportError:  # pragma: no cover
    class PromptCompressor:  # type: ignore
        def __init__(self, *_, **__):
            # Stub: no heavy model load; informs via log once when used
            try:
                print("[warn] llmlingua not installed - compression stub active (no real compression performed)")
            except Exception:
                pass
        def compress_prompt(self, text, rate=0.33, *_, **__):
            # Return original text pretending minimal compression so downstream accounting still works
            return {
                "compressed_prompt": text,
                "compressed_tokens": len(text.split()),
                "origin_tokens": len(text.split()),
            }
import random
import time
# OpenAI import (lazy / test-friendly): provide a lightweight stub if package missing so that
# mock-based unit tests can still import this module without installing openai.
try:  # pragma: no cover
    import openai  # type: ignore
except ImportError:  # pragma: no cover
    class _OpenAIResponsesStub:
        def create(self, **_kwargs):
            raise ImportError("openai package not installed; install 'openai' for live requests or provide a test monkeypatch for responses.create().")

    class _OpenAIStub:  # minimal attributes accessed in this module
        api_type = 'azure'
        responses = _OpenAIResponsesStub()
        # Attributes below are assigned dynamically in initialize_ai_models when real lib exists;
        # keep placeholders to avoid attribute errors in tests.
        azure_ad_token_provider = None
        azure_endpoint = None
        api_version = None

    openai = _OpenAIStub()  # type: ignore
import os
import json
import re
import ast
from pprint import pprint
from helpers.cache_completions import (
    save_completion_to_cache,
    load_answer_from_completion_cache,
    delete_cache_entry,
    make_completion_cache_key,
)
from helpers.completion_pricing import get_completion_pricing_from_usage, is_reasoning_model
from helpers.logging_setup import get_logger, preview_sensitive_text
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

log = get_logger(__name__)

# Globals initialized later in initialize_ai_models
llm_lingua = None  # type: ignore
mistral = None  # type: ignore

# --- Global reasoning summary state (for UI display) ---
_LAST_REASONING_SUMMARY = None  # truncated reasoning steps / plan from last reasoning model call
_LAST_USED_RESPONSES_API = False
_CURRENT_REASONING_VERBOSITY = 'low'  # default verbosity for reasoning summaries (low|medium|high)
_LAST_REASONING_FALLBACK_USED = False  # whether we retried with detailed summary
_LAST_REASONING_SUMMARY_STATUS = 'absent'  # 'captured' | 'empty' | 'absent'

def set_reasoning_verbosity(v: str):
    """Set current reasoning verbosity (low|medium|high). Silently ignore invalid values."""
    global _CURRENT_REASONING_VERBOSITY
    if v in ('low','medium','high'):
        _CURRENT_REASONING_VERBOSITY = v

def get_last_reasoning_summary():
    """Return the last captured reasoning summary string (or None)."""
    return _LAST_REASONING_SUMMARY

def last_used_responses_api():
    return _LAST_USED_RESPONSES_API

def last_reasoning_fallback_used():
    return _LAST_REASONING_FALLBACK_USED

def last_reasoning_summary_status():
    return _LAST_REASONING_SUMMARY_STATUS

# --- Internal helpers for reasoning summary extraction ---
def _safe_get(obj, key, default=None):
    """Access attribute or dict key uniformly."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ensure_iterable(obj):
    if obj is None:
        return []
    if isinstance(obj, (list, tuple, set)):
        return list(obj)
    return [obj]


def _flatten_summary_tree(value):
    segments = []
    visited = set()

    def _walk(node):
        if node is None:
            return
        nid = id(node)
        if nid in visited:
            return
        visited.add(nid)
        if isinstance(node, str):
            text = node.strip()
            if text:
                segments.append(text)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            for val in node.values():
                _walk(val)
        else:
            # Fallback: inspect common attributes on SDK objects
            for attr in ("text", "content", "value", "summary"):
                if hasattr(node, attr):
                    _walk(getattr(node, attr))

    _walk(value)
    return segments


def _deduplicate_preserve_order(items):
    seen = set()
    ordered = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _extract_reasoning_summary(resp):
    """Return (summary_text, status) from a Responses API payload.

    status ∈ {"captured", "empty", "absent"}.
    """
    if resp is None:
        return None, "absent"

    summary_segments = []
    found_reasoning_part = False

    # Top-level .reasoning field (Azure Responses SDK)
    for reasoning_part in _ensure_iterable(_safe_get(resp, "reasoning")):
        if reasoning_part is None:
            continue
        found_reasoning_part = True
        summary_obj = _safe_get(reasoning_part, "summary")
        if summary_obj is None:
            summary_obj = _safe_get(reasoning_part, "content")
        if summary_obj is not None:
            summary_segments.extend(_flatten_summary_tree(summary_obj))

    # Fallback: inspect output entries with type == "reasoning"
    for output_part in _ensure_iterable(_safe_get(resp, "output")):
        if output_part is None:
            continue
        part_type = _safe_get(output_part, "type")
        if part_type and str(part_type).lower() != "reasoning":
            continue
        found_reasoning_part = True
        summary_obj = _safe_get(output_part, "summary")
        if summary_obj is None:
            summary_obj = _safe_get(output_part, "content")
        if summary_obj is not None:
            summary_segments.extend(_flatten_summary_tree(summary_obj))

    if summary_segments:
        ordered_segments = _deduplicate_preserve_order([segment.strip() for segment in summary_segments if segment and segment.strip()])
        joined = "\n".join(ordered_segments)
        return (joined[:1200] + ("…" if len(joined) > 1200 else "")), "captured"

    if found_reasoning_part:
        return None, "empty"

    return None, "absent"

# --- Responses API integration helpers ---
def _invoke_responses_reasoning(model, system_prompt, user_prompt, reasoning_effort, summary_mode, verbosity):
    """Call Azure OpenAI Responses API for reasoning models to obtain reasoning summary.

    Returns response object. Builds a message-style input (system + user) per latest docs;
    supports summary collection heuristics downstream.
    """
    reasoning_obj = {"effort": reasoning_effort} if reasoning_effort else {}
    if summary_mode:
        # GPT-5: supports auto | detailed (concise currently not supported per docs)
        reasoning_obj["summary"] = summary_mode
    # Use list-of-messages form to preserve system vs user separation
    input_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = {
        "model": model,
        "input": input_messages,
        "reasoning": reasoning_obj or None,
    }
    text_cfg = {}
    if verbosity:
        text_cfg["verbosity"] = verbosity
    if text_cfg:
        payload["text"] = text_cfg
    log.info("[responses] invoking model=%s effort=%s summary=%s verbosity=%s", model, reasoning_effort, summary_mode, verbosity)
    log.debug("[responses] payload(reasoning)=%s text=%s", payload.get("reasoning"), payload.get("text"))
    resp = openai.responses.create(**payload)
    try:
        log.debug("[responses] output_part_types=%s", [getattr(o, 'type', None) for o in getattr(resp, 'output', [])])
    except Exception:
        pass
    return resp

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
        print(colored(f"new_context (preview): {_preview_value(new_context)}", "green"))
        print('='*80)
        print(colored(f"context_segs (preview): {_preview_value(context_segs)}", "green"))
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
                compressed_preview = _preview_value(compressed_seg.get('compressed_prompt', ''))
                print(colored(
                    f"Compressed Prompt preview: {compressed_preview}\n{compressed_seg['compressed_tokens']} tokens Vs {compressed_seg['origin_tokens']} tokens",
                    "blue",
                ))
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
    global completion_model, llm_lingua, mistral, openai
    # Lazy import Azure SDK components here to avoid mandatory dependency at module import time
    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider  # type: ignore
        from azure.keyvault.secrets import SecretClient  # type: ignore
        try:  # azure-core ships with azure-identity; guard defensively in case of partial installs
            from azure.core.exceptions import HttpResponseError  # type: ignore
        except ImportError:  # pragma: no cover - fall back to generic Exception grouping
            HttpResponseError = Exception  # type: ignore
    except ImportError as az_e:  # pragma: no cover - clear message for operators
        log.error("Azure SDK modules missing: %s. Install azure-identity and azure-keyvault-secrets.", az_e)
        raise

    # Create a DefaultAzureCredential object to authenticate with Azure (supports managed identity)
    credential = DefaultAzureCredential()
    # managed_identity = os.getenv("AZURE_CONTAINER_MANAGED_IDENTITY", None)
    # credential = DefaultAzureCredential(managed_identity_client_id=managed_identity)

    if credential is None:
        print(colored("Failed to authenticate with Azure.", "red"))
        print(colored("Logging in to Azure OpenAI - execute once an 'az login' for your session from command prompt before calling this method", "cyan"))
        exit(1)

    print(colored("Using Azure Entra ID", "cyan"))

    def _env_flag(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    # Specify the Azure Key Vault URL
    key_vault_url = os.getenv("AZURE_KEYVAULT_URL", None)
    if _env_flag("SKIP_KEYVAULT_FOR_TESTS") or _env_flag("HTMX_ALLOW_DEV_BYPASS"):
        log.info("[init] Local/dev mode detected – skipping Key Vault secret retrieval")
        key_vault_url = None

    azure_ad_token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")

    if not azure_ad_token_provider:
        print(colored("Failed to get the Azure AD token provider.", "red"))
        exit(1)

    # Check if the key vault URL is set
    api_type = (os.getenv("AZURE_OPENAI_API_TYPE", "azure") or "azure").lower()

    completion_model = os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEFAULT_MODEL", "gpt-4o")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("AZURE_OPENAI_DEFAULT_API_VERSION", "2024-02-15-preview")

    azure_endpoint = None
    mistral_url = None
    mistral_key = None
    used_keyvault_for_azure = False
    used_keyvault_for_mistral = False

    if key_vault_url:
        try:
            secret_client = SecretClient(vault_url=key_vault_url, credential=credential)
            if api_type == 'azure':
                azure_endpoint = secret_client.get_secret('AZURE-OPENAI-ENDPOINT').value
                used_keyvault_for_azure = True
                print(colored("Using an Azure key vault (Azure OpenAI endpoint).", "cyan"))
            else:
                mistral_url = secret_client.get_secret('MISTRAL-OPENAI-ENDPOINT').value
                mistral_key = secret_client.get_secret('MISTRAL-OPENAI-API-KEY').value
                used_keyvault_for_mistral = True
                print(colored("Using an Azure key vault (Mistral endpoint).", "cyan"))
        except HttpResponseError as exc:
            log.warning("Key Vault access failed (%s). Falling back to environment variables for OpenAI configuration.", exc)
            key_vault_url = None
        except Exception as exc:  # pragma: no cover - capture unexpected retrieval errors and continue with env vars
            log.warning("Unexpected Key Vault error; falling back to environment variables: %s", exc, exc_info=True)
            key_vault_url = None

    if api_type == 'azure':
        try:
            from openai import AzureOpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            log.error("AzureOpenAI client unavailable: %s", exc)
            raise

        azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        if not azure_endpoint:
            raise RuntimeError("Azure OpenAI endpoint not configured. Set AZURE_OPENAI_ENDPOINT or configure Key Vault.")

        openai = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=azure_ad_token_provider,
            api_version=api_version,
        )

        mistral = None
        openai.api_type = 'azure'  # type: ignore[attr-defined]
        openai.azure_endpoint = azure_endpoint  # type: ignore[attr-defined]
        openai.api_version = api_version  # type: ignore[attr-defined]
        openai.azure_ad_token_provider = azure_ad_token_provider  # type: ignore[attr-defined]
        source_label = "Azure Key Vault" if used_keyvault_for_azure else "environment variables"
        print(f'Using Azure OpenAI API with model {completion_model} ({source_label})\n')
        print(f'Calling Azure with {"Mistral Large" if completion_model == "azureai" else completion_model} model\n')
    else:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover
            log.error("OpenAI client unavailable for non-Azure path: %s", exc)
            raise

        mistral_url = mistral_url or os.getenv("MISTRAL_OPENAI_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
        mistral_key = mistral_key or os.getenv("MISTRAL_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        if not mistral_url:
            raise RuntimeError("Mistral endpoint not configured. Set MISTRAL_OPENAI_ENDPOINT or configure Key Vault.")
        if not mistral_key:
            raise RuntimeError("Mistral API key not configured. Set MISTRAL_OPENAI_API_KEY or configure Key Vault.")

        mistral = OpenAI(base_url=mistral_url, api_key=mistral_key)
        openai = mistral
        source_label = "Azure Key Vault" if used_keyvault_for_mistral else "environment variables"
        print(f'Using Mistral endpoint with configuration from {source_label}\n')
        print(f'Calling Azure with {"Mistral Large" if completion_model == "azureai" else completion_model} model\n')
        setattr(openai, "api_type", api_type)  # type: ignore[attr-defined]

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


def _preview_value(value, head: int = 120, tail: int = 80):
    """Recursively sanitize potentially sensitive structures for logging/diagnostics."""
    if isinstance(value, str):
        return preview_sensitive_text(value, head=head, tail=tail)
    if isinstance(value, list):
        return [_preview_value(item, head=head, tail=tail) for item in value]
    if isinstance(value, tuple):
        return tuple(_preview_value(item, head=head, tail=tail) for item in value)
    if isinstance(value, dict):
        return {key: _preview_value(val, head=head, tail=tail) for key, val in value.items()}
    return value


# ## Method to ask a prompt to LLM (best with GPT-4)
def get_azure_openai_completion_nocache(prompt, system_prompt, model=None, reasoning_effort=None):
    """Lightweight single-call completion (no caching layer) with reasoning summary support by default."""
    if model is None:
        model = completion_model
    global _LAST_USED_RESPONSES_API, _LAST_REASONING_SUMMARY, _LAST_REASONING_SUMMARY_STATUS, _LAST_REASONING_FALLBACK_USED
    # --- Diagnostic log (helps verify whether reasoning path condition evaluates True) ---
    try:
        log.info(
            "[diag] nocache invocation model=%s api_type=%s is_reasoning=%s prompt_chars=%d",
            model,
            getattr(openai, 'api_type', None),
            is_reasoning_model(model),
            len(prompt or ""),
        )
    except Exception:
        pass
    try:
        if openai.api_type == 'azure' and is_reasoning_model(model):
            # First attempt with auto summary
            resp = _invoke_responses_reasoning(
                model,
                system_prompt,
                prompt,
                reasoning_effort,
                'auto',
                _CURRENT_REASONING_VERBOSITY,
            )
            _LAST_USED_RESPONSES_API = True
            global _LAST_REASONING_FALLBACK_USED
            _LAST_REASONING_FALLBACK_USED = False
            # Extract answer & summary
            answer_text = ""
            reasoning_summary, summary_status = _extract_reasoning_summary(resp)
            local_summary_empty = (summary_status == 'empty')
            first_usage_prompt_tokens = getattr(getattr(resp, 'usage', None), 'input_tokens', 0)
            first_usage_output_tokens = getattr(getattr(resp, 'usage', None), 'output_tokens', 0)
            first_reasoning_tokens = 0
            try:
                d = getattr(getattr(resp, 'usage', None), 'output_tokens_details', {}) or {}
                first_reasoning_tokens = d.get('reasoning_tokens', 0) or 0
            except Exception:
                pass
            if getattr(resp, 'output', None):
                for part in resp.output:
                    ptype = getattr(part, 'type', None)
                    if ptype == 'message':
                        contents = getattr(part, 'content', [])
                        if isinstance(contents, list):
                            out_parts = [c.get('text') for c in contents if isinstance(c, dict) and c.get('type') in ('output_text','final_output','text') and c.get('text')]
                            answer_text = "\n".join(t for t in out_parts if t)
            if reasoning_summary is None:
                preamble = getattr(resp, 'preamble', None)
                if isinstance(preamble, dict):
                    ptxt = preamble.get('summary') or preamble.get('text')
                    if isinstance(ptxt, str) and ptxt.strip():
                        reasoning_summary = ptxt.strip()
                        if len(reasoning_summary) > 1200:
                            reasoning_summary = reasoning_summary[:1200] + "…"
                        summary_status = 'captured'
            # Fallback retry with detailed summary if auto produced nothing (one extra call)
            if (reasoning_summary is None) and (summary_status in ('absent', 'empty')):
                log.info("[reasoning] no summary on auto attempt; retrying with summary='detailed'")
                try:
                    resp_detailed = _invoke_responses_reasoning(
                        model,
                        system_prompt,
                        prompt,
                        reasoning_effort,
                        'detailed',
                        _CURRENT_REASONING_VERBOSITY,
                    )
                    _LAST_REASONING_FALLBACK_USED = True
                    # Capture usage delta for logging
                    d2_prompt = getattr(getattr(resp_detailed, 'usage', None), 'input_tokens', 0)
                    d2_output = getattr(getattr(resp_detailed, 'usage', None), 'output_tokens', 0)
                    d2_reasoning = 0
                    try:
                        d2 = getattr(getattr(resp_detailed, 'usage', None), 'output_tokens_details', {}) or {}
                        d2_reasoning = d2.get('reasoning_tokens', 0) or 0
                    except Exception:
                        pass
                    detailed_summary, detailed_status = _extract_reasoning_summary(resp_detailed)
                    if getattr(resp_detailed, 'output', None):
                        for part in resp_detailed.output:
                            if getattr(part, 'type', None) == 'message' and not answer_text:
                                conts2 = getattr(part, 'content', [])
                                if isinstance(conts2, list):
                                    out2 = [c.get('text') for c in conts2 if isinstance(c, dict) and c.get('type') in ('output_text','final_output','text') and c.get('text')]
                                    answer_text = "\n".join(t for t in out2 if t)
                    if detailed_summary is not None:
                        reasoning_summary = detailed_summary
                        summary_status = detailed_status
                    elif detailed_status in ('empty', 'absent'):
                        summary_status = detailed_status
                    try:
                        log.info(
                            "[reasoning-retry] usage_delta prompt=%s->%s output=%s->%s reasoning_tokens=%s->%s",
                            first_usage_prompt_tokens,
                            d2_prompt,
                            first_usage_output_tokens,
                            d2_output,
                            first_reasoning_tokens,
                            d2_reasoning,
                        )
                    except Exception:
                        pass
                except Exception as rexf:
                    log.warning("[reasoning] fallback detailed retry failed: %s", rexf)
            global _LAST_REASONING_SUMMARY_STATUS
            _LAST_REASONING_SUMMARY_STATUS = summary_status if summary_status else ('empty' if local_summary_empty else 'absent')
            if _LAST_REASONING_SUMMARY_STATUS == 'captured' and reasoning_summary:
                _LAST_REASONING_SUMMARY = reasoning_summary[:1200] + ("…" if len(reasoning_summary) > 1200 else "")
            else:
                _LAST_REASONING_SUMMARY = None
            try:
                if _LAST_REASONING_SUMMARY:
                    log.debug("[reasoning-summary] captured chars=%d", len(_LAST_REASONING_SUMMARY))
                else:
                    log.debug("[reasoning-summary] absent (model may legitimately omit summary)")
            except Exception:
                pass
            # Construct pseudo response for uniform extraction path
            class _Msg:  # minimal shim
                def __init__(self, c):
                    self.content = c
            class _Choice:
                def __init__(self, c):
                    self.message = _Msg(c)
            class _Usage:
                def __init__(self, u):
                    self.prompt_tokens = getattr(u, 'input_tokens', 0)
                    self.completion_tokens = getattr(u, 'output_tokens', 0)
                    d = getattr(u, 'output_tokens_details', {}) or {}
                    self.completion_tokens_details = {"reasoning_tokens": d.get('reasoning_tokens', 0)}
            class _Resp:
                def __init__(self, ans, r):
                    self.choices = [_Choice(ans)]
                    self.usage = _Usage(getattr(r, 'usage', type('u',(),{})()))
            pseudo = _Resp(answer_text, resp)
            return pseudo.choices[0].message.content or ""
        # Non-reasoning or non-azure path
        if openai.api_type == 'azure':
            _LAST_USED_RESPONSES_API = False
            _LAST_REASONING_SUMMARY = None
            _LAST_REASONING_SUMMARY_STATUS = 'absent'
            _LAST_REASONING_FALLBACK_USED = False
            chat_resp = _invoke_chat_with_adaptive_params(
                model=model,
                messages=[{"role": "system", "content": system_prompt},{"role": "user", "content": prompt}],
                json_mode=False,
                reasoning_effort=reasoning_effort,
                temperature=0.0,
                verbose=False,
            )
            return chat_resp.choices[0].message.content if (chat_resp and chat_resp.choices and chat_resp.choices[0].message) else ""
        # Mistral style fallback
        if mistral is None:
            raise RuntimeError("Mistral client not initialized.")
        m_resp = mistral.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt},{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return m_resp.choices[0].message.content if (m_resp and m_resp.choices and m_resp.choices[0].message) else ""
    except Exception as exc:
        log.warning("nocache completion failed: %s", exc)
        return ""


# ## Method to ask a prompt to LLM (best with GPT-4-32k)
def get_azure_openai_completion(prompt, system_prompt, model=None, json_mode="text", temperature=0.0, language="English", min_sleep=0, max_sleep=0, rebuildCache=False, compress=False, verbose=False, reasoning_effort=None):

    if model is None:
        model = completion_model

    global _LAST_USED_RESPONSES_API, _LAST_REASONING_SUMMARY, _LAST_REASONING_SUMMARY_STATUS, _LAST_REASONING_FALLBACK_USED

    # Force text mode for models where JSON response_format is unsupported or unreliable.
    # NOTE: previous logic `if '32-k' or 'mistral' in model.lower()` was always truthy due to Python truthiness of non-empty string.
    lowered = model.lower()
    if ('32k' in lowered) or ('32-k' in lowered) or ('mistral' in lowered) or is_reasoning_model(model):
        if json_mode == "json" and verbose:
            print(colored(f"[info] Forcing json_mode=text for model {model}", "cyan"))
        json_mode = "text"  # enforce plain text path

    if not compress:
        system_prompt = system_prompt.replace('<llmlingua, compress=False>', '').replace('<llmlingua, rate=0.5>', '').replace('<llmlingua, rate=0.8>', '').replace('</llmlingua>', '')
        prompt = prompt.replace('<llmlingua, compress=False>', '').replace('<llmlingua, rate=0.5>', '').replace('<llmlingua, rate=0.8>', '').replace('</llmlingua>', '')

    cache_seed = make_completion_cache_key(
        model,
        language,
        prompt,
        temperature,
        compress,
        reasoning_effort if is_reasoning_model(model) else None,
    )
    cached_data, cached_key = load_answer_from_completion_cache(cache_seed, verbose=verbose)
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
                # Diagnostic log once per loop iteration
                try:
                    log.info(
                        "[diag] completion loop model=%s api_type=%s is_reasoning=%s json_mode=%s effort=%s",
                        model,
                        getattr(openai, 'api_type', None),
                        is_reasoning_model(model),
                        json_mode,
                        reasoning_effort,
                    )
                except Exception:
                    pass
                if is_reasoning_model(model):
                    try:
                        resp = _invoke_responses_reasoning(
                            model,
                            use_system_prompt,
                            use_prompt,
                            reasoning_effort,
                            'auto',
                            _CURRENT_REASONING_VERBOSITY,
                        )
                        global _LAST_USED_RESPONSES_API
                        _LAST_USED_RESPONSES_API = True
                        global _LAST_REASONING_FALLBACK_USED
                        _LAST_REASONING_FALLBACK_USED = False
                        # Build pseudo response as in nocache path
                        answer_text = ""
                        reasoning_summary, summary_status = _extract_reasoning_summary(resp)
                        local_summary_empty = (summary_status == 'empty')
                        if getattr(resp, 'output', None):
                            for part in resp.output:
                                if getattr(part, 'type', None) == 'message':
                                    contents = getattr(part, 'content', [])
                                    if isinstance(contents, list):
                                        texts = []
                                        for c in contents:
                                            if isinstance(c, dict):
                                                ctype = c.get('type')
                                                if ctype in ('output_text','final_output','text') and c.get('text'):
                                                    texts.append(c['text'])
                                        answer_text = "\n".join(t for t in texts if t)
                        if reasoning_summary is None:
                            try:
                                preamble = getattr(resp, 'preamble', None)
                                if preamble and isinstance(preamble, dict):
                                    ptxt = preamble.get('summary') or preamble.get('text')
                                    if isinstance(ptxt, str) and ptxt.strip():
                                        reasoning_summary = ptxt.strip()
                                        if len(reasoning_summary) > 1200:
                                            reasoning_summary = reasoning_summary[:1200] + "…"
                                        summary_status = 'captured'
                            except Exception:
                                pass
                        if (reasoning_summary is None) and (summary_status in ('absent', 'empty')):
                            log.info("[reasoning] no summary on auto attempt (loop path); retrying with summary='detailed'")
                            try:
                                resp_d2 = _invoke_responses_reasoning(
                                    model,
                                    use_system_prompt,
                                    use_prompt,
                                    reasoning_effort,
                                    'detailed',
                                    _CURRENT_REASONING_VERBOSITY,
                                )
                                _LAST_REASONING_FALLBACK_USED = True
                                detailed_summary, detailed_status = _extract_reasoning_summary(resp_d2)
                                if getattr(resp_d2, 'output', None):
                                    for part in resp_d2.output:
                                        if getattr(part, 'type', None) == 'message' and not answer_text:
                                            c3 = getattr(part, 'content', [])
                                            if isinstance(c3, list):
                                                o3 = [c.get('text') for c in c3 if isinstance(c, dict) and c.get('type') in ('output_text','final_output','text') and c.get('text')]
                                                answer_text = "\n".join(t for t in o3 if t)
                                if detailed_summary is not None:
                                    reasoning_summary = detailed_summary
                                    summary_status = detailed_status
                                elif detailed_status in ('empty', 'absent'):
                                    summary_status = detailed_status
                            except Exception as r2e:
                                log.warning("[reasoning] detailed fallback failed (loop path): %s", r2e)
                        _LAST_REASONING_SUMMARY_STATUS = summary_status if summary_status else ('empty' if local_summary_empty else 'absent')
                        if _LAST_REASONING_SUMMARY_STATUS == 'captured' and reasoning_summary:
                            _LAST_REASONING_SUMMARY = reasoning_summary[:1200] + ("…" if len(reasoning_summary) > 1200 else "")
                        else:
                            _LAST_REASONING_SUMMARY = None
                        try:
                            if _LAST_REASONING_SUMMARY:
                                log.debug("[reasoning-summary] captured chars=%d (loop path)", len(_LAST_REASONING_SUMMARY))
                            else:
                                log.debug("[reasoning-summary] absent (loop path)")
                        except Exception:
                            pass
                        class _PseudoChoiceMsg:
                            def __init__(self, content):
                                self.content = content
                        class _PseudoChoice:
                            def __init__(self, content):
                                self.message = _PseudoChoiceMsg(content)
                                self.finish_reason = 'stop'
                                self.content_filter_results = None
                        class _PseudoUsage:
                            def __init__(self, usage):
                                self.prompt_tokens = getattr(usage, 'input_tokens', 0)
                                self.completion_tokens = getattr(usage, 'output_tokens', 0)
                                details = getattr(usage, 'output_tokens_details', {}) or {}
                                self.completion_tokens_details = {"reasoning_tokens": details.get('reasoning_tokens', 0)}
                        class _PseudoResponse:
                            def __init__(self, answer_text, resp):
                                self.choices = [_PseudoChoice(answer_text)]
                                self.usage = _PseudoUsage(getattr(resp, 'usage', type('u',(),{})()))
                        response = _PseudoResponse(answer_text, resp)
                        # Info-level diagnostic about summary status each reasoning invocation
                        try:
                            log.info(
                                "[diag] reasoning invocation done model=%s summary_status=%s fallback=%s captured_len=%s",
                                model,
                                _LAST_REASONING_SUMMARY_STATUS,
                                _LAST_REASONING_FALLBACK_USED,
                                (len(_LAST_REASONING_SUMMARY) if _LAST_REASONING_SUMMARY else 0),
                            )
                        except Exception:
                            pass
                    except Exception as rex:
                        log.warning("Responses API reasoning (main path) failed, fallback to chat: %s", rex)
                        _LAST_USED_RESPONSES_API = False
                        _LAST_REASONING_SUMMARY = None
                        _LAST_REASONING_SUMMARY_STATUS = 'absent'
                        _LAST_REASONING_FALLBACK_USED = False
                        response = _invoke_chat_with_adaptive_params(
                            model=model,
                            messages=[
                                {"role": "system", "content": use_system_prompt},
                                {"role": "user", "content": use_prompt},
                            ],
                            json_mode=(json_mode == "json"),
                            reasoning_effort=reasoning_effort,
                            temperature=temperature,
                            verbose=verbose,
                        )
                else:
                    _LAST_REASONING_SUMMARY = None
                    _LAST_REASONING_SUMMARY_STATUS = 'absent'
                    _LAST_REASONING_FALLBACK_USED = False
                    response = _invoke_chat_with_adaptive_params(
                        model=model,
                        messages=[
                            {"role": "system", "content": use_system_prompt},
                            {"role": "user", "content": use_prompt},
                        ],
                        json_mode=(json_mode == "json"),
                        reasoning_effort=reasoning_effort,
                        temperature=temperature,
                        verbose=verbose,
                    )
            else:
                print(colored(f'Calling Azure with {"Mistral Large" if model == "azureai" else model} model', "green"))
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
        try:
            log.exception("Invocation exception model=%s", model)
        except Exception:
            pass
        finish_reason = response.choices[0].finish_reason if response and response.choices and len(response.choices) > 0 else "unknown"
        content_filter_result = response.choices[0].content_filter_results if response and response.choices and len(response.choices) > 0 else None
        print(colored(f"Failed to generate the completion ({finish_reason}).", "red"))
        # Access the individual categories and details
        if content_filter_result:
            for category, details in content_filter_result.items():
                print(colored(f"{category}:\n filtered={details['filtered']}\n severity={details['severity']}", "red"))
        return "", 0, 0, 0, ""

    if response and response.usage:
        prompt_tokens = getattr(response.usage, 'prompt_tokens', 0)
        visible_completion_tokens = getattr(response.usage, 'completion_tokens', 0)
        # Reasoning models expose hidden reasoning tokens in completion_tokens_details.reasoning_tokens
        reasoning_tokens = 0
        if is_reasoning_model(model):
            details = getattr(response.usage, 'completion_tokens_details', None)
            if details and isinstance(details, dict):
                reasoning_tokens = details.get('reasoning_tokens', 0) or 0
        effective_output_tokens = visible_completion_tokens + reasoning_tokens
        input_cost, output_cost = get_completion_pricing_from_usage(
            model,
            prompt_tokens,
            effective_output_tokens
        )
        try:
            log.debug("Usage model=%s prompt=%s visible_out=%s reasoning=%s effective_out=%s in_cost=%.6f out_cost=%.6f finish=%s",
                      model, prompt_tokens, visible_completion_tokens, reasoning_tokens, effective_output_tokens, input_cost, output_cost, finish_reason)
        except Exception:
            pass
    else:
        prompt_tokens = 0
        visible_completion_tokens = 0
        reasoning_tokens = 0
        input_cost, output_cost = 0, 0
        effective_output_tokens = 0

    completion_cost = input_cost + output_cost
    if is_reasoning_model(model) and reasoning_tokens:
        print(colored(
            f"Cost: {completion_cost:.4f}€ - Input: {input_cost:.4f}€ - Output: {output_cost:.4f}€ (visible_out={visible_completion_tokens} reasoning={reasoning_tokens})",
            "yellow")
        )
    else:
        print(colored(
            f"Cost: {completion_cost:.4f}€ - Input: {input_cost:.4f}€ - Output: {output_cost:.4f}€",
            "yellow")
        )

    # --- Normalize answer extraction (reasoning models may return list content parts) ---
    def _coalesce_message_content(raw):
        """Return visible answer text while collecting reasoning parts separately.

        Azure reasoning models may return a list of dict parts like:
          [{"type":"reasoning","text":"..."}, {"type":"output_text","text":"final answer"}]
        We keep only output text for the main answer, but store reasoning elsewhere.
        """
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            texts = []
            reasoning_parts = []
            for part in raw:
                if isinstance(part, dict):
                    ptype = part.get('type')
                    ptext = part.get('text') or part.get('content') or ''
                    if ptype in ("reasoning", "reasoning_content", "chain_of_thought", "thinking"):
                        if ptext:
                            reasoning_parts.append(ptext)
                    # Visible output segment
                    if ptype in ("output_text", "final_output", None):
                        if ptext:
                            texts.append(ptext)
                    # Fallback: if no type but text available
                    if not ptype and ptext and ptext not in texts:
                        texts.append(ptext)
                else:
                    # Raw string element
                    if isinstance(part, str):
                        texts.append(part)
            # Update global reasoning summary (truncated) if we collected anything
            global _LAST_REASONING_SUMMARY, _LAST_REASONING_SUMMARY_STATUS
            if reasoning_parts:
                joined = "\n".join(r.strip() for r in reasoning_parts if r.strip())
                if joined:
                    _LAST_REASONING_SUMMARY = joined[:1200] + ("…" if len(joined) > 1200 else "")
                    _LAST_REASONING_SUMMARY_STATUS = 'captured'
            return "\n".join(t for t in texts if t)
        return str(raw)

    raw_message_content = response.choices[0].message.content if (response and response.choices and len(response.choices) > 0 and response.choices[0].message) else ""
    # Detailed raw choice logging when debugging or empty output
    try:
        if log.isEnabledFor(10) or (is_reasoning_model(model) and (not raw_message_content)):
            choice0 = response.choices[0] if (response and response.choices) else None
            log.debug("Raw choice repr(trunc)=%.500s", repr(choice0)[:500])
            log.debug("Raw message content repr(trunc)=%.500s", repr(raw_message_content)[:500])
    except Exception:
        pass
    answer = _coalesce_message_content(raw_message_content)
    # If reasoning model but no visible answer and we captured reasoning steps only, fall back to exposing part of reasoning as answer
    try:
        if is_reasoning_model(model) and (not answer or not answer.strip()) and _LAST_REASONING_SUMMARY:
            answer = "(Reasoning summary excerpt)\n" + _LAST_REASONING_SUMMARY
    except Exception:
        pass
    if not answer and is_reasoning_model(model):
        log.warning("Empty answer from reasoning model=%s finish_reason=%s prompt_tokens=%s visible_out=%s reasoning_tokens=%s", model, finish_reason, prompt_tokens, visible_completion_tokens, reasoning_tokens)
        answer = "(No text content returned by reasoning model – enable DEBUG level to inspect raw response)"
    try:
        log.debug("Extracted answer length=%d preview=%.200s", len(answer or ''), (answer or '')[:200].replace('\n',' '))
    except Exception:
        pass
    cached_key_list = []
    if answer and answer.strip():
        if model_called_first:  # Save completion for initial model used before fallback (e.g., length escalation)
            initial_seed = make_completion_cache_key(
                model_called_first,
                language,
                prompt,
                temperature,
                compress,
                reasoning_effort if is_reasoning_model(model_called_first) else None,
            )
            cached_key = save_completion_to_cache(
                initial_seed,
                [model_called_first, language, input_cost, output_cost, answer]
            )
            cached_key_list.append(cached_key)
        cache_seed = make_completion_cache_key(
            model,
            language,
            prompt,
            temperature,
            compress,
            reasoning_effort if is_reasoning_model(model) else None,
        )
        cached_key = save_completion_to_cache(
            cache_seed,
            [model, language, input_cost, output_cost, answer]
        )
        cached_key_list.append(cached_key)

    return answer, completion_cost, prompt_tokens, effective_output_tokens, cached_key_list


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
            print('ANSWER preview:\n', _preview_value(answer))
        if answer[0] == '[':    # If the answer is a list, convert it to a dictionary of lists
            answer_json = {
                main_json: ast.literal_eval(answer) # Get a list from the string
            }
            if verbose:
                print(f"\n===>\n {_preview_value(answer_json)}")
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
                            print(f"\n===>\n {_preview_value(answer_json)}")
                except Exception as e:
                    print(e)
                    print(colored(f"Failed to convert the JSON to the expected dictionary.\n{_preview_value(answer)}", "red"))
                    return {}
            except Exception as e:
                print(e)
                print(colored(
                    f"Failed to convert the JSON to a dictionary.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                    "red",
                ))
                return {}
        if verbose:
            print('='*80)
            print(_preview_value(answer_json))
            print('='*80)
        return answer_json

    except Exception as e:
        print(e)
        safe_answer = _preview_value(answer) if 'answer' in locals() else ''
        safe_json = _preview_value(locals().get('json_answer', ''))
        print(colored(f"Failed to convert the JSON answer.\n{safe_answer}\n------\n{safe_json}", "red"))
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
        print(
            colored(
                f"Failed to process risks of bias or prompt injections.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process intended uses.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process fitness for purpose.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process stakeholders.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process goals A5, T1, T2 and T3.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process fairness goals F1, F2 and F3.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process solution scope.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process assessment.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process risk of use.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process harms assessment.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process impact on stakeholders.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process disclosure of AI interaction.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
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
        print(
            colored(
                f"Failed to process solution information.\n{_preview_value(answer)}\n------\n{_preview_value(json_answer)}",
                "red",
            )
        )
        return {}, [], []


# Method to process the solution description audit to detect bias or risks
def process_solution_description_security_analysis(solution_description, language='English', model=None, ui_hook=None, rebuildCache=False, min_sleep=0, max_sleep=0, verbose=False, reasoning_effort=None):
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

    uiprint(f'Auditing the Solution Description Bias or Risks with {"Mistral Large" if model == "azureai" else model} model', ui_hook=ui_hook)

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
            verbose=verbose,
            reasoning_effort=reasoning_effort
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
def process_solution_description_analysis(solution_description, language='English', model=None, ui_hook=None, rebuildCache=False, min_sleep=0, max_sleep=0, verbose=False, reasoning_effort=None):
    
    if model is None:
        model = completion_model

    # Update SYSTEM_PROMPT to include the language
    system_prompt = SYSTEM_PROMPT.replace(TARGET_LANGUAGE_PLACEHOLDER, language)
    prompt = SOLUTION_DESCRIPTION_ANALYSIS_PROMPT
    filled_prompt = prompt.replace(SOLUTION_DESCRIPTION_PLACEHOLDER, solution_description).replace(TARGET_LANGUAGE_PLACEHOLDER, language)
    
    uiprint(f'Auditing the Solution Description with {"Mistral Large" if model == "azureai" else model} model', ui_hook=ui_hook)

    try:
        answer, completion_cost, input_tokens_number, output_tokens_number, cached_key_list = get_azure_openai_completion(
            filled_prompt,
            system_prompt,
            model=model,
            temperature=0.4,  # ignored for reasoning models by adaptive layer
            json_mode="text",
            rebuildCache=rebuildCache,
            min_sleep=min_sleep,
            max_sleep=max_sleep,
            compress=False,
            verbose=verbose,
            reasoning_effort=reasoning_effort
        )
        total_completion_cost = completion_cost
        return answer, total_completion_cost
    except Exception as e:
        print(e)
        print(colored("Failed to audit the solution description.", 'red'))
        return '', 0

# --- Adaptive invocation helper for reasoning vs standard models ---

def _invoke_chat_with_adaptive_params(model, messages, json_mode, reasoning_effort, temperature, verbose=False):
    """Invoke Azure OpenAI Chat Completions handling reasoning model constraints.

    Strategy:
      1. Build initial param set according to model capabilities.
      2. On 400/422 errors, progressively remove optional fields (response_format, max_completion_tokens, reasoning_effort) before failing.
    """
    if openai.api_type != 'azure':  # Fallback: direct pass-through (non-azure path unmodified)
        return openai.chat.completions.create(model=model, messages=messages, temperature=temperature)

    is_reasoning = is_reasoning_model(model)

    # Disallowed for reasoning: temperature (except None), top_p, presence_penalty, frequency_penalty, max_tokens
    # Required special param: max_completion_tokens (not max_tokens) optional but often recommended guardrail
    attempt_params = {
        "model": model,
        "messages": messages,
    }
    removal_sequence = []  # track optional keys we may remove

    if is_reasoning:
        # Use reasoning_effort if provided
        if reasoning_effort:
            # Docs list 'reasoning_effort' (string) not nested object for o/gpt-5 series
            attempt_params["reasoning_effort"] = reasoning_effort
            removal_sequence.append("reasoning_effort")
        # NOTE: Deliberately NOT setting max_completion_tokens to allow very long outputs per user request.
        # If needed later, introduce an env-controlled soft limit.
        if json_mode:
            attempt_params["response_format"] = {"type": "json_object"}
            removal_sequence.append("response_format")
    else:
        attempt_params["temperature"] = temperature
        if json_mode:
            attempt_params["response_format"] = {"type": "json_object"}
            removal_sequence.append("response_format")

    # For debug instrumentation (disabled by default) set env DEBUG_REASONING=1
    debug = os.getenv("DEBUG_REASONING", "0") == "1"

    def _try(params):
        if debug:
            print(colored(f"[debug] invoking with params keys={list(params.keys())}", "cyan"))
        return openai.chat.completions.create(**params)

    last_error = None
    for i in range(len(removal_sequence) + 1):
        try:
            return _try(attempt_params)
        except Exception as e:  # broad catch to adapt quickly
            err_text = str(e)
            last_error = e
            if debug:
                print(colored(f"[debug] attempt {i+1} failed: {err_text}", "yellow"))
            # Stop if no more things to remove or error not param-related
            if i >= len(removal_sequence):
                raise
            key_to_remove = removal_sequence[i]
            attempt_params.pop(key_to_remove, None)
            if debug:
                print(colored(f"[debug] removed '{key_to_remove}' and retrying", "magenta"))
            continue
    # If loop exits unexpectedly
    if last_error:
        raise last_error
    return openai.chat.completions.create(model=model, messages=messages)

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
            verbose=verbose,
            reasoning_effort=reasoning_effort
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
def update_rai_assessment_template(solution_description, rai_filepath, rai_public_filepath, language='English', model=None, ui_hook=None, rebuildCache=False, update_steps=False, min_sleep=0, max_sleep=0, compress=False, verbose=False, reasoning_effort=None):

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
                    verbose=verbose,
                    reasoning_effort=reasoning_effort
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

# --- Logging enhanced adaptive invocation override (appended late to keep minimal diff) ---
def _invoke_chat_with_adaptive_params_logged(model, messages, json_mode, reasoning_effort, temperature, verbose=False):
    """Adaptive invocation with structured logging.

    Removes optional params on parameter errors: response_format, max_completion_tokens, reasoning_effort.
    """
    if openai.api_type != 'azure':
        log.debug("[adaptive] non-azure direct call model=%s", model)
        return openai.chat.completions.create(model=model, messages=messages, temperature=temperature)

    is_reasoning = is_reasoning_model(model)
    log.debug(
        "[adaptive] start model=%s reasoning=%s json_mode=%s temperature=%s effort=%s",
        model, is_reasoning, json_mode, temperature, reasoning_effort
    )

    params = {"model": model, "messages": messages}
    removable = []
    if is_reasoning:
        if reasoning_effort:
            params["reasoning_effort"] = reasoning_effort
            removable.append("reasoning_effort")
        # Removed max_completion_tokens per user request (allow long outputs).
        if json_mode:
            params["response_format"] = {"type": "json_object"}
            removable.append("response_format")
    else:
        params["temperature"] = temperature
        if json_mode:
            params["response_format"] = {"type": "json_object"}
            removable.append("response_format")

    debug_env = os.getenv("DEBUG_REASONING", "0") == "1"
    active_debug = debug_env or log.isEnabledFor(10)
    if active_debug:
        log.debug("[adaptive] initial keys=%s removable=%s", list(params.keys()), removable)

    removed = []
    last_error = None
    for attempt in range(len(removable) + 1):
        try:
            if active_debug:
                log.debug("[adaptive] attempt=%d keys=%s", attempt + 1, list(params.keys()))
            resp = openai.chat.completions.create(**params)
            if active_debug:
                log.debug("[adaptive] success attempt=%d removed=%s", attempt + 1, removed)
            return resp
        except Exception as e:
            err = str(e)
            last_error = e
            if active_debug:
                log.debug("[adaptive] failure attempt=%d error=%s", attempt + 1, err[:400])
            if attempt >= len(removable):
                log.error("[adaptive] giving up model=%s error=%s", model, err)
                raise
            key = removable[attempt]
            params.pop(key, None)
            removed.append(key)
            if active_debug:
                log.debug("[adaptive] removed '%s' retrying", key)
            continue
    if last_error:
        raise last_error
    return openai.chat.completions.create(model=model, messages=messages)

# Override original reference
_invoke_chat_with_adaptive_params = _invoke_chat_with_adaptive_params_logged
