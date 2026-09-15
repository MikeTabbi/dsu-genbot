#!/usr/bin/env python3
"""
The validation gate. Nothing enters the index without passing.

Run in CI on every pull request to the content repo. Exit codes:
    0  passed (possibly with warnings)
    1  hard failures present -- do not index
    2  gate itself could not run

Warnings do not block indexing but DO block launch: the pre-launch bar is zero
unresolved warnings on Tier 0 content.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("FATAL: pip install jsonschema", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"
KB = ROOT / "kb"

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

PAYLOAD_SCHEMA_FOR = {
    ("structured-record", "academic-calendar"): "structured-record.calendar.schema.json",
    ("structured-record", "refund-schedule"): "structured-record.reference-table.schema.json",
    ("structured-record", "contacts"): "structured-record.contact.schema.json",
    ("structured-record", "routing"): "structured-record.routing.schema.json",
    ("qa-pair", None): "qa-pair.schema.json",
    ("prose", None): "prose-chunk.schema.json",
}

# What a complete term calendar is expected to contain, per session.
EXPECTED_COVERAGE = {
    "main": ["instruction-period", "deadline", "registration", "closure", "recess",
             "grading", "evaluation", "housing", "payment", "administrative"],
    "accelerated-1": ["instruction-period", "deadline", "registration", "closure",
                      "grading", "evaluation", "housing", "administrative"],
    "accelerated-2": ["instruction-period", "deadline", "registration", "closure",
                      "recess", "grading", "evaluation", "housing", "administrative"],
}

# Named records every session of a term should have. This is the check that
# surfaces "Accelerated I has no census date while the main semester does" --
# an event-TYPE check is too coarse to see it, because both sessions have other
# administrative records.
EXPECTED_RECORDS = {
    "main": ["classes-begin", "last-day-add-drop", "last-day-withdraw",
             "last-day-of-classes", "final-examinations", "final-grades-due",
             "midterm-grades-due", "census-date"],
    "accelerated-1": ["classes-begin", "last-day-add-drop", "last-day-withdraw",
                      "last-day-of-classes", "final-examinations", "final-grades-due",
                      "midterm-grades-due", "census-date"],
    "accelerated-2": ["classes-begin", "last-day-add-drop", "last-day-withdraw",
                      "last-day-of-classes", "final-examinations", "final-grades-due",
                      "midterm-grades-due", "census-date"],
}


class Report:
    def __init__(self):
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []
        self.checks_run = 0

    def fail(self, check, rid, msg):
        self.failures.append(f"[{check}] {rid}: {msg}")

    def warn(self, check, rid, msg):
        self.warnings.append(f"[{check}] {rid}: {msg}")

    def note(self, msg):
        self.info.append(msg)


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def load_schema(name):
    return json.loads((SCHEMAS / name).read_text())


def collect_records() -> list[dict]:
    records = []
    for path in sorted(KB.rglob("*.json")):
        doc = json.loads(path.read_text())
        for r in doc.get("records", []):
            r["_file"] = str(path.relative_to(ROOT))
            records.append(r)
    return records


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def check_schemas(records, rep: Report):
    env = Draft202012Validator(load_schema("envelope.schema.json"))
    cache: dict[str, Draft202012Validator] = {}

    for r in records:
        rid = r["id"]
        body = {k: v for k, v in r.items() if not k.startswith("_")}
        for e in sorted(env.iter_errors(body), key=lambda e: e.path):
            rep.fail("envelope-schema", rid, f"{'.'.join(map(str, e.path)) or '<root>'}: {e.message}")
        rep.checks_run += 1

        key = (r["kb_class"], r["collection"])
        name = PAYLOAD_SCHEMA_FOR.get(key) or PAYLOAD_SCHEMA_FOR.get((r["kb_class"], None))
        if not name:
            rep.warn("payload-schema", rid,
                     f"no payload schema registered for class={r['kb_class']} collection={r['collection']}")
            continue
        if name not in cache:
            cache[name] = Draft202012Validator(load_schema(name))
        for e in sorted(cache[name].iter_errors(r["payload"]), key=lambda e: e.path):
            rep.fail("payload-schema", rid, f"{'.'.join(map(str, e.path)) or '<root>'}: {e.message}")
        rep.checks_run += 1


def check_weekdays(records, rep: Report):
    """Catches transcription errors. 'September 4 (Friday)' is verified against
    the real 2026 calendar."""
    for r in records:
        p = r["payload"]
        pub = p.get("weekday_as_published")
        if not pub or "date_start" not in p:
            continue
        rep.checks_run += 1
        parts = [x.strip() for x in pub.split("-")]
        actual_start = WEEKDAYS[_d(p["date_start"]).weekday()]
        if parts[0] != actual_start:
            rep.fail("weekday-crosscheck", r["id"],
                     f"source says {parts[0]} for {p['date_start']}, actual weekday is {actual_start}")
        if len(parts) == 2 and p.get("date_end"):
            actual_end = WEEKDAYS[_d(p["date_end"]).weekday()]
            if parts[1] != actual_end:
                rep.fail("weekday-crosscheck", r["id"],
                         f"source says {parts[1]} for end date {p['date_end']}, actual is {actual_end}")


def check_dates(records, rep: Report):
    for r in records:
        p = r["payload"]
        if "date_start" not in p:
            continue
        rep.checks_run += 1
        start = _d(p["date_start"])
        if p.get("date_end"):
            end = _d(p["date_end"])
            if end < start:
                rep.fail("date-sanity", r["id"], f"date_end {end} precedes date_start {start}")
        t = r["temporal"]
        eff_to = t.get("effective_to")
        if eff_to and start > _d(eff_to):
            rep.fail("date-sanity", r["id"],
                     f"event date {start} falls after effective_to {eff_to} -- record would "
                     "expire before the event happens")


def check_references(records, rep: Report):
    ids = {r["id"] for r in records}
    for r in records:
        for ref in r["payload"].get("references", []) + r["payload"].get("extracted_tables", []):
            rep.checks_run += 1
            if ref not in ids:
                rep.fail("reference-resolution", r["id"], f"references unknown record '{ref}'")
    # {{ref:...}} placeholders inside qa-pair answers
    for r in records:
        text = r["payload"].get("answer", "")
        for token in _ref_tokens(text):
            rep.checks_run += 1
            if token not in ids:
                rep.fail("reference-resolution", r["id"],
                         f"answer contains {{{{ref:{token}}}}} which does not resolve")


def _ref_tokens(text: str) -> list[str]:
    out, i = [], 0
    while (i := text.find("{{ref:", i)) != -1:
        j = text.find("}}", i)
        if j == -1:
            break
        out.append(text[i + 6:j].strip())
        i = j
    return out


def check_contradictions(records, rep: Report):
    """Two authoritative records asserting different dates for the same
    (collection, session, event_type, title) key."""
    buckets = defaultdict(list)
    for r in records:
        p = r["payload"]
        if "date_start" not in p or r["governance"]["authority"] != "authoritative":
            continue
        key = (r["collection"], p["session"], p["event_type"], _norm(p["title"]))
        buckets[key].append(r)
    for key, group in buckets.items():
        if len(group) < 2:
            continue
        rep.checks_run += 1
        dates = {r["payload"]["date_start"] for r in group}
        if len(dates) > 1:
            rep.fail("contradiction", " / ".join(r["id"] for r in group),
                     f"same event key {key[1]}/{key[2]}/'{key[3]}' asserted on {sorted(dates)}")
        else:
            rep.warn("duplicate-fact", " / ".join(r["id"] for r in group),
                     f"same fact stated by {len(group)} authoritative records -- one fact, one home")


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("(", " ").replace(")", " ").split())


def check_overlapping_rules(records, rep: Report):
    """A reference table whose rows overlap silently contradicts itself."""
    for r in records:
        rules = r["payload"].get("rules")
        if not rules:
            continue
        rep.checks_run += 1
        numeric = [x for x in rules
                   if isinstance(x["condition"].get("value"), (int, float))
                   and x["condition"]["op"] in ("<=", "<")]
        bounds = [x["condition"]["value"] for x in numeric]
        if bounds != sorted(bounds):
            rep.fail("overlapping-rules", r["id"], f"upper-bound rules out of order: {bounds}")
        if any(x["condition"].get("field") != numeric[0]["condition"]["field"] for x in numeric) if numeric else False:
            rep.warn("overlapping-rules", r["id"], "upper-bound rules mix different input fields")
        if "overlapping-rules" in r["payload"].get("data_quality_flags", []):
            rep.warn("overlapping-rules", r["id"],
                     "source table is self-flagged as overlapping -- the tool must return "
                     "answer_type='ambiguous' in the overlap zone, not pick a row")
        if r["payload"].get("boundary_basis") is None:
            rep.warn("undefined-boundary-basis", r["id"],
                     "day counts have no stated basis (does the first day of instruction "
                     "count as day 0 or day 1?) -- changes the refund a student receives")


def check_flags(records, rep: Report):
    for r in records:
        for f in r["payload"].get("data_quality_flags", []):
            rep.warn("source-data-quality", r["id"],
                     f"{f}" + (f" -- {r['payload']['notes']}" if r["payload"].get("notes") else ""))


def check_governance(records, rep: Report):
    for r in records:
        rep.checks_run += 1
        tier = r["governance"]["data_tier"]
        if tier == 3:
            rep.fail("governance", r["id"], "Tier 3 content must never be indexed")
        if tier > 0:
            rep.warn("governance", r["id"],
                     f"Tier {tier} content is out of Phase 1 scope (Tier 0 only)")
        if r["review"].get("reviewed_by") in (None, "pending-liaison-signoff"):
            rep.warn("signoff", r["id"], "no liaison sign-off recorded -- blocks launch")
        if not r["citation"].get("url"):
            rep.warn("citation", r["id"], "no citation URL -- answers cannot be verified by the student")


def check_routing(records, rep: Report):
    """Routing invariants. The Tier 3 pairing is the important one: a sensitive
    topic whose coverage drifts to 'partial' means the bot would start trying to
    answer it, which is the exact failure the four-tier model exists to prevent."""
    ids = {r["id"] for r in records}
    offices = {r["id"] for r in records
               if r["collection"] == "contacts" and r["payload"].get("contact_type") == "office"}
    queues = set()
    seen_alias: dict[str, str] = {}

    for r in records:
        if r["collection"] != "routing":
            continue
        p = r["payload"]
        rep.checks_run += 1

        if p["topic_data_tier"] == 3 and p["kb_coverage"] != "never-answer":
            rep.fail("routing-tier", r["id"],
                     f"topic_data_tier 3 must pair with kb_coverage 'never-answer', "
                     f"got '{p['kb_coverage']}'")
        if p["kb_coverage"] == "never-answer" and p["topic_data_tier"] != 3:
            rep.warn("routing-tier", r["id"],
                     "kb_coverage 'never-answer' with a non-Tier-3 topic -- intended?")
        if p["kb_coverage"] == "never-answer" and not p.get("answer_guidance"):
            rep.fail("routing-tier", r["id"],
                     "never-answer topic has no answer_guidance; the handoff behavior must "
                     "be written down, not left to the model")
        if p["urgency"] == "crisis" and p["kb_coverage"] != "never-answer":
            rep.fail("routing-crisis", r["id"],
                     "crisis urgency must be never-answer")
        if p.get("requires_own_record_lookup") and p["kb_coverage"] == "answerable":
            rep.fail("routing-phase", r["id"],
                     "marked answerable but needs the student's own records -- out of scope "
                     "until Phase 3, so it must route")

        oc = p.get("office_contact_id")
        if oc and oc not in ids:
            rep.fail("routing-reference", r["id"], f"office_contact_id '{oc}' does not resolve")
        elif oc and oc not in offices:
            rep.warn("routing-reference", r["id"],
                     f"office_contact_id '{oc}' is not an office-type contact")
        queues.add(p["escalation_queue"])

        # A phrase routed to two different offices is a coin flip at answer time.
        for a in p["aliases"]:
            key = a.strip().lower()
            if key in seen_alias and seen_alias[key] != p["office"]:
                rep.warn("routing-alias", r["id"],
                         f"alias '{a}' already routes to {seen_alias[key]}; ambiguous routing")
            seen_alias[key] = p["office"]

    # Every escalation queue named anywhere must be a real, staffed destination.
    for r in records:
        q = r["owner"]["escalation_queue"]
        rep.checks_run += 1
        if q not in queues and r["collection"] == "routing":
            rep.warn("routing-queue", r["id"], f"queue '{q}' has no routing entry")

    if queues:
        rep.note(f"escalation queues in use: {', '.join(sorted(queues))}")


def check_contacts(records, rep: Report):
    for r in records:
        if r["collection"] != "contacts":
            continue
        p = r["payload"]
        rep.checks_run += 1
        ch = p["channels"]
        if not any(ch.get(k) for k in ("email", "phone", "ticket_url", "url")):
            rep.fail("contact-channels", r["id"], "no reachable channel at all")
        if p["source_authority"] == "web-scrape" and r["temporal"].get("effective_to") is None:
            rep.fail("contact-expiry", r["id"],
                     "a scraped contact must expire -- an unexpiring scraped roster becomes "
                     "permanently wrong")
        if p["contact_type"] == "person" and p["source_authority"] == "web-scrape":
            rep.warn("contact-provenance", r["id"],
                     "person record from web-scrape; answers must carry a freshness caveat "
                     "until superseded by a system-of-record import")
        if p.get("do_not_publish"):
            rep.note(f"{r['id']}: do_not_publish set -- excluded from the index by design")


def check_staleness(records, rep: Report, today: date):
    for r in records:
        rep.checks_run += 1
        nd = r["review"].get("next_due")
        if nd and _d(nd) < today:
            rep.warn("staleness", r["id"], f"review overdue since {nd}")
        et = r["temporal"].get("effective_to")
        if et and _d(et) < today:
            rep.warn("expired", r["id"], f"expired {et} -- must be removed from the index")
        if et is None:
            rep.warn("no-expiry", r["id"], "no effective_to; content with no expiry needs justification")


def check_coverage(records, rep: Report):
    have = defaultdict(set)
    for r in records:
        p = r["payload"]
        if r["collection"] == "academic-calendar" and "session" in p:
            have[p["session"]].add(p["event_type"])
    for sess, expected in EXPECTED_COVERAGE.items():
        rep.checks_run += 1
        missing = [e for e in expected if e not in have.get(sess, set())]
        if missing:
            rep.warn("coverage", f"session:{sess}",
                     f"no records of type: {', '.join(missing)}")
    # Named records every session should have -- catches asymmetry between
    # sessions that a type-level check cannot see.
    for sess, slugs in EXPECTED_RECORDS.items():
        for slug in slugs:
            rep.checks_run += 1
            if not any(r["id"].endswith(f".{sess}.{slug}") for r in records):
                present_elsewhere = sorted(
                    s for s in EXPECTED_RECORDS
                    if any(r["id"].endswith(f".{s}.{slug}") for r in records)
                )
                detail = (f" (present for: {', '.join(present_elsewhere)})"
                          if present_elsewhere else "")
                rep.warn("coverage", f"session:{sess}",
                         f"no '{slug}' record{detail}")


# --------------------------------------------------------------------------

def main(as_of: str | None = None):
    today = _d(as_of) if as_of else date.today()
    rep = Report()
    records = collect_records()
    rep.note(f"{len(records)} records across {len({r['_file'] for r in records})} files")

    check_schemas(records, rep)
    check_weekdays(records, rep)
    check_dates(records, rep)
    check_references(records, rep)
    check_contradictions(records, rep)
    check_overlapping_rules(records, rep)
    check_routing(records, rep)
    check_contacts(records, rep)
    check_governance(records, rep)
    check_staleness(records, rep, today)
    check_coverage(records, rep)
    check_flags(records, rep)
    rep.warn("citation-reachability", "*", "SKIPPED -- no network access in this run; "
             "enable in CI to catch dead source URLs")

    print("=" * 78)
    print(f"DSU KB VALIDATION GATE   as of {today}")
    print("=" * 78)
    for n in rep.info:
        print(f"  {n}")
    print(f"  {rep.checks_run} checks executed\n")

    if rep.failures:
        print(f"HARD FAILURES ({len(rep.failures)}) -- content must not be indexed:")
        for f in rep.failures:
            print(f"  x {f}")
        print()
    else:
        print("HARD FAILURES: none\n")

    if rep.warnings:
        grouped = defaultdict(list)
        for w in rep.warnings:
            grouped[w.split("]")[0].lstrip("[")].append(w.split("] ", 1)[1])
        print(f"WARNINGS ({len(rep.warnings)}) -- do not block indexing, DO block launch:")
        for check, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            print(f"\n  {check}  ({len(items)})")
            for it in items[:6]:
                print(f"    ! {it}")
            if len(items) > 6:
                print(f"    ... and {len(items) - 6} more")
        print()

    status = "failed" if rep.failures else ("passed-with-warnings" if rep.warnings else "passed")
    print("=" * 78)
    print(f"RESULT: {status}")
    print("=" * 78)
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
