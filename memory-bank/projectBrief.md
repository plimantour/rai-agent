# Memory Bank: Project Brief

## Maintain Project Context Across Sessions and Memory Resets for Consistent AI-Assisted Development
An AI-assisted tool that ingests a solution description and automatically generates a structured draft Responsible AI (RAI) Impact Assessment (internal + public variants). It orchestrates a multi-step LLM pipeline (Intended Uses → Stakeholders → Risks → Harms → Disclosures) producing token-populated DOCX templates while tracking token cost, enabling faster, standardized compliance workflows. Human review remains required; system focuses on acceleration, coverage, and consistency.

Core Differentiators:
- Deterministic template token substitution with conditional section pruning
- Structured JSON transformation layer per step
- Optional prompt compression to reduce cost
- Integrated Azure security primitives (Key Vault, Managed Identity)
- Dual output formats from one generation run
- Admin-selectable model & reasoning effort (cost / capability flexibility)
- Adaptive reasoning parameter handling (progressive fallback)
- Cost accounting includes hidden reasoning tokens for transparency
- Azure AI Language powered PII screening with deduplicated remediation UI so reviewers can anonymize or approve findings before generation continues
- Default anonymized replacement suggestions per PII finding, reducing clicks while keeping original context readily visible for reviewers
- Inclusive HTMX/Streamlit UI with keyboard-first workflows, screen-reader labels, toast feedback, and a dark/light theme toggle to support accessibility needs during remediation and review

Primary Stakeholders: AI solution architects, compliance / RAI reviewers, engineering teams preparing assessment packages.

Key Risks to Mitigate Next: resilience (error handling), structured logging, test coverage, multi-user scaling & cache integrity, pricing drift, reasoning cost transparency.

## Accessibility & Inclusion
- Keyboard navigation works throughout the dashboard (modal focus traps, file pickers, remediation forms) so power users can work without a mouse.
- Screen-reader support includes descriptive labels, visually hidden text for remediation inputs, and semantic status badges that communicate verification state.
- Toast messaging, live progress feeds, and the loading overlay keep all users informed about long-running actions without relying solely on visual spinners.
- Light and dark themes share tuned color palettes and high-contrast input states (`is-suggested`, `is-deanonymized`) to help reviewers track anonymization choices in their preferred setting.