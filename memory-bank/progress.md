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

## What Works

- Multi-step deterministic pipeline producing two DOCX drafts (internal + public)
- Structured JSON parsing & transformation into search/replace dict
- Intended Use dependent pruning of unused template pages
- Basic bias / risk detection + optional rewritten solution description
- Local pickle cache keyed by MD5 of composite prompt signature (model/lang/temp/compress)
- Progress feedback & cost estimation (now includes reasoning token component for reasoning models)
- Key Vault + DefaultAzureCredential (supports managed identity / keyless)
- Download packaging (ZIP of both assessments)
- Optional prompt compression (llmlingua v2) for cost reduction

## What's Left to Build

- Robust unit & integration tests (none present for processors / JSON schema)
- Structured logging & telemetry (currently plain text appends)
- Retry / timeout / backoff policies for LLM calls
- Cache invalidation strategy (currently manual deletion only)
- Horizontal scaling readiness (shared cache + idempotent steps)
- Input size limits & validation (prevent runaway tokenization)
- Multi-language output parameterization
- Role-based admin / audit (only implicit allow‑list now)
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
| Security | User allow-list logic minimal | Unauthorized use risk if misconfigured | Enforce signed-in principal + RBAC roles |
| Cost Accuracy | Static pricing table may age | Misreported economics | Periodic sync or dynamic pricing fetch |
| Reasoning Cost Transparency | Reasoning tokens previously invisible | Underestimated cost | Included; need UI surfacing |
| Reasoning Extraction Depth | Current summary heuristic only | Limited insight / debugging | Planned deeper structured extraction + safe redaction |
| Empty Answer Recovery | No automatic retry yet | Occasional blank outputs persist | Implement one guarded retry with logging |
| Performance | Sequential steps; no reuse of partials | Longer latency | Persist intermediate JSON & skip unchanged |
| Prompt Compression | Minimal QA on semantic drift | Potential content loss | Add regression tests & opt-in gating |
