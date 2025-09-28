# Security Assessment Notes

## Findings

- **High – Untrusted LLM output rendered as HTML:** `analysis_result.html|safe` injects Azure OpenAI responses directly into the DOM. Malicious or poisoned outputs could contain `<script>` or other dangerous markup, leading to stored/ reflected XSS.
- **High – Toast notifications use `innerHTML`:** `static/js/app.js` inserts toast messages via `innerHTML`. Messages that originate from user-controlled identifiers (e.g., Azure AD display names) could execute script if not sanitized.
- **High – Prompt injection via uploaded content:** Solution descriptions are incorporated directly into prompts. Hostile instructions can manipulate the LLM to leak prompts, reveal secrets, or sabotage outputs without current guardrails.
- **Medium – No CSRF protection on POST routes:** State-changing HTMX requests rely solely on cookies with `SameSite=Lax`. Without CSRF tokens, a malicious site could trigger actions like `/analysis`, `/generate`, or `/upload` for an authenticated user.
- **Medium – Graph access token validation gap:** `/auth/session` only checks that a token can call Microsoft Graph. It does not verify issuer, audience/client ID, or signature, so tokens minted for other apps with delegated scopes could impersonate users.
- **Medium – File upload pipeline lacks guardrails:** `_write_temp_upload` reads entire files into memory and accepts DOCX/PDF/JSON/TXT without size limits or deep validation, opening the door to DoS (oversized or decompression-bomb uploads) or dangerous payloads processed downstream.
- **Medium – Document parser attack surface:** `pdfminer` and `docx2txt` run on untrusted user uploads; crafted docs could exploit parser vulnerabilities or exhaust resources.
- **Medium – Third-party scripts served from CDN without integrity:** htmx loads from `https://unpkg.com` without Subresource Integrity or self-hosting, allowing script injection if the CDN is compromised.
- **Medium – Resource exhaustion risk:** Long-running analysis/generation threads have no rate limiting or quotas, allowing an authenticated user to overwhelm worker pools and rack up costs.
- **Low – Session persistence & log hygiene:** `SESSION_STORE` retains sessions indefinitely and audit logs embed raw user-supplied identifiers, enabling resource creep or log injection tactics.
- **Low – Output retention:** Generated DOCX/ZIP files persist until manual cleanup; failures could leave sensitive drafts on disk.

## Remediation Plan

1. Sanitize or escape all LLM-generated markup before rendering; consider server-side sanitization (e.g., `bleach`) or client-side rendering that strips scripts/attributes.
2. Update toast rendering to use `textContent`/DOM nodes and ensure backend messages are HTML-escaped.
3. Introduce CSRF tokens for every state-changing POST, wiring tokens through HTMX headers or hidden inputs.
4. Validate Microsoft Graph tokens beyond a simple profile fetch (audience/app ID, issuer) before trusting identity information.
5. Apply upload safeguards: enforce max size, MIME/type checking, and scan DOCX/PDF content; harden `extract_text_from_input` against decompression bombs.
6. Pin or self-host htmx with SRI support to prevent CDN supply-chain attacks.
7. Add session expiry/cleanup and normalize/escape identifiers before writing to blob logs and append-only storage.
8. Burn trusted hashes/signatures for critical prompt files into environment variables at build time and verify them before backend load, rejecting unexpected modifications.
9. Introduce prompt-input sanitization and content moderation (e.g., filters, guard prompts, policy checks) to mitigate uploaded prompt injection attempts.
10. Sandboxed or containerized document parsing with strict CPU/time/memory limits to contain PDF/DOCX parser exploits.
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

## Backend Threat Summary

| Severity | Area | Risk | Mitigation Status |
|----------|------|------|--------------------|
| High | Rendering | LLM HTML injected via `analysis_result.html|safe` | Implemented – bleach-sanitized markdown output |
| High | Notifications | Toasts rendered with `innerHTML` | Implemented – escaped backend payloads + text-only rendering |
| High | Prompt Safety | Prompt injection via uploaded content | Open – add guard prompts/moderation |
| High | Request AuthZ | Cross-site request forgery on HTMX POSTs | Open – add CSRF tokens |
| Medium | Identity | Microsoft Graph tokens not validated for issuer/audience | Open – enforce token validation |
| Medium | File Handling | Upload pipeline lacks size/type checks | Open – add bounds + scanning |
| Medium | File Parsing | Untrusted PDFs/DOCX parsed without sandboxing | Open – sandbox parsers |
| Medium | Supply Chain | htmx pulled from CDN without SRI | Open – pin or self-host |
| Medium | Resource Usage | No rate limiting on long-running jobs | Open – add quotas/queues |
| Low | Session/Logging | Sessions never expire; logs accept raw identifiers | Open – add expiry + log normalization |
| Low | Output Retention | Generated artifacts linger on disk | Open – enforce retention |
| Low | Progress Hooks | Progress messages sanitized | Implemented |
| Low | AuthN/AuthZ | Entra ID login + Key Vault allow list | Implemented |
| Low | Admin Controls | Admin roster sourced from Key Vault secret | Implemented |
| Low | Logging Controls | Diagnostics disabled by default; admin-only toggle | Implemented |
