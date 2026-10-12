"""Run the PRD's demonstration scenarios end to end and check the outcomes.

    python scenarios.py            # all review scenarios (1-9)
    python scenarios.py 1 6        # just these

Uses the live LLM, so it is paced by the Groq free-tier token budget; a full
run takes several minutes. Scenario 10 (Q&A) is in qa_scenarios().
"""

from __future__ import annotations

import sys
import time

import config
import review
import rules

SCENARIOS = {
    1: ("incoming/2026-09-18_gulf_crown_hotels_msa_draft.md", {"conflicts": {"R-001"}, "suggestion": rules.SEND_TO_LAWYER, "waiver_not_covering": True}),
    2: ("incoming/2026-09-15_travelhub_services_agreement_draft.md", {"conflicts": {"R-001"}, "suggestion": rules.SEND_TO_LAWYER, "flags": {"wrong_entity"}}),
    3: ("incoming/2026-09-21_blueorchid_hotels_pilot_agreement_draft.md", {"conflicts": {"R-001"}, "suggestion": rules.SEND_TO_LAWYER, "waiver_not_covering": True}),
    4: ("incoming/2026-09-24_datavane_strategic_partnership_agreement_draft.md", {"conflicts": {"R-003"}, "suggestion": rules.SEND_TO_LAWYER}),
    5: ("incoming/2026-09-19_lakeshore_grocers_msa_draft.md", {"conflicts": {"R-004"}, "suggestion": rules.SEND_TO_LAWYER}),
    6: ("incoming/2026-09-25_finserve_capital_mutual_nda_draft.md", {"conflicts": set(), "suggestion": rules.REDLINE, "flags": {"one_sided_nda"}}),
    7: ("incoming/2026-09-27_loopmart_mutual_nda_draft.md", {"conflicts": set(), "suggestion": rules.ACCEPT, "no_high": True}),
    8: ("incoming/2026-09-10_harrington_health_msa_draft.md", {"suggestion": rules.SEND_TO_LAWYER, "flags": {"baa_missing"}, "baa_names": {"Harrington", "Daniel Ortiz"}}),
    80: ("incoming/2026-09-27_daniel_ortiz_contractor_agreement_draft.md", {"suggestion": rules.SEND_TO_LAWYER, "flags": {"baa_missing"}, "baa_names": {"Daniel Ortiz"}}),
    9: ("test_contracts/2026-10-01_nimbus_analytics_services_draft.md", {"conflicts": set(), "suggestion": rules.REDLINE, "title": "Liability out of proportion"}),
}


def run(number: int) -> bool:
    relative, expected = SCENARIOS[number]
    path = config.DATA_DIR / relative
    text = path.read_text(encoding="utf-8")
    audit = review.Audit(path.name)
    started = time.monotonic()
    basics = review.run_basics(path.name, text, audit, progress=lambda m: print("   ..", m, flush=True))
    result = review.run_rest(path.name, text, basics, audit, progress=lambda m: print("   ..", m, flush=True))
    elapsed = time.monotonic() - started

    checks: list[tuple[str, bool]] = []
    flags = {flag for f in result.findings for flag in f.flags}
    conflict_ids = {c.entry_id for c in result.conflicts}
    if "conflicts" in expected:
        checks.append((f"conflicts {sorted(conflict_ids)} == {sorted(expected['conflicts'])}", conflict_ids == expected["conflicts"]))
    checks.append((f"suggestion '{result.suggestion}'", result.suggestion == expected["suggestion"]))
    for flag in expected.get("flags", set()):
        checks.append((f"flag {flag}", flag in flags))
    if expected.get("waiver_not_covering"):
        checks.append(("waiver shown, does not cover", any("does not cover" in (c.waiver_note or "") for c in result.conflicts)))
    if expected.get("no_high"):
        checks.append(("no High findings", not any(f.risk == "High" for f in result.findings)))
    for name in expected.get("baa_names", set()):
        checks.append((f"BAA missing for {name}", any(name in f.title for f in result.findings if "baa_missing" in f.flags)))
    if "title" in expected:
        hit = next((f for f in result.findings if f.title == expected["title"]), None)
        checks.append((f"{expected['title']}: {hit.reason if hit else 'missing'}", hit is not None and hit.risk == "High"))
    checks.append(("all quotes grounded", all(f.quote is None or rules.is_grounded(f.quote, text) for f in result.findings)))
    checks.append(("never says safe", "safe" not in result.explanation.get("explanation", "").lower().split()))

    print(f"\nScenario {number}: {path.name}  ({elapsed:.0f}s)")
    print(f"   basics: {[review.field_value(basics, k) for k, _ in review.BASIC_FIELDS]}")
    for f in result.findings:
        print(f"   [{f.risk:<6}] {f.title} (cl. {f.clause or '-'}) {'/'.join(f.flags)}")
    for c in result.conflicts:
        print(f"   CONFLICT [{c.risk}] {c.title} | {c.waiver_note or ''}")
    print(f"   dropped ungrounded: {len(result.dropped)}; explanation: {result.explanation.get('explanation', '')[:200]}")
    ok = True
    for label, passed in checks:
        print(f"   {'PASS' if passed else 'FAIL'}  {label}")
        ok &= passed
    return ok


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    wanted = [int(a) for a in sys.argv[1:]] or list(SCENARIOS)
    results = {n: run(n) for n in wanted}
    print("\nSUMMARY: " + ", ".join(f"S{n}={'PASS' if ok else 'FAIL'}" for n, ok in results.items()))


if __name__ == "__main__":
    main()
