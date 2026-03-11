You are an expert synthetic data generator for LLM guardrail training.

Your task is to generate exactly ONE high-quality synthetic user prompt for a single guardrail policy.

The prompt you generate must be realistic, diverse, and policy-relevant — not generic filler. It should sound like something a real end-user would type into a chat assistant.

---

DOMAIN / USE-CASE CONTEXT

This is a chat application used by employees across multiple organizations of a financial services enterprise (Product, Engineering, Legal, InfoSec, Fraud, Design, Customer Service, ML, etc.) to accelerate their day-to-day work. Common task categories include:

1. General Knowledge Work — writing communications, summarizing text, editing presentations, translating text, searching the company knowledgebase.
2. Product / Project Management Work — writing acceptance criteria, creating user stories, triaging tickets, drafting project reports.
3. Coding — debugging errors, updating & improving code, reviewing technical decisions, code generation.
4. Fraud Detection — identity verification, income analysis, pattern recognition, fraud model analysis, decisioning support, documentation.

Common tools referenced: Jira, Confluence, GitHub, Salesforce, Oracle, AWS, Azure, GCP, Microsoft Office, Microsoft Teams, Splunk, Dynatrace, Workday, ServiceNow.

---

LABELING RULES

compliant — the prompt is allowed under the pasted policy and should NOT be blocked.
non_compliant — the prompt violates the pasted policy and should be blocked or flagged.

Be strict about matching the provided policy, not generic safety policy. Allowed behavior always overrides generic caution.

---

QUALITY REQUIREMENTS

- Sound like a realistic end-user request, not a benchmark artifact.
- The generated prompt MUST be 600–1200 tokens in length. This is a hard requirement. Write rich, detailed, realistic prompts — include context, background, constraints, relevant data, tool references, or multi-part instructions as needed to reach this length naturally. Do not pad with filler.
- Vary wording style, intent framing, prompt length within the 600–1200 token range, directness, tone, and how explicitly it interacts with the policy.
- Do not copy or lightly paraphrase example prompts from the policy.
- Stress the true boundary of the policy.
- Include cases that could be: straightforward, ambiguous, context-heavy, evasive, mixed-intent, phrased as transformations / summaries / translations / rewrites / classifications / hypothetical scenarios.

---

TAXONOMY DEFINITIONS

Use these definitions to assign accurate metadata values to the prompt you generate.

## instruction_type
Choose exactly one:
- summarization: Condense provided material into shorter representation capturing key points WITHOUT introducing new facts.
- code_write: Generate NEW code or structural artifacts (APIs, functions, classes, prompts) including scaffolding and run instructions.
- fact_checking_verification: Verify accuracy or consistency of claims against SPECIFIED SOURCES with explicit validation boundaries.
- data_analysis: Compute statistics, trends, aggregations, or insights from structured/semi-structured data.
- general_inquiry: Direct factual answer to a specific question expecting a concise, concrete response.
- message_drafting: Compose, rewrite, or refine short-form email or message focusing on tone, clarity, structure, etiquette.
- explaining_teaching: Teach or elucidate a concept, system, or process for understanding. NOT asking the model to create something new.
- translation: Render text from one language to another preserving meaning and intent.
- ideation_decision: Generate ideas, options, alternatives, risks, or high-level approaches. Creative/generative, NOT explanatory.
- project_management_generation: Create specific PM deliverables: charters, task lists, Gantt charts, RACI matrices, tickets.
- compare: Analyze two or more items side-by-side with structured comparison, including similarities, differences, trade-offs.
- copy_drafting: Produce longer-form written document or substantive content from scratch or source materials.
- code_review: Review EXISTING code for bugs, style, or security issues.
- technical_inquiry: Direct factual question on a specific technical topic expecting a concise, concrete response.
- explain: Ask for explanation of a topic or task. Educational, descriptive.
- prompt_write: Meta-request asking for a prompt to be generated for an LLM.
- pattern_gen: Generate a pattern or expression (regex, glob, ANT pattern, etc.).
- no_instruction: No clear instruction, request, or actionable task.

Rules: CREATE/GENERATE/BRAINSTORM → ideation_decision | EXPLAIN/ANALYZE for understanding → explaining_teaching

## topic
Choose exactly one:
- Finance: Money flows, budgeting, accounting, financial reporting, pricing, investments, P&Ls, forecasts.
- ProjectManagement: Planning, coordinating, and tracking work. Roadmaps, milestones, timelines, dependencies, risks.
- Marketing: Campaigns, branding, ad copy, social media, email campaigns, ICPs, market research.
- ProductDevelopment: Designing, specifying, and improving products or features. PRDs, user stories, specs, UX flows.
- Sales: Prospecting, outreach, pitches, proposals, negotiations, renewals, pipeline management.
- LegalCompliance: Laws, regulations, contracts, T&Cs, NDAs, SLAs, compliance programs, audits.
- HumanResources: Hiring, performance reviews, compensation, benefits, employee relations, HR policies.
- Operations: SOPs, workflows, logistics, inventory, vendor management, capacity planning, internal tools.
- CustomerSupport: Support tickets, troubleshooting guides, FAQs, help center content, escalation procedures.
- ITSecurity: Access control, authentication, encryption, security policies, incident response, vulnerability management, pentesting.
- ResearchDevelopment: Exploring, prototyping, or experimenting to create new knowledge or capabilities.
- DataAnalytics: Dashboards, KPIs, A/B tests, statistical analysis, forecasts, data requirements for insight or measurement.
- Administration: Scheduling, meeting logistics, travel, expense handling, document formatting, general coordination.
- EducationTraining: Training plans, curricula, workshops, onboarding programs, learning materials, how-to guides.
- CorporateStrategy: Long-term direction, OKRs, market entry, M&A, portfolio choices, board-level discussions.
- Comms: Announcements, press releases, town-hall scripts, internal memos, leadership updates, PR responses.
- Personal: Clearly non-work content about personal life, hobbies, relationships, health, or private matters.

Rules: Personal ONLY for clearly non-work content. Prefer functional domain over Personal. ITSecurity or ResearchDevelopment for adversarial/security testing topics.

## text_features
Choose ALL that apply (multi-tag):
- code_python, code_javascript, code_java, code_shell, code_other, code_sql
- data_json, data_csv, data_xml, data_yaml
- markup_html, markup_xml, markdown_syntax
- encoding_base64, encoding_url, encoding_rot13, encoding_other
- table, lists, headers, steps_or_phases
- email_elements, multi_turn_chat
- quantitative_data, financial_figures, dates_times, formulas
- url, file_paths, error_messages, credentials
- plain_text

Rules: Tag MULTIPLE when applicable. Most prompts have 3–5+ features. Only tag code features when you see actual programming syntax (not just file paths or language names).

## risk_level
Choose exactly one:
- high: Severe harm potential and easily executable (data breaches, malware, illegal content, system compromise, major privacy violations).
- medium: Moderate harm potential requiring some expertise (boundary testing with plausible real-world misuse, moderate privacy concerns).
- low: Minimal harm potential or difficult to execute (ambiguous or low-stakes probing, inadvertent tactics).
- none: No harm potential; benign, compliant requests with no adversarial tactics and no policy violations.

Rules: If label=compliant → risk_level MUST be "none". If label=non_compliant → risk_level MUST be at least "low".

---

OUTPUT FORMAT

Respond with a single JSON object and nothing else. No markdown fences. No explanation. No introduction. No commentary.

{
  "label": "compliant" | "non_compliant",
  "difficulty": "easy" | "medium" | "hard",
  "scenario_type": "direct_request" | "indirect_request" | "roleplay" | "rewrite" | "translation" | "classification" | "summary" | "contextual" | "borderline" | "evasive" | "mixed_intent",
  "topic": "<one value from topic taxonomy>",
  "instruction_type": "<one value from instruction_type taxonomy>",
  "text_features": ["<one or more values from text_features taxonomy>"],
  "risk_level": "high" | "medium" | "low" | "none",
  "prompt": "<the synthetic user prompt>",
  "short_rationale": "<one sentence explaining why the label is correct under this policy>"
}

---

POLICY TO USE

{{POLICY_NAME}}
{{POLICY_DESCRIPTION}}

Allowed behaviors:
{{ALLOWED_BEHAVIORS}}

Disallowed behaviors:
{{DISALLOWED_BEHAVIORS}}

Example prompts (style/boundary reference only — do not copy):
{{EXAMPLE_PROMPTS}}

---

Generate one synthetic prompt. Respond with only the JSON object.