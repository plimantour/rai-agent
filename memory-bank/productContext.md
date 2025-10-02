# Product Context: Copilot Memory Bank

## Why This Project Exists

Organizations building custom AI solutions must complete a Responsible AI (RAI) Impact Assessment. Manually drafting these assessments is slow, repetitive, and error‑prone. This project automates creation of a first-pass draft (internal + public versions) from a provided solution description, accelerating compliance workflows while keeping humans in the review loop.

## Problems It Solves

- Reduces time to produce structured RAI documentation (multi-section, token-heavy template)
- Ensures coverage of required governance sections (Intended Uses, Stakeholders, Risks, Harms, Fairness Goals, Disclosure)
- Surfaces potential bias / prompt-injection style risks in the source description
- Provides cost transparency (token usage & estimated € pricing)
- Offers deterministic templating over official DOCX formats without format loss
- Enables reuse of intermediate reasoning via caching (cost savings)
- Flags potential PII in uploads with Azure AI Language, guiding reviewers through a deduplicated remediation panel so they can anonymize or approve suspected findings before generation continues

## How It Should Work

1. User supplies a `solution_description.docx` (CLI) or uploads via Streamlit or HTMX UI.
2. System initializes Azure credentials + model deployment metadata from Key Vault (keyless if possible).
3. Azure AI Language PII scan runs during ingestion, presenting a deduplicated remediation queue where reviewers can anonymize text or approve false positives; accepted terms feed a per-session allowlist before generation proceeds.
4. Multi-step LLM pipeline runs in dependency order:
	- Intended Uses → Stakeholders → Goals (A5/T3, Fairness) → Scope → Solution Info → Assessments → Risks → Impact → Harms → Disclosure
5. Each step requests structured JSON; processors map JSON into (search_token → replacement) pairs.

Success Criteria:
- < 15 min typical full generation latency
- > 95% token placeholders replaced when model outputs valid JSON
- Draft clearly marked as AI-generated; requires human review
- Re-runs with caching reduce token spend when description unchanged

Out of Scope (current phase):
- Automated legal / policy approval
- Persistent workflow state across sessions (beyond cached completions)
- Multi-language output beyond English
- Fine-grained role-based editing inside the tool

