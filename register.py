"""Rebuild the commitments register from signed contracts (PRD 6.4).

The LLM reads each signed contract's restrictive clauses and PROPOSES entries.
Proposals are saved with confirmed_by_human = false and are never used in
Step 7 (GR-06) until a person ticks "Confirm" in the UI.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import config
import llm
import prompts
import rules

# Only paragraphs that can carry a restriction are sent to the model; this
# keeps a 17-contract rebuild within the free-tier token budget.
_RESTRICTIVE = re.compile(
    r"non-?compet|exclusiv|solicit|no less favou?rable|most.favou?red|lower rates|"
    r"assign|vest in|restrict|shall not (provide|act|engage|offer)|competing",
    re.IGNORECASE,
)


def restrictive_excerpt(text: str, limit: int = 6000) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if _RESTRICTIVE.search(p)]
    return "\n\n".join(paragraphs)[:limit]


def _is_duplicate(entry: dict, existing: list[dict]) -> bool:
    clause = str(entry.get("clause", "")).strip()
    return any(e["source_file"] == entry["source_file"] and str(e["clause"]).strip() == clause for e in existing)


def rebuild(progress: Callable[[str], None] = lambda _: None) -> list[dict]:
    """Propose new entries from every signed contract. Returns the new proposals."""
    register = rules.load_register()
    tracker = rules.load_tracker()
    proposals: list[dict] = []
    next_number = 1 + max(
        [int(m.group(1)) for e in register if (m := re.match(r"P-(\d+)", e["id"]))] or [0]
    )

    files = sorted(config.SIGNED_DIR.glob("*.md"))
    for index, path in enumerate(files, start=1):
        text = path.read_text(encoding="utf-8")
        excerpt = restrictive_excerpt(text)
        if not excerpt:
            continue
        counterparty = next(
            (r["counterparty"] for r in tracker
             if (k := rules.counterparty_key(r["counterparty"]).replace(" ", "_")) and len(k) >= 4 and k in path.name.lower()),
            "",
        )
        progress(f"Reading {path.name} ({index} of {len(files)})")
        try:
            result = llm.invoke_json(
                prompts.REGISTER_SYSTEM,
                prompts.REGISTER_USER.format(name=path.name, counterparty=counterparty or "unknown", text=excerpt),
                config.MAX_TOKENS_REGISTER,
                on_wait=lambda s: progress(f"Waiting {s:.0f}s for the Groq rate limit"),
            )
        except Exception as error:  # one bad file should not stop the rebuild
            progress(f"Skipped {path.name}: {error}")
            continue

        for item in (result or {}).get("entries", []):
            entry = {
                "id": f"P-{next_number:03d}",
                "source_file": path.name,
                "counterparty": counterparty,
                "atliq_entity": rules.canonical_entity(rules.find_line(text, [r"AtliQ\s+(Inc|Technologies)"]) or ""),
                "clause": str(item.get("clause", "")),
                "type": item.get("type", "other"),
                "summary": item.get("summary", ""),
                "clause_text": item.get("clause_text", ""),
                "industries": [t for t in item.get("industries", []) if t in config.INDUSTRY_TAGS],
                "services": [t for t in item.get("services", []) if t in config.SERVICE_TAGS],
                "regions": sorted(rules.normalise_regions(item.get("regions"))),
                "applies_to_affiliates": bool(item.get("applies_to_affiliates")),
                "start_date": None,
                "end_date": item.get("end_date"),
                "waivers": [],
                "confirmed_by_human": False,
                "proposed_by": "Rebuild register (AI suggestion)",
            }
            # A proposed clause_text that is not in the contract is not evidence.
            if entry["clause_text"] and not rules.is_grounded(entry["clause_text"], text):
                entry["clause_text"] = ""
            if _is_duplicate(entry, register + proposals):
                continue
            proposals.append(entry)
            next_number += 1

    if proposals:
        rules.save_register(register + proposals)
    return proposals


def confirm(entry_ids: list[str]) -> int:
    """Mark entries as checked by a person, so Step 7 will use them."""
    register = rules.load_register()
    changed = 0
    for entry in register:
        if entry["id"] in entry_ids and not entry.get("confirmed_by_human"):
            entry["confirmed_by_human"] = True
            changed += 1
    rules.save_register(register)
    return changed
