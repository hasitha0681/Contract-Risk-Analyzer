# AtliQ Contract Risk Analyzer

An AI contract review assistant for AtliQ's management team, built to `PRD.md`
(Capstone 2, Step 5).

## Quick start

Needs Python 3.11+ and a free Groq API key from https://console.groq.com.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Put your key in `.env` (`GROQ_API_KEY=...`), then:

```bash
.venv\Scripts\streamlit run app.py
```

Open http://localhost:8501. Pick a contract in the sidebar (try
`incoming/2026-09-18_gulf_crown_hotels_msa_draft.md`), click **Run review**,
check the basics, then **Confirm basics and continue**. A review takes 1-2
minutes on Groq's free tier. The **Ask about our contracts** tab answers
questions such as "What have we promised Al Noor?".

On macOS/Linux use `.venv/bin/` and `cp`. The rest of this README covers how it
works, the data, the demo scenarios, the guardrails and cloud deployment.

## What it does

For each new contract it:

1. **Identifies the basics**: type, parties, country, AtliQ entity, AtliQ's role, value, term, healthcare.
2. **Finds related signed contracts and past negotiation history.**
3. **Reviews the contract clause by clause** against AtliQ's 8 principles, serious findings first.
4. **Checks it against promises AtliQ already made** in signed contracts (the commitments register).
5. **Suggests a next step**: Accept, Redline or Send to a lawyer, with reasons and a lawyer pack.

A person makes every decision. The app never signs, sends or approves anything,
and it is not legal advice.

## How it works

```text
Select or upload contract
        |
Personal/patient data check ---found---> stop, warn, nothing stored
        |
Step 2  Basics (LLM extract, every field quoted) -> entity rule + BAA rule (code)
        |   the user can correct any field; corrections are logged
Step 4  Related documents (ChromaDB search + tracker)
        |
Step 6  Clause review (LLM, per section) -> grounding check + proportion rule + NDA check (code)
        |
Step 7  Past commitments (code matching over the confirmed register)
        |
Step 8  Next-step rules (code) -> explanation + redlines / lawyer pack (LLM)
        |
Human decision: Accept / Redline / Send to lawyer -> logs/decisions.csv
```

**Where decisions are made.** The LLM only extracts facts, quotes and drafts
wording. Everything that sets a rating or a suggestion runs in `rules.py`: the
entity rule, the BAA rule, the proportion rule, the NDA check, commitment
matching, the pricing-promise check, waivers, the grounding check and the
next-step rules. The LLM cannot override them.

**Grounded only.** Every finding must quote the contract. A finding whose quote
is not in the contract text (after normalising case, whitespace and markdown)
is dropped and logged as `dropped: quote not found`.

## Setup (local)

Everything installs into a project-local `.venv`.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set `GROQ_API_KEY` (free at https://console.groq.com). Then:

```bash
.venv\Scripts\python ingest.py
.venv\Scripts\streamlit run app.py
```

`ingest.py` builds four ChromaDB collections in `chroma_db/` (safe to re-run).
The embedding model, `all-MiniLM-L6-v2`, runs locally and downloads once (~90 MB).
If you skip `ingest.py`, the app builds the knowledge base on first start.

On macOS/Linux use `.venv/bin/` instead of `.venv\Scripts\`.

### Tests

```bash
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python scenarios.py
```

`tests/test_rules.py` covers every deterministic rule with no LLM calls.
`scenarios.py` runs the demonstration scenarios end to end against the live model.

## Speed and the Groq free tier

The model is `qwen/qwen3.8-27b` on Groq, temperature 0, reasoning off. (The PRD
names Qwen3.6-27B; Groq has retired it and 3.8 is its direct successor. Override
with `GROQ_MODEL` in `.env`.)

Groq's free tier allows **8,000 tokens per minute**, and one long contract is
about 6,000 tokens. `llm.py` paces every call against that budget, so the app
waits instead of failing. A typical review takes 1-2 minutes; the longest
drafts (Harrington, Datavane) take about 3. A paid Groq tier removes the wait.

## Data

The dataset in `Data/` is used as provided (nothing renamed). "Today" is
**2026-09-28**, set in `config.py`.

| Collection | Source |
|---|---|
| `signed_contracts` | `Data/signed_contracts/*.md` |
| `negotiation_history` | `Data/negotiation_notes.md`, `Data/meeting_notes/*.md` |
| `principles` | `Data/principles.md`, `Data/atliq_entities.md` |
| `commitments` | `Data/commitments.json`, one document per entry |

Incoming drafts are not indexed. They are read in full at review time.

### What was added to the dataset

| File | Why |
|---|---|
| `Data/principles.md` | AtliQ's 8 review principles from the management team (PRD 6.3). |
| `Data/commitments.json` | The register of promises already made, R-001 to R-005, each confirmed by a person (PRD 6.4). |
| `Data/test_contracts/2026-10-01_nimbus_analytics_services_draft.md` | A synthetic $24,000 contract with a $500,000 liability cap, to test the proportion rule (PRD 6.5). |

Two optional fields extend the register schema so the checks can run in code:

* `protected_rates` (R-004, Crestline MFN): the protected hourly rates, compared with the new contract's rate card.
* `assets` (R-005, Northwind IP): named tools already assigned away (`PipeKit`). A new contract that uses or licenses one is a conflict.

Tags in `industries` and `services` come from a fixed vocabulary in `config.py`,
so matching is a deterministic set comparison.

### The commitments register

| ID | Source | Restriction | Ends |
|---|---|---|---|
| R-001 | Al Noor MSA 12.1 | No analytics, AI or revenue management for hospitality businesses in the GCC (affiliates too). Waiver: Seaside Hotels, Muscat, one SOW only. | 2029-09-14 |
| R-002 | Al Noor MSA 12.5 | No soliciting staff involved in the services | 2029-03-14 |
| R-003 | CloudSpan 7.1 | No partnership with a competing data-warehouse / lakehouse platform in India or the GCC | 2028-08-31 |
| R-004 | Crestline 6.4 | Most-favoured pricing: $85 / $62 / $58 per hour | 2027-07-31 |
| R-005 | Northwind 9.2 | IP in deliverables, including PipeKit components, assigned to Northwind | permanent |

**Rebuild register** (sidebar) reads every signed contract's restrictive clauses
and proposes new entries. Proposals are saved with `confirmed_by_human: false`
and are never used in reviews until someone ticks **Confirm**.

### Matching rule (Step 7)

An entry is a possible conflict when the review date is before its end date,
the regions overlap (or the entry has no region limit), and either the
counterparty is the same or the contract matches the entry's industries **and**
services. Requiring both (rather than either) follows the wording of the
clauses: the Al Noor non-compete restricts analytics *for hospitality
businesses*, so analytics for a Gulf bank is not a conflict. Hospitality is also
detected in code from words like "hotel" in the contract (expense clauses
excluded), so a booking app that ranks partner hotels is never missed.

## Demonstration scenarios

| # | Contract | Expected |
|---|---|---|
| 1 | Gulf Crown Hotels MSA | High conflict with R-001; Seaside waiver does not cover it; Send to a lawyer |
| 2 | TravelHub services agreement | Wrong AtliQ entity (Dubai client, AtliQ Inc named); R-001 conflict; Send to a lawyer |
| 3 | BlueOrchid hotels pilot | R-001 conflict (Dubai and Muscat properties); Send to a lawyer |
| 4 | Datavane partnership | R-003 conflict (lakehouse platform, India + GCC); Send to a lawyer |
| 5 | Lakeshore Grocers MSA | R-004 conflict: $72 / $55 / $50 below $85 / $62 / $58; Send to a lawyer |
| 6 | FinServe "mutual" NDA | High: one-sided NDA (non-compete, 24-month non-solicit); Redline |
| 7 | LoopMart mutual NDA | No High findings; no conflict in 5 entries; Accept (after your review) |
| 8 | Harrington MSA, Daniel Ortiz contractor agreement | Healthcare detected; BAA missing for Harrington and Daniel Ortiz; Send to a lawyer |
| 9 | Nimbus test contract | High: liability out of proportion ($500,000 vs $24,000, about 20.8x); Redline |
| 10 | Q&A tab | Grounded answer on Al Noor; refuses legal advice, signing and off-topic requests |

Rheinwerk (not a numbered scenario) also flags R-005: it licenses PipeKit,
which was assigned to Northwind.

## Guardrails

* Never signs, approves, sends or emails anything; decisions are only recorded.
* Every finding quotes the contract; ungrounded findings are dropped and logged.
* Entity, BAA, proportion, NDA, commitment and next-step rules run in code.
* Never says a contract is "safe" or "legal": a clean result reads "No issues found in the checks run" and lists the checks.
* A past-commitment conflict can never lead to "Accept".
* Unconfirmed register entries are never used in reviews.
* No legal advice: enforceability questions are referred to outside counsel.
* Files with personal or patient data (SSNs, dates of birth, diagnosis codes) are blocked before any processing and never stored.
* Contract and retrieved text are passed to the model as data, never as instructions.
* Deal value and urgency never lower a rating; value is used only by the proportion rule.

## Logs

* `logs/audit.jsonl`: every step of every review (inputs, outputs, dropped findings, corrections, decisions). Shown in the app's **Audit log** panel. No model reasoning is logged.
* `logs/decisions.csv`: date, contract, AI suggestion, user decision and reason. A decision that differs from the suggestion requires a reason.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository. `.gitignore` keeps `.env`, `.venv/`, `chroma_db/` and `logs/` out of it. Check that `.env.example` contains only the placeholder.
2. At https://share.streamlit.io, choose **Create app**, pick the repository and branch, and set the main file to `app.py`.
3. Under **Advanced settings**, choose Python **3.11**, and under **Secrets** add:
   ```toml
   GROQ_API_KEY = "gsk_..."
   ```
4. Deploy. On first start the app builds the knowledge base (about a minute). On Community Cloud, `logs/` and register confirmations reset when the app restarts.

## Files

| File | Role |
|---|---|
| `app.py` | Streamlit UI: review tab and Q&A tab |
| `config.py` | Paths, model, chunking, top_k, thresholds, review date, tag vocabularies |
| `ingest.py` | Load, chunk, embed and store the four collections |
| `review.py` | Steps 2, 4, 6, 7 and 8; uploads; personal-data check; audit and decision logs |
| `rules.py` | All deterministic business rules |
| `prompts.py` | All LLM prompts |
| `llm.py` | Groq client, token-budget pacing, JSON parsing |
| `qa.py` | Q&A retrieval, answers and refusals |
| `register.py` | Rebuild and confirm the commitments register |
| `scenarios.py` | End-to-end demonstration scenario runner |
| `tests/test_rules.py` | Unit tests for the rules |
