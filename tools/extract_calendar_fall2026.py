#!/usr/bin/env python3
"""
One-time assisted extraction: fall_2026.pdf -> kb/calendar/fall-2026.json

This script exists so the mapping from source text to KB records is auditable
in code review rather than being an opaque hand-edit. Run it ONCE. After the
Registrar liaison signs off, the emitted JSON becomes canonical and is edited
directly -- do not re-run this and clobber their corrections.

Source: Academic Calendar Fall 2026 (202701), "UPDATED: 7/23/2026"
Owner:  Records & Registration
Tier:   0 (public, non-confidential) -- Phase 1 launch scope
"""

import json
import hashlib
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "kb" / "calendar" / "fall-2026.json"

TERM = "fall2026"
SOURCE = {
    "type": "pdf",
    "title": "Academic Calendar Fall 2026 (202701)",
    "uri": "https://www.desu.edu/academics/academic-calendar",  # A4: confirm canonical URL
    "source_updated": "2026-07-23",
    "locator": "p.1-2",
}
OWNER = {
    "department": "Records & Registration",
    "liaison_role": "Registrar's Office KB Liaison",
    "escalation_queue": "records-registration",
}
GOV = {"data_tier": 0, "audience": ["student", "faculty", "staff"], "authority": "authoritative"}
TEMPORAL = {"effective_from": "2026-07-23", "effective_to": "2027-01-31", "supersedes": None}
REVIEW = {
    "cadence": "per-term",
    "last_reviewed": None,
    "next_due": "2026-12-01",
    "reviewed_by": "pending-liaison-signoff",
}
CITATION = {
    "label": "Academic Calendar, Fall 2026 - Office of Records & Registration (updated 7/23/2026)",
    "url": SOURCE["uri"],
}

ALL_CAMPUS = ["all"]
ACCEL_CAMPUS = ["dover", "wilmington", "georgetown"]


def ev(slug, session, title, start, *, end=None, wd=None, etype="administrative",
       affects="unstated", action=False, action_summary=None, time=None,
       campus=None, fee=None, aliases=None, refs=None, notes=None, flags=None):
    """Build one enveloped calendar record."""
    payload = {
        "title": title,
        "session": session,
        "campus": campus or ALL_CAMPUS,
        "event_type": etype,
        "date_start": start,
        "date_end": end,
        "weekday_as_published": wd,
        "time": time,
        "affects_classes": affects,
        "student_action_required": action,
        "action_summary": action_summary,
        "related_fee": fee,
        "aliases": aliases or [],
        "references": refs or [],
        "notes": notes,
        "data_quality_flags": flags or [],
    }
    body = json.dumps(payload, sort_keys=True).encode()
    return {
        "id": f"cal.{TERM}.{session}.{slug}",
        "kb_class": "structured-record",
        "collection": "academic-calendar",
        "payload": payload,
        "source": SOURCE,
        "owner": OWNER,
        "governance": GOV,
        "temporal": TEMPORAL,
        "review": REVIEW,
        "citation": CITATION,
        "provenance": {
            "ingested_at": "2026-08-26T00:00:00Z",
            "ingest_method": "assisted-extraction",
            "content_hash": "sha256:" + hashlib.sha256(body).hexdigest()[:32],
            "validation_status": "unvalidated",
        },
    }


# --------------------------------------------------------------------------
# MAIN SEMESTER  (page 1)
# --------------------------------------------------------------------------
MAIN = [
    ev("fall-payment-due", "main", "Fall Payment Due Date", "2026-08-06",
       wd="Thursday", etype="payment", affects="not-applicable", action=True,
       action_summary="Fall semester tuition and fees must be paid or a payment plan in place.",
       aliases=["when is tuition due", "fall payment deadline", "when do I have to pay for fall"]),

    ev("residence-halls-open", "main", "Residence Halls Open for All Students", "2026-08-19",
       end="2026-08-22", wd="Wednesday-Saturday", etype="housing", affects="not-applicable",
       aliases=["when can I move in", "dorm move in", "when do the dorms open", "residence hall opening"]),

    ev("welcome-days", "main", "Welcome Days", "2026-08-20", end="2026-08-23",
       wd="Thursday-Sunday", etype="ceremony", affects="not-applicable",
       aliases=["welcome week", "new student welcome", "orientation events"]),

    ev("i-love-dsu-week", "main", "I Love DSU Week", "2026-08-23", end="2026-08-29",
       wd="Sunday-Saturday", etype="ceremony", affects="not-applicable",
       aliases=["I love DSU week", "spirit week"]),

    ev("classes-begin", "main", "Classes Begin", "2026-08-25", wd="Tuesday",
       etype="instruction-period", affects="yes", time="08:00",
       aliases=["first day of classes", "when does school start", "when does the semester start",
                "first day of school", "when do classes begin"],
       notes="Classes begin at 8:00 am."),

    ev("late-registration-begins", "main", "Late Registration Begins", "2026-08-25",
       wd="Tuesday", etype="registration", affects="not-applicable", action=True,
       action_summary="Students not yet registered may register late beginning this date.",
       aliases=["late registration", "can I still register", "register after classes start"]),

    ev("faculty-institute", "main", "Faculty Institute", "2026-08-27", wd="Thursday",
       etype="administrative", affects="partial",
       aliases=["faculty institute", "do I have class August 27", "no morning classes"],
       notes="No morning classes held; evening classes only."),

    ev("last-day-add-drop", "main", "Last Day to Add and Drop Courses (without financial penalty)",
       "2026-09-03", wd="Thursday", etype="deadline", affects="yes", action=True,
       action_summary="Last day to add or drop a course with no financial penalty and no W on the transcript.",
       refs=["ref.refund-schedule.fall-spring", f"cal.{TERM}.main.drop-fee-effective"],
       aliases=["add drop deadline", "last day to drop a class", "can I still drop a class",
                "drop without penalty", "last day to add a class", "schedule change deadline"]),

    ev("last-day-audit-change", "main", "Last Day to Change Course(s) to Audit Status",
       "2026-09-03", wd="Thursday", etype="deadline", affects="not-applicable", action=True,
       action_summary="Last day to switch a course to audit status.",
       aliases=["audit a class", "change to audit", "audit deadline"]),

    ev("drop-fee-effective", "main", "Effective Date for $10 Drop Processing Fee",
       "2026-09-04", wd="Friday", etype="deadline", affects="not-applicable",
       fee={"amount_usd": 10, "description": "$10 processing fee per dropped course"},
       refs=["ref.refund-schedule.fall-spring"],
       aliases=["drop fee", "does it cost money to drop a class", "$10 fee"],
       notes="Source reads 'Effective Date for $10 drop processing fee)' with an unmatched "
             "parenthesis; text otherwise transcribed verbatim. Source directs readers to the "
             "Refund Schedule for financial responsibility on withdrawn courses.",
       flags=["source-typo"]),

    ev("academic-student-success-committee", "main",
       "Academic & Student Success Committee Meeting", "2026-09-03", wd="Thursday",
       etype="administrative", affects="not-applicable",
       aliases=["academic committee meeting"]),

    ev("non-attendance-documentation", "main", "Documentation for Non-Attendance Period",
       "2026-09-04", end="2026-09-08", wd="Friday-Tuesday", etype="administrative",
       affects="not-applicable",
       aliases=["non attendance", "never attended", "attendance documentation"]),

    ev("labor-day", "main", "Labor Day (University Closed)", "2026-09-07", wd="Monday",
       etype="closure", affects="no",
       aliases=["labor day", "is the university closed labor day", "do we have class on labor day"]),

    ev("early-alert-period", "main", "Academic Early Alert Period", "2026-09-07", wd="Monday",
       etype="administrative", affects="not-applicable",
       aliases=["early alert", "academic alert"],
       notes="Source lists a single start date with no end date for this period.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("general-faculty-meeting", "main", "General Faculty Meeting", "2026-09-10",
       wd="Thursday", etype="administrative", affects="unstated",
       aliases=["faculty meeting"]),

    ev("constitution-day", "main", "Constitution Day (DSU Observed)", "2026-09-11",
       wd="Friday", etype="ceremony", affects="unstated",
       aliases=["constitution day", "is the university closed constitution day",
                "do I have class on constitution day"],
       notes="Source says 'DSU Observed' but does not state whether classes meet or offices close.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("convocation", "main", "Convocation", "2026-09-15", wd="Tuesday", etype="ceremony",
       affects="unstated",
       aliases=["convocation", "do I have class on convocation day", "is convocation mandatory"],
       notes="Source does not state whether classes are cancelled or attendance is expected.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("graduation-application-due", "main",
       "Application & Audit for December and May Graduates Due", "2026-09-18", wd="Friday",
       etype="deadline", affects="not-applicable", action=True,
       action_summary="December and May graduates must submit their graduation application and audit.",
       aliases=["graduation application", "apply to graduate", "graduation deadline",
                "how do I apply for graduation"]),

    ev("midterm-evaluations", "main", "Mid-Term Evaluations Administered", "2026-10-05",
       end="2026-10-09", wd="Monday-Friday", etype="evaluation", affects="yes",
       aliases=["midterms", "midterm exams", "when are midterms"]),

    ev("residency-status-audit", "main", "Residency Status Audit", "2026-10-07",
       wd="Wednesday", etype="administrative", affects="not-applicable",
       aliases=["residency audit", "in state residency"]),

    ev("last-day-remove-incompletes", "main", "Last Day to Remove Incompletes", "2026-10-08",
       wd="Thursday", etype="deadline", affects="not-applicable", action=True,
       action_summary="Last day to resolve an Incomplete grade from a prior term.",
       aliases=["incomplete grade", "remove an incomplete", "I grade deadline"]),

    ev("homecoming", "main", "Homecoming", "2026-10-10", wd="Saturday", etype="ceremony",
       affects="unstated",
       aliases=["homecoming", "when is homecoming"],
       notes="Source does not state associated closures or schedule changes.",
       flags=["source-ambiguous"]),

    ev("midterm-grades-due", "main", "Mid-Term Grades Due", "2026-10-12", wd="Monday",
       etype="grading", affects="not-applicable",
       aliases=["midterm grades", "when will I get midterm grades"]),

    ev("advisement-period", "main", "Academic Advisement Period", "2026-10-12",
       end="2026-11-18", wd="Monday-Wednesday", etype="registration", affects="not-applicable",
       action=True, action_summary="Meet with your academic advisor before registering for spring.",
       aliases=["advisement", "see my advisor", "advising period", "academic advising"]),

    ev("priority-pre-registration", "main", "Priority Pre-Registration", "2026-10-19",
       end="2026-10-20", wd="Monday-Tuesday", etype="registration", affects="not-applicable",
       action=True, action_summary="Eligible students may register for spring/summer first.",
       aliases=["priority registration", "early registration"],
       notes="Source does not state eligibility criteria for priority status.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("pre-registration-spring-summer", "main", "Pre-Registration for Spring & Summer",
       "2026-10-21", end="2026-11-18", wd="Wednesday-Wednesday", etype="registration",
       affects="not-applicable", action=True,
       action_summary="Register for spring and summer courses.",
       aliases=["spring registration", "when can I register for spring",
                "summer registration", "registration opens"]),

    ev("census-date", "main", "Census Date", "2026-10-30", wd="Friday",
       etype="administrative", affects="not-applicable",
       aliases=["census date", "enrollment census"]),

    ev("election-day", "main", "Election Day (University Closed)", "2026-11-03",
       wd="Tuesday", etype="closure", affects="no",
       aliases=["election day", "is the university closed election day"]),

    ev("open-house", "main", "Open House", "2026-11-07", wd="Saturday", etype="ceremony",
       affects="unstated", aliases=["open house", "campus visit day"]),

    ev("fall-course-evaluations", "main", "Fall Course Evaluations", "2026-11-16",
       end="2026-12-03", wd="Monday-Thursday", etype="evaluation", affects="not-applicable",
       action=True, action_summary="Complete course evaluations for your fall courses.",
       aliases=["course evaluations", "evaluate my professor", "student evaluations"],
       notes="Printed out of chronological order in the source (listed between Nov 7 and Nov 11).",
       flags=["listed-out-of-order"]),

    ev("last-day-withdraw", "main",
       "Last Day to Withdraw from Course(s) / University; Last Day to Submit Pass-Fail Request",
       "2026-11-11", wd="Wednesday", etype="deadline", affects="yes", action=True,
       action_summary="Last day to withdraw from a course or from the University, and last day "
                      "to request Pass-Fail grading for a fall course.",
       refs=["ref.refund-schedule.fall-spring"],
       aliases=["withdrawal deadline", "last day to withdraw", "can I still withdraw",
                "pass fail deadline", "drop with a W", "last day to drop with a W"],
       notes="Source directs readers to the academic catalog for the Pass-Fail policy."),

    ev("december-graduate-exit-interview", "main", "Exit Interview for December Graduates",
       "2026-11-15", wd="Sunday", etype="deadline", affects="not-applicable", action=True,
       action_summary="December graduates must complete their exit interview.",
       aliases=["exit interview", "graduating in December"]),

    ev("residence-halls-close-thanksgiving", "main", "Residence Halls Close for Thanksgiving",
       "2026-11-25", wd="Wednesday", etype="housing", affects="not-applicable", time="17:00",
       aliases=["do the dorms close for thanksgiving", "residence halls thanksgiving",
                "when do I have to leave for thanksgiving"],
       notes="Residence halls close at 5:00 pm."),

    ev("thanksgiving-recess", "main", "Thanksgiving Recess", "2026-11-26", end="2026-11-29",
       wd="Thursday-Sunday", etype="recess", affects="no",
       aliases=["thanksgiving break", "thanksgiving recess", "when is thanksgiving break"]),

    ev("residence-halls-reopen", "main",
       "Residence Halls Re-Open for the Remainder of Fall Semester", "2026-11-29",
       wd="Sunday", etype="housing", affects="not-applicable",
       aliases=["when do the dorms reopen", "come back after thanksgiving"]),

    ev("last-day-of-classes", "main", "Last Day of Classes", "2026-12-03", wd="Thursday",
       etype="instruction-period", affects="yes",
       aliases=["last day of classes", "when does the semester end", "when do classes end"]),

    ev("reading-day", "main", "Reading Day", "2026-12-04", wd="Friday",
       etype="instruction-period", affects="no",
       aliases=["reading day", "study day"]),

    ev("residency-status-final-audit", "main", "Residency Status Final Audit", "2026-12-04",
       wd="Friday", etype="administrative", affects="not-applicable",
       aliases=["final residency audit"]),

    ev("final-examinations", "main", "Final Examinations", "2026-12-07", end="2026-12-11",
       wd="Monday-Friday", etype="evaluation", affects="yes",
       aliases=["finals", "final exams", "when are finals", "exam week", "finals week"]),

    ev("winter-recess-students", "main", "Winter Recess Begins (Students)", "2026-12-11",
       wd="Friday", etype="recess", affects="no",
       aliases=["winter break", "when does winter break start", "christmas break"],
       notes="Distinct from the University closure of Dec 24 - Jan 1: the University remains "
             "open for business between these dates."),

    ev("residence-halls-close-winter", "main", "Residence Halls Close for Winter Recess",
       "2026-12-11", wd="Friday", etype="housing", affects="not-applicable", time="17:00",
       aliases=["when do the dorms close for winter", "move out for winter break"],
       notes="Residence halls close at 5:00 pm."),

    ev("final-grades-due", "main", "Final Grades Due", "2026-12-14", wd="Monday",
       etype="grading", affects="not-applicable",
       aliases=["final grades", "when will I get my grades", "when are grades posted"]),

    ev("spring-new-student-orientation", "main", "Spring New Student Orientation (Virtual)",
       "2026-12-15", wd="Tuesday", etype="administrative", affects="not-applicable",
       aliases=["spring orientation", "new student orientation"]),

    ev("winter-recess-closure", "main", "Winter Recess (University Closed)", "2026-12-24",
       end="2027-01-01", wd="Thursday-Friday", etype="closure", affects="no",
       aliases=["is the university closed for the holidays", "winter closure",
                "christmas closure", "holiday break"]),
]

# Winter session payment date, printed on the fall calendar
MAIN.append(
    ev("winter-payment-due", "winter", "Winter Payment Due Date", "2026-12-07", wd="Monday",
       etype="payment", affects="not-applicable", action=True,
       action_summary="Winter session tuition and fees due.",
       aliases=["winter session payment", "when is winter tuition due"],
       notes="Printed on the Fall 2026 calendar out of chronological order (listed after "
             "December 11 entries). Applies to the winter session, not the fall semester.",
       flags=["listed-out-of-order"])
)

# --------------------------------------------------------------------------
# ACCELERATED SESSION I  (Aug 25 - Oct 16, 2026)  page 2
# --------------------------------------------------------------------------
A1 = [
    ev("session-dates", "accelerated-1", "Accelerated Session I", "2026-08-25",
       end="2026-10-16", etype="instruction-period", affects="yes", campus=ACCEL_CAMPUS,
       aliases=["accelerated session 1", "8 week session 1", "first 8 week session",
                "accelerated I dates"],
       notes="8-week accelerated session offered at the Dover, Wilmington, and Georgetown campuses."),

    ev("classes-begin", "accelerated-1", "Classes Begin", "2026-08-25", wd="Tuesday",
       etype="instruction-period", affects="yes", time="08:00", campus=ACCEL_CAMPUS,
       aliases=["when does accelerated 1 start", "first day accelerated session 1"]),

    ev("late-registration-begins", "accelerated-1", "Late Registration Begins", "2026-08-25",
       wd="Tuesday", etype="registration", affects="not-applicable", campus=ACCEL_CAMPUS,
       action=True, action_summary="Late registration for Accelerated Session I opens.",
       aliases=["late registration accelerated 1"]),

    ev("last-day-add-drop", "accelerated-1",
       "Last Day to Add and Drop Courses (without financial penalty)", "2026-09-03",
       wd="Thursday", etype="deadline", affects="yes", campus=ACCEL_CAMPUS, action=True,
       action_summary="Last day to add or drop an Accelerated I course with no financial penalty.",
       refs=["ref.refund-schedule.accelerated"],
       aliases=["add drop deadline accelerated 1", "drop an accelerated class"]),

    ev("withdraw-window-opens", "accelerated-1",
       "Withdrawal Period Begins ($10 fee per course, W on transcript)", "2026-09-04",
       wd="Friday", etype="deadline", affects="not-applicable", campus=ACCEL_CAMPUS,
       fee={"amount_usd": 10, "description": "$10 fee for each withdrawn course"},
       refs=["ref.refund-schedule.accelerated"],
       aliases=["withdraw from accelerated 1", "W on transcript accelerated"],
       notes="A grade of W will be placed on the transcript. Source directs readers to the "
             "Refund Schedule for financial responsibility."),

    ev("labor-day", "accelerated-1", "Labor Day Recess (University Closed)", "2026-09-07",
       wd="Monday", etype="closure", affects="no", campus=ACCEL_CAMPUS,
       aliases=["labor day accelerated"]),

    ev("early-alert-period", "accelerated-1", "Academic Early Alert Period", "2026-09-07",
       wd="Monday", etype="administrative", affects="not-applicable", campus=ACCEL_CAMPUS,
       notes="Source lists a single start date with no end date.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("non-attendance-documentation", "accelerated-1",
       "Documentation for Non-Attendance Period", "2026-09-08", end="2026-09-09",
       wd="Tuesday-Wednesday", etype="administrative", affects="not-applicable",
       campus=ACCEL_CAMPUS),

    ev("midterm-evaluations", "accelerated-1", "Mid-Term Evaluations Administered",
       "2026-09-14", end="2026-09-18", wd="Monday-Friday", etype="evaluation",
       affects="yes", campus=ACCEL_CAMPUS,
       aliases=["accelerated 1 midterms", "when are midterms accelerated"]),

    ev("midterm-grades-due", "accelerated-1", "Mid-Term Grades Due", "2026-09-21",
       wd="Monday", etype="grading", affects="not-applicable", campus=ACCEL_CAMPUS),

    ev("last-day-withdraw", "accelerated-1",
       "Last Day to Withdraw from Accelerated I Course(s) / University; "
       "Last Day to Submit Pass-Fail Request", "2026-09-25", wd="Friday", etype="deadline",
       affects="yes", campus=ACCEL_CAMPUS, action=True,
       action_summary="Last day to withdraw from an Accelerated I course or the University, "
                      "and last day to request Pass-Fail grading for an Accelerated I course.",
       refs=["ref.refund-schedule.accelerated"],
       aliases=["withdrawal deadline accelerated 1", "last day to withdraw accelerated",
                "pass fail accelerated 1"],
       notes="Source directs readers to the academic catalog for the Pass-Fail policy."),

    ev("course-evaluations", "accelerated-1", "Accelerated I Fall Course Evaluations",
       "2026-10-05", end="2026-10-16", wd="Monday-Friday", etype="evaluation",
       affects="not-applicable", campus=ACCEL_CAMPUS, action=True,
       action_summary="Complete course evaluations for Accelerated I courses.",
       aliases=["course evaluations accelerated 1"]),

    ev("final-examinations", "accelerated-1", "Final Examinations", "2026-10-12",
       end="2026-10-16", wd="Monday-Friday", etype="evaluation", affects="yes",
       campus=ACCEL_CAMPUS,
       aliases=["accelerated 1 finals", "final exams accelerated session 1"],
       notes="Source places the final examination period Oct 12-16 and the last day of classes "
             "on Oct 16, so the two overlap. Confirm the intended relationship.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("last-day-of-classes", "accelerated-1", "Last Day of Classes", "2026-10-16",
       wd="Friday", etype="instruction-period", affects="yes", campus=ACCEL_CAMPUS,
       aliases=["when does accelerated 1 end", "last day accelerated session 1"]),

    ev("final-grades-due", "accelerated-1", "Final Grades Due", "2026-10-19", wd="Monday",
       etype="grading", affects="not-applicable", campus=ACCEL_CAMPUS,
       aliases=["accelerated 1 grades"]),
]

# --------------------------------------------------------------------------
# ACCELERATED SESSION II  (Oct 19 - Dec 11, 2026)  page 2
# --------------------------------------------------------------------------
A2 = [
    ev("session-dates", "accelerated-2", "Accelerated Session II", "2026-10-19",
       end="2026-12-11", etype="instruction-period", affects="yes", campus=ACCEL_CAMPUS,
       aliases=["accelerated session 2", "8 week session 2", "second 8 week session",
                "accelerated II dates"],
       notes="8-week accelerated session offered at the Dover, Wilmington, and Georgetown campuses."),

    ev("classes-begin", "accelerated-2", "Classes Begin", "2026-10-19", wd="Monday",
       etype="instruction-period", affects="yes", campus=ACCEL_CAMPUS,
       aliases=["when does accelerated 2 start", "first day accelerated session 2"],
       notes="Source gives no start time for Accelerated II (Accelerated I specifies 8:00 am).",
       flags=["source-ambiguous"]),

    ev("late-registration-begins", "accelerated-2", "Late Registration Begins", "2026-10-19",
       wd="Monday", etype="registration", affects="not-applicable", campus=ACCEL_CAMPUS,
       action=True, action_summary="Late registration for Accelerated Session II opens.",
       aliases=["late registration accelerated 2"]),

    ev("last-day-add-drop", "accelerated-2",
       "Last Day to Add and Drop Courses (without financial penalty)", "2026-10-22",
       wd="Thursday", etype="deadline", affects="yes", campus=ACCEL_CAMPUS, action=True,
       action_summary="Last day to add or drop an Accelerated II course with no financial penalty.",
       refs=["ref.refund-schedule.accelerated"],
       aliases=["add drop deadline accelerated 2", "drop an accelerated 2 class"]),

    ev("withdraw-window-opens", "accelerated-2",
       "Withdrawal Period Begins ($10 fee per course, W on transcript)", "2026-10-23",
       wd="Friday", etype="deadline", affects="not-applicable", campus=ACCEL_CAMPUS,
       fee={"amount_usd": 10, "description": "$10 fee for each withdrawn course"},
       refs=["ref.refund-schedule.accelerated"],
       aliases=["withdraw from accelerated 2"],
       notes="A grade of W will be placed on the transcript."),

    ev("non-attendance-documentation", "accelerated-2",
       "Documentation for Non-Attendance Period", "2026-10-23", end="2026-10-26",
       wd="Friday-Monday", etype="administrative", affects="not-applicable",
       campus=ACCEL_CAMPUS),

    ev("census-date", "accelerated-2", "Census Date", "2026-10-29", wd="Thursday",
       etype="administrative", affects="not-applicable", campus=ACCEL_CAMPUS),

    ev("early-alert-period", "accelerated-2", "Academic Early Alert Period", "2026-11-02",
       wd="Monday", etype="administrative", affects="not-applicable", campus=ACCEL_CAMPUS,
       notes="Source lists a single start date with no end date.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("midterm-evaluations", "accelerated-2", "Mid-Term Evaluations Administered",
       "2026-11-09", end="2026-11-13", wd="Monday-Friday", etype="evaluation",
       affects="yes", campus=ACCEL_CAMPUS,
       aliases=["accelerated 2 midterms"]),

    ev("midterm-grades-due", "accelerated-2", "Mid-Term Grades Due", "2026-11-16",
       wd="Monday", etype="grading", affects="not-applicable", campus=ACCEL_CAMPUS),

    ev("last-day-withdraw", "accelerated-2",
       "Last Day to Withdraw from Accelerated II Course(s) / University; "
       "Last Day to Submit Pass-Fail Request", "2026-11-23", wd="Monday", etype="deadline",
       affects="yes", campus=ACCEL_CAMPUS, action=True,
       action_summary="Last day to withdraw from an Accelerated II course or the University, "
                      "and last day to request Pass-Fail grading for an Accelerated II course.",
       refs=["ref.refund-schedule.accelerated"],
       aliases=["withdrawal deadline accelerated 2", "pass fail accelerated 2"],
       notes="Source directs readers to the academic catalog for the Pass-Fail policy."),

    ev("thanksgiving-recess", "accelerated-2", "Thanksgiving Recess", "2026-11-26",
       end="2026-11-29", wd="Thursday-Sunday", etype="recess", affects="no",
       campus=ACCEL_CAMPUS,
       aliases=["thanksgiving break accelerated 2"],
       notes="Printed out of chronological order in the source (listed after the "
             "Nov 30 - Dec 11 course evaluation period).",
       flags=["listed-out-of-order"]),

    ev("course-evaluations", "accelerated-2", "Accelerated II Fall Course Evaluations",
       "2026-11-30", end="2026-12-11", wd="Monday-Friday", etype="evaluation",
       affects="not-applicable", campus=ACCEL_CAMPUS, action=True,
       action_summary="Complete course evaluations for Accelerated II courses.",
       aliases=["course evaluations accelerated 2"]),

    ev("final-examinations", "accelerated-2", "Final Examinations", "2026-12-07",
       end="2026-12-11", wd="Monday-Friday", etype="evaluation", affects="yes",
       campus=ACCEL_CAMPUS,
       aliases=["accelerated 2 finals", "final exams accelerated session 2"],
       notes="Source places the final examination period Dec 7-11 and the last day of classes "
             "on Dec 11, so the two overlap. Confirm the intended relationship.",
       flags=["source-ambiguous", "needs-owner-confirmation"]),

    ev("last-day-of-classes", "accelerated-2", "Last Day of Classes", "2026-12-11",
       wd="Friday", etype="instruction-period", affects="yes", campus=ACCEL_CAMPUS,
       aliases=["when does accelerated 2 end"]),

    ev("final-grades-due", "accelerated-2", "Final Grades Due", "2026-12-14", wd="Monday",
       etype="grading", affects="not-applicable", campus=ACCEL_CAMPUS,
       aliases=["accelerated 2 grades"]),

    ev("winter-recess-closure", "accelerated-2", "Winter Recess (University Closed)",
       "2026-12-24", end="2027-01-01", wd="Thursday-Friday", etype="closure", affects="no",
       campus=ACCEL_CAMPUS,
       notes="Source label reads 'Winter Recess Begins (University Closed)' for the Dec 24 - "
             "Jan 1 range, while the main calendar labels the same range 'Winter Recess "
             "(University Closed)'. Treated as the same closure.",
       flags=["source-ambiguous"]),
]


def build():
    records = MAIN + A1 + A2

    # Session boundaries the tool needs for day-count math (refund tiers, "am I in session").
    session_meta = {
        "main": {
            "label": "Main Fall Semester",
            "first_day_of_instruction": "2026-08-25",
            "last_day_of_classes": "2026-12-03",
            "last_day_to_add": "2026-09-03",
            "refund_table": "ref.refund-schedule.fall-spring",
        },
        "accelerated-1": {
            "label": "Accelerated Session I (8 weeks)",
            "first_day_of_instruction": "2026-08-25",
            "last_day_of_classes": "2026-10-16",
            "last_day_to_add": "2026-09-03",
            "refund_table": "ref.refund-schedule.accelerated",
        },
        "accelerated-2": {
            "label": "Accelerated Session II (8 weeks)",
            "first_day_of_instruction": "2026-10-19",
            "last_day_of_classes": "2026-12-11",
            "last_day_to_add": "2026-10-22",
            "refund_table": "ref.refund-schedule.accelerated",
        },
    }

    doc = {
        "collection": "academic-calendar",
        "term": "Fall 2026",
        "term_code": "202701",
        "discovery_card": {
            "id": "card.academic-calendar",
            "text": (
                "Academic calendar dates and deadlines for Delaware State University: semester "
                "start and end dates, add/drop and withdrawal deadlines, registration and "
                "advisement periods, holidays and university closures, final exam schedules, "
                "grade due dates, residence hall open and close dates, and payment due dates. "
                "Covers the main semester and the 8-week accelerated sessions at the Dover, "
                "Wilmington, and Georgetown campuses."
            ),
            "answered_by_tool": "academic_calendar",
            "note": "This card is embedded for semantic discovery; the records below are not. "
                    "Retrieval matches the card, the card routes to the tool, the tool returns the fact.",
        },
        "session_meta": session_meta,
        "records": records,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {OUT}  ({len(records)} records)")
    for s in ("main", "winter", "accelerated-1", "accelerated-2"):
        n = sum(1 for r in records if r["payload"]["session"] == s)
        print(f"  {s:<16} {n}")


if __name__ == "__main__":
    build()
