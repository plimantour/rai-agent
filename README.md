## 🚀 Installation (Development Demo – Harden Before Production)

Requirements: Python >= 3.11 (tested with 3.12)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.template .env
# Edit .env with your Azure OpenAI / Key Vault / Storage / Content Safety values
```

### Environment Configuration

`/.env.template` mirrors every setting consumed by the app. After copying it to `.env`, provide tenant-specific values for the entries below (placeholders show required format):

| Variable | Purpose | Notes |
| --- | --- | --- |
| `AZURE_KEYVAULT_URL` | Key Vault URI that stores secrets and allow/admin lists | Required |
| `AZURE_TENANT_ID` | Microsoft Entra tenant GUID | Required |
| `AZURE_APP_REGISTRATION_CLIENT_ID` | Client ID of the app registration used for login | Required |
| `AZURE_CONTAINER_MANAGED_IDENTITY` | Client ID of the Container App managed identity | Optional for local dev; populated automatically in Azure |
| `AZURE_REDIRECT_URI` | Redirect URI registered for the HTMX UI | Use container app FQDN or local URL |
| `AZURE_STORAGE_ACCOUNT_NAME` | Blob storage for assessment artifacts/logs | Required |
| `AZURE_STORAGE_CONTAINER_NAME` | Default blob container name | `assessments` by default |
| `AZURE_OPENAI_API_TYPE` | Usually `azure` | Required |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint | Required |
| `AZURE_OPENAI_API_VERSION` | API version to call (e.g. `2024-08-01-preview`) | Required |
| `AZURE_OPENAI_GPT_DEPLOYMENT` | Deployment name for GPT model | Required |
| `AZURE_CONTENT_SAFETY_ENDPOINT` | Content Safety resource endpoint | Required; use the custom subdomain (`https://<resource>.cognitiveservices.azure.com`) so managed identities succeed |
| `AZURE_CONTENT_SAFETY_API_VERSION` | Content Safety API version (`2024-09-01`) | Required |
| `AZURE_CONTENT_SAFETY_DISABLED` | Set to `1` only to bypass Prompt Shields during local testing | Leave unset or `0` in production |
| `SHOW_REASONING_SUMMARY_DEFAULT` et al. | UI feature flags for reasoning summaries | Optional |
| `HTMX_FALLBACK_ALLOW_LIST` / `HTMX_FALLBACK_ADMIN_LIST` | Comma/semicolon separated allow/admin list fallback values | Optional for local development |
| `HTMX_ALLOW_DEV_BYPASS` and related `HTMX_DEV_*` | Opt-in local auth bypass | Never enable in shared environments |

The Container Apps provisioning script (`azure-container-apps/1-setup_app-raiassessment.sh`) auto-creates the Content Safety account (if missing) and assigns the managed identity the `Cognitive Services OpenAI User` and `Cognitive Services User` roles. End users do **not** require these roles; they only need to authenticate through the app registration and appear in `RAI-ASSESSMENT-USERS` (and `RAI-ASSESSMENT-ADMINS` for admin features).

## 🏃 Running & Deployment

Common preparatory commands (Azure):
```bash
az login
az acr login --name YOUR_DOCKER_REGISTRY
./docker_build_image.sh
# Push image to ACR and deploy (see ./azure-container-apps/*.sh)
```

Supported deployment modes (preferred first):
1. Azure Container Apps (recommended)
2. Docker locally
3. Direct Python (no container)

### Azure Container Apps Quick Start
1. Create an Entra ID app registration (enable user_impersonation & access to user profile)
2. Review `/azure-container-apps` scripts for environment / secret expectations
3. Ensure Key Vault contains required secrets (OpenAI endpoint, users allow‑list, etc.)

### Local CLI Generation
Place your solution description DOCX:
```bash
cp 'your-solution-description.docx' 'rai-solution/solution_description.docx'
python main.py -i rai-solution
```

CLI optional arguments:
- `-v` verbose logging
- `-s` stepwise update (writes/intermediate doc updates for debugging)

### Streamlit UI (Local)
```bash
python -m streamlit run streamlit_ui_main.py --server.port 8000 --server.address 0.0.0.0
```

### HTMX UI (FastAPI)
```bash
uvicorn htmx_ui_main:app --host 0.0.0.0 --port 8001
```

The HTMX version uses FastAPI + Jinja templates and reuses the same Azure configuration
as the Streamlit app. When running locally without Azure App Service authentication,
explicitly opt in to the dev bypass and set the following environment variables to emulate
an authenticated user:

```bash
export HTMX_ALLOW_DEV_BYPASS=true  # only for local development
export HTMX_DEV_USER_ID="00000000-0000-0000-0000-000000000000"
export HTMX_DEV_USER_NAME="Firstname Lastname"
# optional if you want to match the Key Vault allow list
export HTMX_DEV_USER_UPN="alias@example.com"
```

The bypass works only for requests originating from `localhost`/`127.0.0.1` and should
never be enabled in shared or production environments. Ensure the chosen user appears
in the `RAI-ASSESSMENT-USERS` Key Vault secret (or the
`HTMX_FALLBACK_ALLOW_LIST` environment variable for local testing) and, if required,
`RAI_ADMIN_USERS` for admin actions.

The HTMX UI now mirrors the Streamlit MSAL login experience. When deployed to Azure,
the FastAPI app presents a Microsoft sign-in using `AZURE_APP_REGISTRATION_CLIENT_ID`,
`AZURE_TENANT_ID`, and `AZURE_REDIRECT_URI`, then validates the returning access token
against Microsoft Graph before applying the same allow-list checks.

## 🔁 Admin Model & Reasoning Effort Selection
When signed in as an admin (username present in Key Vault allow‑list) the sidebar shows:
- Model select (each option annotated with input/output EUR per 1K tokens)
- Reasoning effort selector for reasoning models (gpt‑5*, o*-series): minimal | low | medium | high (gpt‑5 adds `minimal`)

Changing either logs an event and immediately applies to subsequent steps.

## 💰 Cost Calculation (Reasoning Inclusive)
Costs derive from `helpers/completion_pricing.py`:
- Input cost = prompt_tokens / 1000 * input_price
- Output cost = (completion_tokens + reasoning_tokens) / 1000 * output_price
- reasoning_tokens are hidden internal tokens for reasoning models; now included to avoid under-reporting.

Cached responses reuse stored (first-run) cost numbers (cache hits do not re-bill but remain informative).

## 🧠 Reasoning Parameters & Adaptive Fallback
For reasoning models the code automatically:
- Removes unsupported parameters (temperature, top_p, penalties, max_tokens)
- Adds `reasoning_effort`
- (No forced output cap) We intentionally DO NOT set `max_completion_tokens` to allow very long answers (per user requirement). A future optional env var (e.g. `RAI_MAX_COMPLETION_TOKENS`) may reintroduce a soft guardrail.
- Attempts JSON output only if safe; otherwise falls back to plain text
- Progressive fallback on HTTP 400/422 now: `response_format` → `reasoning_effort` (since there is no cap parameter to remove)
- Uses the official `AzureOpenAI` client so Responses API requests automatically target the deployment-scoped endpoint (prevents 404s seen with the generic client).

Enable debug instrumentation (also surfaces raw choice + token details when reasoning output seems empty):
```bash
export DEBUG_REASONING=1
```

### Empty Answer Diagnostics
If a reasoning response returns an empty `message.content`, a WARNING is logged including model, finish_reason, and token usage (visible vs reasoning tokens). Enable DEBUG to see a truncated raw choice structure for deeper inspection.

### Dynamic Log Level
An admin-only sidebar control lets you switch log level (NONE/DEBUG/INFO/…); underlying code resets noisy third‑party loggers to WARNING each time to avoid clutter.

### Reasoning Summary Display
If enabled the app will request sanctioned reasoning summaries (Responses API) for supported reasoning models and display a truncated summary (first ~1200 chars) in a "Reasoning Summary" expander. The AzureOpenAI client ensures these calls hit the deployment (`/openai/deployments/<name>/responses`), so summaries appear whenever the service emits one. Summaries are still not guaranteed for every call, but 404 fallbacks should no longer occur.

Env variables controlling this feature:
```
SHOW_REASONING_SUMMARY_DEFAULT=true        # default UI toggle
USE_RESPONSES_API_FOR_REASONING=true       # route reasoning models through Responses API
REASONING_SUMMARY_MODE=auto                # auto | detailed (concise not supported for GPT-5 per docs)
REASONING_VERBOSITY=low                    # low | medium | high (GPT-5 verbosity)
```
Fallback: if the Responses API still fails (e.g., throttling, unsupported model), the code reverts to Chat Completions—no summary, but the final answer is preserved and logged.

## 🛡️ Content Safety Prompt Shields
The FastAPI upload and analysis flows call Azure Content Safety `text:shieldPrompt` for every document using the managed identity. Payloads follow the REST contract exactly (`userPrompt` as a string and `documents` as an array of strings); changing this structure will yield `InvalidRequestBody` responses.

### Manual Verification (curl)
When debugging managed identity issues, request an access token and invoke the endpoint directly:

```bash
TOKEN=$(az account get-access-token --resource https://cognitiveservices.azure.com/.default --query accessToken -o tsv)
ENDPOINT=https://<your-resource>.cognitiveservices.azure.com
curl -sS \
  -X POST "$ENDPOINT/contentsafety/text:shieldPrompt?api-version=2024-09-01" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "userPrompt": "Example prompt to scan",
    "documents": ["Sample document text to vet"]
  }'
```

Expect `attackDetected: false` for benign content. Substitute `documents` with any strings you need to vet; omit the array entirely if you only want to scan the user prompt. Re-run the container or redeploy after updating `helpers/content_safety.py` or environment variables so the managed identity picks up changes.

## 📦 Caching & Reproducibility
Local pickle cache (key = hash(model|language|prompt|temperature|compression)).
Recommended before scale-out: migrate to Redis (Azure Cache) with TTL + optimistic locking.

## 🔐 Authentication & Authorization
- MSAL-based login component populates user session
- Allow‑list retrieved from Key Vault
- Keyless Azure AD (DefaultAzureCredential) preferred; Azure Key Vault holds endpoints
- All downstream Azure calls (OpenAI, Content Safety Prompt Shields, Blob Storage, Key Vault) execute with the container app's managed identity. The app never impersonates end users.
- Azure Content Safety Prompt Shields run against every uploaded/analyzed document. Set `AZURE_CONTENT_SAFETY_DISABLED=1` only for local testing scenarios where the API is unavailable.

## 📊 Observability (Current & Planned)
Current:
- Console + blob append logs
- Rotating local system logs (downloadable via single-click timestamped ZIP: System Logs)
- Access logs (blob) downloadable separately
- Per-run cost summary (includes reasoning tokens)
- Dynamic log level UI (admin sidebar) with noisy logger suppression
- Reasoning summary expander (Responses API) when enabled
- File handler pinned to DEBUG level so full traces land in `logs/app.log` regardless of console setting.

Planned:
- Structured JSON logging & central ingestion
- Surface reasoning vs visible token ratio in UI
- Per-step latency & cache hit metrics
- Deeper structured reasoning extraction (recursive parts traversal)
- Automatic retry logic for empty / truncated reasoning answers with adjusted params

## 🛣 Roadmap (Condensed)
- Unit tests + JSON schema validation for each step output
- Structured logging & usage export (JSONL) for analytics
- Multi-language output support
- Redis cache + incremental streaming updates
- UI surfaces reasoning vs visible token ratio & per-effort guardrails
 - Deeper reasoning extraction + automated retry on empty answers

## 📁 Additional Documentation
- `memory-bank/architecture.md` – high-level architecture & data flow
- `memory-bank/changelog.md` – chronological feature changes

## ⚠️ Production Hardening Checklist (Excerpt)
- Replace pickle cache → Redis / durable store
- Add retry/backoff + circuit breaker around LLM calls
- Implement structured audit logging (user + model + token usage)
- Add schema validation & output safety checks
- Enforce size limits on uploaded DOCX

## 📝 License & Attribution
See `LICENSE` and `LICENSE-CODE`. This repository contains a demonstration implementation—evaluate compliance obligations (privacy, security, RAI) before production use.

***
Feedback & contributions welcome. Open an issue or PR with proposed improvements.
