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
| `AZURE_LANGUAGE_ENDPOINT` | Azure AI Language resource endpoint for PII detection | Required unless `AZURE_LANGUAGE_PII_DISABLED=1` |
| `AZURE_LANGUAGE_API_VERSION` | AI Language API version (`2023-04-01`) | Optional override |
| `AZURE_LANGUAGE_PII_AUTO_DETECT` | Enable automatic language detection for PII scans | Defaults to `true` |
| `AZURE_LANGUAGE_PII_LANGUAGE` | Force a specific language code (e.g. `en`) | Leave blank to auto-detect |
| `AZURE_LANGUAGE_PII_ALLOWLIST` | Comma-separated global PII allowlist terms | Optional |
| `SHOW_REASONING_SUMMARY_DEFAULT` et al. | UI feature flags for reasoning summaries | Optional |
| `HTMX_FALLBACK_ALLOW_LIST` / `HTMX_FALLBACK_ADMIN_LIST` | Comma/semicolon separated allow/admin list fallback values | Optional for local development |
| `HTMX_ALLOW_DEV_BYPASS` and related `HTMX_DEV_*` | Opt-in local auth bypass | Never enable in shared environments |

#### Upload Guardrail Settings (defaults shown in `.env.template`)

- `UPLOAD_MAX_BYTES` / `UPLOAD_MAX_UNZIPPED_BYTES` / `UPLOAD_MAX_ARCHIVE_ENTRY_BYTES` / `UPLOAD_MAX_ARCHIVE_ENTRIES` – cap raw upload size, archive expansion, and embedded payload counts to block oversized submissions (defaults: 8 MiB raw, ~20 MiB expanded, 10 MiB per entry, 500 entries).
- `UPLOAD_MALWARE_SCAN_CMD` / `UPLOAD_MALWARE_SCAN_TIMEOUT` – optional ClamAV (or similar) command and timeout for new uploads.
- `UPLOAD_ENABLE_MACRO_LINT` / `UPLOAD_ENABLE_PDF_ACTIVE_CONTENT_LINT` – toggle macro and active-content linting for DOCX/PDF uploads.
- `UPLOAD_PARSER_TIMEOUT` / `UPLOAD_PARSER_CPU_SECONDS` / `UPLOAD_PARSER_MEMORY_MB` – sandboxed document parsing limits (wall clock, CPU seconds, memory MB) applied to pdfminer/docx2txt extraction to terminate hostile or runaway conversions (defaults: 30s / 15 CPU s / 512 MB).

The Container Apps provisioning script (`azure-container-apps/1-setup_app-raiassessment.sh`) auto-creates the Content Safety account (if missing) and assigns the managed identity the `Cognitive Services OpenAI User` and `Cognitive Services User` roles. End users do **not** require these roles; they only need to authenticate through the app registration and appear in `RAI-ASSESSMENT-USERS` (and `RAI-ASSESSMENT-ADMINS` for admin features).

> **Heads-up:** The project `.dockerignore` intentionally excludes `.env` so your secrets never enter the container build context. Use the sync script documented below to publish environment variables to Azure Container Apps instead of copying `.env` into the image.

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

#### Sync environment variables to the container app
Use `azure-container-apps/sync_env_to_containerapp.sh` to push key/value pairs from your local `.env` into the running Azure Container App. Typical flow:

```bash
az login
cd azure-container-apps
./sync_env_to_containerapp.sh --dry-run            # inspect planned changes
./sync_env_to_containerapp.sh                      # apply updates from ../.env
```

- `--env-file` points to an alternate dotenv file (defaults to `../.env`)
- `--exclude` skips specific keys (comma-separated) so secrets handled elsewhere stay untouched
- `--prune` removes container app settings that no longer exist in the dotenv file

The script requires `az` CLI access to the target subscription and validates the container app before applying changes. Combine with `--dry-run` during reviews to confirm exactly which variables will be added/updated.

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

## 🔒 PII Detection & Remediation Workflow
- Azure AI Language scans every uploaded document before analysis, chunking large files and auto-detecting language (configurable via `AZURE_LANGUAGE_PII_*`).
- Findings render in the HTMX remediation panel as a deduplicated list with confidence, category, and occurrence counts so reviewers focus on unique threats.
- Each finding defaults the replacement field to an anonymized suggestion (category/subcategory label) that the reviewer can fine-tune; the original value remains available via placeholder text for quick comparison.
- Users may keep specific terms by editing the replacement back to the original, which feeds a per-session allowlist so subsequent scans treat approved false positives as safe without re-flagging.
- Proceeding with only approved findings clears the threat gate, preserving user decisions while ensuring new uploads always re-run detection.

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
