"""Unit tests for the deterministic rules (PRD section 15, step 4).

    python -m unittest discover -s tests -v

These run without the LLM or the vector store: every rule is plain code.
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import rules  # noqa: E402
from rules import ContractProfile  # noqa: E402

TRACKER = rules.load_tracker()
REGISTER = rules.load_register()


def read(folder: Path, name: str) -> str:
    return (folder / name).read_text(encoding="utf-8")


def profile(counterparty, entity, industries, services, regions, text="", rates=None):
    return ContractProfile(
        counterparty=counterparty,
        atliq_entity=entity,
        industries=set(industries),
        services=set(services),
        regions=set(regions),
        text=text,
        rates=rates or {},
    )


class GroundingTests(unittest.TestCase):
    TEXT = "12.1 The **Supplier** shall not  provide data analytics\nservices to any Hospitality Business in the GCC."

    def test_exact_quote_with_markdown_and_whitespace(self):
        self.assertTrue(rules.is_grounded("the Supplier shall not provide data analytics services", self.TEXT))

    def test_quote_with_ellipsis(self):
        self.assertTrue(rules.is_grounded("The Supplier shall not ... Hospitality Business in the GCC", self.TEXT))

    def test_paraphrase_is_rejected(self):
        self.assertFalse(rules.is_grounded("The supplier may not work for hotels in the Gulf", self.TEXT))

    def test_tiny_fragment_is_rejected(self):
        self.assertFalse(rules.is_grounded("the GCC", self.TEXT))


class EntityRuleTests(unittest.TestCase):
    def test_travelhub_dubai_with_atliq_inc_is_wrong(self):
        status, finding = rules.entity_rule("United Arab Emirates", "AtliQ Inc", "supplier", "AtliQ Inc, a Delaware corporation")
        self.assertEqual(status, "mismatch")
        self.assertEqual(finding.risk, "High")
        self.assertIn(config.ENTITY_ROW, finding.reason)

    def test_us_client_with_atliq_inc_is_ok(self):
        self.assertEqual(rules.entity_rule("USA", "AtliQ Inc", "supplier", None)[0], "ok")

    def test_us_state_counts_as_usa(self):
        self.assertEqual(rules.entity_rule("Texas, USA", "AtliQ Inc", "supplier", None)[0], "ok")

    def test_india_client_with_pvt_ltd_is_ok(self):
        self.assertEqual(rules.entity_rule("India", "AtliQ Technologies Pvt Ltd", "nda_party", None)[0], "ok")

    def test_us_freelancer_on_india_template_is_wrong(self):
        status, _ = rules.entity_rule("USA", "AtliQ Technologies Pvt Ltd", "buyer", None)
        self.assertEqual(status, "mismatch")

    def test_partnership_is_not_a_client_contract(self):
        self.assertEqual(rules.entity_rule("USA", "AtliQ Technologies Pvt Ltd", "partner", None)[0], "not_applied_partnership")


class BaaRuleTests(unittest.TestCase):
    def test_harrington_client_and_linked_freelancer_are_missing(self):
        status, findings, parties = rules.baa_rule("Harrington Health Systems Inc", True, TRACKER, "HIPAA")
        self.assertEqual(status, "baa_missing")
        names = " ".join(f.title for f in findings)
        self.assertIn("Harrington", names)
        self.assertIn("Daniel Ortiz", names)
        self.assertTrue(all("baa_missing" in f.flags for f in findings))

    def test_daniel_ortiz_is_healthcare_via_tracker_even_without_llm_flag(self):
        status, findings, _ = rules.baa_rule("Daniel Ortiz", False, TRACKER, None)
        self.assertEqual(status, "baa_missing")
        self.assertTrue(any("Daniel Ortiz" in f.title for f in findings))

    def test_carebridge_has_signed_baa(self):
        self.assertTrue(rules.has_signed_baa("CareBridge Clinics Inc", TRACKER))

    def test_non_healthcare_is_skipped(self):
        self.assertEqual(rules.baa_rule("LoopMart", False, TRACKER, None)[0], "not_healthcare")


class ProportionRuleTests(unittest.TestCase):
    def test_nimbus_500k_cap_on_24k_contract(self):
        status, finding = rules.proportion_rule(
            "Services Agreement",
            {"type": "capped_amount", "amount": 500000, "currency": "USD", "quote": "q"},
            24000,
            "USD",
        )
        self.assertEqual(status, "out_of_proportion")
        self.assertEqual(finding.risk, "High")
        self.assertIn("20.8x", finding.reason)

    def test_cap_at_contract_value_is_ok(self):
        status, finding = rules.proportion_rule("MSA", {"type": "multiple_of_fees", "multiple": 1}, 140000, "USD")
        self.assertEqual((status, finding), ("ok", None))

    def test_unlimited_is_high_and_sends_to_lawyer(self):
        _, finding = rules.proportion_rule("MSA", {"type": "unlimited", "quote": "q"}, 210000, "USD")
        self.assertEqual(finding.risk, "High")
        self.assertIn("unlimited_liability", finding.flags)

    def test_missing_numbers_is_medium(self):
        _, finding = rules.proportion_rule("MSA", {"type": "not_found"}, None, None)
        self.assertEqual(finding.risk, "Medium")

    def test_nda_is_not_applicable(self):
        self.assertEqual(rules.proportion_rule("Mutual NDA", None, None, None), ("not_applicable_nda", None))


class NdaRuleTests(unittest.TestCase):
    def test_finserve_pattern(self):
        findings = rules.nda_rule("Mutual NDA", {
            "obligations_bind": "one_party", "obligations_quote": "a",
            "non_compete": True, "non_compete_quote": "b",
            "non_solicit_months": 24, "non_solicit_quote": "c",
        })
        self.assertEqual(len(findings), 3)
        self.assertTrue(all(f.risk == "High" for f in findings))

    def test_clean_mutual_nda(self):
        self.assertEqual(rules.nda_rule("Mutual NDA", {"obligations_bind": "both", "non_compete": False, "non_solicit_months": None}), [])

    def test_twelve_month_non_solicit_is_not_long(self):
        self.assertEqual(rules.nda_rule("NDA", {"obligations_bind": "both", "non_solicit_months": 12}), [])


class CommitmentTests(unittest.TestCase):
    def test_gulf_crown_conflicts_with_r001_and_waiver_does_not_cover(self):
        conflicts, summary = rules.match_commitments(
            profile("Gulf Crown Hotels & Resorts Co.", "AtliQ Technologies Pvt Ltd",
                    ["hospitality"], ["revenue_management", "data_analytics"], ["Saudi Arabia"]),
            REGISTER,
        )
        self.assertEqual([c.entry_id for c in conflicts], ["R-001"])
        self.assertEqual(conflicts[0].risk, "High")
        self.assertIn("does not cover", conflicts[0].waiver_note)
        self.assertEqual(summary["register_checked"], 5)

    def test_seaside_waiver_downgrades_to_medium(self):
        conflicts, _ = rules.match_commitments(
            profile("Seaside Hotels LLC", "AtliQ Technologies Pvt Ltd", ["hospitality"], ["data_analytics"], ["Oman"]),
            REGISTER,
        )
        self.assertEqual(conflicts[0].risk, "Medium")
        self.assertIn("Check waiver scope", conflicts[0].waiver_note)

    def test_r001_applies_to_affiliates_so_atliq_inc_is_caught(self):
        conflicts, _ = rules.match_commitments(
            profile("TravelHub FZ-LLC", "AtliQ Inc", ["travel", "hospitality"], ["artificial_intelligence"], ["UAE", "Saudi Arabia"]),
            REGISTER,
        )
        self.assertIn("R-001", [c.entry_id for c in conflicts])

    def test_hotels_outside_gcc_do_not_conflict(self):
        conflicts, _ = rules.match_commitments(
            profile("Some Hotels", "AtliQ Technologies Pvt Ltd", ["hospitality"], ["data_analytics"], ["India"]),
            REGISTER,
        )
        self.assertEqual(conflicts, [])

    def test_gcc_bank_analytics_is_not_a_hotel_conflict(self):
        conflicts, _ = rules.match_commitments(
            profile("Gulf Bank", "AtliQ Technologies Pvt Ltd", ["financial_services"], ["data_analytics"], ["UAE"]),
            REGISTER,
        )
        self.assertEqual(conflicts, [])

    def test_datavane_conflicts_with_cloudspan_exclusivity(self):
        conflicts, _ = rules.match_commitments(
            profile("Datavane Inc", "AtliQ Technologies Pvt Ltd", ["cloud_data_platform"], ["platform_partnership"], ["India", "UAE", "Germany"]),
            REGISTER,
        )
        self.assertEqual([c.entry_id for c in conflicts], ["R-003"])

    def test_lakeshore_rates_break_crestline_mfn(self):
        text = read(config.INCOMING_DIR, "2026-09-19_lakeshore_grocers_msa_draft.md")
        rates = rules.parse_rate_card(text)
        self.assertEqual(rates, {"senior data engineer": 72.0, "data engineer": 55.0, "bi developer": 50.0})
        conflicts, _ = rules.match_commitments(
            profile("Lakeshore Grocers Inc.", "AtliQ Inc", ["grocery", "retail"], ["data_engineering", "business_intelligence"], ["USA"], text, rates),
            REGISTER,
        )
        self.assertEqual([c.entry_id for c in conflicts], ["R-004"])
        self.assertIn("$72/hr vs protected $85/hr", conflicts[0].reason)

    def test_equal_or_higher_rates_are_fine(self):
        conflicts, _ = rules.match_commitments(
            profile("X Corp", "AtliQ Inc", ["retail"], ["data_engineering"], ["USA"], "", {"senior data engineer": 90}),
            REGISTER,
        )
        self.assertEqual(conflicts, [])

    def test_rheinwerk_pipekit_conflicts_with_northwind_ip(self):
        text = read(config.INCOMING_DIR, "2026-09-23_rheinwerk_analytics_services_agreement_draft.md")
        conflicts, _ = rules.match_commitments(
            profile("Rheinwerk Analytics GmbH", "AtliQ Technologies Pvt Ltd", ["technology"], ["data_engineering"], ["Germany"], text),
            REGISTER,
        )
        self.assertEqual([c.entry_id for c in conflicts], ["R-005"])
        self.assertIn("PipeKit", conflicts[0].new_clause)

    def test_unconfirmed_entries_are_never_used(self):
        register = [dict(e) for e in REGISTER]
        for entry in register:
            entry["confirmed_by_human"] = False
        conflicts, summary = rules.match_commitments(
            profile("Gulf Crown Hotels", "AtliQ Technologies Pvt Ltd", ["hospitality"], ["data_analytics"], ["Saudi Arabia"]),
            register,
        )
        self.assertEqual(conflicts, [])
        self.assertEqual(summary["register_checked"], 0)
        self.assertEqual(len(summary["unconfirmed"]), 5)

    def test_expired_entries_are_skipped(self):
        conflicts, _ = rules.match_commitments(
            profile("Gulf Crown Hotels", "AtliQ Technologies Pvt Ltd", ["hospitality"], ["data_analytics"], ["Saudi Arabia"]),
            REGISTER,
            today=date(2030, 1, 1),
        )
        self.assertEqual(conflicts, [])


class RegionTests(unittest.TestCase):
    def test_blueorchid_annexure_muscat_is_found(self):
        text = read(config.INCOMING_DIR, "2026-09-21_blueorchid_hotels_pilot_agreement_draft.md")
        regions = rules.regions_in_text(text)
        self.assertIn("Oman", regions)
        self.assertIn("UAE", regions)

    def test_atliq_address_is_ignored(self):
        self.assertEqual(rules.regions_in_text("4th Floor, Baner Business Bay, Pune 411045, Maharashtra, India"), set())

    def test_gcc_group_expands(self):
        self.assertEqual(rules.normalise_regions(["GCC"]), set(config.GCC))


class NextStepTests(unittest.TestCase):
    def finding(self, risk, flags=()):
        return rules.Finding(title="t", risk=risk, reason="r", flags=list(flags))

    def conflict(self):
        return rules.Conflict("R-001", "Medium", "t", "r", None, "old", "f.md", "12.1", None, [])

    def test_conflict_never_gives_accept(self):
        self.assertEqual(rules.next_step([], [self.conflict()])[0], rules.SEND_TO_LAWYER)

    def test_baa_missing_goes_to_lawyer(self):
        self.assertEqual(rules.next_step([self.finding("High", ["baa_missing"])], [])[0], rules.SEND_TO_LAWYER)

    def test_high_finding_is_redline(self):
        self.assertEqual(rules.next_step([self.finding("High", ["one_sided_nda"])], [])[0], rules.REDLINE)

    def test_only_low_findings_is_accept(self):
        self.assertEqual(rules.next_step([self.finding("Low"), self.finding("Needs human reading")], [])[0], rules.ACCEPT)


class TrackerTests(unittest.TestCase):
    def test_crestline_sows_are_expected_but_missing(self):
        missing = rules.expected_but_missing("Crestline Retail Inc", TRACKER)
        self.assertEqual({m["contract_id"] for m in missing}, {"C-003", "C-004"})

    def test_al_noor_documents_are_all_present(self):
        self.assertEqual(rules.expected_but_missing("Al Noor Hospitality Group", TRACKER), [])

    def test_sort_puts_high_first_then_document_order(self):
        f = [
            rules.Finding("a", "Low", "", position=1),
            rules.Finding("b", "High", "", position=50),
            rules.Finding("c", "High", "", position=10),
            rules.Finding("d", "Medium", "", position=5),
        ]
        self.assertEqual([x.title for x in rules.sort_findings(f)], ["c", "b", "d", "a"])


if __name__ == "__main__":
    unittest.main()
