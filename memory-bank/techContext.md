# Tech Context: Copilot Memory Bank

## Technologies Used

- Python 3.11+
- Streamlit (UI shell)
- FastAPI + HTMX (alternate UI shell with shared templates/static assets)
- MSAL.js + Microsoft Graph (interactive auth flow shared across UIs)
- Azure OpenAI (chat & reasoning models: gpt-4.x, gpt-5, o*-series) & optional Mistral endpoint (reasoning path now uncapped — no forced `max_completion_tokens`; Responses API used for sanctioned summaries when enabled)
- Azure Content Safety Prompt Shields (managed identity auth, custom subdomain endpoint)
- ClamAV (command-line malware scanner warmed up on FastAPI startup)
- Azure Identity (DefaultAzureCredential) for keyless auth
- Azure Key Vault (secret & endpoint retrieval)
- Azure Blob Storage (logs, user allow‑list text, misc data)
- Bleach (server-side sanitization for HTMX-rendered markup)
- llmlingua2 (prompt compression)
- pdfminer / docx2txt / python-docx (content extraction & templating)
- zipfile / io for packaging outputs
- termcolor for console diagnostics

## Developement setup

Baseline Steps:
1. Create venv (Python >= 3.11)
2. Install `requirements.txt`
3. Configure `.env` (or ensure Key Vault contains required secrets)
4. Run CLI: `python main.py -i <folder>` (expects `solution_description.docx` inside folder)
5. Or UIs:
	- Streamlit: `python -m streamlit run streamlit_ui_main.py --server.port 8000`
	- HTMX/FastAPI: `uvicorn htmx_ui_main:app --host 0.0.0.0 --port 8001`

Environment Variables (representative):
- **Core services**: `AZURE_KEYVAULT_URL`; `AZURE_OPENAI_API_TYPE`; `AZURE_OPENAI_ENDPOINT`; `AZURE_OPENAI_GPT_DEPLOYMENT`; `AZURE_OPENAI_API_VERSION`; `AZURE_STORAGE_ACCOUNT_NAME`
- **Authentication**: `AZURE_TENANT_ID`; `AZURE_APP_REGISTRATION_CLIENT_ID`; `AZURE_REDIRECT_URI`; `MSAL_CLIENT_ID`; `MSAL_TENANT_ID`; `MSAL_REDIRECT_URI`
- **HTMX dev bypass**: `HTMX_ALLOW_DEV_BYPASS`; `HTMX_DEV_USER_ID`; `HTMX_DEV_USER_NAME`; `HTMX_DEV_USER_UPN`
- **Content safety**: `AZURE_CONTENT_SAFETY_ENDPOINT`; `AZURE_CONTENT_SAFETY_API_VERSION`; `AZURE_CONTENT_SAFETY_DISABLED`
- **Uploads & scanning**: `UPLOAD_ALLOWED_EXTENSIONS`; `UPLOAD_ALLOWED_MIME_TYPES`; `UPLOAD_MAX_BYTES`; `UPLOAD_MAX_UNZIPPED_BYTES`; `UPLOAD_MAX_ARCHIVE_ENTRIES`; `UPLOAD_MAX_ARCHIVE_ENTRY_BYTES`; `UPLOAD_ENABLE_MACRO_LINT`; `UPLOAD_ENABLE_PDF_ACTIVE_CONTENT_LINT`; `UPLOAD_MALWARE_SCAN_CMD`; `UPLOAD_MALWARE_SCAN_TIMEOUT`; `UPLOAD_PARSER_TIMEOUT`; `UPLOAD_PARSER_CPU_SECONDS`; `UPLOAD_PARSER_MEMORY_MB`
- **Temp/cache control**: `UPLOAD_TMP_DIR`; `UPLOAD_CHUNK_SIZE`; `STATIC_ASSET_VERSION`; `BUILD_TIME`
- **Prompt & reasoning**: `SHOW_REASONING_SUMMARY_DEFAULT`; `USE_PROMPT_COMPRESSION`; `REASONING_MODEL_DEFAULT`

Sandboxed document parsing honours `UPLOAD_PARSER_TIMEOUT` (wall-clock seconds), `UPLOAD_PARSER_CPU_SECONDS`, and `UPLOAD_PARSER_MEMORY_MB` to terminate hostile or runaway conversions before they can impact the host process; defaults target 30s / 15 CPU seconds / 512 MB.

Key Vault Secret Names (observed):
- `AZURE-OPENAI-ENDPOINT` (when keyless) / alternative Mistral secrets
- `MISTRAL-OPENAI-ENDPOINT`, `MISTRAL-OPENAI-API-KEY`
- `RAI-ASSESSMENT-USERS`
- `RAI-ASSESSMENT-ADMINS`

## Technical constraints

- Local pickle cache prevents transparent horizontal scaling (stateful node) — race conditions possible, though keys now include model + reasoning effort to avoid cross-model reuse.
- DOCX mutation cost grows linearly with paragraph/table count; no streaming writing optimization.
- JSON contract with LLM is implicit; absence of schema validation risks silent degradation.
- Pricing table static; manually updated (now includes reasoning & cached input pricing; risk of drift).
- Authentication: UI relies on MSAL component + allow‑list; lacking granular role model.
- No formal rate limiting or concurrency guard around LLM calls (provider throttling risk).
- Logging unstructured → limited queryability & alerting.

Potential Enhancements:
- Introduce pydantic schemas for each JSON section
- Migrate cache to Redis (Azure Cache for Redis) with TTL + optimistic locking
- Adopt structured logging (OpenTelemetry) + central ingestion
- Add async / concurrency for independent steps (after dependency graph explicit encoding)
- Provide configuration manifest (YAML) for pipeline + pricing instead of hard-coded dicts
- Surface reasoning vs visible token breakdown (UI & logs)
- Optional env var (`RAI_MAX_COMPLETION_TOKENS`) to reintroduce a soft output cap if needed
- Structured usage export (JSONL) for cost analytics & governance
 - Deeper recursive reasoning extraction (structured segments + safe redaction)
 - Automatic retry logic for empty reasoning responses (single bounded attempt)
 - Combine access + system logs into unified on-demand archive with metadata manifest
- Implement structured notifications when prompt shield blocks content (admin alerting path)
- Add automated health check for Content Safety endpoint (managed identity probe + curl payload) to detect custom domain drift

