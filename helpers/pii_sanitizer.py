"""Utilities for detecting PII in uploaded content via Azure AI Language."""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests
from azure.core.credentials import AccessToken  # type: ignore
from azure.identity import DefaultAzureCredential  # type: ignore

from helpers.logging_setup import get_logger

log = get_logger(__name__)

_SCOPE = "https://cognitiveservices.azure.com/.default"
_DEFAULT_API_VERSION = "2023-04-01"
_ENDPOINT_ENV = "AZURE_LANGUAGE_ENDPOINT"
_DISABLED_ENV = "AZURE_LANGUAGE_PII_DISABLED"
_LANGUAGE_ENV = "AZURE_LANGUAGE_PII_LANGUAGE"
_AUTO_DETECT_ENV = "AZURE_LANGUAGE_PII_AUTO_DETECT"
_DOMAIN_ENV = "AZURE_LANGUAGE_PII_DOMAIN"
_CATEGORIES_ENV = "AZURE_LANGUAGE_PII_CATEGORIES"
_ALLOWLIST_ENV = "AZURE_LANGUAGE_PII_ALLOWLIST"
_MAX_DOC_CHARS_ENV = "AZURE_LANGUAGE_PII_MAX_CHARS"
_DEFAULT_LANGUAGE = "en"
_DEFAULT_MAX_CHARS = 4800
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5
_TOKEN_REFRESH_BUFFER = 60  # seconds

_credential: Optional[DefaultAzureCredential] = None
_cached_token: Optional[AccessToken] = None
_SESSION = requests.Session()


class PiiConfigurationError(RuntimeError):
	"""Raised when the PII detection service is misconfigured."""


class PiiServiceError(RuntimeError):
	"""Raised when the PII detection service fails."""


class PiiDetectionError(RuntimeError):
	"""Raised when PII is detected in the supplied text."""


@dataclass
class PiiEntity:
	"""Represents a detected PII entity."""

	category: str
	offset: int
	length: int
	confidence: float
	subcategory: Optional[str] = None
	text_preview: Optional[str] = None
	raw_text: Optional[str] = None

	@property
	def confidence_percent(self) -> int:
		return max(0, min(100, int(round(self.confidence * 100))))

	@property
	def description(self) -> str:
		label = self.category
		if self.subcategory:
			label = f"{label} ({self.subcategory})"
		return f"{label} · {self.confidence_percent}% confidence"

	@property
	def preview(self) -> Optional[str]:
		return self.text_preview

	@property
	def display_text(self) -> str:
		if self.raw_text:
			return self.raw_text
		if self.text_preview:
			return self.text_preview
		return ""

	def canonical_key(self) -> Tuple[str, bool]:
		"""Return normalized key and flag indicating whether it originated from text."""

		raw = (self.raw_text or "").strip()
		if not raw:
			raw = (self.text_preview or "").strip()
		if raw:
			return _normalize_term(raw), True
		return _normalize_term(self.description), False


@dataclass
class PiiScanResult:
	"""Outcome of invoking Azure AI Language PII detection."""

	entities: Sequence[PiiEntity]
	redacted_text: str
	raw_response: Dict[str, Any]
	chunk_count: int
	language: str

	@property
	def has_pii(self) -> bool:
		return bool(self.entities)

	def summary_items(self) -> List[str]:
		counts: Dict[Tuple[str, bool], int] = {}
		for entity in self.entities:
			key = entity.canonical_key()
			counts[key] = counts.get(key, 0) + 1
		items: List[str] = []
		for entity in self.unique_entities():
			snippet = entity.display_text
			descriptor = entity.description
			key = entity.canonical_key()
			occurrences = counts.get(key, 1)
			if snippet:
				text = f"Detected '{snippet}' — {descriptor}"
			else:
				text = descriptor
			if occurrences > 1:
				text = f"{text} · {occurrences} occurrences"
			items.append(text)
		return items

	def unique_entities(self) -> List[PiiEntity]:
		text_entities: Dict[str, PiiEntity] = {}
		descriptor_entities: Dict[str, PiiEntity] = {}
		for entity in self.entities:
			key, has_text = entity.canonical_key()
			if has_text:
				current = text_entities.get(key)
				if current is None or entity.confidence > current.confidence:
					text_entities[key] = entity
			else:
				current = descriptor_entities.get(key)
				if current is None or entity.confidence > current.confidence:
					descriptor_entities[key] = entity
		ordered = list(text_entities.values()) + list(descriptor_entities.values())
		ordered.sort(key=lambda e: (0 if e.canonical_key()[1] else 1, e.canonical_key()[0]))
		return ordered


def _is_disabled() -> bool:
	flag = os.getenv(_DISABLED_ENV, "").strip().lower()
	return flag in {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
	raw = os.getenv(name)
	if raw is None:
		return default
	return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_endpoint() -> str:
	endpoint = os.getenv(_ENDPOINT_ENV, "").strip()
	if not endpoint:
		raise PiiConfigurationError(
			f"Missing {_ENDPOINT_ENV}; configure your Azure AI Language endpoint or set {_DISABLED_ENV}=1 to bypass."
		)
	return endpoint.rstrip("/")


def _get_api_version() -> str:
	return os.getenv("AZURE_LANGUAGE_API_VERSION", _DEFAULT_API_VERSION)


def _get_language_override() -> str:
	return os.getenv(_LANGUAGE_ENV, "").strip()


def _get_domain() -> Optional[str]:
	domain = os.getenv(_DOMAIN_ENV, "").strip()
	return domain or None


def _get_categories() -> Optional[List[str]]:
	raw = os.getenv(_CATEGORIES_ENV, "").strip()
	if not raw:
		return None
	return [part.strip() for part in raw.split(",") if part.strip()]


def _get_max_chars() -> int:
	raw = os.getenv(_MAX_DOC_CHARS_ENV)
	if raw:
		try:
			value = int(raw)
			if value >= 256:
				return min(value, 15000)
		except ValueError:
			pass
	return _DEFAULT_MAX_CHARS


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


def _chunk_text(text: str, max_chars: int) -> Tuple[List[str], List[int]]:
	if max_chars <= 0:
		return [text], [0]
	chunks: List[str] = []
	offsets: List[int] = []
	cursor = 0
	length = len(text)
	while cursor < length:
		chunk = text[cursor : cursor + max_chars]
		chunks.append(chunk)
		offsets.append(cursor)
		cursor += max_chars
	if not chunks:
		chunks = [""]
		offsets = [0]
	return chunks, offsets


def _mask_hash(text: str) -> str:
	if not text:
		return "sha1:0"
	digest = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
	return f"sha1:{digest[:12]}"


def _preview_text(raw_text: str) -> str:
	preview = (raw_text or "").strip()
	preview = preview.replace("\n", " ").replace("\r", " ")
	preview = re.sub(r"\s+", " ", preview)
	if len(preview) > 80:
		preview = f"{preview[:40]}…{preview[-35:]}"
	return preview


def _normalize_term(value: str) -> str:
	return re.sub(r"\s+", " ", value.strip()).lower()


def _get_allowlist() -> Set[str]:
	raw = os.getenv(_ALLOWLIST_ENV, "")
	if not raw:
		return set()
	parts = raw.replace("\n", ",")
	entries = [part.strip() for part in parts.split(",") if part.strip()]
	return {_normalize_term(entry) for entry in entries}


def _detect_language(text: str) -> Optional[str]:
	sample = (text or "").strip()
	if not sample:
		return None
	max_len = min(len(sample), 10000)
	sample = sample[:max_len]
	endpoint = _get_endpoint()
	api_version = _get_api_version()
	documents = [{"id": "1", "text": sample}]
	payload = {
		"kind": "LanguageDetection",
		"analysisInput": {"documents": documents},
		"parameters": {"stringIndexType": "Utf16CodeUnit"},
	}
	headers = {
		"Authorization": f"Bearer {_get_token()}",
		"Content-Type": "application/json",
	}
	url = f"{endpoint}/language/:analyze-text"
	params = {"api-version": api_version}
	try:
		data = _post_with_retry(url, payload, headers, params)
	except Exception as exc:  # noqa: BLE001
		log.warning("[pii] language detection failed: %s", exc)
		return None
	results = data.get("results") or {}
	docs: Iterable[Dict[str, Any]] = results.get("documents") or []
	for doc in docs:
		candidates: Iterable[Dict[str, Any]] = doc.get("detectedLanguages") or []
		best_lang = None
		best_score = 0.0
		for candidate in candidates:
			language = str(candidate.get("language") or "")
			confidence = float(candidate.get("confidenceScore") or 0.0)
			if confidence > best_score and language:
				best_lang = language
				best_score = confidence
		if best_lang and best_score >= 0.5:
			log.debug("[pii] language detection chose %s (%.2f confidence)", best_lang, best_score)
			return best_lang
	return None


def _determine_language(text: str) -> str:
	override = _get_language_override()
	if override:
		return override
	if not _env_bool(_AUTO_DETECT_ENV, True):
		return _DEFAULT_LANGUAGE
	try:
		language = _detect_language(text)
	except PiiConfigurationError:
		return _DEFAULT_LANGUAGE
	if language:
		return language
	return _DEFAULT_LANGUAGE


def _post_with_retry(url: str, payload: Dict[str, Any], headers: Dict[str, str], params: Dict[str, Any]) -> Dict[str, Any]:
	last_exc: Optional[Exception] = None
	for attempt in range(1, _RETRY_ATTEMPTS + 1):
		try:
			response = _SESSION.post(url, params=params, json=payload, headers=headers, timeout=20)
			if response.status_code // 100 != 2:
				detail = _safe_json(response)
				log.warning("[pii] non-success response %s detail=%s", response.status_code, detail)
				raise PiiServiceError(f"PII detection call failed with status {response.status_code}")
			try:
				return response.json()
			except ValueError as exc:
				log.warning("[pii] failed to parse response JSON: %s", exc)
				raise PiiServiceError("PII detection returned invalid JSON") from exc
		except PiiServiceError as exc:
			last_exc = exc
		except requests.RequestException as exc:
			last_exc = exc
			log.warning("[pii] request attempt %s failed: %s", attempt, exc)
		if attempt < _RETRY_ATTEMPTS:
			time.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
	assert last_exc is not None
	raise PiiServiceError("PII detection request failed") from last_exc


def _safe_json(response: requests.Response) -> Any:
	try:
		return response.json()
	except ValueError:
		return response.text[:200]


def scan_text_for_pii(
	text: str,
	*,
	label: str = "uploaded_text",
	additional_allowlist: Optional[Sequence[str]] = None,
) -> PiiScanResult:
	"""Scan text for PII entities using Azure AI Language."""

	clean_text = (text or "").strip()
	language = _determine_language(clean_text)
	if not clean_text:
		return PiiScanResult(entities=(), redacted_text="", raw_response={"skipped": "empty"}, chunk_count=0, language=language)

	if _is_disabled():
		log.info("[pii] scan disabled via %s", _DISABLED_ENV)
		return PiiScanResult(entities=(), redacted_text=clean_text, raw_response={"skipped": "disabled"}, chunk_count=0, language=language)

	endpoint = _get_endpoint()
	api_version = _get_api_version()
	domain = _get_domain()
	categories = _get_categories()
	max_chars = _get_max_chars()
	allowlist: Set[str] = set(_get_allowlist())
	if additional_allowlist:
		for entry in additional_allowlist:
			if entry is None:
				continue
			allowlist.add(_normalize_term(str(entry)))

	chunks, offsets = _chunk_text(clean_text, max_chars)
	documents = []
	for idx, chunk in enumerate(chunks, start=1):
		documents.append({"id": str(idx), "text": chunk, "language": language})

	parameters: Dict[str, Any] = {"stringIndexType": "Utf16CodeUnit"}
	if domain:
		parameters["domain"] = domain
	if categories:
		parameters["piiCategories"] = categories

	payload = {
		"kind": "PiiEntityRecognition",
		"analysisInput": {"documents": documents},
		"parameters": parameters,
	}

	headers = {
		"Authorization": f"Bearer {_get_token()}",
		"Content-Type": "application/json",
	}
	url = f"{endpoint}/language/:analyze-text"
	params = {"api-version": api_version}

	log.debug("[pii] scanning %s chunks=%s len=%s", label, len(chunks), len(clean_text))
	data = _post_with_retry(url, payload, headers, params)

	results = data.get("results") or {}
	result_docs: Iterable[Dict[str, Any]] = results.get("documents") or []
	errors: Iterable[Dict[str, Any]] = results.get("errors") or []

	error_messages = [f"id={err.get('id')}: {err.get('error', {}).get('message')}" for err in errors]
	if error_messages:
		raise PiiServiceError(f"PII detection returned document errors: {'; '.join(error_messages)}")

	entities: List[PiiEntity] = []
	redacted_parts: List[str] = []
	allowed_spans: List[Tuple[int, int]] = []

	for doc in result_docs:
		doc_id = str(doc.get("id") or "1")
		try:
			doc_index = int(doc_id) - 1
		except ValueError:
			doc_index = 0
		base_offset = offsets[doc_index] if 0 <= doc_index < len(offsets) else 0
		for entity in doc.get("entities") or []:
			category = str(entity.get("category") or "Unknown")
			subcategory = entity.get("subCategory") or None
			offset = int(entity.get("offset") or 0) + base_offset
			length = int(entity.get("length") or 0)
			confidence = float(entity.get("confidenceScore") or 0.0)
			raw_text = entity.get("text") or ""
			raw_value = str(raw_text)
			preview_text = _preview_text(raw_value) if raw_value else None
			normalized_raw = _normalize_term(raw_value) if raw_value else ""
			if allowlist and normalized_raw in allowlist:
				allowed_spans.append((offset, length))
				log.debug(
					"[pii] allowlist matched '%s' (category=%s) at offset=%s",
					raw_value or preview_text or raw_text,
					category,
					offset,
				)
				continue
			log.debug(
				"[pii] entity category=%s sub=%s offset=%s length=%s mask=%s",
				category,
				subcategory,
				offset,
				length,
				_mask_hash(raw_value),
			)
			entities.append(
				PiiEntity(
					category=category,
					subcategory=str(subcategory) if subcategory else None,
					offset=offset,
					length=length,
					confidence=confidence,
					text_preview=preview_text,
					raw_text=raw_value or None,
				)
			)
		redacted = doc.get("redactedText")
		if isinstance(redacted, str):
			redacted_parts.append(redacted)

	if not redacted_parts:
		redacted_text = clean_text
	else:
		redacted_text = "".join(redacted_parts)

		if allowlist and allowed_spans:
			if len(redacted_text) == len(clean_text):
				temp_chars = list(redacted_text)
				for start, length in allowed_spans:
					end = min(start + length, len(temp_chars))
					temp_chars[start:end] = clean_text[start:end]
				redacted_text = "".join(temp_chars)
			elif not entities:
				redacted_text = clean_text
		if allowlist and allowed_spans and not entities:
			log.debug("[pii] all detected entities were allowlisted and ignored")

	return PiiScanResult(
		entities=tuple(entities),
		redacted_text=redacted_text,
		raw_response=data,
		chunk_count=len(chunks),
		language=language,
	)


def ensure_text_is_pii_free(text: str, *, label: str = "uploaded_text") -> PiiScanResult:
	"""Scan text and raise if PII is detected."""

	result = scan_text_for_pii(text, label=label)
	if result.has_pii:
		raise PiiDetectionError("PII detected in the supplied text.")
	return result

