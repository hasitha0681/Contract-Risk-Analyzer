"""Deterministic business rules (PRD GR-03).

Everything that decides a risk rating, a conflict or the next step lives here
as plain Python. The LLM only extracts facts and quotes; these functions turn
those facts into flags, and the LLM cannot override them.

Rules implemented:
  * grounding check             FR-13, GR-02
  * entity rule                 FR-06
  * BAA rule                    FR-07
  * proportion rule             FR-14
  * NDA check                   FR-15
  * commitment matching         FR-18, FR-19, FR-21, GR-06
  * pricing promise (MFN)       FR-20
  * next-step rules             FR-24, GR-05
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import config

RISK_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Needs human reading": 3}

# Flags that force "Send to a lawyer" (FR-24).
LAWYER_FLAGS = {"baa_missing", "unlimited_liability", "no_principle"}


# =============================================================================
# Findings
# =============================================================================
@dataclass
class Finding:
    title: str
    risk: str                      # High / Medium / Low / Needs human reading
    reason: str
    quote: str | None = None
    clause: str | None = None
    principle: str | None = None
    suggested_wording: str | None = None
    past_reference: str | None = None
    source: str = "rule"           # "rule" (code) or "ai" (LLM clause review)
    flags: list[str] = field(default_factory=list)
    position: int = 10**9          # character offset of the quote, for ordering

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """High first, then Medium, Low, unrated; document order within a level (FR-16)."""
    return sorted(findings, key=lambda f: (RISK_ORDER.get(f.risk, 9), f.position))


# =============================================================================
# Text helpers and the grounding check (FR-13)
# =============================================================================
_QUOTE_CHARS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                              "–": "-", "—": "-", " ": " "})


def normalise(text: str) -> str:
    """Lower-case, unify quotes and dashes, drop markdown emphasis, collapse spaces."""
    text = text.translate(_QUOTE_CHARS)
    text = text.replace("*", "").replace("_", " ").replace("`", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def quote_position(quote: str | None, text: str) -> int | None:
    """Offset of `quote` in `text` after normalisation, or None if absent.

    A quote may elide with "..." or an ellipsis; each piece must then appear,
    in order. Nothing else is tolerated: a paraphrase is not a quote.
    """
    if not quote or not quote.strip():
        return None
    haystack = normalise(text)
    pieces = [normalise(p) for p in re.split(r"\.\.\.|…", quote)]
    pieces = [p.strip(" .,;:\"'") for p in pieces]
    pieces = [p for p in pieces if p]
    if not pieces:
        return None
    # Very short fragments prove nothing; require real text.
    if sum(len(p) for p in pieces) < 12:
        return None

    start = None
    cursor = 0
    for piece in pieces:
        found = haystack.find(piece, cursor)
        if found < 0:
            return None
        if start is None:
            start = found
        cursor = found + len(piece)
    return start


def is_grounded(quote: str | None, text: str) -> bool:
    return quote_position(quote, text) is not None


def find_line(text: str, patterns: list[str]) -> str | None:
    """First non-empty line matching any regex in `patterns` (case-insensitive)."""
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        for pattern in patterns:
            if re.search(pattern, clean, re.IGNORECASE):
                return clean[:500]
    return None


# =============================================================================
# Names, countries, regions
# =============================================================================
_LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "pvt", "private", "co", "corp", "corporation",
    "plc", "gmbh", "pte", "fz", "the", "company", "&", "and",
}


def counterparty_key(name: str | None) -> str:
    """Short stable key for matching a counterparty across files and the tracker.

    "Harrington Health Systems Inc" -> "harrington"; "Al Noor Hospitality" ->
    "al noor" (the first word alone is too short to be distinctive).
    """
    if not name:
        return ""
    words = re.findall(r"[a-z0-9]+", name.lower())
    words = [w for w in words if w not in _LEGAL_SUFFIXES]
    if not words:
        return ""
    if len(words[0]) >= 4 or len(words) == 1:
        return words[0]
    return f"{words[0]} {words[1]}"


def same_counterparty(a: str | None, b: str | None) -> bool:
    ka, kb = counterparty_key(a), counterparty_key(b)
    return bool(ka) and ka == kb


def normalise_country(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().lower().rstrip("?").strip()
    if raw in config.REGION_ALIASES:
        return config.REGION_ALIASES[raw]
    for alias, country in config.REGION_ALIASES.items():
        if len(alias) > 3 and alias in raw:
            return country
    # US states written as the country ("Texas", "Delaware corporation").
    if re.search(r"\b(texas|delaware|new york|illinois|ohio|california|new jersey)\b", raw):
        return "USA"
    return value.strip()


def normalise_regions(values: list[str] | None) -> set[str]:
    """Map free-text regions to canonical countries; expand groups like GCC."""
    regions: set[str] = set()
    for value in values or []:
        raw = value.strip().lower()
        if raw in config.REGION_GROUPS:
            regions.update(config.REGION_GROUPS[raw])
            continue
        country = normalise_country(value)
        if country:
            regions.add(country)
    return regions


# Lines naming AtliQ's own offices say nothing about where the work happens.
_ATLIQ_ADDRESS = re.compile(r"baner|pune\s*411045|college road east|princeton", re.IGNORECASE)
# Short aliases are only trusted in their usual upper-case form ("US", "UK").
_CASE_SENSITIVE = {"us", "uk", "ksa", "uae", "eu"}


def regions_in_text(text: str) -> set[str]:
    """Countries named anywhere in the contract except AtliQ's own address lines.

    Catches places the LLM may skip, such as a Muscat property listed in an
    annexure at the end of a long pilot agreement.
    """
    found: set[str] = set()
    for line in text.splitlines():
        if _ATLIQ_ADDRESS.search(line):
            continue
        for alias, country in config.REGION_ALIASES.items():
            if alias in _CASE_SENSITIVE:
                if re.search(rf"\b{re.escape(alias.upper())}\b", line):
                    found.add(country)
            elif re.search(rf"\b{re.escape(alias)}\b", line, re.IGNORECASE):
                found.add(country)
        for group, members in config.REGION_GROUPS.items():
            if group in {"eu", "middle east"}:
                continue
            if re.search(rf"\b{re.escape(group)}\b", line, re.IGNORECASE):
                found.update(members)
    return found


_EXPENSE_LINE = re.compile(r"expense|reimburs|accommodation|travel polic|per diem", re.IGNORECASE)


def mentions_hospitality(text: str) -> bool:
    """True if the work itself involves hotels. Expense clauses ("hotel
    accommodation reimbursed at cost") say nothing about the industry."""
    for line in text.splitlines():
        if _EXPENSE_LINE.search(line):
            continue
        if any(re.search(rf"\b{w}\b", line, re.IGNORECASE) for w in config.HOSPITALITY_WORDS):
            return True
    return False


# =============================================================================
# Entity rule (FR-06)
# =============================================================================
def canonical_entity(named: str | None) -> str | None:
    if not named:
        return None
    lowered = named.lower()
    if "pvt" in lowered or "private" in lowered or "technologies" in lowered:
        return config.ENTITY_ROW
    if re.search(r"\binc\b", lowered):
        return config.ENTITY_US
    return None


def entity_rule(
    country: str | None, named_entity: str | None, role: str | None, quote: str | None
) -> tuple[str, Finding | None]:
    """Return (status, finding). Status is logged; a finding means a mismatch."""
    if (role or "").lower() == "partner":
        # A partnership is not a client contract; principle 6 is about clients.
        return "not_applied_partnership", None

    canonical_country = normalise_country(country)
    named = canonical_entity(named_entity)
    if not canonical_country or not named:
        return "not_checked_missing_fields", None

    expected = config.ENTITY_US if canonical_country == "USA" else config.ENTITY_ROW
    if named == expected:
        return "ok", None

    return "mismatch", Finding(
        title="Wrong AtliQ entity",
        risk="High",
        reason=(
            f"The counterparty is in {canonical_country}, so the contract should be with "
            f"{expected}, but it names {named}."
        ),
        quote=quote,
        principle="P6. Right AtliQ entity",
        suggested_wording=f"Replace the AtliQ party with {expected} and its registered details.",
        flags=["wrong_entity"],
    )


# =============================================================================
# Tracker and the BAA rule (FR-07, FR-11)
# =============================================================================
def load_tracker(path: Path = config.TRACKER_CSV) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _tracker_rows_for(name: str, tracker: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in tracker if same_counterparty(row["counterparty"], name)]


def project_links(counterparty: str, tracker: list[dict[str, str]]) -> tuple[str | None, list[str]]:
    """Find the healthcare project a contract belongs to, via tracker notes.

    Returns (client_name, freelancers_and_subcontractors). A note such as
    "US freelancer for Harrington" links that freelancer to Harrington.
    """
    def linked_people(client: str) -> list[str]:
        key = counterparty_key(client)
        people = []
        for row in tracker:
            if not re.search(r"contractor|subcontractor|freelanc|vendor|staff aug", row["doc_type"] + " " + row["notes"], re.IGNORECASE):
                continue
            if re.search(rf"\bfor\s+{re.escape(key)}\b", row["notes"], re.IGNORECASE):
                if row["counterparty"] not in people:
                    people.append(row["counterparty"])
        return people

    # Is this counterparty itself a freelancer linked to a client project?
    for row in _tracker_rows_for(counterparty, tracker):
        match = re.search(r"\bfor\s+([A-Z][A-Za-z]+)", row["notes"])
        if match and re.search(r"freelanc|contractor|subcontract", row["notes"] + row["doc_type"], re.IGNORECASE):
            client_key = match.group(1).lower()
            for other in tracker:
                if counterparty_key(other["counterparty"]) == client_key:
                    return other["counterparty"], linked_people(other["counterparty"])

    return counterparty, linked_people(counterparty)


def has_signed_baa(name: str, tracker: list[dict[str, str]], signed_dir: Path = config.SIGNED_DIR) -> bool:
    for row in _tracker_rows_for(name, tracker):
        if "baa" in row["doc_type"].lower() and row["status"].lower() == "signed":
            return True
    key = counterparty_key(name).replace(" ", "_")
    if key:
        for file in signed_dir.glob("*.md"):
            if "baa" in file.name.lower() and key in file.name.lower():
                return True
    return False


def is_healthcare_client(name: str, tracker: list[dict[str, str]]) -> bool:
    """Tracker evidence that a counterparty is a healthcare client (BAA rows or notes)."""
    for row in _tracker_rows_for(name, tracker):
        if "baa" in row["doc_type"].lower() or "health" in row["notes"].lower():
            return True
    return False


BAA_MESSAGE = (
    "Healthcare project: a BAA must be signed first, with the client and with "
    "every freelancer or subcontractor."
)


def baa_rule(
    counterparty: str,
    is_healthcare: bool,
    tracker: list[dict[str, str]],
    evidence_quote: str | None,
) -> tuple[str, list[Finding], list[str]]:
    """Return (status, findings, parties_checked).

    Healthcare is decided by the LLM flag OR tracker evidence that the project
    client is a healthcare client, so a freelancer contract that never says
    "patient" is still caught when the tracker links it to a hospital project.
    """
    client, people = project_links(counterparty, tracker)
    healthcare = is_healthcare or (client is not None and is_healthcare_client(client, tracker))
    if not healthcare:
        return "not_healthcare", [], []

    parties: list[str] = []
    for name in [client or counterparty, counterparty, *people]:
        if name and not any(same_counterparty(name, p) for p in parties):
            parties.append(name)

    findings = []
    for party in parties:
        if has_signed_baa(party, tracker):
            continue
        role = "client" if same_counterparty(party, client) else "freelancer or subcontractor"
        findings.append(
            Finding(
                title=f"BAA missing: {party}",
                risk="High",
                reason=f"{BAA_MESSAGE} No signed BAA was found for {party} ({role}).",
                quote=evidence_quote,
                principle="P5. Healthcare: BAA first",
                suggested_wording="Do not sign until a Business Associate Agreement is signed with this party.",
                flags=["baa_missing"],
            )
        )
    status = "baa_missing" if findings else "baa_ok"
    return status, findings, parties


_DOC_TYPE_KEYWORDS = [
    ("baa", ["baa"]),
    ("nda", ["nda"]),
    ("waiver", ["waiver"]),
    ("settlement", ["settlement"]),
    ("sow", ["sow"]),
    ("partnership", ["partnership"]),
    ("subcontractor", ["subcontractor"]),
    ("contractor", ["contractor"]),
    ("pilot", ["pilot"]),
    ("dpa", ["dpa"]),
    ("vendor", ["vendor"]),
    ("staff aug", ["staff"]),
    ("msa", ["msa", "services_agreement", "master"]),
]


def expected_but_missing(counterparty: str, tracker: list[dict[str, str]]) -> list[dict[str, str]]:
    """Tracker rows for this counterparty with no matching file in Data/ (FR-11)."""
    key = counterparty_key(counterparty).replace(" ", "_")
    if not key:
        return []
    files = [p.name.lower() for d in (config.SIGNED_DIR, config.INCOMING_DIR) for p in d.glob("*")]
    own = [f for f in files if key in f]
    incoming_own = [p.name for p in config.INCOMING_DIR.glob("*") if key in p.name.lower()]

    missing = []
    for row in _tracker_rows_for(counterparty, tracker):
        doc = row["doc_type"].lower()
        keywords = next((kws for marker, kws in _DOC_TYPE_KEYWORDS if marker in doc), [doc])
        found = any(any(k in f for k in keywords) for f in own)
        if not found and row["status"].lower() != "signed" and incoming_own:
            found = True   # the draft under review
        if not found:
            missing.append(
                {
                    "contract_id": row["contract_id"],
                    "doc_type": row["doc_type"],
                    "status": row["status"] or "(blank)",
                    "file_location": row["file_location"] or "(not recorded)",
                }
            )
    return missing


# =============================================================================
# Proportion rule (FR-14)
# =============================================================================
def proportion_rule(
    contract_type: str | None,
    liability: dict[str, Any] | None,
    contract_value: float | None,
    value_currency: str | None,
) -> tuple[str, Finding | None]:
    """Compare the liability cap with the contract value. Code, not LLM."""
    if contract_type and "nda" in contract_type.lower():
        return "not_applicable_nda", None

    liability = liability or {}
    kind = (liability.get("type") or "not_found").lower()
    quote = liability.get("quote")

    if kind == "unlimited":
        return "unlimited", Finding(
            title="Unlimited liability",
            risk="High",
            reason="Liability for the service provider is unlimited or uncapped. Unlimited liability is never in proportion to a fixed contract value.",
            quote=quote,
            principle="P3. Risk in proportion to value",
            suggested_wording="Cap each party's aggregate liability at the fees paid or payable under the contract, with carve-outs limited to fraud and wilful misconduct.",
            flags=["unlimited_liability"],
        )

    cap_amount = liability.get("amount")
    cap_currency = liability.get("currency") or value_currency
    multiple = liability.get("multiple")

    if kind == "multiple_of_fees" and isinstance(multiple, (int, float)) and multiple > 0:
        ratio = float(multiple)
        if ratio > config.PROPORTION_THRESHOLD:
            return "out_of_proportion", Finding(
                title="Liability out of proportion",
                risk="High",
                reason=f"The liability cap is {ratio:g} times the fees, above the {config.PROPORTION_THRESHOLD:g}x limit.",
                quote=quote,
                principle="P3. Risk in proportion to value",
                suggested_wording="Cap liability at 1x the fees paid or payable under the contract.",
                flags=["liability_ratio"],
            )
        return "ok", None

    if kind == "capped_amount" and isinstance(cap_amount, (int, float)) and isinstance(contract_value, (int, float)) and contract_value > 0:
        if value_currency and cap_currency and value_currency.upper() != cap_currency.upper():
            return "currency_mismatch", Finding(
                title="Could not compare liability to contract value",
                risk="Medium",
                reason=f"The cap is in {cap_currency} and the contract value in {value_currency}.",
                quote=quote,
                principle="P3. Risk in proportion to value",
            )
        ratio = cap_amount / contract_value
        if ratio > config.PROPORTION_THRESHOLD:
            return "out_of_proportion", Finding(
                title="Liability out of proportion",
                risk="High",
                reason=(
                    f"Liability cap {cap_currency or ''} {cap_amount:,.0f} vs contract value "
                    f"{value_currency or ''} {contract_value:,.0f}: about {ratio:.1f}x, above the "
                    f"{config.PROPORTION_THRESHOLD:g}x limit."
                ).replace("  ", " "),
                quote=quote,
                principle="P3. Risk in proportion to value",
                suggested_wording=f"Cap liability at the fees paid or payable under the contract ({value_currency or ''} {contract_value:,.0f}).".replace("( ", "("),
                flags=["liability_ratio"],
            )
        return "ok", None

    return "missing_numbers", Finding(
        title="Could not compare liability to contract value",
        risk="Medium",
        reason="The liability cap or the contract value was not found, so the proportion check could not run.",
        quote=quote,
        principle="P3. Risk in proportion to value",
    )


# =============================================================================
# NDA check (FR-15)
# =============================================================================
def nda_rule(contract_type: str | None, nda: dict[str, Any] | None) -> list[Finding]:
    if not contract_type or "nda" not in contract_type.lower():
        return []
    nda = nda or {}
    findings = []

    if (nda.get("obligations_bind") or "").lower() in {"one_party", "one", "recipient_only"}:
        findings.append(Finding(
            title="One-sided NDA: obligations bind only one party",
            risk="High",
            reason="The confidentiality obligations bind only one side, whatever the title says.",
            quote=nda.get("obligations_quote"),
            principle="P2. Mutual NDAs",
            suggested_wording="Make every confidentiality obligation apply to each party as both discloser and recipient.",
            flags=["one_sided_nda"],
        ))

    if nda.get("non_compete"):
        findings.append(Finding(
            title="One-sided NDA: contains a non-compete",
            risk="High",
            reason="An NDA should not restrict who AtliQ may work for.",
            quote=nda.get("non_compete_quote"),
            principle="P2. Mutual NDAs",
            suggested_wording="Delete the non-compete clause.",
            flags=["one_sided_nda"],
        ))

    months = nda.get("non_solicit_months")
    if isinstance(months, (int, float)) and months > config.LONG_NON_SOLICIT_MONTHS:
        findings.append(Finding(
            title=f"One-sided NDA: {months:g}-month non-solicit",
            risk="High",
            reason=f"A non-solicit longer than {config.LONG_NON_SOLICIT_MONTHS} months does not belong in an NDA.",
            quote=nda.get("non_solicit_quote"),
            principle="P2. Mutual NDAs",
            suggested_wording="Delete the non-solicit, or make it mutual and limited to 12 months for staff directly involved.",
            flags=["one_sided_nda"],
        ))
    return findings


# =============================================================================
# Commitments register (FR-18 to FR-23)
# =============================================================================
def load_register(path: Path = config.COMMITMENTS_FILE) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)["entries"]


def save_register(entries: list[dict[str, Any]], path: Path = config.COMMITMENTS_FILE) -> None:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    data["entries"] = entries
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def canonical_role(role: str) -> str | None:
    for pattern, canonical in config.ROLE_PATTERNS:
        if re.search(pattern, role, re.IGNORECASE):
            return canonical
    return None


_RATE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(?:USD|US\$|\$)?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*h(?:ou)?r)?\s*\|", re.IGNORECASE)


def parse_rate_card(text: str) -> dict[str, float]:
    """Hourly rates from markdown rate-card tables, keyed by canonical role."""
    rates: dict[str, float] = {}
    for line in text.splitlines():
        match = _RATE_ROW.match(line.strip())
        if not match:
            continue
        role = canonical_role(match.group(1))
        if role and role not in rates:
            rates[role] = float(match.group(2))
    return rates


def merge_rates(table_rates: dict[str, float], llm_rates: list[dict[str, Any]] | None) -> dict[str, float]:
    rates = dict(table_rates)
    for item in llm_rates or []:
        role = canonical_role(str(item.get("role", "")))
        rate = item.get("rate")
        if role and isinstance(rate, (int, float)) and role not in rates:
            rates[role] = float(rate)
    return rates


@dataclass
class ContractProfile:
    """The facts Step 7 needs, extracted by the LLM and normalised by code."""

    counterparty: str
    atliq_entity: str | None
    industries: set[str]
    services: set[str]
    regions: set[str]
    text: str
    rates: dict[str, float] = field(default_factory=dict)
    scope_quote: str | None = None


@dataclass
class Conflict:
    entry_id: str
    risk: str
    title: str
    reason: str
    new_clause: str | None
    old_clause: str
    source_file: str
    clause: str
    end_date: str | None
    waivers: list[dict[str, Any]]
    waiver_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_line(text: str, terms: list[str]) -> str | None:
    """The contract line that best shows the overlap (most matching terms)."""
    best, best_score = None, 0
    for line in text.splitlines():
        clean = line.strip()
        if len(clean) < 20 or _ATLIQ_ADDRESS.search(clean):
            continue
        score = sum(1 for t in terms if re.search(rf"\b{re.escape(t)}\b", clean, re.IGNORECASE))
        if score > best_score:
            best, best_score = clean, score
    return best[:600] if best else None


def _region_terms(regions: set[str]) -> list[str]:
    terms = []
    for alias, country in config.REGION_ALIASES.items():
        if country in regions and alias not in _CASE_SENSITIVE:
            terms.append(alias)
    return terms + ["GCC", "Territory"]


def _end_date(entry: dict[str, Any]) -> date | None:
    value = entry.get("end_date")
    return date.fromisoformat(value) if value else None


def match_commitments(
    profile: ContractProfile,
    register: list[dict[str, Any]],
    today: date = config.TODAY,
) -> tuple[list[Conflict], dict[str, Any]]:
    """Check a new contract against confirmed register entries (code only).

    Matching follows FR-19, reading condition (b) the way the clauses read: an
    entry that restricts certain services for a certain industry needs BOTH to
    overlap (a non-compete on hotel analytics is not triggered by bank
    analytics). A counterparty match always counts.
    """
    confirmed = [e for e in register if e.get("confirmed_by_human") is True]  # GR-06
    unconfirmed = [e["id"] for e in register if e.get("confirmed_by_human") is not True]
    conflicts: list[Conflict] = []
    notes: list[str] = []

    for entry in confirmed:
        end = _end_date(entry)
        if end and today > end:
            notes.append(f"{entry['id']}: expired {end.isoformat()}")
            continue

        if not entry.get("applies_to_affiliates") and profile.atliq_entity:
            if canonical_entity(profile.atliq_entity) != canonical_entity(entry.get("atliq_entity")):
                notes.append(f"{entry['id']}: binds {entry.get('atliq_entity')} only")
                continue

        old = f"Clause {entry['clause']}: {entry.get('clause_text') or entry['summary']}"
        common = dict(
            entry_id=entry["id"],
            old_clause=old,
            source_file=entry["source_file"],
            clause=entry["clause"],
            end_date=entry.get("end_date"),
            waivers=entry.get("waivers", []),
        )

        # IP already given away: the asset name in the new contract is the trigger.
        if entry.get("type") == "ip_assignment":
            hits = [a for a in entry.get("assets", []) if re.search(rf"\b{re.escape(a)}\b", profile.text, re.IGNORECASE)]
            if hits:
                conflicts.append(Conflict(
                    risk="High",
                    title=f"IP already assigned: {', '.join(hits)} ({entry['id']})",
                    reason=(
                        f"{entry['summary']} This contract uses or grants rights in {', '.join(hits)}, "
                        f"which AtliQ may no longer fully own."
                    ),
                    new_clause=_evidence_line(profile.text, hits + ["grant", "warrant", "owner", "incorporated"]),
                    **common,
                ))
            continue

        region_ok = not entry.get("regions") or bool(profile.regions & set(entry["regions"]))
        industries_ok = not entry.get("industries") or bool(profile.industries & set(entry["industries"]))
        services_ok = not entry.get("services") or bool(profile.services & set(entry["services"]))
        has_criteria = bool(entry.get("industries") or entry.get("services"))
        counterparty_hit = same_counterparty(profile.counterparty, entry.get("counterparty"))
        scope_hit = counterparty_hit or (has_criteria and industries_ok and services_ok)

        if not (scope_hit and region_ok):
            continue

        # Pricing promise: only a lower rate for a similar role is a conflict.
        if entry.get("type") == "pricing_promise":
            protected = entry.get("protected_rates", {})
            lower = [
                (role, profile.rates[role], protected[role])
                for role in protected
                if role in profile.rates and profile.rates[role] < protected[role]
            ]
            if not lower:
                if not profile.rates:
                    notes.append(f"{entry['id']}: pricing promise applies, but no rate card was found to compare")
                continue
            detail = "; ".join(f"{role.title()} ${new:g}/hr vs protected ${old:g}/hr" for role, new, old in lower)
            conflicts.append(Conflict(
                risk="High",
                title=f"Pricing promise broken ({entry['id']})",
                reason=f"{entry['summary']} New rates are lower: {detail}.",
                new_clause=" | ".join(
                    _evidence_line(profile.text, [role]) or role for role, _, _ in lower
                ),
                **common,
            ))
            continue

        overlap_terms = (
            sorted(profile.regions & set(entry.get("regions", [])))
            + sorted(profile.industries & set(entry.get("industries", [])))
        )
        risk, waiver_note = "High", None
        for waiver in entry.get("waivers", []):
            if same_counterparty(waiver.get("counterparty"), profile.counterparty):
                risk = "Medium"
                waiver_note = f"Check waiver scope: the waiver covers \"{waiver['covers']}\"."
                break
        else:
            if entry.get("waivers"):
                covered = "; ".join(w["covers"] for w in entry["waivers"])
                waiver_note = f"Waiver on file does not cover {profile.counterparty}: it covers only \"{covered}\"."

        evidence_terms = _region_terms(profile.regions & set(entry.get("regions", []))) + config.HOSPITALITY_WORDS + ["platform", "lakehouse", "partner"]
        conflicts.append(Conflict(
            risk=risk,
            title=f"{entry['type'].replace('_', ' ').title()} conflict ({entry['id']})",
            reason=(
                f"{entry['summary']} Overlap: {', '.join(overlap_terms) or 'same counterparty'}. "
                f"Runs to {entry.get('end_date') or 'no end date'}."
            ),
            new_clause=profile.scope_quote or _evidence_line(profile.text, evidence_terms),
            waiver_note=waiver_note,
            **common,
        ))

    summary = {
        "register_checked": len(confirmed),
        "unconfirmed": unconfirmed,
        "notes": notes,
    }
    return conflicts, summary


# =============================================================================
# Next step (FR-24, GR-05)
# =============================================================================
SEND_TO_LAWYER = "Send to a lawyer"
REDLINE = "Redline"
ACCEPT = "Accept (after your review)"


def next_step(findings: list[Finding], conflicts: list[Conflict]) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if conflicts:
        reasons.append(f"{len(conflicts)} conflict(s) with promises in signed contracts: "
                       + ", ".join(c.entry_id for c in conflicts) + ".")
    for flag, label in [
        ("baa_missing", "A required BAA is missing."),
        ("unlimited_liability", "Liability is unlimited."),
        ("no_principle", "A risky clause is not covered by any AtliQ principle."),
    ]:
        if any(flag in f.flags for f in findings):
            reasons.append(label)
    if reasons:
        return SEND_TO_LAWYER, reasons

    serious = [f for f in findings if f.risk in {"High", "Medium"}]
    if serious:
        high = sum(1 for f in serious if f.risk == "High")
        return REDLINE, [f"{high} High and {len(serious) - high} Medium finding(s) to negotiate."]

    return ACCEPT, ["No High or Medium findings and no conflicts in the checks run."]
