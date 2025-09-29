# Progress: Copilot Memory Bank

# Development Progress: Solver Pipeline with Dynamic Reasoning

## Project Timeline

- Mar 2024: Initial prototype (CLI) for DOCX token replacement and LLM section generation.
- Mar–Jun 2024: Streamlit UI added (authentication component, progress tracker, dual templates, caching).
- Jun 2024: Azure Blob logging + Key Vault integration; optional llmlingua prompt compression introduced.
- Feb 2025: Container Apps deployment revision (see `azure-container-apps/app-raiassessment.yaml`).
- Sep 2025 (early): Architectural analysis + memory-bank initialization.
- Sep 2025 (mid): Added admin model selector, reasoning effort control, adaptive reasoning param handling, reasoning token cost inclusion.
- Sep 2025 (late): Removed `max_completion_tokens` cap for reasoning models (allow long outputs); added dynamic log level UI, raw response & empty-answer diagnostics, noisy logger suppression, Responses API reasoning summaries, single-click timestamped system logs download.
- Sep 2025 (latest): Switched to `AzureOpenAI` SDK client to keep Responses API calls on deployment endpoints (fixing 404 fallbacks) and ensured rotating file handler captures DEBUG traces regardless of console level.
- Sep 2025 (current): Delivered HTMX + FastAPI UI alternative (`htmx_ui_main.py`) with shared templates/static assets while tightening local dev auth bypass (explicit `HTMX_ALLOW_DEV_BYPASS` + localhost restriction) and documenting dual-launch workflows.
- 2025-09-26: Matched Streamlit MSAL authentication inside HTMX (Graph validation, allow-list parity, session cookie) and hardened Container Apps provisioning for idempotent redeploys (Log Analytics `customerId`, RBAC-safe Key Vault set-policy, forced revision updates) with README alignment.
- 2025-09-27: Implemented HTMX live progress polling (`/progress`) with session-backed queues for incremental `ui_hook` updates, real-time toast delivery, and cache-busted static assets ensuring freshly deployed CSS/JS loads without manual refresh. Generation path now mirrors analysis (progress sink, toast queue, graceful failure handling), the poller condition was corrected to a dataset comparison to stop HTMX syntax errors, Docker builds inject `STATIC_ASSET_VERSION` for deterministic cache busting, and subsequent JS/backend refinements ensure toast payloads hydrate immediately after HX swaps while clearing residual progress state so the "Live processing" banner disappears once results render while progress steps now render as bold div rows without ordered numbering for improved readability. Follow-on hardening introduced session-scoped toast dedupe (paired with client-side suppression) to stop duplicate notifications and surfaced the build timestamp in the settings modal for quick release provenance checks.
- 2025-09-28: Replaced hard-coded admin checks with a Key Vault backed roster (`RAI-ASSESSMENT-ADMINS`) mirrored after the allow list, caching the secret and supporting local fallbacks so admin access can be rotated without redeploying while development bypass remains opt-in and localhost-only.
- 2025-09-28: Added per-session CSRF tokens enforced across HTMX POST routes (auth, uploads, settings, admin actions) with client-side header injection and hidden form fallbacks, closing the cross-site request forgery gap.
- 2025-09-28 (late): Wired Azure Content Safety Prompt Shields into HTMX upload/analysis flows (managed identity auth, retry/caching helper, user messaging) and extended the Container Apps setup script to auto-provision the Content Safety resource plus RBAC (`Cognitive Services User`) while documenting new `AZURE_CONTENT_SAFETY_*` env vars in `.env`/`.env.template`.
- 2025-09-28 (latest): Validated managed-identity access against the custom Content Safety subdomain, updated `helpers/content_safety.py` to send `userPrompt` + `documents` as plain strings per the REST contract, refreshed the cache key to prevent stale verdict reuse, and confirmed `.env` / `.env.template` configurations align with the working curl sample for future debugging.
- 2025-09-29: Added `.dockerignore` to shrink the Docker build context, created `azure-container-apps/sync_env_to_containerapp.sh` to replicate local `.env` values into the Container App (with dry-run/exclude/prune options), and updated the markdown sanitizer to allow heading tags so HTMX renders analysis sections with proper titles.
- 2025-09-29 (later): Hardened `/auth/session` with offline token validation (signature and claim checks with safe fallback) and confirmed production login works under the stricter validation path.
- 2025-09-29 (latest): Implemented phased HTMX upload guardrails: Phase 1/2 introduced extension/MIME allow list, chunked streaming to a locked temp dir, size caps, UTF-8 enforcement, optional `python-magic`, DOCX/PDF/JSON/TXT validators, and safer zip packaging; Phase 3 now adds decompression-bomb detection, macro linting, PDF active-content blocking, and an optional malware scan command. Syntax verified via `python -m compileall htmx_ui_main.py`.
- 2025-09-29 (latest+1): Restricted malware scanning to genuinely new uploads so stored documents skip redundant ClamAV runs, tightened HTMX form submissions to avoid re-posting file inputs, and kept Azure Content Safety verification in place for both new uploads and stored text reuse.
- 2025-09-29 (latest+2): Sandboxed PDF/DOCX parsing via resource-constrained worker processes (CPU/memory/time caps), surfaced friendly error handling across HTMX and CLI paths, and introduced env toggles (`UPLOAD_PARSER_TIMEOUT`, `UPLOAD_PARSER_CPU_SECONDS`, `UPLOAD_PARSER_MEMORY_MB`) for future tuning.
- 2025-09-29 (latest+3): Added a background ClamAV warm-up thread on FastAPI startup so the first scan completes before users interact, replaced queued toast messages in-place to avoid duplicate banners, hid reasoning-effort controls unless a reasoning-capable model is selected, and expanded completion cache keys to include model + reasoning effort to prevent cross-model reuse.

## What Works

- Multi-step deterministic pipeline producing two DOCX drafts (internal + public)
- Structured JSON parsing & transformation into search/replace dict
- Intended Use dependent pruning of unused template pages
- Basic bias / risk detection + optional rewritten solution description
- Local pickle cache keyed by MD5 of composite prompt signature (model/lang/temp/compress/reasoning-effort)
- FastAPI startup primes the ClamAV scanner in a background thread so the first malware check finishes before users launch a scan
- Reasoning effort/verbosity controls dynamically hide for non-reasoning models to keep the settings modal focused
- Progress feedback & cost estimation (now includes reasoning token component for reasoning models)
- Key Vault + DefaultAzureCredential (supports managed identity / keyless)
- Download packaging (ZIP of both assessments)
- Dual UI surfaces (Streamlit & HTMX/FastAPI) sharing the same business logic and allow-list enforcement, now with live progress feed + toast queue in the HTMX experience
- Admin roster + allow list centrally managed via Key Vault secrets with cached fallbacks for resilience and zero-code rotation
- CSRF protection enforced on all state-changing endpoints via per-session tokens, HTMX header injection, and server-side validation
- Optional prompt compression (llmlingua v2) for cost reduction

## What's Left to Build

- Robust unit & integration tests (none present for processors / JSON schema)
- Structured logging & telemetry (currently plain text appends)
- Retry / timeout / backoff policies for LLM calls
- Cache invalidation strategy (currently manual deletion only)
- Horizontal scaling readiness (shared cache + idempotent steps)
- Quarantine workflow for flagged uploads (durable storage + admin review) and automated reporting
- Multi-language output parameterization
- Role-based admin / audit (admin list now secret driven but lacks fine-grained roles/audit trail)
- Formal automated CSRF regression tests (manual validation only so far)
- Output quality scoring / evaluation harness
- Persist & surface reasoning vs visible token breakdown per step
- Optional env var controlled output length guardrail (off by default)
- Secrets inventory & rotation process documentation

## Current Status

Prototype / advanced MVP. Functional for internal controlled users; not production-hardened for broader enterprise rollout.

## Known Issues

| Area | Issue | Impact | Mitigation Status |
|------|-------|--------|-------------------|
| Error Handling | Broad except blocks swallow root causes | Debug difficulty | Add structured exceptions & logging |
| JSON Drift | Model typos (e.g., `inteduse`) require ad-hoc fixes | Fragile parsing | Implement schema validation & normalization layer |
| Caching | Pickle file not concurrency-safe | Race conditions in multi-instance | Migrate to Redis / Blob ETag guarded writes |
| Logging | Unstructured blob append | Hard to query / alert | Adopt JSON structured logs + Log Analytics |
| Security | User allow-list logic minimal | Unauthorized use risk if misconfigured | Enforce signed-in principal + RBAC roles (dev bypass now opt-in & localhost-only) |
| Cost Accuracy | Static pricing table may age | Misreported economics | Periodic sync or dynamic pricing fetch |
| Reasoning Cost Transparency | Reasoning tokens previously invisible | Underestimated cost | Included; need UI surfacing |
| Reasoning Extraction Depth | Current summary heuristic only | Limited insight / debugging | Planned deeper structured extraction + safe redaction |
| Empty Answer Recovery | No automatic retry yet | Occasional blank outputs persist | Implement one guarded retry with logging |
| Performance | Sequential steps; no reuse of partials | Longer latency | Persist intermediate JSON & skip unchanged |
| Prompt Compression | Minimal QA on semantic drift | Potential content loss | Add regression tests & opt-in gating |
