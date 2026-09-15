#!/usr/bin/env python3
"""
Authors the topic-routing table and the pilot-department office contacts.

This is the one piece of the knowledge base that cannot be harvested from
anywhere: no page on desu.edu says "a hold on your account is Student Accounts
unless it's academic, in which case it's Advisement." That mapping lives in
people's heads, and writing it down is most of what makes the bot feel like a
front desk instead of a search box.

Phone numbers and emails are deliberately left NULL here. Roughly 80 department
numbers sit on a single page -- https://www.desu.edu/about/campus-contacts --
and the honest way to fill these in is one crawler run against that page
followed by a human check, not by me typing numbers I have not verified:

    python3 crawl_directory.py --crawl --urls one-page.txt \\
        --out ../kb/reference/contacts-offices-raw.json

Then paste the confirmed values into kb/reference/routing.json and clear the
`office-contact-unpopulated` flag.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "kb" / "reference" / "routing.json"
TODAY = "2026-09-02"

# (office display name, id slug, escalation queue, aliases)
OFFICES = [
    ("Records & Registration", "records-registration", "records-registration",
     ["the registrar", "registrar's office", "records office", "registration office"]),
    ("Student Accounts", "student-accounts", "student-accounts",
     ["the bursar", "bursar's office", "billing", "student billing", "cashier"]),
    ("Financial Aid", "financial-aid", "financial-aid",
     ["aid office", "financial aid office", "fafsa office", "scholarship office"]),
    ("IT Help Desk", "it-help-desk", "it-help-desk",
     ["help desk", "tech support", "IT", "computer help", "OIT"]),
    ("Housing & Residence Life", "housing", "housing",
     ["res life", "residence life", "housing office", "dorm office", "RA office"]),
    ("Academic Advisement", "advisement", "advisement",
     ["advising", "academic advising", "my advisor", "advisement center"]),
]

# topic, aliases, office slug, coverage, tier, needs_own_record, guidance, handoff, urgency
T = [
    # ---------------- Records & Registration ----------------
    ("Registering for classes",
     ["how do I register", "sign up for classes", "add a class", "course registration",
      "when can I register"], "records-registration", "partial", 0, False,
     "Registration windows and add/drop deadlines come from the academic calendar. "
     "Eligibility, holds, and open seats do not.",
     ["term", "course or CRN if known", "whether they've met with an advisor"], "time-sensitive"),
    ("Dropping or withdrawing from a course",
     ["drop a class", "withdraw from a class", "quit a course", "take a W",
      "get out of a class"], "records-registration", "partial", 0, False,
     "Deadlines and the W/refund consequences are answerable from the calendar and refund "
     "schedule. Whether it's the right choice for the student is not.",
     ["course", "academic session", "reason if they offer it"], "time-sensitive"),
    ("Transcript request",
     ["get my transcript", "order a transcript", "send my transcript",
      "official transcript", "unofficial transcript"], "records-registration",
     "route-only", 0, True, "Requests are tied to the student's record and any balance owed.",
     ["official or unofficial", "where it's being sent", "deadline"], "routine"),
    ("Enrollment or degree verification",
     ["enrollment verification", "proof of enrollment", "verify I'm a student",
      "insurance form", "degree verification"], "records-registration", "route-only", 0, True,
     None, ["who needs the verification", "deadline"], "routine"),
    ("Grades and grade posting",
     ["when do grades come out", "my grades aren't posted", "final grades",
      "midterm grades", "grade change"], "records-registration", "partial", 0, True,
     "Grade due dates are on the academic calendar. A student's own grades are not "
     "accessible to the assistant.",
     ["term", "course", "instructor"], "routine"),
    ("Incomplete grade",
     ["I have an incomplete", "remove an incomplete", "I grade", "finish an incomplete"],
     "records-registration", "partial", 0, False,
     "The deadline to remove incompletes is on the calendar; the arrangement is between "
     "the student and the instructor.",
     ["course", "instructor", "term the incomplete is from"], "time-sensitive"),
    ("Applying for graduation",
     ["apply to graduate", "graduation application", "am I graduating",
      "senior audit", "commencement"], "records-registration", "partial", 0, True,
     "The application deadline is on the calendar. Whether requirements are met is a "
     "degree audit and requires the student's record.",
     ["expected graduation term", "major", "whether they've applied already"], "time-sensitive"),
    ("Name, address, or personal information change",
     ["change my name", "update my address", "change my legal name",
      "update my phone number", "preferred name"], "records-registration", "route-only",
     0, True, None, ["what's changing", "whether documentation is needed"], "routine"),
    ("Pass-Fail request",
     ["take a class pass fail", "pass/fail option", "switch to pass fail"],
     "records-registration", "partial", 0, False,
     "The deadline is on the calendar. Eligibility rules are in the academic catalog and "
     "should not be summarized from memory.",
     ["course", "session"], "time-sensitive"),

    # ---------------- Student Accounts ----------------
    ("Tuition bill and payment",
     ["my bill", "how much do I owe", "pay my tuition", "payment due date",
      "where do I pay"], "student-accounts", "partial", 0, True,
     "Payment due dates are on the academic calendar. A student's balance is not "
     "accessible to the assistant.",
     ["term", "whether they're on a payment plan"], "time-sensitive"),
    ("Payment plan",
     ["set up a payment plan", "pay in installments", "monthly payments",
      "can I pay later"], "student-accounts", "route-only", 0, True, None,
     ["term", "amount they can pay now"], "time-sensitive"),
    ("Refund for a dropped or withdrawn course",
     ["will I get my money back", "refund for dropping", "tuition refund",
      "am I getting a refund"], "student-accounts", "partial", 0, True,
     "The published refund schedule can be applied to a date, but it currently contradicts "
     "itself in the first nine days -- see the data-quality report. Amounts are advisory "
     "until Student Accounts confirms.",
     ["withdrawal date", "session", "course"], "time-sensitive"),
    ("Financial hold on my account",
     ["I have a hold", "why can't I register", "account hold", "balance hold",
      "hold on my account"], "student-accounts", "route-only", 0, True,
     "Holds are account-specific. Note that not every hold is financial -- academic and "
     "advisement holds route elsewhere, so ask before assuming.",
     ["what the hold message says", "term they're trying to register for"], "time-sensitive"),
    ("1098-T tax form",
     ["1098-T", "tax form for tuition", "tuition tax statement"],
     "student-accounts", "route-only", 0, True, None, ["tax year"], "routine"),
    ("Refund disbursement and direct deposit",
     ["when will I get my refund check", "direct deposit", "refund disbursement",
      "excess aid refund"], "student-accounts", "route-only", 0, True, None,
     ["term", "whether direct deposit is set up"], "routine"),

    # ---------------- Financial Aid ----------------
    ("FAFSA and aid application",
     ["fafsa", "apply for financial aid", "aid application", "fafsa deadline"],
     "financial-aid", "partial", 0, False,
     "General process and deadlines only. Anything about the student's own application "
     "routes to the office.",
     ["aid year", "whether the FAFSA is submitted"], "time-sensitive"),
    ("Award letter and aid package",
     ["my award letter", "how much aid did I get", "aid package", "my financial aid offer"],
     "financial-aid", "route-only", 0, True, None, ["aid year"], "routine"),
    ("Verification and required documents",
     ["aid verification", "they need documents", "selected for verification",
      "missing paperwork financial aid"], "financial-aid", "route-only", 0, True, None,
     ["what document was requested", "aid year"], "time-sensitive"),
    ("Scholarships",
     ["scholarships", "apply for a scholarship", "scholarship deadline",
      "institutional scholarship"], "financial-aid", "partial", 0, False, None,
     ["type of scholarship", "class year"], "routine"),
    ("Satisfactory Academic Progress appeal",
     ["SAP appeal", "lost my financial aid", "aid suspension", "appeal my aid"],
     "financial-aid", "route-only", 0, True,
     "Sensitive and consequential. Route promptly and warmly; do not describe appeal odds.",
     ["term", "whether they've received an SAP notice"], "time-sensitive"),
    ("Work study",
     ["work study", "campus job", "federal work study", "student employment"],
     "financial-aid", "partial", 0, False, None, ["whether work study is in their award"],
     "routine"),

    # ---------------- IT Help Desk ----------------
    ("Password reset and account lockout",
     ["reset my password", "I'm locked out", "forgot my password", "can't log in",
      "password expired"], "it-help-desk", "answerable", 0, False,
     "Self-service reset steps are documented and stable. This is the single highest-volume "
     "question on most campuses and should be fully answerable without a handoff.",
     ["username", "what error they see"], "time-sensitive"),
    ("Multi-factor authentication",
     ["MFA", "two factor", "authenticator app", "new phone MFA", "verification code"],
     "it-help-desk", "partial", 0, False,
     "Setup steps are answerable. Re-enrolling a lost device needs identity verification.",
     ["whether they still have the old device", "phone model"], "time-sensitive"),
    ("Campus wifi and network",
     ["wifi", "can't connect to wifi", "internet in my dorm", "network is down",
      "ethernet"], "it-help-desk", "partial", 0, False, None,
     ["building and room", "device type"], "routine"),
    ("Email access",
     ["my email", "webmail", "outlook", "can't get my email", "student email"],
     "it-help-desk", "partial", 0, False, None, ["device", "error message"], "routine"),
    ("Learning management system access",
     ["blackboard", "canvas", "my courses aren't showing", "LMS",
      "can't see my class online"], "it-help-desk", "partial", 0, False,
     "Access problems are IT. Missing course content is the instructor.",
     ["course", "whether registration is confirmed"], "time-sensitive"),
    ("Banner Self-Service access",
     ["banner", "self service", "can't get into banner", "banner 9"],
     "it-help-desk", "partial", 0, False, None, ["error message", "username"], "routine"),

    # ---------------- Housing ----------------
    ("Housing application and room assignment",
     ["apply for housing", "my room assignment", "where am I living",
      "housing application", "get a dorm"], "housing", "partial", 0, True, None,
     ["term", "class year", "whether they've applied"], "time-sensitive"),
    ("Move-in and move-out dates",
     ["when can I move in", "when do the dorms open", "move out date",
      "when do I have to leave"], "housing", "answerable", 0, False,
     "Residence hall open and close dates are on the academic calendar and fully answerable.",
     [], "routine"),
    ("Break and holiday housing",
     ["stay over thanksgiving", "housing during break", "winter break housing",
      "can I stay in my dorm over break"], "housing", "partial", 0, False,
     "The calendar gives hall closing dates; whether break housing is available and how to "
     "request it is a Housing question. Note the calendar publishes no residence-hall dates "
     "for the accelerated sessions.",
     ["which break", "dates needed"], "time-sensitive"),
    ("Room change or roommate issue",
     ["change my room", "roommate problem", "room swap", "I want to move rooms",
      "my roommate"], "housing", "route-only", 0, False,
     "Interpersonal. Route with warmth and without editorializing.",
     ["building and room", "nature of the issue at a high level"], "routine"),
    ("Maintenance request",
     ["my ac is broken", "maintenance request", "work order", "something is broken in my room",
      "no hot water"], "housing", "route-only", 0, False, None,
     ["building and room", "what's broken", "whether it's urgent"], "time-sensitive"),
    ("Meal plan",
     ["meal plan", "dining dollars", "change my meal plan", "flex dollars"],
     "housing", "partial", 0, True, None, ["current plan if known", "term"], "routine"),

    # ---------------- Advisement ----------------
    ("Choosing courses for next term",
     ["what classes should I take", "pick my classes", "course selection",
      "what do I need to graduate"], "advisement", "route-only", 0, True,
     "Requires the student's degree progress. The advisement period dates are on the calendar.",
     ["major", "class year", "term"], "time-sensitive"),
    ("Changing major or adding a minor",
     ["change my major", "add a minor", "switch majors", "declare a major",
      "double major"], "advisement", "partial", 0, False, None,
     ["current major", "intended major"], "routine"),
    ("Degree audit and progress",
     ["degree audit", "how many credits do I need", "am I on track",
      "what requirements do I have left"], "advisement", "route-only", 0, True, None,
     ["major", "expected graduation term"], "routine"),
    ("Academic probation and early alert",
     ["academic probation", "early alert", "I got a warning", "failing a class",
      "academic standing"], "advisement", "route-only", 0, True,
     "Sensitive. Lead with support, not procedure. The Early Alert period is on the calendar.",
     ["course", "term", "whether they've been contacted already"], "time-sensitive"),
    ("Tutoring and academic support",
     ["tutoring", "I need help in a class", "study help", "academic support",
      "writing center"], "advisement", "partial", 0, False, None,
     ["course", "type of help needed"], "routine"),

    # ---------------- Tier 3: never answer, always route ----------------
    ("Mental health support",
     ["I need to talk to someone", "counseling", "I'm struggling", "therapist",
      "mental health", "I'm depressed"], "advisement", "never-answer", 3, False,
     "Follow the crisis protocol. Do not attempt advice, assessment, or triage questions. "
     "Offer Counseling Services and the 988 Suicide & Crisis Lifeline warmly and directly. "
     "This routing exists to guarantee a human path, not to enable a KB answer.",
     [], "crisis"),
    ("Sexual misconduct, harassment, or discrimination",
     ["title ix", "harassment", "assault", "discrimination", "report misconduct",
      "someone hurt me"], "advisement", "never-answer", 3, False,
     "Follow the crisis protocol and the Title IX notice requirements confirmed in Phase 0. "
     "Provide the reporting path; do not ask for details, do not summarize policy, do not "
     "characterize what happened.",
     [], "crisis"),
    ("Immediate safety emergency",
     ["emergency", "call the police", "I'm in danger", "someone is hurt",
      "public safety"], "advisement", "never-answer", 3, False,
     "Direct to 911 and DSU Public Safety immediately, at the top of the response, before "
     "anything else.",
     [], "crisis"),
    ("Disciplinary or conduct matter",
     ["student conduct", "I got written up", "disciplinary hearing", "code of conduct violation"],
     "advisement", "never-answer", 3, False,
     "Tier 3. Route to the appropriate office; hold no content and offer no interpretation.",
     [], "routine"),
]


def env(rid, coll, payload, schema_dept, queue, tier=0, authority="authoritative"):
    body = json.dumps(payload, sort_keys=True).encode()
    return {
        "id": rid,
        "kb_class": "structured-record",
        "collection": coll,
        "payload": payload,
        "source": {
            "type": "authored",
            "title": "DSU Chatbot topic routing table",
            "uri": "https://www.desu.edu/about/campus-contacts",
            "source_updated": TODAY,
            "locator": payload.get("topic") or payload.get("display_name"),
        },
        "owner": {
            "department": schema_dept,
            "liaison_role": f"{schema_dept} KB Liaison",
            "escalation_queue": queue,
        },
        "governance": {"data_tier": tier, "audience": ["student"], "authority": authority},
        "temporal": {"effective_from": TODAY, "effective_to": "2027-06-30", "supersedes": None},
        "review": {"cadence": "quarterly", "last_reviewed": None,
                   "next_due": "2026-12-01", "reviewed_by": "pending-liaison-signoff"},
        "citation": {"label": f"{schema_dept}, Delaware State University",
                     "url": "https://www.desu.edu/about/campus-contacts"},
        "provenance": {
            "ingested_at": TODAY + "T00:00:00Z",
            "ingest_method": "manual-authoring",
            "content_hash": "sha256:" + hashlib.sha256(body).hexdigest()[:32],
            "validation_status": "unvalidated",
        },
    }


def build():
    records = []

    # Office contacts. Channels intentionally null -- see the module docstring.
    for name, slug, queue, aliases in OFFICES:
        records.append(env(
            f"contact.office.{slug}", "contacts",
            {
                "contact_type": "office",
                "display_name": name,
                "department": name,
                "job_title": None,
                "reports_to_office": None,
                "channels": {"email": None, "phone": None, "phone_extension": None,
                             "fax": None, "url": "https://www.desu.edu/about/campus-contacts",
                             "ticket_url": None, "appointment_url": None},
                "location": None,
                "hours": None,
                "serves_audience": ["student"],
                "source_authority": "manually-verified",
                "preferred_contact_note": None,
                "aliases": aliases,
                "do_not_publish": False,
                "data_quality_flags": ["office-contact-unpopulated", "no-hours-published",
                                       "needs-owner-confirmation"],
            },
            name, queue))

    # Routing entries.
    for (topic, aliases, office_slug, coverage, tier, own_rec,
         guidance, handoff, urgency) in T:
        office_name = next(n for n, s, _, _ in OFFICES if s == office_slug)
        queue = next(q for _, s, q, _ in OFFICES if s == office_slug)
        slug = topic.lower().replace("&", "and")
        slug = "".join(c if c.isalnum() else "-" for c in slug).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        flags = ["office-contact-unpopulated"]
        if coverage == "never-answer":
            flags.append("needs-owner-confirmation")
        records.append(env(
            f"routing.{slug[:56]}", "routing",
            {
                "topic": topic,
                "aliases": aliases,
                "office": office_name,
                "office_contact_id": f"contact.office.{office_slug}",
                "escalation_queue": queue,
                "kb_coverage": coverage,
                # Sensitivity of the TOPIC. The routing record itself is Tier 0
                # public information and is indexed -- it is what guarantees the
                # handoff happens. See the schema note.
                "topic_data_tier": tier,
                "requires_own_record_lookup": own_rec,
                "answer_guidance": guidance,
                "handoff_needs": handoff,
                "urgency": urgency,
                "related_records": [],
                "data_quality_flags": flags,
            },
            office_name, queue, tier=0))

    doc = {
        "collection": "routing",
        "discovery_card": {
            "id": "card.routing",
            "text": ("Which Delaware State University office handles which student question, "
                     "and how to reach them: registration and records, tuition and billing, "
                     "financial aid, IT and password help, housing and dining, academic "
                     "advising. Answers 'who do I talk to about...' and 'where do I go for...' "
                     "questions."),
            "answered_by_tool": "routing",
            "note": "Class A. Authored institutional knowledge -- this mapping exists on no "
                    "web page and cannot be harvested.",
        },
        "authoring_note": (
            "Office phone numbers and emails are NULL by design. About 80 department numbers "
            "are on one page (desu.edu/about/campus-contacts); populate them with one crawler "
            "run plus a human check rather than by transcription. Clear the "
            "'office-contact-unpopulated' flag per record as each is confirmed."
        ),
        "coverage_summary": {},
        "records": records,
    }

    counts = {}
    for r in records:
        if r["collection"] == "routing":
            c = r["payload"]["kb_coverage"]
            counts[c] = counts.get(c, 0) + 1
    doc["coverage_summary"] = counts

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    n_route = sum(1 for r in records if r["collection"] == "routing")
    print(f"wrote {OUT}")
    print(f"  {len(OFFICES)} office contacts, {n_route} routing topics")
    for k in ("answerable", "partial", "route-only", "never-answer"):
        if k in counts:
            print(f"    {k:<14} {counts[k]}")


if __name__ == "__main__":
    build()
