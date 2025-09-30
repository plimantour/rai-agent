# Security Assessment Notes

## Findings

- **High – Untrusted LLM output rendered as HTML:** `analysis_result.html|safe` injects Azure OpenAI responses directly into the DOM. Malicious or poisoned outputs could contain `<script>` or other dangerous markup, leading to stored/ reflected XSS.
- **High – Toast notifications use `innerHTML`:** `static/js/app.js` inserts toast messages via `innerHTML`. Messages that originate from user-controlled identifiers (e.g., Azure AD display names) could execute script if not sanitized.
- **High – Prompt injection via uploaded content:** Solution descriptions are incorporated directly into prompts. Hostile instructions can manipulate the LLM to leak prompts, reveal secrets, or sabotage outputs. Azure Content Safety Prompt Shields now screen uploads, and a dedicated prompt sanitizer now normalizes text, neutralizes directive phrases, escapes template markers, and blocks high-risk jailbreak cues before prompts are built, providing an additional guard rail.
- **Medium – Graph access token validation gap:** `/auth/session` only checks that a token can call Microsoft Graph. It does not verify issuer, audience/client ID, or signature, so tokens minted for other apps with delegated scopes could impersonate users.
- **Low – Upload pipeline residual risks:** `_write_temp_upload` now streams to disk with size caps, extension/MIME allow lists, decompression-bomb detection, macro/PDF active-content linting, and optional ClamAV scans on newly supplied files; remaining work focuses on sandboxing downstream parsers and monitoring long-running conversions.
- **Low – Document parser attack surface:** Text extraction now runs inside a sandboxed worker with CPU, memory, file descriptor, and wall-clock limits; remaining work focuses on further isolating rare parser escapes in future iterations.
- **Medium – Third-party scripts served from CDN without integrity:** htmx loads from `https://unpkg.com` without Subresource Integrity or self-hosting, allowing script injection if the CDN is compromised.
- **Medium – Resource exhaustion risk:** Long-running analysis/generation threads have no rate limiting or quotas, allowing an authenticated user to overwhelm worker pools and rack up costs.
- **Low – Session persistence & log hygiene:** `SESSION_STORE` retains sessions indefinitely and audit logs embed raw user-supplied identifiers, enabling resource creep or log injection tactics.
- **Low – Output retention:** Generated DOCX/ZIP files persist until manual cleanup; failures could leave sensitive drafts on disk.

## Remediation Plan

1. Sanitize or escape all LLM-generated markup before rendering; consider server-side sanitization (e.g., `bleach`) or client-side rendering that strips scripts/attributes. ✅ Implemented via server-side markdown sanitization with Bleach (Sep 2025).
2. Update toast rendering to use `textContent`/DOM nodes and ensure backend messages are HTML-escaped. ✅ Implemented with escaped payloads and client-side `textContent` rendering (Sep 2025).
3. Introduce CSRF tokens for every state-changing POST, wiring tokens through HTMX headers or hidden inputs. ✅ Implemented via per-session tokens, HTMX request headers, and server-side validation (Sep 2025).
4. Validate Microsoft Graph tokens beyond a simple profile fetch (audience/app ID, issuer) before trusting identity information. ✅ Implemented by verifying signature, issuer, tenant, and client ID (Sep 2025).
5. Apply upload safeguards: enforce max size, MIME/type checking, and scan DOCX/PDF content; harden `extract_text_from_input` against decompression bombs. ✅ Completed via chunked streaming, size/MIME allow lists, decompression-bomb detection, macro/PDF linting, and ClamAV integration (Sep 2025).
6. Pin or self-host htmx with SRI support to prevent CDN supply-chain attacks.
7. Add session expiry/cleanup and normalize/escape identifiers before writing to blob logs and append-only storage.
8. Burn trusted hashes/signatures for critical prompt files into environment variables at build time and verify them before backend load, rejecting unexpected modifications.
9. Introduce prompt-input sanitization and content moderation (e.g., filters, guard prompts, policy checks) to mitigate uploaded prompt injection attempts. ✅ Implemented via prompt sanitizer helper that normalizes uploads, neutralizes directives, escapes template markers, and blocks high-risk cues (Sep 2025).
10. Sandboxed or containerized document parsing with strict CPU/time/memory limits to contain PDF/DOCX parser exploits. ✅ Implemented via resource-limited worker process (Sep 2025).
11. Implement rate limiting, per-user quotas, or job queueing for analysis/generation to prevent resource exhaustion and cost abuse.
12. Establish automatic retention policies for generated artifacts (short-lived storage, secure deletion) and audit storage locations for sensitive drafts.

## Implemented Remediations

- **Progress hook sanitization:** `ProgressCollector._sanitize_message` strips control characters and HTML/ XML tags from progress updates before they reach the UI or toast queue, reducing XSS risks coming from hook callbacks.
- **Stored progress cleanup:** After analysis/generation completes, `session.live_progress` and `progress_pending_toasts` are cleared, preventing stale or attacker-supplied messages from resurfacing in later sessions.
- **Azure Entra ID authentication flow:** `/auth/session` validates Microsoft Entra tokens via Graph, ensures allow-list membership before granting access, and restricts the development bypass to explicit localhost opt-in.
- **Key Vault-backed allow list:** Authorized user identities are sourced from the `RAI-ASSESSMENT-USERS` secret in Azure Key Vault (with controlled fallbacks), allowing centralized access management without code changes.
- **Key Vault-backed admin roster:** Admin privileges now derive from the `RAI-ASSESSMENT-ADMINS` secret in Azure Key Vault (cached with fallbacks), so rotating admin access no longer requires redeploying the app.
- **Admin-gated logging:** Session log level defaults to "None"; only Entra-verified admins may toggle logging from the settings modal, limiting diagnostics exposure to trusted operators.
- **Sanitized LLM rendering:** `render_markdown_safe` now funnels all LLM content through `bleach.clean`, preserving a controlled HTML allowlist and stripping scripts/unsafe attributes before response rendering.
- **Toast hardening:** Backend toast payloads are HTML-escaped and normalized, while the frontend renders via `textContent` with duplicate-suppression to block XSS vectors and message replay.
- **CSRF tokens enforced:** Each session now issues a cryptographically random token stored in server memory, injected into forms/meta tags, attached to HTMX headers, and validated on every state-changing POST (including auth, uploads, settings, and admin endpoints).
- **Prompt shield pre-checks:** `helpers/content_safety.ensure_uploaded_text_safe` runs Azure Content Safety Prompt Shields against every uploaded/analysis document with retries, caching, and managed identity authentication; unsafe content is rejected with user-visible messaging.
- **Upload pipeline hardening:** `_write_temp_upload` streams uploads to disk with strict size/MIME/extension limits, macro and PDF active-content linting, and only invokes the malware scanner for newly supplied files while stored solution text continues to pass Prompt Shield validation; HTMX forms avoid re-posting file inputs so cached documents are reused without redundant scans.
- **Sandboxed document parsing:** Text extraction now executes inside a separate process with CPU, memory, and wall-clock constraints (defaults 30s / 15 CPU seconds / 512 MB via `UPLOAD_PARSER_TIMEOUT`, `UPLOAD_PARSER_CPU_SECONDS`, `UPLOAD_PARSER_MEMORY_MB`), returning friendly user errors on timeout or parser failures for both HTMX and CLI flows.
- **Malware scanner warm-up:** The ClamAV wrapper primes the daemon during FastAPI startup with a dummy scan (240 s max) so first uploads are scanned immediately and no longer hit cold-start timeouts.
- **Managed identity-only data plane access:** All calls to Azure OpenAI, Content Safety, Key Vault, and Blob Storage use the container app's managed identity; end-user tokens are never forwarded, reducing impersonation risk.
- **Token signature validation:** `helpers/token_validation.validate_graph_access_token` verifies Graph access tokens offline (signature when available, otherwise strict claim checks for issuer/tenant/client) before the app trusts session identity data; production login confirmed.
- **Container env management:** `.dockerignore` deliberately excludes `.env`; secrets stay local and are projected into Azure via `azure-container-apps/sync_env_to_containerapp.sh` (supports `--dry-run`, `--exclude`, `--prune`). Operators review planned changes before applying and avoid `--prune` unless the dotenv file is canonical for the environment.

## Backend Threat Summary

| Severity | Area | Risk | Mitigation Status |
|----------|------|------|--------------------|
| High | Rendering | LLM HTML injected via `analysis_result.html|safe` | ✅ Implemented – bleach-sanitized markdown output |
| High | Notifications | Toasts rendered with `innerHTML` | ✅ Implemented – escaped backend payloads + text-only rendering |
| High | Prompt Safety | Prompt injection via uploaded content | ✅ Mitigated – Prompt Shield plus prompt sanitizer neutralize uploads before prompt assembly |
| High | Request AuthZ | Cross-site request forgery on HTMX POSTs | ✅ Implemented – per-session tokens validated on every POST |
| High | Malware Scanning | ClamAV cold start delayed first scan / caused timeouts | ✅ Implemented – startup warm-up primes daemon with dummy scan |
| Medium | Identity | Microsoft Graph tokens not validated for issuer/audience | ✅ Implemented – token signature, issuer, tenant, and client checks |
| Low | File Handling | Upload pipeline hardened (size/MIME caps, macro/PDF linting, ClamAV on new uploads) | ✅ Implemented – residual work is parser sandboxing |
| Low | File Parsing | Document parsing isolated with CPU/memory/time caps | ✅ Implemented – monitor for future hardening |
| Medium | Supply Chain | htmx pulled from CDN without SRI | Open – pin or self-host |
| Medium | Resource Usage | No rate limiting on long-running jobs | Open – add quotas/queues |
| Low | Session/Logging | Sessions never expire; logs accept raw identifiers | Open – add expiry + log normalization |
| Low | Output Retention | Generated artifacts linger on disk | Open – enforce retention |
| Low | Progress Hooks | Progress messages sanitized | ✅ Implemented |
| Low | AuthN/AuthZ | Entra ID login + Key Vault allow list | ✅ Implemented |
| Low | Admin Controls | Admin roster sourced from Key Vault secret | ✅ Implemented |
| Low | Logging Controls | Diagnostics disabled by default; admin-only toggle | ✅ Implemented |
