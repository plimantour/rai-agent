"""Utilities for running Azure Content Safety Prompt Shields before using uploaded text."""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from azure.core.credentials import AccessToken  # type: ignore
from azure.identity import DefaultAzureCredential  # type: ignore

from helpers.logging_setup import get_logger

log = get_logger(__name__)

_SCOPE = "https://cognitiveservices.azure.com/.default"
_DEFAULT_API_VERSION = "2024-09-01"
_ENDPOINT_ENV = "AZURE_CONTENT_SAFETY_ENDPOINT"
_DISABLED_ENV = "AZURE_CONTENT_SAFETY_DISABLED"
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5  # seconds
_TOKEN_REFRESH_BUFFER = 60  # seconds
_SESSION = requests.Session()


class PromptShieldConfigurationError(RuntimeError):
    """Raised when Prompt Shields can't run due to misconfiguration."""


class PromptShieldServiceError(RuntimeError):
    """Raised when the Content Safety service can't be reached."""


class PromptShieldAttackDetected(RuntimeError):
    """Raised when Prompt Shields flags the uploaded content as unsafe."""


@dataclass
class PromptShieldResult:
    attack_detected: bool
    user_prompt_attack: bool
    document_attack: bool
    attack_types: Sequence[str]
    raw_response: Dict[str, Any]
    shielding_type: Optional[str] = None
    confidence: Optional[str] = None
    categories: Sequence[str] = ()
    reason: Optional[str] = None

    @property
    def safe(self) -> bool:
        return not self.attack_detected


_credential: Optional[DefaultAzureCredential] = None
_cached_token: Optional[AccessToken] = None
_scan_cache: Dict[str, PromptShieldResult] = {}


def _is_disabled() -> bool:
    flag = os.getenv(_DISABLED_ENV, "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _get_endpoint() -> str:
    endpoint = os.getenv(_ENDPOINT_ENV, "").strip()
    if endpoint:
        return endpoint.rstrip("/")
    raise PromptShieldConfigurationError(
        f"Missing {_ENDPOINT_ENV}; configure your Azure Content Safety endpoint or set {_DISABLED_ENV}=1 to bypass."
    )


def _get_api_version() -> str:
    return os.getenv("AZURE_CONTENT_SAFETY_API_VERSION", _DEFAULT_API_VERSION)


def _get_credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _get_token() -> str:
    global _cached_token
    now = time.time()
    if _cached_token is None or (_cached_token.expires_on - now) < _TOKEN_REFRESH_BUFFER:
        credential = _get_credential()
        _cached_token = credential.get_token(_SCOPE)
    return _cached_token.token


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def _coerce_documents(documents: Optional[Iterable[str]]) -> List[str]:
    docs: List[str] = []
    if documents:
        for doc in documents:
            if doc is None:
                continue
            doc_str = str(doc)
            if doc_str.strip():
                docs.append(doc_str)
    return docs


def _post_with_retry(url: str, payload: Dict[str, Any], headers: Dict[str, str], params: Dict[str, Any]) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            response = _SESSION.post(url, params=params, json=payload, headers=headers, timeout=15)
            if response.status_code // 100 != 2:
                detail = _safe_json(response)
                log.warning("[promptshields] non-success response %s detail=%s", response.status_code, detail)
                raise PromptShieldServiceError(
                    f"Prompt Shields call failed with status {response.status_code}"
                )
            try:
                return response.json()
            except ValueError as exc:
                log.warning("[promptshields] failed to parse response json: %s", exc)
                raise PromptShieldServiceError("Prompt Shields returned invalid JSON") from exc
        except PromptShieldServiceError as exc:
            last_exc = exc
        except requests.RequestException as exc:
            last_exc = exc
            log.warning("[promptshields] request attempt %s failed: %s", attempt, exc)
        if attempt < _RETRY_ATTEMPTS:
            sleep_for = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            time.sleep(sleep_for)
    assert last_exc is not None
    raise PromptShieldServiceError("Prompt Shields request failed") from last_exc


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:200]


def scan_uploaded_text(
    text: str,
    *,
    documents: Optional[Iterable[str]] = None,
    label: str = "uploaded_text",
) -> PromptShieldResult:
    """Run Prompt Shields on uploaded text and return the parsed result."""
    clean_text = (text or "").strip()
    if not clean_text:
        log.info("[promptshields] skipping empty %s", label)
        return PromptShieldResult(False, False, False, [], {"skipped": "empty"})

    if _is_disabled():
        log.warning("[promptshields] %s check disabled via %s", label, _DISABLED_ENV)
        return PromptShieldResult(False, False, False, [], {"skipped": "disabled"})

    endpoint = _get_endpoint()
    api_version = _get_api_version()
    doc_list = _coerce_documents(documents)
    cache_key = _hash_text("\x1f".join([clean_text, *doc_list]))
    if cache_key in _scan_cache:
        return _scan_cache[cache_key]

    payload = {"userPrompt": clean_text}
    if doc_list:
        payload["documents"] = doc_list

    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }
    url = f"{endpoint}/contentsafety/text:shieldPrompt"
    params = {"api-version": api_version}
    log.debug("[promptshields] scanning %s digest=%s", label, cache_key)
    data = _post_with_retry(url, payload, headers, params)

    user_analysis = data.get("userPromptAnalysis") or {}
    docs_analysis = data.get("documentsAnalysis") or []

    user_attack = bool(user_analysis.get("attackDetected"))
    document_attack = any(bool(item.get("attackDetected")) for item in docs_analysis)
    attack_detected = bool(data.get("attackDetected")) or user_attack or document_attack

    attack_types: List[str] = []
    maybe_type = user_analysis.get("attackType")
    if maybe_type:
        attack_types.append(str(maybe_type))
    for category in user_analysis.get("attackCategories") or []:
        attack_types.append(str(category))
    for item in docs_analysis:
        doc_type = item.get("attackType")
        if doc_type:
            attack_types.append(str(doc_type))
        for category in item.get("attackCategories") or []:
            attack_types.append(str(category))

    shielding_type = data.get("shieldingType")
    confidence = user_analysis.get("confidence")
    categories = user_analysis.get("attackCategories") or []
    reason = user_analysis.get("attackReason") or data.get("message")

    result = PromptShieldResult(
        attack_detected=attack_detected,
        user_prompt_attack=user_attack,
        document_attack=document_attack,
        attack_types=attack_types,
        raw_response=data,
        shielding_type=shielding_type,
        confidence=confidence,
        categories=categories,
        reason=reason,
    )
    _scan_cache[cache_key] = result
    return result


def ensure_uploaded_text_safe(
    text: str,
    *,
    documents: Optional[Iterable[str]] = None,
    label: str = "uploaded_text",
) -> PromptShieldResult:
    """Raise if Prompt Shields detects an attack in the uploaded content."""
    result = scan_uploaded_text(text, documents=documents, label=label)
    if result.attack_detected:
        log.error(
            "[promptshields] attack detected for %s (user=%s doc=%s types=%s)",
            label,
            result.user_prompt_attack,
            result.document_attack,
            result.attack_types,
        )
        detail_parts: List[str] = []
        if result.reason:
            detail_parts.append(str(result.reason))
        if result.attack_types:
            detail_parts.append(f"types={list(result.attack_types)}")
        raise PromptShieldAttackDetected(
            f"Prompt Shields flagged {label} as unsafe ({'; '.join(detail_parts) or 'unspecified reason'})."
        )
    return result
