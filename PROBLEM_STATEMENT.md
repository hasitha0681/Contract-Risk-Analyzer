# PROBLEM STATEMENT - ATLIQ CONTRACT RISK ANALYZER

For: Capstone 2, Step 5 (Build the Prototype)
Your task: Read this brief and the PRD, then build a working prototype over the data in `data/`.


## THE SITUATION

AtliQ is a founder-led IT services company with two legal entities: AtliQ Inc (US clients only) and
AtliQ Technologies Pvt Ltd (all other countries). AtliQ has no legal team. The management team
(the CEO and founders) reviews every contract itself, and only the CEO signs.

In the management team's own words:

> "As a management team, we are taking more time to review contracts. We need to reduce the time
> it takes to review contracts effectively."

Today:

- AtliQ receives 3 to 4 contracts and 4 to 5 NDAs a month.
- Each review takes about 2 hours. Complex contracts need several passes.
- Contracts wait 1 week to 1 month in the queue.
- AtliQ spends about $5,000 a year on outside counsel.
- There is no fixed checklist. Each contract is judged fresh, aiming for a win-win deal.

The root cause: AtliQ has no quick way to identify risky clauses or to see how similar clauses were
handled before. Past contracts, negotiation notes and meeting notes sit in separate files, so the team
reads every contract page by page and searches old documents by hand.

The most serious risk is breaking a promise AtliQ already made in an older contract. For example, if
one contract stops AtliQ from working with hotels in Dubai, nothing warns the team when a new hotel
contract arrives. There is no list of what AtliQ has already promised.


## THE PRODUCT TO BUILD

An AI contract review assistant for the AtliQ management team. For each new contract it:

1. Identifies the basics: type, parties, country, AtliQ entity, AtliQ's role.
2. Finds related signed contracts and past negotiation history.
3. Reviews the contract clause by clause against AtliQ's principles, serious findings first.
4. Checks the contract against promises AtliQ has already made in signed contracts.
5. Suggests a next step (accept, redline or send to a lawyer) with reasons.

A person makes every decision. The assistant never signs, sends or approves anything.

Build the prototype around these fixed constraints:

- Grounded only - every finding must quote the exact clause it is based on. No made-up clauses,
  numbers or rules.
- Key business rules run in code, not in the AI (entity rule, BAA rule, liability-to-value check,
  past-commitment matching, next-step rules).
- The AI suggests; the human decides. Every decision is recorded.
- Not legal advice. Questions the data cannot answer are refused or sent to a lawyer.
- No patient data or personal data is processed.
