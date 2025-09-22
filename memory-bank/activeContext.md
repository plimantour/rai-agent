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

- Added initial memory-bank documentation (this file plus product, progress, system patterns, tech context, brief)
- Captured architectural decisions (pipeline design, caching strategy, Azure resource usage)
- Normalized terminology ("Intended Uses", "Stakeholders", "Harms Assessment" phases)

## Next Steps

Short term (high leverage):
1. Add automated tests for prompt processors (JSON parsing & token replacement)
2. Introduce structured logging (correl IDs, levels) instead of raw blob appends
3. Harden security: input sanitization, size limits, user role enforcement
4. Abstract model provider (Azure OpenAI vs Mistral) behind a strategy class
5. Add observability metrics (token counts, per-step latency, cache hit ratio)

Medium term:
6. Support multi-language assessments (currently English hard-coded in most flows)
7. Move pricing + model metadata to a config service / JSON
8. Replace pickle cache with Azure Cache (Redis) for horizontal scaling
9. Implement streaming partial updates to UI (progress already structured)
10. Add retry / backoff & circuit breaker around LLM calls

Longer term:
11. Role-based workflow (Draft -> Review -> Approved) with audit trail
12. Versioned prompt sets & A/B experimentation harness
13. Automatic evaluation heuristics for output quality & red-teaming

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
- Should we persist intermediate JSON sections for re-run minimization? (Currently only final DOCX gets persisted.)
- How to handle partial failures mid-pipeline (presently aborts silently in some except blocks)?
- Introduce schema validation for each JSON response? (Would reduce silent structural drift.)

Risks / Watch Items:
- Silent exception catching can hide malformed model outputs.
- Absence of rate limiting & exponential backoff may cause throttling under concurrent users.
- Inconsistent naming (e.g., typos from model outputs: 'inteduse') requires stronger normalization layer.


