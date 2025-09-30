"""Prompt sanitization utilities to defend against injection attempts in uploaded text."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List

from helpers.logging_setup import get_logger

log = get_logger(__name__)

# Regex patterns for control characters and whitespace normalization.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Injection phrases we will neutralize in-place.
_INJECTION_PATTERNS = [
    re.compile(r"\b(?:ignore|forget)\s+(?:all\s+)?previous\s+(?:instructions|prompts)\b", re.IGNORECASE),
    re.compile(r"\b(?:disregard|bypass)\s+(?:all\s+)?safety\s+(?:rules|guidelines)\b", re.IGNORECASE),
    re.compile(r"<\|?\s*system\s*\|?>", re.IGNORECASE),
    re.compile(r"\b(?:override|disable)\s+(?:policies|guardrails)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+(?:is|becomes)\s+your\s+new\s+system\s+prompt\b", re.IGNORECASE),
    re.compile(r"\b(?:roleplay|simulate)\s+as\s+an\s+unrestricted\s+model\b", re.IGNORECASE),
]

# Template markers that must not slip into prompts unchanged.
_TEMPLATE_MARKER_REPLACEMENTS = (
    ("{{", "[["),
    ("}}", "]]"),
    ("<prompt>", "[prompt]"),
    ("</prompt>", "[/prompt]"),
)

# High-risk patterns that trigger an outright block instead of redaction.
_BLOCK_PATTERNS = [
    re.compile(r"\b(begin|start)\s+\w*\s*jailbreak\b", re.IGNORECASE),
    re.compile(r"\bdo\s+anything\s+now\b", re.IGNORECASE),
    re.compile(r"\b4chan\b", re.IGNORECASE),
]

# Suspicious keywords we will flag (still sanitized but worth logging).
_ALERT_PATTERNS = [
    re.compile(r"\b(base64|rot13|hex)\b", re.IGNORECASE),
    re.compile(r"\b(encrypt|encode)\s+the\s+following\b", re.IGNORECASE),
]

_REDACTION_TOKEN = "[sanitized-directive]"


@dataclass
class SanitizationFinding:
    message: str
    original: str = ""
    replacement: str = ""


@dataclass
class SanitizerResult:
    text: str
    findings: List[SanitizationFinding] = field(default_factory=list)
    blocked: bool = False

    @property
    def modified(self) -> bool:
        return bool(self.findings)


def sanitize_prompt_input(raw_text: str) -> SanitizerResult:
    """Neutralize common prompt-injection tricks while keeping readable text."""
    if raw_text is None:
        return SanitizerResult(text="")

    text = str(raw_text)
    findings: List[SanitizationFinding] = []
    blocked = False

    # Normalize Unicode to a canonical form to collapse lookalike characters.
    normalized = unicodedata.normalize("NFKC", text)
    if normalized != text:
        findings.append(SanitizationFinding(message="Unicode normalized to NFKC"))
    text = normalized

    # Remove non-printable control characters.
    cleaned = _CONTROL_CHARS_RE.sub("", text)
    if cleaned != text:
        findings.append(SanitizationFinding(message="Removed control characters"))
    text = cleaned

    # Collapse repeated spaces and blank lines to reduce obfuscation.
    collapsed_spaces = _MULTI_SPACE_RE.sub(" ", text)
    if collapsed_spaces != text:
        findings.append(SanitizationFinding(message="Collapsed repeated spaces"))
    text = collapsed_spaces

    collapsed_lines = _MULTI_NEWLINE_RE.sub("\n\n", text)
    if collapsed_lines != text:
        findings.append(SanitizationFinding(message="Collapsed repeated blank lines"))
    text = collapsed_lines

    # Neutralize known injection directives.
    for pattern in _INJECTION_PATTERNS:
        def _replacement(match: re.Match[str]) -> str:
            findings.append(
                SanitizationFinding(
                    message="Neutralized prompt directive",
                    original=match.group(0),
                    replacement=_REDACTION_TOKEN,
                )
            )
            return _REDACTION_TOKEN

        text, count = pattern.subn(_replacement, text)
        if count:
            log.debug("Prompt sanitizer neutralized %s occurrences of %s", count, pattern.pattern)

    # Escape template markers that could interfere with prompt formatting.
    for marker, replacement in _TEMPLATE_MARKER_REPLACEMENTS:
        if marker in text:
            text = text.replace(marker, replacement)
            findings.append(
                SanitizationFinding(
                    message=f"Escaped template marker '{marker}'",
                    original=marker,
                    replacement=replacement,
                )
            )

    # Flag suspicious keywords for auditing.
    for pattern in _ALERT_PATTERNS:
        if pattern.search(text):
            findings.append(
                SanitizationFinding(
                    message="Suspicious keyword detected",
                    original=pattern.pattern,
                )
            )

    # Block uploads containing obvious jailbreak cues that we do not want to rewrite.
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(text):
            findings.append(
                SanitizationFinding(
                    message="Blocked upload due to high-risk jailbreak cue",
                    original=pattern.pattern,
                )
            )
            blocked = True
            log.warning("Prompt sanitizer blocked upload due to pattern %s", pattern.pattern)
            break

    return SanitizerResult(text=text, findings=findings, blocked=blocked)
