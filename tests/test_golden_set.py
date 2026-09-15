#!/usr/bin/env python3
"""
Golden set for the academic-calendar collection.

Step 7 of the 8-step ingestion path: real student phrasings with expected
answers. A source without golden questions cannot be measured, so it cannot be
launched. This file is both the regression suite and the measurement instrument
for the >=95% groundedness target.

Run:  python3 -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from calendar_tool import Calendar, call  # noqa: E402
from render import render  # noqa: E402

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CAL = Calendar.load()


class SourceIntegrity(unittest.TestCase):
    """The extraction must match the PDF. These catch transcription drift."""

    def test_every_published_weekday_matches_the_real_calendar(self):
        bad = []
        for r in CAL.records:
            p = r["payload"]
            pub = p.get("weekday_as_published")
            if not pub:
                continue
            parts = [x.strip() for x in pub.split("-")]
            d = datetime.strptime(p["date_start"], "%Y-%m-%d").date()
            if parts[0] != WEEKDAYS[d.weekday()]:
                bad.append((r["id"], parts[0], WEEKDAYS[d.weekday()]))
        self.assertEqual(bad, [], f"weekday mismatches: {bad}")

    def test_every_record_has_a_session(self):
        missing = [r["id"] for r in CAL.records if not r["payload"].get("session")]
        self.assertEqual(missing, [])

    def test_every_record_has_an_escalation_queue(self):
        missing = [r["id"] for r in CAL.records
                   if not r["owner"].get("escalation_queue")]
        self.assertEqual(missing, [])

    def test_record_count_matches_extraction(self):
        self.assertEqual(len(CAL.records), 77)


class GoldenAnswers(unittest.TestCase):
    """Real student phrasings -> expected answer. AS_OF is fixed so the suite
    is deterministic; vary it in the cases that test time-dependence."""

    AS_OF = "2026-08-26"

    def test_when_does_school_start(self):
        r = call(name="find_events", query="when does school start", as_of=self.AS_OF)
        self.assertEqual(r["answer_type"], "resolved")
        self.assertEqual(r["events"][0]["date_start"], "2026-08-25")
        # Must volunteer that the accelerated sessions differ.
        self.assertTrue(r["alternatives"])

    def test_drop_deadline_differs_by_session_so_it_asks(self):
        r = call(name="deadline_for", action="drop", as_of=self.AS_OF)
        self.assertEqual(r["answer_type"], "needs_clarification")
        self.assertEqual(len(r["options"]), 3)

    def test_drop_deadline_main(self):
        r = call(name="deadline_for", action="drop", session="main", as_of=self.AS_OF)
        self.assertEqual(r["answer_type"], "resolved")
        self.assertEqual(r["deadline"], "2026-09-03")
        self.assertFalse(r["has_passed"])

    def test_drop_deadline_accelerated_2_is_a_different_date(self):
        r = call(name="deadline_for", action="drop", session="accelerated-2", as_of=self.AS_OF)
        self.assertEqual(r["deadline"], "2026-10-22")

    def test_withdraw_returns_the_last_day_not_the_window_opening(self):
        """The most likely wrong answer: 'withdrawal deadline' resolving to the
        date the withdrawal period OPENS."""
        for sess, expected in [("main", "2026-11-11"),
                               ("accelerated-1", "2026-09-25"),
                               ("accelerated-2", "2026-11-23")]:
            with self.subTest(sess=sess):
                r = call(name="deadline_for", action="withdraw", session=sess, as_of=self.AS_OF)
                self.assertEqual(r["deadline"], expected)

    def test_missed_deadline_is_reported_as_missed(self):
        r = call(name="deadline_for", action="drop", session="main", as_of="2026-10-01")
        self.assertTrue(r["has_passed"])
        self.assertLess(r["days_remaining"], 0)

    def test_pass_fail_deadline_matches_withdrawal_deadline(self):
        r = call(name="deadline_for", action="pass-fail", session="main", as_of=self.AS_OF)
        self.assertEqual(r["deadline"], "2026-11-11")

    def test_labor_day_closed(self):
        r = call(name="is_university_closed", on="2026-09-07")
        self.assertTrue(r["closed"])

    def test_regular_tuesday_not_closed(self):
        r = call(name="is_university_closed", on="2026-10-06")
        self.assertFalse(r["closed"])

    def test_winter_closure_spans_the_year_boundary(self):
        for d in ("2026-12-24", "2026-12-31", "2027-01-01"):
            with self.subTest(d=d):
                self.assertTrue(call(name="is_university_closed", on=d)["closed"])

    def test_no_class_on_labor_day(self):
        r = call(name="classes_meet_on", on="2026-09-07")
        self.assertIs(r["classes_meet"], False)

    def test_faculty_institute_is_partial_not_a_full_cancellation(self):
        r = call(name="classes_meet_on", on="2026-08-27")
        self.assertEqual(r["classes_meet"], "partial")
        self.assertIn("evening", r["detail"].lower())

    def test_graduation_application_deadline(self):
        r = call(name="deadline_for", action="graduation-application",
                 session="main", as_of=self.AS_OF)
        self.assertEqual(r["deadline"], "2026-09-18")

    def test_dorm_move_in(self):
        r = call(name="find_events", query="when can I move in to the dorms", as_of=self.AS_OF)
        self.assertEqual(r["events"][0]["date_start"], "2026-08-19")

    def test_finals_week(self):
        r = call(name="find_events", query="when are finals", session="main", as_of=self.AS_OF)
        top = r["events"][0]
        self.assertEqual((top["date_start"], top["date_end"]), ("2026-12-07", "2026-12-11"))

    def test_thanksgiving_break(self):
        r = call(name="find_events", query="when is thanksgiving break", session="main",
                 as_of=self.AS_OF)
        self.assertEqual(r["events"][0]["date_start"], "2026-11-26")

    def test_session_status_mid_october(self):
        r = call(name="session_status", as_of="2026-10-14")
        by = {s["session"]: s for s in r["sessions"]}
        self.assertEqual(by["main"]["status"], "in-progress")
        self.assertEqual(by["accelerated-1"]["status"], "in-progress")
        self.assertEqual(by["accelerated-2"]["status"], "upcoming")

    def test_upcoming_only_returns_future_action_items(self):
        r = call(name="upcoming", as_of=self.AS_OF, within_days=10,
                 action_required_only=True, limit=20)
        for e in r["events"]:
            self.assertGreaterEqual(e["days_from_now"], 0)
            self.assertTrue(e["student_action_required"])

    def test_expired_records_are_never_returned(self):
        """Temporal validity is enforced at retrieval. Asking in March must not
        surface Fall 2026 deadlines."""
        r = call(name="deadline_for", action="drop", session="main", as_of="2027-03-01")
        self.assertEqual(r["answer_type"], "no_coverage")


class RefundLogic(unittest.TestCase):

    def test_before_instruction_is_full_refund(self):
        r = call(name="refund_schedule", withdrawal_date="2026-08-20", session="main")
        self.assertEqual(r["answer_type"], "resolved")
        self.assertEqual(r["tuition_refund_pct"], 100)

    def test_overlap_zone_is_ambiguous_not_guessed(self):
        """Sept 1 is inside the published contradiction. The tool must refuse to
        pick a row -- this is the behavior that protects a student's bill."""
        r = call(name="refund_schedule", withdrawal_date="2026-09-01", session="main")
        self.assertEqual(r["answer_type"], "ambiguous")
        self.assertEqual(len(r["conflicting_outcomes"]), 2)
        self.assertEqual(r["escalate"]["queue"], "student-accounts")

    def test_clear_zone_resolves_with_a_caveat(self):
        r = call(name="refund_schedule", withdrawal_date="2026-09-15", session="main")
        self.assertEqual(r["answer_type"], "resolved")
        self.assertEqual(r["tuition_refund_pct"], 0)
        self.assertTrue(r["caveats"])

    def test_accelerated_2_has_no_overlap_so_early_days_resolve(self):
        """Accel II's last-day-to-add is only 3 days after its start, so the
        published rows do not collide."""
        r = call(name="refund_schedule", withdrawal_date="2026-10-24", session="accelerated-2")
        self.assertEqual(r["answer_type"], "resolved")
        self.assertEqual(r["tuition_refund_pct"], 80)

    def test_accelerated_sessions_use_their_own_start_date(self):
        """Same calendar date, different session -> different day count."""
        a = call(name="refund_schedule", withdrawal_date="2026-10-25", session="main")
        b = call(name="refund_schedule", withdrawal_date="2026-10-25", session="accelerated-2")
        self.assertEqual(a["days_since_first_instruction"], 61)
        self.assertEqual(b["days_since_first_instruction"], 6)
        self.assertNotEqual(a["tuition_refund_pct"], b["tuition_refund_pct"])


class AnswerContract(unittest.TestCase):
    """The invariant that keeps the bot honest: the renderer may not state a
    fact unless the tool resolved one."""

    NON_ASSERTING = ("known_unknown", "ambiguous", "needs_clarification", "no_coverage")

    def test_renderer_never_asserts_on_a_non_resolved_result(self):
        cases = [
            dict(name="classes_meet_on", on="2026-09-15"),          # Convocation
            dict(name="classes_meet_on", on="2026-09-11"),          # Constitution Day
            dict(name="classes_meet_on", on="2026-10-10"),          # Homecoming
            dict(name="deadline_for", action="drop", as_of="2026-08-26"),
            dict(name="refund_schedule", withdrawal_date="2026-09-01", session="main"),
            dict(name="find_events", query="where is the parking office", as_of="2026-08-26"),
        ]
        for kw in cases:
            with self.subTest(**kw):
                res = call(**kw)
                self.assertIn(res["answer_type"], self.NON_ASSERTING,
                              f"{kw} unexpectedly resolved")
                out = render(res)
                self.assertFalse(out["may_state_a_fact"])

    def test_unstated_events_always_offer_escalation(self):
        for d in ("2026-09-15", "2026-09-11", "2026-10-10"):
            with self.subTest(d=d):
                out = render(call(name="classes_meet_on", on=d))
                self.assertTrue(out["escalation_offered"])

    def test_resolved_answers_always_carry_a_citation(self):
        cases = [
            dict(name="deadline_for", action="drop", session="main", as_of="2026-08-26"),
            dict(name="is_university_closed", on="2026-11-03"),
            dict(name="refund_schedule", withdrawal_date="2026-09-15", session="main"),
        ]
        for kw in cases:
            with self.subTest(**kw):
                out = render(call(**kw))
                self.assertTrue(out["may_state_a_fact"])
                self.assertTrue(out["citations"], "grounded answer with no citation")

    def test_citations_are_deduplicated_for_the_student(self):
        out = render(call(name="deadline_for", action="drop", session="main",
                          as_of="2026-08-26"))
        labels = [c["label"] for c in out["citations"]]
        self.assertEqual(len(labels), len(set(labels)))


class CrossCollectionReferences(unittest.TestCase):
    """One fact, one home: the FAQ must not restate dates, it must reference
    them -- and every reference must resolve."""

    def test_faq_reference_tokens_all_resolve(self):
        all_ids = set()
        for path in (ROOT / "kb").rglob("*.json"):
            for r in json.loads(path.read_text()).get("records", []):
                all_ids.add(r["id"])

        faq = json.loads((ROOT / "kb" / "faq" / "records-registration.json").read_text())
        checked = 0
        for r in faq["records"]:
            answer = r["payload"]["answer"]
            i = 0
            while (i := answer.find("{{ref:", i)) != -1:
                j = answer.find("}}", i)
                token = answer[i + 6:j].strip()
                self.assertIn(token, all_ids, f"{r['id']} references missing {token}")
                checked += 1
                i = j
            for ref in r["payload"]["references"]:
                self.assertIn(ref, all_ids, f"{r['id']} references missing {ref}")
                checked += 1
        self.assertGreater(checked, 10, "expected the FAQ to lean on references")

    def test_faq_answers_do_not_hardcode_dates(self):
        """A literal date in an FAQ answer is a second home for a fact that
        already has one, and it will drift."""
        import re
        faq = json.loads((ROOT / "kb" / "faq" / "records-registration.json").read_text())
        pattern = re.compile(
            r"\b(January|February|March|April|May|June|July|August|September|October|"
            r"November|December)\s+\d{1,2}\b")
        offenders = [r["id"] for r in faq["records"]
                     if pattern.search(r["payload"]["answer"])]
        self.assertEqual(offenders, [], f"hardcoded dates found in: {offenders}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
