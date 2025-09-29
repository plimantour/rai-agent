# Active Context: Copilot Memory Bank

## Current Work Focus

Initialize structured project knowledge for the RAI Assessment automation tool. Completed an in-depth codebase and architecture analysis covering:
- Execution modes: CLI (`main.py`) and Streamlit UI (`streamlit_ui_main.py`)
- Multi-step LLM-driven document generation pipeline (`prompts/prompts_engineering_llmlingua.py`)
- Azure integration (Key Vault, Managed Identity, Blob Storage logging & access control)
- Prompt compression via llmlingua2 (optional)
- Caching layer (local pickle MD5-keyed)
- DOCX template population workflow (search/replace tokens + conditional pruning)
- Authentication / authorization (MSAL component + Key Vault user allow‑list)

## Recent Changes

- Added HTMX live progress streaming: session-backed `/progress` poller surfaces ongoing `ui_hook` events, drives real-time step list updates, and dispatches queued toasts while auto-disabling once complete. Long-running analysis & generation now execute in a thread pool so the poller stays responsive, `show-toasts` HX triggers are listened for at the document level to fire notifications immediately, and the generation route mirrors analysis by wiring progress sinks before invocation, cleaning up state on errors, and returning a graceful dashboard refresh instead of surfacing 500s when failures occur (polling conditions now use dataset checks to avoid HTMX syntax issues). The live progress panel auto-hides once a run finishes to let the result blocks take focus, the progress collector now sanitizes incoming messages to block HTML/control-character injection, recent JS updates immediately hydrate toast payloads from HX swaps so success/failure notifications appear without extra user interaction while clearing residual progress state so "Live processing" never lingers over final results, and progress steps now render as bold heading rows without numeric prefixes to match UX feedback.
- Introduced toast hardening (session-scoped dedupe on the backend plus client-side suppression) to eliminate duplicate notifications alongside settings modal build metadata surfacing via the `BUILD_TIME` env var for release traceability.
- Swapped hard-coded admin checks for a Key Vault-backed roster loader that resolves admins by display name, UPN, or object ID (`RAI-ASSESSMENT-ADMINS`), sharing the same caching/fallback strategy as the allow list so security teams can rotate privileged operators without redeployment while preserving the localhost dev bypass toggle for opt-in testing.
- Shipped per-session CSRF protection: every state-changing HTMX POST now carries a cryptographically random token sourced from session state, injected via meta + hidden inputs, attached to HX headers in `app.js`, and verified server-side before processing uploads, settings changes, admin actions, or Graph login handshakes.
- Introduced cache-busted static assets (versioned URLs) and dedicated progress feed partial/CSS so UI refreshes immediately after deploys without manual hard refresh. Docker build now injects `STATIC_ASSET_VERSION` so each image carries a deterministic cache-busting token.
- Introduced a parallel HTMX + FastAPI UI (`htmx_ui_main.py`) with shared templates/static assets to mirror the Streamlit experience; users can launch either interface interchangeably.
- Implemented an MSAL login flow for the HTMX UI that mirrors Streamlit authentication (Graph `User.Read` validation, allow-list enforcement, cookie-backed session caching, consistent messaging), with shared templates and README guidance.
- Hardened the local development auth bypass to require `HTMX_ALLOW_DEV_BYPASS` opt-in and restrict usage to localhost, with documentation updates describing safe setup.
- Hardened Azure Container Apps provisioning scripts for idempotency (Log Analytics `customerId`, RBAC-safe Key Vault policies, forced revision updates) and refreshed README deployment guidance.
- Migrated Azure OpenAI initialization to the official `AzureOpenAI` client so Responses API calls hit deployment-scoped endpoints (fixes 404 fallbacks and restores reasoning summaries in the UI).
- Added `.dockerignore` to trim the container build context (excluding user settings, docs, deployment scripts) while keeping `.env` in scope.
- Introduced `azure-container-apps/sync_env_to_containerapp.sh` so `.env` key/value pairs stay in sync with Azure Container App environment variables (supports dry-run, exclude, and prune modes).
- Relaxed markdown sanitizer to allow heading tags, fixing HTMX analysis rendering so `###` sections display as titles instead of bullet rows.
- Integrated Azure Content Safety Prompt Shields before ingesting uploads: helpers/content_safety.py uses managed identity + retries, the HTMX upload/analysis routes block unsafe documents with user-facing messaging, and `.env`/`.env.template` now surface `AZURE_CONTENT_SAFETY_*` settings (with optional disable flag). Updated on 2025-09-28 to point the service at the dedicated custom domain, fix the helper payload to the REST contract (`userPrompt` string + `documents` string array), refresh the cache key to avoid stale verdicts, and document the manual curl validation path so developers can debug managed identity calls quickly.
- Deployment script (`azure-container-apps/1-setup_app-raiassessment.sh`) provisions the Content Safety account on demand and grants the container app's managed identity the `Cognitive Services User` role so runtime calls succeed without user impersonation.
- Initial memory-bank documentation established (core architecture & patterns)
- Architectural decisions captured (pipeline design, caching strategy, Azure resource usage)
- Terminology normalized ("Intended Uses", "Stakeholders", "Harms Assessment")
- Admin-only dynamic model selection UI with per‑model pricing preview
- Reasoning model support (gpt‑5, o*-series) + reasoning effort selector (minimal/low/medium/high)
- Adaptive parameter builder for reasoning models (auto strips unsupported params; progressive fallback; removed hard `max_completion_tokens` cap to permit long outputs)
- Pricing metadata expanded (cached input + reasoning token cost integration)
- Cost calculator updated to include hidden reasoning_tokens in output pricing
 - Dynamic log level control (admin sidebar) + suppression of noisy external loggers
 - Raw response & empty-answer diagnostics for reasoning models (DEBUG reveals truncated choice structure)
 - Single-click timestamped system logs download (sidebar) alongside access log export
 - Responses API integration for sanctioned reasoning summaries (summary mode + verbosity env controlled)

## Next Steps

Short term (high leverage):
1. Automated tests for prompt processors (JSON parsing & token replacement)
2. Structured logging (correlation IDs, levels) vs unstructured blob appends
3. Security hardening: input sanitization, size limits, role enforcement
4. Provider abstraction (Azure OpenAI vs future providers)
5. Observability metrics (prompt vs completion vs reasoning tokens, per-step latency, cache hit ratio)
6. Persist per-step usage snapshot (audit & cost analytics)
7. Deeper recursive reasoning extraction + segmentation (capture chain-of-thought parts without leaking sensitive reasoning) 
8. Automated regression test to ensure Azure OpenAI initialization keeps Responses API routing healthy (guard against future SDK/config drift)

Medium term:
7. Multi-language assessments (English default)
8. Externalize pricing + model metadata (JSON/service) & auto-refresh
9. Redis cache for horizontal scaling
10. Streaming partial updates (incremental section rendering)
11. Circuit breaker + structured retry policies (beyond reasoning fallback)

Longer term:
12. Role-based workflow (Draft -> Review -> Approved) with audit trail
13. Versioned prompt sets & A/B experimentation harness
14. Quality, safety & fairness evaluation heuristics + red-teaming harness

## Active Decisions & Considerations

Decision Log (initial snapshot):
- Use DOCX templating via token replacement instead of a higher-level templating engine: keeps compatibility with official templates.
- Local pickle caching chosen for speed & simplicity; NOT suitable for multi-instance scaling — slated for replacement.
- Azure Key Vault holds endpoints / secrets; Azure AD (DefaultAzureCredential) preferred over static keys (keyless design goal).
- Blob Storage used for append-only operational logs and user allow-list reference (improves central visibility but lacks structured querying).
- Multi-step pipeline executes sequentially to keep dependency ordering (Intended Uses precedes Stakeholders, etc.).
- llmlingua compression optional to trade cost vs. determinism; off by default in UI.
- Pricing computed client-side from static table: risk of drift vs. provider billing — requires periodic validation.

Open Questions:
- Persist intermediate JSON to skip re-computation? (Currently only final DOCX persisted.)
- Best way to surface reasoning vs visible token ratio in UI? (Cost transparency)
- Optional env-controlled output length guardrail? (Currently intentionally uncapped)
- Schema validation for each JSON response? (Reduce silent structural drift)
- Partial failure recovery strategy (resume at failed step?)
 - How to present reasoning summaries vs deeper extraction without exposing sensitive chain-of-thought (balance transparency vs safety)?

Risks / Watch Items:
- Silent exception catching can hide malformed outputs
- No global backoff / rate limiting – throttling risk under concurrency
- Inconsistent naming (e.g., 'inteduse') needs normalization layer
- Reasoning effort 'high' may inflate cost/latency unpredictably without per-tier ceilings
- Static pricing requires manual updates; drift risks under/over cost reporting
 - Potential increased latency from future deeper extraction / retry logic (needs guardrails & telemetry)


