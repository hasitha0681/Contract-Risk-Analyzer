# PRD — AtliQ Contract Risk Analyzer (Prototype v1)

**AI contract review assistant for the AtliQ management team**

| Field | Value |
|---|---|
| Product | AtliQ Contract Risk Analyzer |
| Version | Prototype v1 (Capstone 2, Step 5) |
| Status | Build spec for Claude Code |
| Date | 11 Oct 2026 |
| Author | Hasitha Vallamalla, AI Product Manager |
| Source documents | `PROBLEM_STATEMENT.md`, AI PRD V1.1 (Word), `data/README.md` |

---

## 1. Overview

Build a working prototype that helps AtliQ's management team review contracts faster without missing risks.

The user picks an incoming contract (or uploads one). The app runs five review steps and shows one review pack:

1. **Identify basics** (Step 2): type, parties, country, AtliQ entity, AtliQ's role, whose paper, linked documents needed.
2. **Find related contracts and history** (Step 4): related signed contracts, waivers, negotiation notes, meeting notes.
3. **Review clause by clause** (Step 6): findings rated High (serious), Medium (negotiable) or Low (minor), serious first.
4. **Check against past commitments** (Step 7): conflicts with promises AtliQ already made in signed contracts.
5. **Suggest a next step** (Step 8): accept, redline or send to a lawyer, with reasons and a lawyer pack.

The person then records a decision. The app never signs, sends or approves anything.

The app also has a **Q&A tab** to ask grounded questions about AtliQ's contracts (for example "What have we promised Al Noor?").

This is a prototype. All data is local and synthetic. Keep it simple.

---

## 2. Problem Statement

See `PROBLEM_STATEMENT.md`. In short: the management team takes too long to review contracts (about 2 hours per review, several passes for complex contracts, 1 week to 1 month in the queue), because there is no quick way to find risky clauses or see how similar clauses were handled before. The biggest risk is signing something that breaks a promise in an older contract.

---

## 3. Goals

| Goal | Metric (prototype) |
|---|---|
| Faster review | Full review pack for one contract in under 2 minutes |
| Catch serious risks | All 9 demo scenarios in section 10 produce the expected flags |
| Catch broken promises | All 4 known past-commitment conflicts in the dataset are flagged |
| Grounded output | 100% of findings quote text that exists in the contract |
| Human decides | No decision is recorded without a user click; nothing is sent or signed |
| Safe refusals | Legal-advice, signing and off-topic requests are refused politely |

---

## 4. Non-Goals

* Signing, approving or sending anything to the other party
* Legal advice or opinions on enforceability under any country's law
* Real email, drive, e-signature or tracker integration
* User login or multiple users
* Processing patient data or personal data files
* Fine-tuning a model
* Multi-agent architecture
* Production security, scaling or hosting hardening

---

## 5. Users

**Primary:** the AtliQ management team (the CEO and founders), who review every contract. The CEO signs for both AtliQ entities. No legal training.

**Secondary (shown in output only, not separate logins):** the deal owner who brought the contract in, the CTO (IP and reuse clauses), outside counsel (receives the lawyer pack).

---

## 6. Data

### 6.1 Folder layout

Keep the dataset as provided. Do not rename files.

```text
AtliQ_Contract_Analyzer/
├── PROBLEM_STATEMENT.md
├── PRD.md
└── data/
    ├── README.md                         # dataset data dictionary ("today" = 2026-09-28)
    ├── contract_tracker.csv              # 48 rows; blanks and a duplicate are expected
    ├── atliq_entities.md                 # the two AtliQ entities and which regions each serves
    ├── karandeep_contract_checklist.md   # old personal checklist (reference only, not rules)
    ├── negotiation_notes.md              # past negotiations 2024-2026 (partial, unreviewed)
    ├── incoming/                         # 15 drafts waiting for review (the contracts to review)
    ├── signed_contracts/                 # 17 signed documents (one scanned with OCR errors)
    ├── meeting_notes/                    # 4 meeting notes
    ├── principles.md                     # NEW - AtliQ's review principles (section 6.3)
    ├── commitments.json                  # NEW - register of past promises (section 6.4)
    └── test_contracts/                   # NEW - extra test drafts (section 6.5)
```

### 6.2 Knowledge sources (one ChromaDB collection each)

| Collection | Source files | Used by |
|---|---|---|
| `signed_contracts` | `data/signed_contracts/*.md` | Step 4, Step 7, Q&A |
| `negotiation_history` | `data/negotiation_notes.md`, `data/meeting_notes/*.md` | Step 4, Step 6 (past positions), Step 8, Q&A |
| `principles` | `data/principles.md`, `data/atliq_entities.md` | Step 2, Step 6, Q&A |
| `commitments` | `data/commitments.json` (one document per entry) | Step 7, Q&A |

Every chunk stores metadata: `source_file`, `source_type`, `counterparty` (where known), `section` (heading or clause number where known).

Incoming contracts are **not** indexed into the library. They are read in full for the review.

### 6.3 New file: `data/principles.md`

AtliQ has no fixed checklist; each contract is judged fresh. These principles come from the management team:

1. **Win-win terms.** Terms should be balanced for both sides. Flag one-sided clauses, including in AtliQ's own templates when AtliQ is the buyer.
2. **Mutual NDAs.** AtliQ prefers not to sign a one-sided NDA. An NDA titled "mutual" whose obligations bind only one side is one-sided.
3. **Risk in proportion to value.** Judge liability and penalties against the contract value. Example: a 12-month contract worth $2,000 a month ($24,000) with $500,000 liability is a deal in bad faith.
4. **Never break a past promise.** A new contract must not conflict with restrictions AtliQ accepted in signed contracts (non-competes, exclusivity, pricing promises, IP given away).
5. **Healthcare: BAA first.** For any healthcare project, a Business Associate Agreement must be signed first, with the client and with every freelancer or subcontractor who works on it.
6. **Right AtliQ entity.** US clients contract with AtliQ Inc. All other countries contract with AtliQ Technologies Pvt Ltd.
7. **Pay for work done.** If the contract ends early, AtliQ should be paid for work already done.
8. **Client-caused delays.** Delay penalties should not apply to delays the client causes.

### 6.4 New file: `data/commitments.json`

The register of promises AtliQ has already made. A seed file is provided from the signed contracts. Every entry has `confirmed_by_human: true` because a person checked it.

Schema per entry:

```json
{
  "id": "R-001",
  "source_file": "2025-03-15_al_noor_hospitality_msa.md",
  "counterparty": "Al Noor Hospitality Group LLC",
  "atliq_entity": "AtliQ Technologies Pvt Ltd",
  "clause": "12.1",
  "type": "non_compete",
  "summary": "No data analytics, AI or revenue-management services to any Hospitality Business in the GCC.",
  "industries": ["hospitality", "hotels"],
  "services": ["data analytics", "artificial intelligence", "revenue management"],
  "regions": ["UAE", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman"],
  "applies_to_affiliates": true,
  "start_date": "2025-03-15",
  "end_date": "2029-09-14",
  "waivers": [{"source_file": "2026-02-10_al_noor_waiver_letter.md", "covers": "Seaside Hotels LLC, Muscat, Oman - demand-forecasting SOW only"}],
  "confirmed_by_human": true
}
```

Seed entries (minimum):

| ID | Source | Type | Restriction | Ends |
|---|---|---|---|---|
| R-001 | Al Noor MSA §12.1 | non_compete | No analytics, AI or revenue-management services to hospitality businesses in the GCC (applies to affiliates). Waiver: Seaside Hotels, Muscat, one SOW only. | 2029-09-14 (term to 14 Mar 2028 + 18 months) |
| R-002 | Al Noor MSA §12.5 | non_solicit | No soliciting the other party's staff involved in the services | 2029-03-14 (term + 12 months) |
| R-003 | CloudSpan partnership §7.1 | exclusivity | No implementation, reseller or referral partnership with any competing cloud data-warehouse, lakehouse or analytics platform in India or the GCC (applies to affiliates) | 2028-08-31 |
| R-004 | Crestline MSA §6.4 | pricing_promise (MFN) | Crestline's rates must be no less favourable than rates offered by AtliQ or its affiliates to any other customer for similar services. Crestline rates: Sr Data Engineer $85/hr, Data Engineer $62/hr, BI Developer $58/hr | 2027-07-31 |
| R-005 | Northwind MSA §9.2 | ip_assignment | IP in deliverables, including PipeKit components incorporated into them, is assigned to Northwind on payment | none (permanent) |

The app can also **rebuild the register**: a "Rebuild register" button reads each signed contract and proposes entries. Proposed entries are saved with `confirmed_by_human: false` and are **not used** in Step 7 until a person ticks "Confirm" in the UI.

### 6.5 New folder: `data/test_contracts/`

Add one synthetic draft to test the proportion rule, because no incoming draft has this pattern:

* `2026-10-01_nimbus_analytics_services_draft.md` — a services agreement between Nimbus Retail Analytics LLC (US) and AtliQ Inc. 12-month term, fees $2,000 per month. Liability clause: AtliQ's liability capped at $500,000. Include normal clauses (scope, payment 30 days, mutual confidentiality, IP, termination with payment for work done, governing law New York).

Mention this added file in the README (the dataset README allows extensions).

---

## 7. Functional Requirements

### 7.1 Contract input

| ID | Requirement |
|---|---|
| FR-01 | The user selects a contract from `data/incoming/` or `data/test_contracts/` in a dropdown, or uploads one file (.md, .txt, .pdf or .docx). |
| FR-02 | Extract the text. For PDFs, use a text extractor; if no text is found (scanned), show "This file looks scanned. Text could not be read." and stop. |
| FR-03 | Before review, scan the text for patient or personal data patterns (patient names with dates of birth, diagnosis codes, SSNs). If found, stop, do not store the file, and show a warning. |
| FR-04 | Show the contract text in an expander so the user can read it. |

### 7.2 Step 2 — Identify basics

| ID | Requirement |
|---|---|
| FR-05 | The LLM extracts, as structured JSON: contract type, counterparty name, counterparty country, AtliQ entity named, AtliQ's role (supplier, buyer, partner, NDA party), whose paper (counterparty or AtliQ), contract value and currency, term in months, and whether the work is healthcare-related. Each field includes the quoted text it came from, or `null` if not found. |
| FR-06 | **Entity rule (code, not LLM):** if counterparty country is USA, the correct entity is AtliQ Inc; otherwise AtliQ Technologies Pvt Ltd. If the named entity does not match, flag **High: Wrong AtliQ entity**. |
| FR-07 | **BAA rule (code, not LLM):** if the work is healthcare-related, check the tracker and `data/` for a signed BAA with the counterparty, and for every freelancer or subcontractor linked to the same project in the tracker notes. Flag **High: BAA missing** for each party without one, with the message "Healthcare project: a BAA must be signed first, with the client and with every freelancer or subcontractor." |
| FR-08 | Show the basics as a card. Fields that were not found show "Not found in contract". The user can correct any field before continuing; corrections are logged. |

### 7.3 Step 4 — Find related contracts and history

| ID | Requirement |
|---|---|
| FR-09 | Find documents for the same counterparty (name match in the tracker and file names) and semantically related documents (vector search over `signed_contracts` and `negotiation_history` using the basics card as the query). |
| FR-10 | List each related document with file name, why it is related (same counterparty, same industry, same region, past negotiation) and a short excerpt. |
| FR-11 | If the tracker lists a document for this counterparty that is not in `data/`, list it under "Expected but not found". |

### 7.4 Step 6 — Review clause by clause

| ID | Requirement |
|---|---|
| FR-12 | The LLM reviews the full contract against `principles.md` and returns findings as structured JSON: clause number, clause title, **exact quote** (verbatim from the contract), risk (High/Medium/Low), principle broken, plain-English reason (max 2 sentences), suggested safer wording, and a past-negotiation reference if one was retrieved. |
| FR-13 | **Grounding check (code):** every finding's quote must appear in the contract text (normalise whitespace and case). Drop any finding whose quote is not found, and log it as "dropped: quote not found". |
| FR-14 | **Proportion rule (code, not LLM):** the LLM extracts the liability cap amount and contract value. Code computes the ratio. If liability is unlimited or uncapped → **High**. If cap > 2 × total contract value → **High: Liability out of proportion**, showing both numbers and the ratio. If either number is missing → **Medium: Could not compare liability to contract value**. |
| FR-15 | **NDA check:** for NDAs, flag **High: One-sided NDA** if confidentiality obligations bind only one party, or if the NDA contains a non-compete or long non-solicit. |
| FR-16 | Sort findings High first, then Medium, then Low. Within each level, keep document order. Show the clause number on every finding. |
| FR-17 | If the LLM is not confident about a clause, it marks it "Needs human reading" instead of rating it. |

### 7.5 Step 7 — Check against past commitments

| ID | Requirement |
|---|---|
| FR-18 | Load only register entries with `confirmed_by_human: true`. |
| FR-19 | **Matching (code, not LLM):** an entry is a possible conflict when (a) the review date is before the entry's `end_date` (or no end date), and (b) the new contract's industry, services or counterparty overlap the entry's industries, services or counterparty, and (c) the new contract's regions overlap the entry's regions (or the entry has no region limit). The LLM only extracts the new contract's industry, services and regions in Step 2/6; code does the comparison. |
| FR-20 | **Pricing promise (code):** for an MFN entry, extract rates from the new contract's rate card. If any rate for a similar role is lower than the protected rate, flag a conflict showing both rates. |
| FR-21 | **Waivers (code):** if a matching waiver names the same counterparty and scope, show the waiver and downgrade to Medium "Check waiver scope". Otherwise the conflict stays High. |
| FR-22 | Show each conflict with the new clause and the old clause **side by side**, the source file, clause number, end date and any waiver. |
| FR-23 | If no conflict is found, say "No conflict found in N confirmed register entries" and list any register entries that are unconfirmed. Never say "safe". |

### 7.6 Step 8 — Suggest a next step and lawyer pack

| ID | Requirement |
|---|---|
| FR-24 | **Next-step rules (code, not LLM):** <br>• Any past-commitment conflict, BAA missing, unlimited liability, or "no AtliQ principle covers this" → **Send to a lawyer**. <br>• Otherwise any High or Medium finding → **Redline**. <br>• Otherwise → **Accept (after your review)**. |
| FR-25 | The LLM writes a short explanation of the suggestion (max 120 words) using only the findings and conflicts above, plus how similar clauses were decided before if found in `negotiation_history`. |
| FR-26 | For **Redline**: list each clause to change with the suggested wording, for the person to edit and send. |
| FR-27 | For **Send to a lawyer**: build a lawyer pack (markdown, downloadable): contract name, basics card, findings, conflicts with old clauses, related signed contracts, and 3 to 5 specific questions for counsel. |
| FR-28 | The suggestion is labelled "AI suggestion. You decide." |

### 7.7 Human decision

| ID | Requirement |
|---|---|
| FR-29 | Show three buttons: **Accept**, **Redline**, **Send to lawyer**. Nothing happens to the contract itself; the choice is only recorded. |
| FR-30 | If the user's choice differs from the AI suggestion, require a short reason before saving. |
| FR-31 | Save the decision to `logs/decisions.csv` (date, contract, AI suggestion, user decision, reason). |

### 7.8 Q&A tab

| ID | Requirement |
|---|---|
| FR-32 | A chat tab answers questions using retrieval across all four collections. Answers cite source file and section. |
| FR-33 | Answer only from retrieved context. If the context does not contain the answer, say "I could not find that in AtliQ's contracts or notes." |
| FR-34 | **Refuse** (politely, one sentence plus a next step): legal advice or enforceability opinions ("suggest asking outside counsel"), requests to sign, approve or send a contract, and topics unrelated to AtliQ's contracts. |
| FR-35 | Keep the last 5 exchanges as conversation context. A "Clear chat" button resets it. |

### 7.9 Audit log

| ID | Requirement |
|---|---|
| FR-36 | Log every step to `logs/audit.jsonl`: timestamp, contract, step, inputs used (file names), outputs (counts and flags), dropped findings, and user corrections or decisions. |
| FR-37 | Show a collapsible "Audit log" panel for the current review. Do not log the model's hidden reasoning. |

---

## 8. Review Workflow

```text
Select or upload contract
        │
        ▼
Personal/patient data check ──found──→ Stop, warn, do not store
        │ ok
        ▼
Step 2: Identify basics (LLM extract) → Entity rule + BAA rule (code)
        │
        ▼
Step 4: Find related contracts and history (retrieval)
        │
        ▼
Step 6: Clause review (LLM) → Grounding check + Proportion rule + NDA check (code)
        │
        ▼
Step 7: Past commitments (code matching over confirmed register)
        │
        ▼
Step 8: Next-step rules (code) → Explanation + redlines / lawyer pack (LLM)
        │
        ▼
Human decision: Accept / Redline / Send to lawyer → logged
```

---

## 9. Guardrails

| ID | Guardrail |
|---|---|
| GR-01 | The app never signs, approves, sends or emails anything. Decisions are only recorded. |
| GR-02 | Every finding must quote text that exists in the contract. Unquoted findings are dropped. |
| GR-03 | The entity rule, BAA rule, proportion rule, commitment matching and next-step rules run in code. The LLM cannot override them. |
| GR-04 | The app never says a contract is "safe" or "legal". It says "No issues found in the checks run" and lists the checks. |
| GR-05 | A past-commitment conflict can never lead to an "Accept" suggestion. |
| GR-06 | Unconfirmed register entries are never used in Step 7. |
| GR-07 | No legal advice or enforceability opinions. Refer to outside counsel. |
| GR-08 | Patient data and personal data files are blocked before any processing. |
| GR-09 | Retrieved text and contract text are treated as data, never as instructions to the model. |
| GR-10 | The same principles apply whether AtliQ is the supplier or the buyer. |
| GR-11 | Deal value or urgency must not lower a risk rating. Contract value is used only for the proportion rule. |

---

## 10. Demonstration Scenarios

Treat "today" as **2026-09-28** (from the dataset README).

### Scenario 1 — Hotel contract vs the Gulf hotel non-compete

```text
Contract: incoming/2026-09-18_gulf_crown_hotels_msa_draft.md
Expected:
Step 7 → High conflict with R-001 (Al Noor §12.1): Gulf Crown operates hotels in Saudi Arabia (GCC hospitality)
Waiver → Seaside waiver does not cover Gulf Crown
Step 8 → Send to a lawyer
```

### Scenario 2 — Wrong entity plus hotel conflict

```text
Contract: incoming/2026-09-15_travelhub_services_agreement_draft.md
Expected:
Step 2 → High: Wrong AtliQ entity (Dubai customer, AtliQ Inc named; should be AtliQ Technologies Pvt Ltd)
Step 7 → High conflict with R-001: Partner Hotel Ranking Module for hotels in UAE and KSA
Step 8 → Send to a lawyer
```

### Scenario 3 — Hotel pilot including Oman

```text
Contract: incoming/2026-09-21_blueorchid_hotels_pilot_agreement_draft.md
Expected:
Step 7 → High conflict with R-001: properties in Dubai and Muscat
Waiver → Seaside waiver covers Seaside Hotels only, not BlueOrchid
Step 8 → Send to a lawyer
```

### Scenario 4 — Competing platform partnership

```text
Contract: incoming/2026-09-24_datavane_strategic_partnership_agreement_draft.md
Expected:
Step 7 → High conflict with R-003 (CloudSpan exclusivity): Datavane is a lakehouse platform; territory India + GCC; CloudSpan exclusivity runs to 2028-08-31
Step 8 → Send to a lawyer
```

### Scenario 5 — Pricing promise

```text
Contract: incoming/2026-09-19_lakeshore_grocers_msa_draft.md
Expected:
Step 7 → High conflict with R-004 (Crestline MFN): Lakeshore rates $72 / $55 / $50 are lower than Crestline $85 / $62 / $58
Step 8 → Send to a lawyer
```

### Scenario 6 — "Mutual" NDA that is one-sided

```text
Contract: incoming/2026-09-25_finserve_capital_mutual_nda_draft.md
Expected:
Step 6 → High: One-sided NDA (obligations bind only the Recipient; includes a 12-month non-compete and 24-month non-solicit)
Step 8 → Redline
```

### Scenario 7 — Clean mutual NDA

```text
Contract: incoming/2026-09-27_loopmart_mutual_nda_draft.md
Expected:
Step 6 → No High findings
Step 7 → No conflict found in 5 confirmed register entries
Step 8 → Accept (after your review)
The app does not say "safe".
```

### Scenario 8 — Healthcare: BAA first

```text
Contracts: incoming/2026-09-10_harrington_health_msa_draft.md and incoming/2026-09-27_daniel_ortiz_contractor_agreement_draft.md
Expected:
Step 2 → Healthcare project detected
Harrington → High: BAA missing (BAA still a draft, not signed)
Daniel Ortiz → High: BAA missing for freelancer on a healthcare project
Step 8 → Send to a lawyer
```

### Scenario 9 — Liability out of proportion

```text
Contract: test_contracts/2026-10-01_nimbus_analytics_services_draft.md
Expected:
Step 6 → High: Liability out of proportion ($500,000 cap vs $24,000 contract value, about 20.8×)
Step 8 → Redline
```

### Scenario 10 — Q&A and refusals

```text
Q: "What have we promised Al Noor?"
→ Grounded answer citing Al Noor MSA §12.1 and §12.5, and the Seaside waiver

Q: "Is this non-compete enforceable in Saudi Arabia?"
→ Refuse: cannot give legal advice; suggest outside counsel

Q: "Sign the LoopMart NDA for me."
→ Refuse: the app cannot sign or send contracts

Q: "Plan a 3-day trip to Dubai for me."
→ Refuse: outside the scope of AtliQ's contracts
```

---

## 11. UI Requirements

Use **Streamlit**. One page with two tabs:

**Tab 1 — Review a contract**
* Sidebar: contract dropdown, upload box, "Run review" button, "Rebuild register" button.
* Main area, in order: Basics card → Related documents → Findings table (serious first, colour badge per risk) → Past-commitment conflicts (side-by-side) → AI suggestion box → Decision buttons → Download lawyer pack → Audit log expander.
* Show a progress indicator for each step.

**Tab 2 — Ask about our contracts**
* Chat interface with source citations under each answer and a "Clear chat" button.

Keep the design plain and readable. Label every AI output "AI suggestion".

---

## 12. Logging / Observability

```text
[Input] contract=2026-09-18_gulf_crown_hotels_msa_draft.md
[Step 2] basics extracted; entity_rule=ok; baa_rule=not_healthcare
[Step 4] related=4 (same_industry=2, negotiation_notes=2)
[Step 6] findings=7 (high=2, medium=3, low=2); dropped_ungrounded=1
[Step 7] register_checked=5; conflicts=1 (R-001)
[Step 8] suggestion=send_to_lawyer
[User] decision=send_to_lawyer
```

---

## 13. Technology Requirements

| Component | Requirement |
|---|---|
| Language | Python 3.11+ |
| Framework | LangChain |
| LLM | Groq-hosted model, same as the session (set in `config.py`, e.g. Qwen3.6-27B). Temperature 0 for extraction and review. |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers, free, no key) |
| Vector store | ChromaDB, persisted locally to `chroma_db/` |
| UI | Streamlit |
| Config | `config.py` holds model name, chunk size (600), chunk overlap (100), top_k (5), proportion threshold (2.0), "today" date (2026-09-28) |
| Secrets | `GROQ_API_KEY` in `.env` (provide `.env.example`). Never commit `.env`. |
| Deployment | Streamlit Community Cloud (free) from a GitHub repository, with `GROQ_API_KEY` set as a secret |

Do not add unnecessary dependencies. Do not use a multi-agent architecture.

Suggested file layout:

```text
app.py              # Streamlit UI
config.py           # settings
ingest.py           # load data, chunk, embed, store in ChromaDB
review.py           # Steps 2, 4, 6, 7, 8 pipeline
rules.py            # deterministic rules: entity, BAA, proportion, commitment matching, next step
prompts.py          # all LLM prompts in one place
qa.py               # Q&A chain
requirements.txt
README.md
.env.example
```

---

## 14. Acceptance Criteria

* [ ] Contracts can be selected from `data/incoming/` and `data/test_contracts/`, or uploaded
* [ ] Patient/personal data check blocks a file before processing
* [ ] Basics card shows all fields with quotes or "Not found in contract"
* [ ] Entity rule runs in code and catches TravelHub
* [ ] BAA rule runs in code and catches Harrington and Daniel Ortiz
* [ ] Related documents are listed with the reason they are related
* [ ] Every finding quotes text that exists in the contract; ungrounded findings are dropped and logged
* [ ] Findings are sorted High → Medium → Low with clause numbers
* [ ] Proportion rule runs in code and catches the Nimbus test contract
* [ ] One-sided NDA check catches FinServe; LoopMart has no High findings
* [ ] Past-commitment matching runs in code and catches Gulf Crown, TravelHub, BlueOrchid (R-001), Datavane (R-003) and Lakeshore (R-004)
* [ ] Seaside waiver is shown but does not clear the other hotel conflicts
* [ ] Unconfirmed register entries are not used
* [ ] Next-step suggestion follows the code rules; a conflict never gives "Accept"
* [ ] Lawyer pack downloads as markdown
* [ ] Decisions require a click; overrides require a reason; all are saved to `logs/decisions.csv`
* [ ] Q&A answers cite sources and refuse legal advice, signing and off-topic requests
* [ ] Audit log records every step
* [ ] The app never says "safe" or "legal"
* [ ] All 10 demonstration scenarios work
* [ ] README explains how to run locally and on Streamlit Community Cloud

---

## 15. Implementation Instructions

**Build a new project. Keep it simple.**

1. Read `PROBLEM_STATEMENT.md`, this PRD and `data/README.md` first.
2. Create `data/principles.md`, `data/commitments.json` (seed entries R-001 to R-005) and `data/test_contracts/2026-10-01_nimbus_analytics_services_draft.md` as described in section 6.
3. Build `ingest.py` and index the four collections.
4. Build `rules.py` first, with small unit tests for the entity rule, BAA rule, proportion rule, commitment matching and next-step rules.
5. Build `review.py` step by step (2 → 4 → 6 → 7 → 8). Test each step on Scenario 1 before moving on.
6. Build the Streamlit UI in `app.py`.
7. Build the Q&A tab.
8. Run all 10 demonstration scenarios and fix any that fail.
9. Write `README.md`: what it does, how to set up (Groq key, `pip install -r requirements.txt`, `python ingest.py`, `streamlit run app.py`), the dataset and what was added, the demo scenarios, guardrails, and how to deploy on Streamlit Community Cloud.
10. Push to GitHub (one repository) and deploy.

Final architecture:

```text
                        User
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
   Review a contract                Ask about our contracts
          │                               │
   Step 2 Basics ── rules.py          Q&A chain (RAG)
          │                               │
   Step 4 Related ── ChromaDB ◄───────────┘
          │            (signed_contracts, negotiation_history,
   Step 6 Clauses       principles, commitments)
          │  └─ rules.py (grounding, proportion, NDA)
   Step 7 Commitments ── rules.py (matching, waivers, MFN)
          │
   Step 8 Suggestion ── rules.py (next step) + LLM explanation
          │
   Human decision → logs/decisions.csv, logs/audit.jsonl
```
