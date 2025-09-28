# Changelog

# Changelog

## 2025-09-28
### Added
- Key Vault-backed admin roster loader that resolves privileged users from the `RAI-ASSESSMENT-ADMINS` secret (with caching and fallback env support) so admin rotation no longer requires code changes.
- Per-session CSRF tokens injected via meta tags/hidden fields and attached to all HTMX requests, blocking cross-site POST attempts across auth, uploads, settings, and admin endpoints.

### Changed
- Admin authorization now matches display name, UPN, or object ID against both allow and admin lists, reusing the same caching + Key Vault retrieval path as the standard allow list while retaining the localhost-only dev bypass toggle.
- Frontend `app.js` now adds the CSRF header on every HTMX request; server routes enforce validation before executing side effects.

## 2025-09-27
### Added
- HTMX dashboard progress feed partial with `/progress` polling so in-flight `ui_hook` messages surface in real time (step list + toast queue).
 - Progress sink wiring for `/generate` so draft creation emits live updates and toasts like analysis.
 - Docker build arg `STATIC_ASSET_VERSION` to stamp static asset URLs per image build.
- Settings modal footer now surfaces the current build timestamp sourced from the `BUILD_TIME` environment variable for auditability.

### Fixed
- Generation failures now roll back partial outputs and re-render the dashboard with a toast message instead of returning HTTP 500 errors.
- Duplicate toast notifications eliminated via session-scoped dedupe on the backend paired with client-side suppression of repeat payloads.

### Changed
- Dashboard templates and CSS updated to embed the live progress panel and companion styling while versioning static assets to bust browser caches on deploy.
- Session state now tracks `live_progress` payloads and pending toast batches, ensuring the poller drains state safely before deactivating.
 - Generation flow initializes session progress buffers before template updates and only raises errors on genuine failures.
 - HTMX polling trigger rewritten to check `this.dataset.progressActive` so client-side console errors no longer fire on load.
 - Analysis & generation now run in a thread pool to keep `/progress` polling and toast delivery responsive during long-running operations.
 - Toast notifications listen on document-level HX triggers so progress toasts surface during execution, and the progress panel hides automatically once a run completes.
 - Progress collector sanitizes incoming messages to reject HTML/control characters before they reach the UI.

## 2025-09-25
### Changed
- README reasoning-summary section updated to document the Azure OpenAI client migration and clarified fallback behaviour.

### Fixed
- Replaced generic `openai` client with `AzureOpenAI` so Responses API requests target deployment-scoped endpoints, eliminating 404 errors and restoring reasoning summary capture.
- Ensured Azure OpenAI client retains compatibility attributes (`api_type`, `azure_endpoint`, `api_version`, `azure_ad_token_provider`) for downstream diagnostics.

## 2025-09-23
### Added
- Admin sidebar model selector with per‑model pricing (EUR / 1K input & output tokens).
- Reasoning model support (gpt‑5 family, o*-series) including reasoning effort selector (minimal | low | medium | high).
- Adaptive reasoning parameter invocation (progressive removal of unsupported params: response_format → max_completion_tokens → reasoning_effort).
- Inclusion of hidden reasoning_tokens in cost calculation (output tokens = completion_tokens + reasoning_tokens).
- Expanded pricing metadata (cached_input_cost_per_1k, reasoning flag, context windows) in `helpers/completion_pricing.py`.
- Memory bank documentation updates (activeContext, progress, systemPatterns, techContext, projectBrief).
- `architecture.md` (high-level architecture & data flow) and this `changelog.md`.

### Changed
- README translated to English and expanded (cost model, reasoning, roadmap, production hardening checklist).
- Pricing entries for gpt-4.1*, gpt-5*, o4-mini converted from per 1M → per 1K tokens.
- Cost logging now shows reasoning token breakdown when applicable.

### Fixed
- Always-true JSON mode condition (`if '32-k' or 'mistral' in model.lower()`) replaced with explicit substring checks.
- Restored lost body of `process_solution_description_analysis` (was returning None, causing unpack TypeError).
- Removed unsupported parameters (temperature, top_p, penalties, max_tokens) from reasoning calls.

### Known Issues
- Non-Azure (Mistral) path still references undefined `mistral` client if executed—guard or implement strategy pattern.
- Broad exception handling in adaptive reasoning helper may mask credential / quota errors.
- Pricing still static; no automated sync from provider pricing endpoints.

## 2025-09-22
### Added
- Pricing validation script (detects zero or placeholder pricing entries) [initial commit earlier in cycle].
- Extended pricing metadata structure (`MODEL_METADATA`).

### Changed
- GPT-5 pricing corrected from per 1M tokens to per 1K tokens after unit conversion review.

## 2024-06 – 2025-08 (Historical Summary)
- Streamlit UI with progress tracking and dual DOCX output support.
- Key Vault / Azure AD integration (keyless authentication pattern).
- llmlingua v2 optional prompt compression integrated.
- Local pickle-based completion cache with cost persistence.
- Multi-step generation pipeline (Intended Uses → Disclosures) established.

---
Future entries should follow Keep a Changelog style with Added / Changed / Fixed / Removed / Security sections where relevant.
