# Architecture Overview

## 1. High-Level Layers
| Layer | Components | Responsibility |
|-------|------------|----------------|
| Presentation | `streamlit_ui_main.py`, `htmx_ui_main.py` | Streamlit and HTMX/FastAPI surfaces (MSAL auth, progress UX, admin model & reasoning selection, prompt shield gating, CSRF validation) |
| CLI | `main.py` | Headless batch generation of RAI assessment drafts |
| Orchestration / Pipeline | `prompts/prompts_engineering_llmlingua.py` | Multi-step prompt execution, adaptive reasoning parameter handling, caching & cost accumulation |
| Utilities | `helpers/*.py` | DOCX manipulation, pricing, caching, auth, blob logging, Key Vault access, malware scanning (with startup warm-up), Content Safety prompt shielding, prompt sanitization |
| Model / Pricing Metadata | `helpers/completion_pricing.py` | Legacy + extended metadata (context window, reasoning flag, pricing incl. cached & reasoning tokens) |
| Persistence / External | Azure OpenAI, Key Vault, Blob Storage, (future Redis) | Model inference, secret storage, logging, shared cache (planned) |
| Templates / Assets | `rai-template/*.docx` | Master DOCX templates (internal + public) |

## 2. Data Flow (UI Path)
```
User Uploads DOCX
  → Stream upload to locked temp dir with chunked writes, size/MIME/decompression guards, then extract text inside sandboxed worker (`helpers/docs_utils` with `UPLOAD_PARSER_*` caps)
  → Run malware scan if configured (external ClamAV command warmed on startup to avoid cold scans)
    → Run Content Safety Prompt Shields (helpers/content_safety.py using managed identity)
      → Apply prompt sanitization (helpers/prompt_sanitizer.py normalizes text, neutralizes directives, escapes template markers, blocks high-risk cues)
    → Initialize models (DefaultAzureCredential + Key Vault)
      → (Admin) Select model & reasoning effort
        → Sequential generation steps (prompts module)
          → Each step: build prompt → call Azure OpenAI → parse JSON/text → accumulate replacements
            → After final step: apply replacements & prune unused intended-use sections
              → Produce Internal & Public DOCX variants → Offer downloads / ZIP
                → Log actions & usage (blob)
```

## 3. Generation Steps (Ordered Pipeline)
1. Intended Uses (foundation for dependent steps)
2. Solution Scope / Information
3. Fitness for Purpose
4. Stakeholders
5. Goals (A5/T3) & Fairness Goals
6. Solution Assessment
7. Risks of Use
8. Impact on Stakeholders
9. Harms Assessment
10. Disclosure of AI Interaction

Each step returns JSON (or text fallback) which is normalized and merged into a composite search/replace mapping.

## 4. Reasoning Model Adaptation
Reasoning models (gpt‑5 family, o*-series) differ from standard chat models:
- Unsupported: temperature, top_p, penalties, max_tokens
- Required / recommended: `reasoning_effort` (minimal|low|medium|high, gpt‑5 adds `minimal`), `max_completion_tokens`
- Hidden `reasoning_tokens` (chain-of-thought style internal tokens) included in cost output

Adaptive invocation attempts a superset of safe parameters then progressively strips:
1. response_format → 2. max_completion_tokens → 3. reasoning_effort (last resort)

## 5. Caching Strategy
- Local pickle file keyed by hash(model|language|prompt|temperature|compression|reasoning_effort for reasoning-capable models)
- Stores (model, language, input_cost, output_cost, answer)
- Cache hits skip recomputation; cost shown from original run for transparency
- Planned evolution: Redis with TTL and optimistic locking for multi-instance scale

## 6. Pricing & Cost Accounting
- `model_pricing_euros`: legacy dict (Input/Output per 1K tokens)
- `MODEL_METADATA`: extended (family, reasoning flag, cached_input_cost_per_1k, context windows)
- Effective output tokens = completion_tokens + reasoning_tokens for reasoning models
- Cached input pricing (if present) currently informational (future: incorporate when provider exposes cache hit ratios)

## 7. DOCX Template Processing
- Token placeholders: `##TOKEN_NAME` convention
- After all steps: single bulk replacement via dictionary (performance vs per-step writes)
- Conditional pruning: remove unused intended use sections (> actual count)
- Public vs Internal templates processed in parallel with shared mapping

## 8. Error Handling & Risks
| Concern | Current Handling | Improvement Plan |
|---------|------------------|------------------|
| Broad exception catches | Logs error, returns empty | Replace with typed exceptions + structured logging |
| JSON drift / typos | Ad-hoc key normalization | Introduce schema validation (pydantic) |
| Reasoning fallback masking real errors | Broad try/except | Narrow to HTTP / validation errors |
| Silent cost drift | Manual pricing updates | Scheduled sync or pricing endpoint integration |

## 9. Observability Roadmap
- Add structured JSON logs (event: step_start, step_complete, tokens, reasoning_ratio)
- Expose reasoning vs visible token ratio in UI footer
- Export usage JSONL (model, prompt hash, input/output/ reasoning tokens, cost)
- Latency histogram per step

## 10. Security Considerations
- Keyless auth via managed identity (preferred)
- Key Vault for secret indirection (no raw secrets in repo)
- Allow‑list gating admin actions (model selection)
- Azure Content Safety Prompt Shields block unsafe uploads before generation; custom subdomain required for managed identity.
- Prompt sanitizer runs after Content Safety to normalize uploads, neutralize directive phrases, escape template markers, and block high-risk jailbreak cues before prompt assembly.
- Sandboxed document parsing constrains pdfminer/docx2txt extraction using env-tunable limits (`UPLOAD_PARSER_TIMEOUT`, `UPLOAD_PARSER_CPU_SECONDS`, `UPLOAD_PARSER_MEMORY_MB`).
- Upload pipeline streams files to disk in bounded chunks, enforces size / MIME / archive limits, and only passes sanitized temp paths to the sandboxed extractor to mitigate decompression bombs and resource exhaustion.
- Malware scanner warm-up primes ClamAV on startup so security scans run without cold-start latency.
- Per-session CSRF tokens enforced across HTMX POST endpoints.
- Container builds exclude `.env`; runtime secrets/configs flow in via Azure Container Apps environment variables using the sync script, keeping credentials out of images.
- TODO: Rate limiting (size limits & parser caps enforced via env vars)

## 11. Extensibility Hooks
| Extension | How |
|-----------|-----|
| New generation step | Append tuple to steps list (prompt constant + processor) |
| New model family | Add pricing + metadata entry; UI auto-lists |
| Alternate provider | Introduce strategy implementing unified `invoke` interface |
| Multi-language | Parameterize TARGET_LANGUAGE placeholders across prompts |

## 12. Production Hardening Checklist
- Redis cache & concurrency-safe logging
- Structured telemetry (OpenTelemetry) + dashboards
- Schema & safety validation layer
- Fine-grained RBAC (roles: viewer, generator, admin)
- Automated regression test suite (prompt compression vs fidelity)

---
For change history see `memory-bank/changelog.md`.
