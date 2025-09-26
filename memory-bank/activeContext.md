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

- Introduced a parallel HTMX + FastAPI UI (`htmx_ui_main.py`) with shared templates/static assets to mirror the Streamlit experience; users can launch either interface interchangeably.
- Implemented an MSAL login flow for the HTMX UI that mirrors Streamlit authentication (Graph `User.Read` validation, allow-list enforcement, cookie-backed session caching, consistent messaging), with shared templates and README guidance.
- Hardened the local development auth bypass to require `HTMX_ALLOW_DEV_BYPASS` opt-in and restrict usage to localhost, with documentation updates describing safe setup.
- Hardened Azure Container Apps provisioning scripts for idempotency (Log Analytics `customerId`, RBAC-safe Key Vault policies, forced revision updates) and refreshed README deployment guidance.
- Migrated Azure OpenAI initialization to the official `AzureOpenAI` client so Responses API calls hit deployment-scoped endpoints (fixes 404 fallbacks and restores reasoning summaries in the UI).
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


