#!/usr/bin/env python3
"""
Routing and contact tests.

The important ones here are the negative tests. It is easy to write a table that
currently satisfies an invariant; what matters is whether the gate CATCHES a
violation when someone edits the table six months from now. Each invariant test
therefore corrupts a copy of a real record and asserts that the gate fails it.

Run:  python3 -m unittest discover -s tests -v
"""

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import validate_kb as V  # noqa: E402

ROUTING = json.loads((ROOT / "kb" / "reference" / "routing.json").read_text())
RECORDS = ROUTING["records"]
ROUTES = [r for r in RECORDS if r["collection"] == "routing"]
CONTACTS = [r for r in RECORDS if r["collection"] == "contacts"]


def run_checks(records, *checks) -> V.Report:
    rep = V.Report()
    for c in checks:
        c(records, rep)
    return rep


class RoutingTable(unittest.TestCase):

    def test_every_pilot_department_is_represented(self):
        offices = {r["payload"]["office"] for r in ROUTES}
        for expected in ("Records & Registration", "Student Accounts", "Financial Aid",
                         "IT Help Desk", "Housing & Residence Life", "Academic Advisement"):
            self.assertIn(expected, offices)

    def test_every_route_resolves_to_an_office_contact(self):
        ids = {r["id"] for r in RECORDS}
        for r in ROUTES:
            self.assertIn(r["payload"]["office_contact_id"], ids, r["id"])

    def test_every_route_has_at_least_two_student_phrasings(self):
        for r in ROUTES:
            self.assertGreaterEqual(len(r["payload"]["aliases"]), 2, r["id"])

    def test_own_record_topics_never_claim_to_be_answerable(self):
        """Phase 1 has no access to a student's own records. A topic that needs
        one must route, whatever content exists."""
        for r in ROUTES:
            if r["payload"]["requires_own_record_lookup"]:
                self.assertNotEqual(r["payload"]["kb_coverage"], "answerable", r["id"])

    def test_tier_3_topics_all_route_and_never_answer(self):
        t3 = [r for r in ROUTES if r["payload"]["topic_data_tier"] == 3]
        self.assertGreaterEqual(len(t3), 4, "expected crisis/Title IX/safety/conduct routes")
        for r in t3:
            self.assertEqual(r["payload"]["kb_coverage"], "never-answer", r["id"])
            self.assertTrue(r["payload"]["answer_guidance"], r["id"])

    def test_crisis_topics_are_marked_crisis_urgency(self):
        crisis = [r for r in ROUTES if r["payload"]["urgency"] == "crisis"]
        self.assertGreaterEqual(len(crisis), 3)
        for r in crisis:
            self.assertEqual(r["payload"]["kb_coverage"], "never-answer", r["id"])

    def test_routing_records_are_themselves_tier_0(self):
        """A routing record for a sensitive topic is public information and MUST
        be indexed -- it is what guarantees the handoff exists. Conflating topic
        sensitivity with record sensitivity would silently delete the crisis
        routes from the index."""
        for r in ROUTES:
            self.assertEqual(r["governance"]["data_tier"], 0, r["id"])

    def test_no_alias_routes_to_two_offices(self):
        seen = {}
        for r in ROUTES:
            for a in r["payload"]["aliases"]:
                k = a.strip().lower()
                if k in seen:
                    self.assertEqual(seen[k], r["payload"]["office"],
                                     f"alias {a!r} is ambiguous")
                seen[k] = r["payload"]["office"]

    def test_handoff_needs_present_where_a_handoff_will_happen(self):
        """route-only topics hand off every time, so the escalation card needs
        something to carry -- except crisis topics, where interrogating the
        student is the wrong behavior."""
        for r in ROUTES:
            p = r["payload"]
            if p["kb_coverage"] == "route-only" and p["urgency"] != "crisis":
                self.assertTrue(p["handoff_needs"], r["id"])

    def test_crisis_topics_collect_nothing(self):
        for r in ROUTES:
            if r["payload"]["urgency"] == "crisis":
                self.assertEqual(r["payload"]["handoff_needs"], [], r["id"])


class ContactRecords(unittest.TestCase):

    def test_every_contact_has_a_reachable_channel(self):
        for r in CONTACTS:
            ch = r["payload"]["channels"]
            self.assertTrue(any(ch.get(k) for k in ("email", "phone", "ticket_url", "url")),
                            r["id"])

    def test_unpopulated_offices_are_flagged_not_guessed(self):
        """Phone numbers I could not verify are null and flagged, not invented."""
        for r in CONTACTS:
            p = r["payload"]
            if p["channels"]["phone"] is None:
                self.assertIn("office-contact-unpopulated", p["data_quality_flags"], r["id"])

    def test_office_aliases_use_what_students_say(self):
        aliases = {a for r in CONTACTS for a in r["payload"]["aliases"]}
        for expected in ("the bursar", "the registrar", "help desk", "res life"):
            self.assertIn(expected, aliases)


class GateEnforcesInvariants(unittest.TestCase):
    """Negative tests. Corrupt a real record; assert the gate rejects it."""

    def _route(self, **overrides):
        r = copy.deepcopy(next(x for x in ROUTES
                               if x["payload"]["topic_data_tier"] == 3))
        r["payload"].update(overrides)
        return r

    def test_gate_rejects_a_tier_3_topic_that_becomes_answerable(self):
        bad = self._route(kb_coverage="partial", urgency="routine")
        rep = run_checks(CONTACTS + [bad], V.check_routing)
        self.assertTrue(any("routing-tier" in f for f in rep.failures),
                        f"gate did not catch it; failures={rep.failures}")

    def test_gate_rejects_a_never_answer_topic_with_no_guidance(self):
        bad = self._route(answer_guidance=None)
        rep = run_checks(CONTACTS + [bad], V.check_routing)
        self.assertTrue(any("routing-tier" in f for f in rep.failures))

    def test_gate_rejects_crisis_urgency_that_is_answerable(self):
        bad = self._route(kb_coverage="route-only", topic_data_tier=0, urgency="crisis")
        rep = run_checks(CONTACTS + [bad], V.check_routing)
        self.assertTrue(any("routing-crisis" in f for f in rep.failures))

    def test_gate_rejects_answerable_topic_needing_own_records(self):
        bad = self._route(kb_coverage="answerable", topic_data_tier=0,
                          urgency="routine", requires_own_record_lookup=True)
        rep = run_checks(CONTACTS + [bad], V.check_routing)
        self.assertTrue(any("routing-phase" in f for f in rep.failures))

    def test_gate_rejects_a_dangling_office_reference(self):
        bad = self._route(office_contact_id="contact.office.does-not-exist")
        rep = run_checks(CONTACTS + [bad], V.check_routing)
        self.assertTrue(any("routing-reference" in f for f in rep.failures))

    def test_gate_rejects_a_scraped_contact_with_no_expiry(self):
        """A scraped roster that never expires becomes permanently wrong."""
        c = copy.deepcopy(CONTACTS[0])
        c["payload"]["source_authority"] = "web-scrape"
        c["payload"]["contact_type"] = "person"
        c["temporal"]["effective_to"] = None
        rep = run_checks([c], V.check_contacts)
        self.assertTrue(any("contact-expiry" in f for f in rep.failures))

    def test_gate_rejects_a_contact_with_no_channel(self):
        c = copy.deepcopy(CONTACTS[0])
        c["payload"]["channels"] = {"email": None, "phone": None, "phone_extension": None,
                                    "fax": None, "url": None, "ticket_url": None,
                                    "appointment_url": None}
        rep = run_checks([c], V.check_contacts)
        self.assertTrue(any("contact-channels" in f for f in rep.failures))

    def test_clean_table_produces_no_failures(self):
        """The corruption tests above are only meaningful if the real table passes."""
        rep = run_checks(RECORDS, V.check_routing, V.check_contacts)
        self.assertEqual(rep.failures, [])


class ScraperParsing(unittest.TestCase):
    """The crawler's extraction, against a fixture of the real page structure."""

    @classmethod
    def setUpClass(cls):
        try:
            import bs4  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("beautifulsoup4 not installed")
        from crawl_directory import extract_page
        cls.extract = staticmethod(extract_page)
        cls.html = (ROOT / "tests" / "fixtures" / "hr-staff.html").read_text()

    def test_extracts_every_person_and_no_prose(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        names = {r["display_name"] for r in found}
        self.assertEqual(len(found), 4, names)
        self.assertIn("Dr. Irene Chapman-Hawkins", names)
        self.assertIn("Tanya Wilson", names)

    def test_keeps_credentials_in_the_published_name(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        self.assertTrue(any("SHRM-PMQ" in r["display_name"] for r in found))

    def test_deobfuscates_bracket_at_emails_and_flags_them(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        irene = next(r for r in found if "Irene" in r["display_name"])
        self.assertEqual(irene["email"], "ihawkins@desu.edu")
        self.assertIn("email-obfuscated-in-source", irene["flags"])

    def test_prefers_mailto_links_without_flagging_them(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        tanya = next(r for r in found if "Tanya" in r["display_name"])
        self.assertEqual(tanya["email"], "twilson@desu.edu")
        self.assertNotIn("email-obfuscated-in-source", tanya["flags"])

    def test_no_emails_flag_suppresses_all_harvesting(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", False)
        self.assertEqual(len(found), 4)
        self.assertTrue(all(r["email"] is None for r in found))

    def test_flags_the_row_where_a_phone_sits_in_the_email_field(self):
        """A real error on the live HR page. Detected by comparing the row
        against its siblings, not by per-row heuristics."""
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        charlotte = next(r for r in found if "Charlotte" in r["display_name"])
        self.assertIsNone(charlotte["email"])
        self.assertIn("malformed-source-row", charlotte["flags"])

    def test_titles_are_not_mistaken_for_names(self):
        found, _ = self.extract(self.html, "https://www.desu.edu/x", True)
        for r in found:
            self.assertNotIn("Vice President", r["display_name"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
