# Tech Context: Copilot Memory Bank

## Technologies Used

- Python 3.11+
- Streamlit (UI shell)
- Azure OpenAI (chat & reasoning models: gpt-4.x, gpt-5, o*-series) & optional Mistral endpoint
 - Azure OpenAI (chat & reasoning models: gpt-4.x, gpt-5, o*-series) & optional Mistral endpoint (reasoning path now uncapped — no forced `max_completion_tokens`; Responses API used for sanctioned summaries when enabled)
- Azure Identity (DefaultAzureCredential) for keyless auth
- Azure Key Vault (secret & endpoint retrieval)
- Azure Blob Storage (logs, user allow‑list text, misc data)
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
5. Or UI: `python -m streamlit run streamlit_ui_main.py --server.port 8000`

Environment Variables (representative):
- `AZURE_KEYVAULT_URL`
- `AZURE_OPENAI_API_TYPE` ("azure" or other)
- `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_GPT_DEPLOYMENT` / `AZURE_OPENAI_API_VERSION`
- `AZURE_TENANT_ID`, `AZURE_APP_REGISTRATION_CLIENT_ID`, `AZURE_REDIRECT_URI`
- Storage: `AZURE_STORAGE_ACCOUNT_NAME`

Key Vault Secret Names (observed):
- `AZURE-OPENAI-ENDPOINT` (when keyless) / alternative Mistral secrets
- `MISTRAL-OPENAI-ENDPOINT`, `MISTRAL-OPENAI-API-KEY`
- `RAI-ASSESSMENT-USERS`

## Technical constraints

- Local pickle cache prevents transparent horizontal scaling (stateful node) — race conditions possible.
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

