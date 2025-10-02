# System Patterns: Copilot Memory Bank

## System Architecture

High-Level Layers:
1. Ingestion Layer: CLI (`main.py`), Streamlit UI (`streamlit_ui_main.py`), and HTMX/FastAPI UI (`htmx_ui_main.py`)
2. Orchestration & Prompt Pipeline: `prompts/prompts_engineering_llmlingua.py`
3. Processing Utilities: document mutation (`helpers/docs_utils.py`), caching (`helpers/cache_completions.py`), pricing (`helpers/completion_pricing.py`), auth/session (`helpers/user_auth.py`), blob/keyvault integration (`helpers/blob_cache.py`), PII detection (`helpers/pii_sanitizer.py`)
4. Persistence / External Services: Azure OpenAI / Mistral (LLM), Azure Key Vault (secrets + config, allow/admin rosters), Azure Blob (logs & allow‑list), Local FS (cache, outputs)
5. Presentation: Streamlit reactive components (progress, download, parameter toggles) plus HTMX partials with polling-driven progress feed, toast queue, and shared static assets

Data Flow (UI path):
Upload DOCX → Extract raw text inside sandboxed worker (resource caps via `UPLOAD_PARSER_*`) → Run Azure Content Safety Prompt Shields (helpers/content_safety.py; managed identity, retry/cache) → Invoke Azure AI Language PII scan (helpers/pii_sanitizer.py) with chunking, auto language detection, and allowlist support → Present deduplicated remediation queue where users anonymize spans or approve false positives (session-level allowlist) → Initialize models (credential + endpoints) → (Admin selects model & reasoning effort if authorized) → Multi-step LLM calls (adaptive params, JSON or text) → Accumulate token replacement map → Apply replacements & prune template → Save DOCX variants → Offer ZIP/individual downloads → Stream progress via Streamlit callbacks or HTMX `/progress` poller (step list + toasts) → Log user actions & usage.

## Key Technical Decisions

- Sequential pipeline with ordered dependencies (Intended Uses precedes Stakeholders etc.) simplifies state management.
- Token replacement via direct DOCX paragraph + table traversal avoids template pre-compilation; trades speed for simplicity.
- Local pickle cache keyed by composite hash reduces repeated LLM costs; simplicity preferred over distributed cache in MVP.
- Keyless Azure AD auth chosen over static keys (security posture improvement) where supported.
- Allow and admin rosters centralized in Key Vault secrets so access can be rotated without code changes.
- Azure Content Safety Prompt Shields enforce pre-ingestion scanning using managed identity-authenticated REST calls; helper caches verdicts to reduce duplicate scans and surfaces developer-friendly diagnostics.
- HTMX upload ingestion helper persists a `stored_solution_validated` flag in session state so downstream analysis/generation paths trust previously scanned text, eliminating duplicate ClamAV or Content Safety invocations while still forcing revalidation when a new file arrives.
- Remediation route stores user-approved PII terms in a per-session allowlist, feeds the additional allowlist into subsequent Azure AI Language scans, and deduplicates entities by canonical key so recap cards display unique findings with occurrence counts.
- Self-hosted htmx asset upgraded to 2.0.7 with client defaults forcing smooth scroll + native form validity prompts so 2.x behavioral changes do not regress UX.
- Prompt sanitizer helper (`sanitize_prompt_input`) runs after Content Safety to normalize user uploads, neutralize jailbreak directives, escape template markers, and optionally block high-risk patterns before prompts are built, giving future user inputs a reusable defense layer.
- Optional llmlingua compression controlled per-run to manage risk of semantic loss.
- Bias / risk analysis separated from generation (distinct functions) enabling optional pre-flight validation.
- HTMX UI hardened with per-session CSRF tokens and session-scoped toast dedupe to avoid replay.

## Design Patterns

- Pipeline Pattern: Ordered list of (name, prompt, temperature, mode, processor) driving uniform execution.
- Adapter Pattern (implicit): Abstraction over Azure OpenAI vs Mistral via conditional branches (candidate for explicit interface).
- Caching Pattern: MD5 signature –> serialized response (model, lang, pricing, content) enabling reuse & cost display.
- Template Method (partial): `get_azure_openai_completion` + adaptive reasoning helper (param fallback, unsupported param stripping, cost integration).
- Token Replacement Strategy: Two passes (collect vs. incremental update if `update_steps=True`).
- Defensive Parsing: `get_json_from_answer` attempts normalization & reshaping when model output deviates.
- Security Gate: Prompt Shield helper throws typed exceptions that short-circuit the pipeline before unsafe content reaches prompts.

## Component Relationships

| Component | Depends On | Provides |
|-----------|------------|----------|
| `htmx_ui_main.py` | helpers.*, prompts.*, `templates/htmx/*`, `static/js/app.js` | HTMX/FastAPI UI endpoints, live progress poller, toast dedupe orchestration, Key Vault allow/admin roster loaders, CSRF validation |
| `streamlit_ui_main.py` | helpers.*, prompts.* | User interaction, progress, output delivery |
| `main.py` | prompts module, docs_utils | CLI doc generation |
| `prompts_engineering_llmlingua.py` | helpers.*, llmlingua, openai | Orchestrates multi-step LLM workflow |
| `helpers/docs_utils.py` | docx, pdfminer | File extraction & DOCX mutation |
| `helpers/cache_completions.py` | hashlib, pickle | Response caching layer |
| `helpers/blob_cache.py` | azure.identity, storage, keyvault | Logs + secret retrieval |
| `helpers/user_auth.py` | Streamlit, requests | Authentication info retrieval |
| `helpers/completion_pricing.py` | static pricing table | Cost estimation |
| `static/js/app.js` | Bootstrap toasts, HTMX events, `htmx_ui_main.py` data attributes | Client-side toast rendering, dedupe suppression, progress UX glue |
| `templates/htmx/partials/*` | Jinja context from `htmx_ui_main.py` | Shared partials for progress feed, settings modal, and build metadata display |
| `helpers/content_safety.py` | azure.identity, requests | Managed identity auth, prompt shield payload assembly, caching/verdict interpretation |

Scalability Considerations:
- Current single-instance assumptions (local cache, no locking)
- Blob log append risk under concurrency (no atomic semantics at app layer)
- Statelessness of generation pipeline favorable for future queue-based orchestration.

Resilience Gaps:
- Limited retry/backoff; broad exception catches reduce observability.
- Prompt Shield service errors currently bubble to users after retry; consider queueing + admin alerting.
- No circuit breaker around LLM provider errors.
- Adaptive reasoning fallback uses broad exception capture (risk: masks credential/quota errors) – requires refinement (simplified after removing forced output cap).

Extensibility Hooks:
- Adding a new section = append to `steps` list with processor + prompt constant.
- Switching model provider: encapsulate conditional branches behind interface.
- Adding new reasoning tiers: extend effort → (optional future output cap) + pricing metadata.
- CSRF middleware pattern can be adapted to future SPAs by emitting per-session tokens via meta tags + JS header injection.

