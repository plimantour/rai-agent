# System Patterns: Copilot Memory Bank

## System Architecture

High-Level Layers:
1. Ingestion Layer: CLI (`main.py`) & Streamlit UI (`streamlit_ui_main.py`)
2. Orchestration & Prompt Pipeline: `prompts/prompts_engineering_llmlingua.py`
3. Processing Utilities: document mutation (`helpers/docs_utils.py`), caching (`helpers/cache_completions.py`), pricing (`helpers/completion_pricing.py`), auth/session (`helpers/user_auth.py`), blob/keyvault integration (`helpers/blob_cache.py`)
4. Persistence / External Services: Azure OpenAI / Mistral (LLM), Azure Key Vault (secrets + config), Azure Blob (logs & allow‑list), Local FS (cache, outputs)
5. Presentation: Streamlit reactive components (progress, download, parameter toggles)

Data Flow (UI path):
Upload DOCX → Extract raw text → Initialize models (credential + endpoints) → Multi-step LLM calls (JSON) → Accumulate token replacement map → Apply replacements & prune template → Save DOCX variants → Offer ZIP download → Log user actions.

## Key Technical Decisions

- Sequential pipeline with ordered dependencies (Intended Uses precedes Stakeholders etc.) simplifies state management.
- Token replacement via direct DOCX paragraph + table traversal avoids template pre-compilation; trades speed for simplicity.
- Local pickle cache keyed by composite hash reduces repeated LLM costs; simplicity preferred over distributed cache in MVP.
- Keyless Azure AD auth chosen over static keys (security posture improvement) where supported.
- Optional llmlingua compression controlled per-run to manage risk of semantic loss.
- Bias / risk analysis separated from generation (distinct functions) enabling optional pre-flight validation.

## Design Patterns

- Pipeline Pattern: Ordered list of (name, prompt, temperature, mode, processor) driving uniform execution.
- Adapter Pattern (implicit): Abstraction over Azure OpenAI vs Mistral via conditional branches (candidate for explicit interface).
- Caching Pattern: MD5 signature –> serialized response (model, lang, pricing, content) enabling reuse & cost display.
- Template Method (partial): Shared `get_azure_openai_completion` handles compression, caching, pricing, fallback.
- Token Replacement Strategy: Two passes (collect vs. incremental update if `update_steps=True`).
- Defensive Parsing: `get_json_from_answer` attempts normalization & reshaping when model output deviates.

## Component Relationships

| Component | Depends On | Provides |
|-----------|------------|----------|
| `streamlit_ui_main.py` | helpers.*, prompts.* | User interaction, progress, output delivery |
| `main.py` | prompts module, docs_utils | CLI doc generation |
| `prompts_engineering_llmlingua.py` | helpers.*, llmlingua, openai | Orchestrates multi-step LLM workflow |
| `helpers/docs_utils.py` | docx, pdfminer | File extraction & DOCX mutation |
| `helpers/cache_completions.py` | hashlib, pickle | Response caching layer |
| `helpers/blob_cache.py` | azure.identity, storage, keyvault | Logs + secret retrieval |
| `helpers/user_auth.py` | Streamlit, requests | Authentication info retrieval |
| `helpers/completion_pricing.py` | static pricing table | Cost estimation |

Scalability Considerations:
- Current single-instance assumptions (local cache, no locking)
- Blob log append risk under concurrency (no atomic semantics at app layer)
- Statelessness of generation pipeline favorable for future queue-based orchestration.

Resilience Gaps:
- Limited retry/backoff; broad exception catches reduce observability.
- No circuit breaker around LLM provider errors.

Extensibility Hooks:
- Adding a new section = append to `steps` list with processor + prompt constant.
- Switching model provider: encapsulate current conditional branches behind interface.

