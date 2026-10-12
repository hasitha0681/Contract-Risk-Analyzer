"""The review pipeline: Steps 2, 4, 6, 7 and 8 (PRD sections 7 and 8).

    Select / upload -> personal-data check -> Step 2 basics (LLM) + entity & BAA rules
    -> Step 4 related documents (retrieval) -> Step 6 clause review (LLM) + grounding,
    proportion & NDA rules -> Step 7 commitments (code) -> Step 8 next step (code)
    + explanation (LLM) -> human decision (logged)

The LLM extracts facts and drafts wording. Every rating, conflict and
suggestion is decided in rules.py.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import llm
import prompts
import rules
from rules import ContractProfile, Finding

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# =============================================================================
# Contract input (FR-01 to FR-04)
# =============================================================================
def list_contracts() -> list[Path]:
    paths = sorted(config.INCOMING_DIR.glob("*.md"))
    if config.TEST_CONTRACTS_DIR.exists():
        paths += sorted(config.TEST_CONTRACTS_DIR.glob("*.md"))
    return paths


class UnreadableFile(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    """Text from an uploaded .md/.txt/.pdf/.docx. Nothing is written to disk."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if len(text.strip()) < 50:
            raise UnreadableFile("This file looks scanned. Text could not be read.")
        return text
    if suffix == ".docx":
        from docx import Document as DocxDocument

        document = DocxDocument(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append("| " + " | ".join(cell.text for cell in row.cells) + " |")
        return "\n".join(parts)
    raise UnreadableFile("Unsupported file type. Use .md, .txt, .pdf or .docx.")


# Patterns of real patient or personal data (FR-03, GR-08). Definitions such as
# "PHI includes dates of birth" are fine; an actual DOB value or SSN is not.
_PERSONAL_PATTERNS = [
    ("US Social Security number", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    ("date of birth value", re.compile(r"\b(?:DOB|D\.O\.B\.?|date of birth)\s*[:=\-]\s*\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}", re.IGNORECASE)),
    ("medical record number", re.compile(r"\bMRN\s*[:#]?\s*\d{5,}", re.IGNORECASE)),
]
_ICD10 = re.compile(r"\b[A-TV-Z]\d{2}\.\d{1,4}\b")


def personal_data_check(text: str) -> list[str]:
    """Names of personal-data patterns found. Any hit blocks the review."""
    hits = [label for label, pattern in _PERSONAL_PATTERNS if pattern.search(text)]
    codes = _ICD10.findall(text)
    if codes and (len(codes) >= 3 or re.search(r"diagnos|\bICD\b", text, re.IGNORECASE)):
        hits.append("diagnosis codes")
    return hits


# =============================================================================
# Audit log (FR-36, FR-37)
# =============================================================================
class Audit:
    """Writes every step to logs/audit.jsonl and keeps this review's lines for the UI."""

    def __init__(self, contract: str):
        self.contract = contract
        self.lines: list[str] = []
        self.records: list[dict[str, Any]] = []

    def log(self, step: str, line: str, **details: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "contract": self.contract,
            "step": step,
            "summary": line,
            **details,
        }
        self.records.append(record)
        self.lines.append(f"[{step}] {line}")
        print(f"[{step}] {line}", flush=True)
        config.LOG_DIR.mkdir(exist_ok=True)
        with config.AUDIT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# =============================================================================
# Step 2: basics (FR-05 to FR-08)
# =============================================================================
BASIC_FIELDS = [
    ("contract_type", "Contract type"),
    ("counterparty_name", "Counterparty"),
    ("counterparty_country", "Counterparty country"),
    ("atliq_entity_named", "AtliQ entity named"),
    ("atliq_role", "AtliQ's role"),
    ("whose_paper", "Whose paper"),
    ("contract_value", "Contract value"),
    ("term_months", "Term (months)"),
    ("healthcare", "Healthcare-related"),
]
NOT_FOUND = "Not found in contract"


def _basics_input(text: str) -> str:
    """Whole contract if it fits the token budget, else the head plus key lines."""
    if len(text) <= config.BASICS_FULL_TEXT_CHARS:
        return text
    head = text[:9000]
    keywords = re.compile(r"fee|value|price|\$|USD|EUR|term|month|liabil|territor|propert|rate|health|patient|HIPAA|non-compet|solicit|exclusiv", re.IGNORECASE)
    rest = [line for line in text[9000:].splitlines() if keywords.search(line)]
    tail = "\n".join(rest)[:5500]
    return f"{head}\n\n[... selected lines from the rest of the contract ...]\n{tail}"


def _ground_basics(basics: dict[str, Any], text: str, audit: Audit) -> None:
    """Drop any quote the contract does not contain (FR-13 applied to Step 2)."""
    dropped = []
    for key, _ in BASIC_FIELDS:
        item = basics.get(key)
        if isinstance(item, dict) and item.get("quote") and not rules.is_grounded(item["quote"], text):
            dropped.append(key)
            item["quote"] = None
    for key in ("liability",):
        item = basics.get(key) or {}
        if item.get("quote") and not rules.is_grounded(item["quote"], text):
            dropped.append(key)
            item["quote"] = None
    nda = basics.get("nda") or {}
    for key in ("obligations_quote", "non_compete_quote", "non_solicit_quote"):
        if nda.get(key) and not rules.is_grounded(nda[key], text):
            dropped.append(f"nda.{key}")
            nda[key] = None
    if basics.get("scope_quote") and not rules.is_grounded(basics["scope_quote"], text):
        dropped.append("scope_quote")
        basics["scope_quote"] = None
    if dropped:
        audit.log("Step 2", f"quotes dropped (not found in contract): {', '.join(dropped)}", dropped=dropped)


def field_value(basics: dict[str, Any], key: str) -> Any:
    item = basics.get(key)
    if isinstance(item, dict):
        return item.get("value")
    return item


def extract_basics(name: str, text: str, audit: Audit, progress: Progress = _noop) -> dict[str, Any]:
    progress("Step 2: reading the basics")
    basics = llm.invoke_json(
        prompts.BASICS_SYSTEM,
        prompts.BASICS_USER.format(name=name, text=_basics_input(text)),
        config.MAX_TOKENS_BASICS,
        on_wait=lambda s: progress(f"Step 2: waiting {s:.0f}s for the Groq rate limit"),
    )
    if not isinstance(basics, dict):
        raise ValueError("The model returned basics in an unexpected shape.")
    _ground_basics(basics, text, audit)
    audit.log("Step 2", "basics extracted", inputs=[name],
              outputs={k: field_value(basics, k) for k, _ in BASIC_FIELDS})
    return basics


def apply_corrections(basics: dict[str, Any], corrections: dict[str, Any], audit: Audit) -> None:
    """User edits to the basics card (FR-08). Every change is logged."""
    changed = {}
    for key, new in corrections.items():
        if isinstance(new, float) and new.is_integer():
            new = int(new)
        old = field_value(basics, key)
        if str(old if old is not None else "") == str(new if new is not None else ""):
            continue
        item = basics.setdefault(key, {})
        if not isinstance(item, dict):
            item = basics[key] = {}
        item["value"] = new
        item["quote"] = None
        item["corrected_by_user"] = True
        changed[key] = {"from": old, "to": new}
    if changed:
        audit.log("User", f"corrected basics: {', '.join(changed)}", corrections=changed)


def basics_rules(basics: dict[str, Any], text: str, tracker, audit: Audit) -> tuple[list[Finding], dict[str, str]]:
    """Entity rule and BAA rule (FR-06, FR-07). Code, not LLM."""
    findings: list[Finding] = []
    entity_quote = (basics.get("atliq_entity_named") or {}).get("quote") or rules.find_line(text, [r"AtliQ (Inc|Technologies)"])
    entity_status, entity_finding = rules.entity_rule(
        field_value(basics, "counterparty_country"),
        field_value(basics, "atliq_entity_named"),
        field_value(basics, "atliq_role"),
        entity_quote,
    )
    if entity_finding:
        findings.append(entity_finding)

    healthcare_quote = (basics.get("healthcare") or {}).get("quote") or rules.find_line(
        text, [r"HIPAA", r"patient", r"health record", r"Health System", r"\bhealth"]
    )
    baa_status, baa_findings, parties = rules.baa_rule(
        field_value(basics, "counterparty_name") or "",
        bool(field_value(basics, "healthcare")),
        tracker,
        healthcare_quote,
    )
    findings += baa_findings
    audit.log("Step 2", f"entity_rule={entity_status}; baa_rule={baa_status}",
              outputs={"entity_rule": entity_status, "baa_rule": baa_status, "baa_parties_checked": parties})
    return findings, {"entity_rule": entity_status, "baa_rule": baa_status, "baa_parties": ", ".join(parties)}


# =============================================================================
# Step 4: related contracts and history (FR-09 to FR-11)
# =============================================================================
def find_related(basics: dict[str, Any], tracker, audit: Audit, progress: Progress = _noop) -> dict[str, Any]:
    from ingest import get_store

    progress("Step 4: finding related contracts and history")
    counterparty = field_value(basics, "counterparty_name") or ""
    regions = rules.normalise_regions(basics.get("regions"))
    query = " ".join(str(x) for x in [
        field_value(basics, "contract_type"), counterparty,
        " ".join(basics.get("industries") or []), " ".join(basics.get("services") or []),
        " ".join(regions), basics.get("scope_quote") or "",
    ])

    related: dict[str, dict[str, Any]] = {}

    def add(file: str, reason: str, excerpt: str, section: str = "") -> None:
        entry = related.setdefault(file, {"file": file, "reasons": [], "excerpt": excerpt, "section": section})
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    key = rules.counterparty_key(counterparty).replace(" ", "_")
    if key:
        for path in sorted(config.SIGNED_DIR.glob("*.md")):
            if key in path.name.lower():
                add(path.name, "same counterparty", path.read_text(encoding="utf-8")[:300].strip())

    for name in (config.COLLECTION_SIGNED, config.COLLECTION_HISTORY):
        for doc in get_store(name).similarity_search(query, k=config.TOP_K):
            meta = doc.metadata
            if rules.same_counterparty(meta.get("counterparty"), counterparty):
                reason = "same counterparty"
            elif meta.get("source_type") in {"negotiation_note", "meeting_note"}:
                reason = "past negotiation"
            elif regions & rules.regions_in_text(doc.page_content):
                reason = "same region"
            elif "hospitality" in (basics.get("industries") or []) and rules.mentions_hospitality(doc.page_content):
                reason = "same industry"
            else:
                reason = "similar clauses"
            label = meta["source_file"]
            if meta.get("source_type") == "negotiation_note":
                label = f"{meta['source_file']} ({meta.get('section', '')})"
            add(label, reason, doc.page_content[:300].strip(), meta.get("section", ""))

    tracker_rows = [r for r in tracker if rules.same_counterparty(r["counterparty"], counterparty)]
    missing = rules.expected_but_missing(counterparty, tracker) if counterparty else []

    reason_counts: dict[str, int] = {}
    for item in related.values():
        for reason in item["reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    audit.log("Step 4", f"related={len(related)} ({', '.join(f'{k}={v}' for k, v in reason_counts.items())}); expected_not_found={len(missing)}",
              inputs=list(related), outputs={"related": len(related), "missing": missing})
    return {"related": list(related.values()), "tracker_rows": tracker_rows, "missing": missing}


def history_context(basics: dict[str, Any], limit_chars: int = 2500) -> str:
    """Past negotiations relevant to this contract, for Steps 6 and 8."""
    from ingest import get_store

    query = f"{field_value(basics, 'counterparty_name')} {field_value(basics, 'contract_type')} liability liquidated damages payment indemnity non-compete"
    parts, total = [], 0
    for doc in get_store(config.COLLECTION_HISTORY).similarity_search(query, k=config.TOP_K):
        piece = f"[{doc.metadata['source_file']} | {doc.metadata.get('section', '')}]\n{doc.page_content}"
        if total + len(piece) > limit_chars:
            break
        parts.append(piece)
        total += len(piece)
    return "\n\n".join(parts) or "(none found)"


# =============================================================================
# Step 6: clause-by-clause review (FR-12 to FR-17)
# =============================================================================
def split_for_review(text: str, limit: int = config.REVIEW_CHUNK_CHARS) -> list[str]:
    """Split on section headings into excerpts that fit one paced LLM call."""
    sections = re.split(r"\n(?=#{1,3} )", text)
    chunks, current = [], ""
    for section in sections:
        while len(section) > limit:
            cut = section.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(section[:cut])
            section = section[cut:]
        if len(current) + len(section) > limit and current:
            chunks.append(current)
            current = ""
        current += ("\n" if current else "") + section
    if current.strip():
        chunks.append(current)
    return chunks


def review_clauses(
    name: str, text: str, basics: dict[str, Any], history: str, audit: Audit, progress: Progress = _noop
) -> tuple[list[Finding], list[dict[str, Any]], list[str]]:
    principles = config.PRINCIPLES_FILE.read_text(encoding="utf-8")
    system = prompts.REVIEW_SYSTEM.format(
        principles=principles, role=field_value(basics, "atliq_role") or "unknown", history=history
    )
    chunks = split_for_review(text)
    findings: list[Finding] = []
    dropped: list[dict[str, Any]] = []
    unreviewed: list[str] = []
    seen_quotes: set[str] = set()

    for index, chunk in enumerate(chunks, start=1):
        progress(f"Step 6: reviewing clauses (part {index} of {len(chunks)})")
        try:
            result = llm.invoke_json(
                system,
                prompts.REVIEW_USER.format(name=name, part=index, parts=len(chunks), text=chunk),
                config.MAX_TOKENS_REVIEW,
                on_wait=lambda s, i=index: progress(f"Step 6: part {i} of {len(chunks)}, waiting {s:.0f}s for the Groq rate limit"),
            )
        except llm.MissingKeyError:
            raise
        except Exception as error:
            # One unreadable answer must not sink the review; the part is
            # flagged for a person to read instead.
            first_line = chunk.strip().splitlines()[0][:80] if chunk.strip() else ""
            unreviewed.append(f"part {index} of {len(chunks)} (starts: {first_line})")
            audit.log("Step 6", f"part {index} not reviewed: {error}", error=str(error))
            continue
        if isinstance(result, dict) and result.get("truncated"):
            audit.log("Step 6", f"part {index}: answer was cut off; kept {len(result.get('findings', []))} complete finding(s)")
        items = result.get("findings", []) if isinstance(result, dict) else result
        for item in items or []:
            if not isinstance(item, dict):
                continue
            quote = (item.get("quote") or "").strip()
            position = rules.quote_position(quote, text)
            if position is None:   # FR-13, GR-02
                dropped.append({"clause": item.get("clause"), "title": item.get("title"), "quote": quote, "why": "quote not found"})
                continue
            key = rules.normalise(quote)
            if key in seen_quotes:
                continue
            seen_quotes.add(key)

            risk = str(item.get("risk") or "").strip().title()
            if risk.lower().startswith("needs"):
                risk = "Needs human reading"
            if risk not in rules.RISK_ORDER:
                risk = "Needs human reading"
            principle = item.get("principle") or "No principle covers this"
            flags = []
            if "no principle" in principle.lower() and risk in {"High", "Medium"}:
                flags.append("no_principle")
            past = item.get("past_reference")
            if isinstance(past, str) and past.strip().lower() in {"", "null", "none", "n/a"}:
                past = None

            findings.append(Finding(
                title=item.get("title") or "Clause",
                risk=risk,
                reason=item.get("reason") or "",
                quote=quote,
                clause=str(item.get("clause") or "") or None,
                principle=principle,
                suggested_wording=item.get("suggested_wording"),
                past_reference=past,
                source="ai",
                flags=flags,
                position=position,
            ))
    for item in dropped:
        audit.log("Step 6", f"dropped: quote not found ({item.get('clause')} {item.get('title')})", dropped=item)
    return findings, dropped, unreviewed


def code_findings(basics: dict[str, Any], text: str, audit: Audit) -> tuple[list[Finding], str]:
    """Proportion rule and NDA check (FR-14, FR-15)."""
    findings: list[Finding] = []
    value = basics.get("contract_value") or {}
    status, finding = rules.proportion_rule(
        field_value(basics, "contract_type"),
        basics.get("liability"),
        value.get("value") if isinstance(value, dict) else None,
        value.get("currency") if isinstance(value, dict) else None,
    )
    if finding:
        findings.append(finding)
    findings += rules.nda_rule(field_value(basics, "contract_type"), basics.get("nda"))
    return findings, status


def _place(findings: list[Finding], text: str) -> list[Finding]:
    """Give rule findings a document position and drop any without a real quote."""
    placed = []
    for f in findings:
        position = rules.quote_position(f.quote, text) if f.quote else None
        if position is None and f.quote:
            f.quote = None
        f.position = position if position is not None else -1   # rule findings first within a level
        placed.append(f)
    return placed


# =============================================================================
# Step 7: past commitments (FR-18 to FR-23)
# =============================================================================
def build_profile(basics: dict[str, Any], text: str) -> ContractProfile:
    industries = {t for t in basics.get("industries") or [] if t in config.INDUSTRY_TAGS}
    if rules.mentions_hospitality(text):
        industries.add("hospitality")
    services = {t for t in basics.get("services") or [] if t in config.SERVICE_TAGS}
    regions = rules.normalise_regions(basics.get("regions")) | rules.regions_in_text(text)
    country = rules.normalise_country(field_value(basics, "counterparty_country"))
    if country:
        regions.add(country)
    rates = rules.merge_rates(rules.parse_rate_card(text), basics.get("rates"))
    return ContractProfile(
        counterparty=field_value(basics, "counterparty_name") or "",
        atliq_entity=field_value(basics, "atliq_entity_named"),
        industries=industries,
        services=services,
        regions=regions,
        text=text,
        rates=rates,
        scope_quote=basics.get("scope_quote"),
    )


# =============================================================================
# Step 8: next step, explanation, redlines, lawyer pack (FR-24 to FR-28)
# =============================================================================
_UNSAFE_WORDS = re.compile(r"\b(safe|safely|is legal|legally sound|enforceable)\b", re.IGNORECASE)


def explain(name, suggestion, reasons, findings, conflicts, history, progress: Progress = _noop) -> dict[str, Any]:
    progress("Step 8: writing the explanation")
    finding_lines = "\n".join(f"- [{f.risk}] {f.title} (clause {f.clause or '-'}): {f.reason}" for f in findings) or "(none)"
    conflict_lines = "\n".join(f"- [{c.risk}] {c.title}: {c.reason} {c.waiver_note or ''}" for c in conflicts) or "(none)"
    try:
        result = llm.invoke_json(
            prompts.EXPLAIN_SYSTEM,
            prompts.EXPLAIN_USER.format(name=name, suggestion=suggestion, reasons=" ".join(reasons),
                                        findings=finding_lines[:5000], conflicts=conflict_lines[:3000], history=history),
            config.MAX_TOKENS_EXPLAIN,
            on_wait=lambda s: progress(f"Step 8: waiting {s:.0f}s for the Groq rate limit"),
        )
    except Exception:
        result = {}
    explanation = (result or {}).get("explanation") or " ".join(reasons)
    words = explanation.split()
    if len(words) > 130:
        explanation = " ".join(words[:120]) + " ..."
    if _UNSAFE_WORDS.search(explanation):   # GR-04
        explanation = " ".join(reasons)
    questions = [q for q in (result or {}).get("lawyer_questions") or [] if isinstance(q, str)][:5]
    return {"explanation": explanation, "lawyer_questions": questions}


def redlines(findings: list[Finding]) -> list[dict[str, str]]:
    return [
        {"clause": f.clause or "-", "title": f.title, "current": f.quote or "", "suggested": f.suggested_wording or ""}
        for f in findings
        if f.risk in {"High", "Medium"} and f.suggested_wording
    ]


def lawyer_pack(result: "ReviewResult") -> str:
    """Markdown pack for outside counsel (FR-27)."""
    b = result.basics
    lines = [
        f"# Lawyer pack: {result.contract}",
        "",
        f"*Prepared by the AtliQ Contract Risk Analyzer on {config.TODAY.isoformat()}. AI-assisted summary for counsel; not legal advice.*",
        "",
        "## Basics",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for key, label in BASIC_FIELDS:
        value = field_value(b, key)
        lines.append(f"| {label} | {value if value not in (None, '') else NOT_FOUND} |")
    lines += ["", f"**AI suggestion:** {result.suggestion}", "", " ".join(result.reasons), ""]

    lines += ["## Conflicts with promises in signed contracts", ""]
    if result.conflicts:
        for c in result.conflicts:
            lines += [
                f"### {c.title} - {c.risk}",
                f"- Source: `{c.source_file}` clause {c.clause}; ends {c.end_date or 'no end date'}",
                f"- Old clause: {c.old_clause}",
                f"- New contract: {c.new_clause or '(see contract)'}",
                f"- {c.reason}",
            ]
            if c.waiver_note:
                lines.append(f"- Waiver: {c.waiver_note}")
            lines.append("")
    else:
        lines += [f"No conflict found in {result.commitment_summary.get('register_checked', 0)} confirmed register entries.", ""]

    lines += ["## Findings (serious first)", ""]
    for f in result.findings:
        lines.append(f"- **[{f.risk}] {f.title}** (clause {f.clause or '-'}; {f.principle or ''})")
        if f.quote:
            lines.append(f"  > {f.quote}")
        lines.append(f"  {f.reason}")
    lines += ["", "## Related signed contracts", ""]
    for r in result.related.get("related", []):
        lines.append(f"- `{r['file']}` ({', '.join(r['reasons'])})")
    lines += ["", "## Questions for counsel", ""]
    for i, q in enumerate(result.explanation.get("lawyer_questions") or [], start=1):
        lines.append(f"{i}. {q}")
    return "\n".join(lines) + "\n"


# =============================================================================
# The whole review
# =============================================================================
@dataclass
class ReviewResult:
    contract: str
    text: str
    basics: dict[str, Any]
    rule_status: dict[str, str] = field(default_factory=dict)
    related: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[rules.Conflict] = field(default_factory=list)
    commitment_summary: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    reasons: list[str] = field(default_factory=list)
    explanation: dict[str, Any] = field(default_factory=dict)
    checks_run: list[str] = field(default_factory=list)
    unreviewed: list[str] = field(default_factory=list)


def run_basics(name: str, text: str, audit: Audit, progress: Progress = _noop) -> dict[str, Any]:
    audit.log("Input", f"contract={name}", inputs=[name])
    return extract_basics(name, text, audit, progress)


def run_rest(name: str, text: str, basics: dict[str, Any], audit: Audit, progress: Progress = _noop) -> ReviewResult:
    """Steps 2 (rules) through 8, after the user has confirmed the basics."""
    tracker = rules.load_tracker()
    result = ReviewResult(contract=name, text=text, basics=basics)

    rule_findings, result.rule_status = basics_rules(basics, text, tracker, audit)

    result.related = find_related(basics, tracker, audit, progress)
    history = history_context(basics)

    ai_findings, result.dropped, result.unreviewed = review_clauses(name, text, basics, history, audit, progress)
    extra, proportion_status = code_findings(basics, text, audit)
    result.rule_status["proportion_rule"] = proportion_status
    result.findings = rules.sort_findings(_place(rule_findings + extra, text) + ai_findings)
    counts = {r: sum(1 for f in result.findings if f.risk == r) for r in rules.RISK_ORDER}
    audit.log("Step 6", f"findings={len(result.findings)} (high={counts['High']}, medium={counts['Medium']}, low={counts['Low']}, needs_reading={counts['Needs human reading']}); dropped_ungrounded={len(result.dropped)}; proportion_rule={proportion_status}",
              outputs={"findings": counts, "dropped": len(result.dropped)})

    progress("Step 7: checking past commitments")
    profile = build_profile(basics, text)
    result.conflicts, result.commitment_summary = rules.match_commitments(profile, rules.load_register())
    audit.log("Step 7", f"register_checked={result.commitment_summary['register_checked']}; conflicts={len(result.conflicts)}"
              + (f" ({', '.join(c.entry_id for c in result.conflicts)})" if result.conflicts else ""),
              inputs=[config.COMMITMENTS_FILE.name],
              outputs={"profile": {"industries": sorted(profile.industries), "services": sorted(profile.services),
                                   "regions": sorted(profile.regions), "rates": profile.rates},
                       "conflicts": [c.entry_id for c in result.conflicts],
                       "notes": result.commitment_summary["notes"]})

    result.suggestion, result.reasons = rules.next_step(result.findings, result.conflicts)
    if result.unreviewed and result.suggestion == rules.ACCEPT:
        # An unread part can hide anything; a clean result is not earned.
        result.suggestion = rules.REDLINE
        result.reasons = [f"{len(result.unreviewed)} part(s) of the contract could not be reviewed by the AI and need human reading."]
    audit.log("Step 8", f"suggestion={result.suggestion}", outputs={"suggestion": result.suggestion, "reasons": result.reasons})
    result.explanation = explain(name, result.suggestion, result.reasons, result.findings, result.conflicts, history, progress)

    result.checks_run = [
        f"Entity rule ({result.rule_status.get('entity_rule')})",
        f"BAA rule ({result.rule_status.get('baa_rule')})",
        f"Proportion rule ({proportion_status})",
        "NDA check" + (" (applied)" if "nda" in str(field_value(basics, "contract_type")).lower() else " (not an NDA)"),
        f"Clause review against 8 principles ({len(split_for_review(text))} part(s))",
        f"Past commitments ({result.commitment_summary['register_checked']} confirmed entries)",
    ]
    progress("Review complete")
    return result


def record_decision(contract: str, suggestion: str, decision: str, reason: str, audit: Audit | None = None) -> None:
    """Save a human decision (FR-29 to FR-31). Nothing is sent or signed."""
    config.LOG_DIR.mkdir(exist_ok=True)
    new_file = not config.DECISIONS_CSV.exists()
    with config.DECISIONS_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["date", "contract", "ai_suggestion", "user_decision", "reason"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), contract, suggestion, decision, reason])
    if audit:
        audit.log("User", f"decision={decision}", outputs={"ai_suggestion": suggestion, "decision": decision, "reason": reason})
