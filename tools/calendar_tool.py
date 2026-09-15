#!/usr/bin/env python3
"""
Deterministic academic-calendar tool for the DSU chatbot.

This is the Class A retrieval path. The model never does date arithmetic on
retrieved text; it calls these functions and renders the structured result.

Every function returns an envelope with an explicit `answer_type`:

    resolved            -> a fact, with citation. Render it.
    needs_clarification -> the question is session-sensitive and the session is
                           unknown. Ask ONE question, using `options`.
    known_unknown       -> the calendar genuinely does not say. Do NOT infer.
                           Offer the escalation in `escalate`.
    ambiguous           -> the source contradicts itself. Do NOT pick a side.
                           Offer the escalation in `escalate`.
    no_coverage         -> nothing in the KB matches. Escalate.

`answer_type` is the contract that keeps the bot honest. A renderer that treats
known_unknown / ambiguous as "resolved" defeats the entire design.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

KB = Path(__file__).resolve().parent.parent / "kb"

SESSION_LABELS = {
    "main": "the main fall semester (15-week)",
    "accelerated-1": "Accelerated Session I (8-week, Aug 25 - Oct 16)",
    "accelerated-2": "Accelerated Session II (8-week, Oct 19 - Dec 11)",
    "winter": "the winter session",
}

# Types where being wrong about the session costs the student money or a grade.
# These force a clarifying question when the session is unknown AND the dates
# actually differ. Everything else answers for the main semester and notes the
# accelerated alternatives -- the conversation design allows one clarifying
# question, so it must be spent where it matters.
CLARIFY_TYPES = {"deadline"}
SESSION_SENSITIVE_TYPES = {"deadline", "instruction-period", "grading", "evaluation"}

_STOP = {
    "a", "an", "the", "is", "are", "do", "does", "did", "i", "my", "me", "we", "you",
    "to", "for", "of", "in", "on", "at", "and", "or", "it", "this", "that", "when",
    "what", "which", "can", "still", "have", "has", "get", "got", "be", "am", "was",
    "if", "there", "any", "how", "much", "many", "will", "would", "should", "class",
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

@dataclass
class Calendar:
    term: str
    term_code: str
    session_meta: dict
    records: list[dict]
    refund_tables: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, kb_root: Path = KB) -> "Calendar":
        cal = json.loads((kb_root / "calendar" / "fall-2026.json").read_text())
        refunds = json.loads((kb_root / "reference" / "refund-schedule.json").read_text())
        return cls(
            term=cal["term"],
            term_code=cal["term_code"],
            session_meta=cal["session_meta"],
            records=cal["records"],
            refund_tables={r["id"]: r for r in refunds["records"]},
        )

    def active(self, as_of: date) -> list[dict]:
        """Temporal validity enforced here, not in the prompt. Expired records
        are never returned -- that is what stops the bot from quoting last
        term's deadline."""
        out = []
        for r in self.records:
            t = r["temporal"]
            if _d(t["effective_from"]) > as_of:
                continue
            if t.get("effective_to") and _d(t["effective_to"]) < as_of:
                continue
            out.append(r)
        return out


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _today(as_of: str | date | None) -> date:
    if as_of is None:
        return date.today()
    return as_of if isinstance(as_of, date) else _d(as_of)


# --------------------------------------------------------------------------
# Result envelope
# --------------------------------------------------------------------------

def _result(answer_type: str, **kw) -> dict:
    out = {"answer_type": answer_type}
    out.update(kw)
    return out


def _cite(rec: dict) -> dict:
    return {
        "label": rec["citation"]["label"],
        "url": rec["citation"].get("url"),
        "source_updated": rec["source"]["source_updated"],
        "record_id": rec["id"],
    }


def _event_view(rec: dict, as_of: date) -> dict:
    p = rec["payload"]
    start, end = _d(p["date_start"]), _d(p["date_end"]) if p.get("date_end") else None
    return {
        "id": rec["id"],
        "title": p["title"],
        "session": p["session"],
        "session_label": SESSION_LABELS.get(p["session"], p["session"]),
        "event_type": p["event_type"],
        "date_start": p["date_start"],
        "date_end": p.get("date_end"),
        "weekday": start.strftime("%A"),
        "time": p.get("time"),
        "date_human": _human_range(start, end),
        "days_from_now": (start - as_of).days,
        "is_past": (end or start) < as_of,
        "in_progress": start <= as_of <= (end or start),
        "affects_classes": p["affects_classes"],
        "student_action_required": p["student_action_required"],
        "action_summary": p.get("action_summary"),
        "related_fee": p.get("related_fee"),
        "notes": p.get("notes"),
        "flags": p.get("data_quality_flags", []),
        "citation": _cite(rec),
    }


def _human_range(start: date, end: date | None) -> str:
    if not end or end == start:
        return start.strftime("%A, %B %-d, %Y")
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.strftime('%B %-d')}-{end.strftime('%-d, %Y')}"
    return f"{start.strftime('%B %-d')} - {end.strftime('%B %-d, %Y')}"


def _escalate(rec: dict | None, reason: str, queue: str | None = None) -> dict:
    return {
        "queue": queue or (rec["owner"]["escalation_queue"] if rec else "records-registration"),
        "department": rec["owner"]["department"] if rec else "Records & Registration",
        "reason": reason,
    }


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 1}


def _score(query: str, rec: dict) -> float:
    p = rec["payload"]
    q = _tokens(query)
    if not q:
        return 0.0
    best = 0.0
    for cand, weight in [(p["title"], 1.0)] + [(a, 1.15) for a in p.get("aliases", [])]:
        c = _tokens(cand)
        if not c:
            continue
        overlap = len(q & c)
        if not overlap:
            continue
        # Recall against the query, lightly penalising very broad candidates.
        best = max(best, weight * overlap / (len(q) ** 0.5 * len(c) ** 0.5))
    return best


# --------------------------------------------------------------------------
# Public tool functions
# --------------------------------------------------------------------------

def find_events(
    query: str | None = None,
    session: str | None = None,
    event_type: str | None = None,
    as_of: str | None = None,
    upcoming_only: bool = False,
    limit: int = 5,
    cal: Calendar | None = None,
) -> dict:
    """Look up calendar events. Primary entry point."""
    cal = cal or Calendar.load()
    today = _today(as_of)
    pool = cal.active(today)

    if session:
        pool = [r for r in pool if r["payload"]["session"] in (session, "all")]
    if event_type:
        pool = [r for r in pool if r["payload"]["event_type"] == event_type]
    if upcoming_only:
        pool = [
            r for r in pool
            if _d(r["payload"].get("date_end") or r["payload"]["date_start"]) >= today
        ]

    if query:
        scored = [(s, r) for r in pool if (s := _score(query, r)) > 0.30]
        scored.sort(key=lambda x: (-x[0], _d(x[1]["payload"]["date_start"])))
        hits = [r for _, r in scored[:limit]]
    else:
        pool.sort(key=lambda r: _d(r["payload"]["date_start"]))
        hits = pool[:limit]

    if not hits:
        return _result(
            "no_coverage",
            message="No academic calendar entry matches that.",
            escalate=_escalate(None, "No calendar record matched the student's question."),
        )

    # Same question, different answer per session -> clarify, but only where
    # being wrong is expensive and only where the dates genuinely differ.
    by_session = _group_by_session(hits)
    if session is None and _dates_differ(by_session):
        if {r["payload"]["event_type"] for r in hits} & CLARIFY_TYPES:
            return _result(
                "needs_clarification",
                question="Which session is your course in? The deadline is different for each.",
                options=_session_options(by_session, today),
            )
        # Lower-stakes: answer for the main semester, surface the alternatives.
        main_hits = by_session.get("main") or hits
        views = [_event_view(r, today) for r in main_hits]
        return _result(
            "resolved",
            events=views,
            as_of=today.isoformat(),
            assumed_session="main",
            alternatives=_session_options(
                {k: v for k, v in by_session.items() if k != "main"}, today
            ),
            caveats=[
                "Answered for the main fall semester. The 8-week accelerated sessions "
                "have different dates - see alternatives."
            ],
        )

    views = [_event_view(r, today) for r in hits]
    # Caveat only on the event the answer actually rests on -- flagging every
    # lower-ranked hit trains the renderer to ignore caveats.
    top_unstated = views[0]["affects_classes"] == "unstated"

    return _result(
        "resolved",
        events=views,
        as_of=today.isoformat(),
        caveats=(
            [f"The calendar does not state whether classes meet on {views[0]['title']}."]
            if top_unstated else []
        ),
        escalate=(
            _escalate(hits[0], "Calendar does not state whether classes meet on this date.")
            if top_unstated else None
        ),
    )


def _group_by_session(recs: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in recs:
        out.setdefault(r["payload"]["session"], []).append(r)
    for v in out.values():
        v.sort(key=lambda r: _d(r["payload"]["date_start"]))
    return out


def _dates_differ(by_session: dict[str, list[dict]]) -> bool:
    """True only when sessions actually disagree. Classes beginning Aug 25 for
    both the main semester and Accelerated I is not a reason to ask anything."""
    dates = {recs[0]["payload"]["date_start"] for recs in by_session.values() if recs}
    return len(dates) > 1


def _session_options(by_session: dict[str, list[dict]], today: date) -> list[dict]:
    return [
        {
            "value": s,
            "label": SESSION_LABELS.get(s, s),
            "preview": _event_view(recs[0], today)["date_human"],
        }
        for s, recs in sorted(by_session.items()) if recs
    ]


def deadline_for(
    action: str,
    session: str | None = None,
    as_of: str | None = None,
    cal: Calendar | None = None,
) -> dict:
    """Deadline lookup for a specific student action.

    action: one of 'add', 'drop', 'withdraw', 'audit', 'pass-fail',
            'remove-incomplete', 'graduation-application'
    """
    cal = cal or Calendar.load()
    today = _today(as_of)

    slug_map = {
        "add": ["last-day-add-drop"],
        "drop": ["last-day-add-drop", "drop-fee-effective"],
        "withdraw": ["last-day-withdraw", "withdraw-window-opens"],
        "audit": ["last-day-audit-change"],
        "pass-fail": ["last-day-withdraw"],
        "remove-incomplete": ["last-day-remove-incompletes"],
        "graduation-application": ["graduation-application-due"],
    }
    slugs = slug_map.get(action)
    if not slugs:
        return _result(
            "no_coverage",
            message=f"No deadline mapping for action '{action}'.",
            escalate=_escalate(None, f"Unmapped action: {action}"),
        )

    pool = [
        r for r in cal.active(today)
        if any(r["id"].endswith("." + s) for s in slugs)
    ]
    if session:
        pool = [r for r in pool if r["payload"]["session"] == session]

    if not pool:
        return _result(
            "no_coverage",
            message=f"No {action} deadline on record for {session or 'this term'}.",
            escalate=_escalate(None, f"Missing {action} deadline for session {session}."),
        )

    by_session = _group_by_session(pool)

    if session is None and len(by_session) > 1 and _dates_differ(by_session):
        return _result(
            "needs_clarification",
            question=f"Which session is the course in? The {action} deadline is different for each.",
            options=_session_options(by_session, today),
        )

    sess = session or next(iter(by_session))
    # The deadline is the slug listed first in slug_map, not the earliest date:
    # for "withdraw", the answer is the LAST day to withdraw, not the day the
    # withdrawal window opens.
    recs = sorted(
        by_session[sess],
        key=lambda r: next(i for i, s in enumerate(slugs) if r["id"].endswith("." + s)),
    )
    views = [_event_view(r, today) for r in recs]
    primary = views[0]

    return _result(
        "resolved",
        action=action,
        session=sess,
        session_label=SESSION_LABELS.get(sess, sess),
        deadline=primary["date_start"],
        deadline_human=primary["date_human"],
        days_remaining=(_d(primary["date_start"]) - today).days,
        has_passed=_d(primary["date_start"]) < today,
        events=views,
        as_of=today.isoformat(),
        follow_up=(
            "Ask whether they want the refund implications - call refund_schedule()."
            if action in ("drop", "withdraw") else None
        ),
    )


def upcoming(
    session: str | None = None,
    as_of: str | None = None,
    within_days: int = 21,
    action_required_only: bool = False,
    limit: int = 8,
    cal: Calendar | None = None,
) -> dict:
    """What's coming up. Backs 'what do I need to know about this month' and,
    in Phase 4, proactive nudges."""
    cal = cal or Calendar.load()
    today = _today(as_of)
    horizon = today + timedelta(days=within_days)

    pool = []
    for r in cal.active(today):
        p = r["payload"]
        start = _d(p["date_start"])
        if not (today <= start <= horizon):
            continue
        if session and p["session"] not in (session, "all"):
            continue
        if action_required_only and not p["student_action_required"]:
            continue
        pool.append(r)

    pool.sort(key=lambda r: (_d(r["payload"]["date_start"]), r["payload"]["title"]))
    views = [_event_view(r, today) for r in pool[:limit]]
    return _result(
        "resolved" if views else "no_coverage",
        as_of=today.isoformat(),
        window_days=within_days,
        events=views,
        message=None if views else f"Nothing on the calendar in the next {within_days} days.",
    )


def is_university_closed(on: str, cal: Calendar | None = None) -> dict:
    """Is the University closed on this date?"""
    cal = cal or Calendar.load()
    day = _d(on)

    for r in cal.active(day):
        p = r["payload"]
        if p["event_type"] != "closure":
            continue
        start = _d(p["date_start"])
        end = _d(p["date_end"]) if p.get("date_end") else start
        if start <= day <= end:
            return _result(
                "resolved",
                date=on,
                closed=True,
                reason=p["title"],
                events=[_event_view(r, day)],
                citation=_cite(r),
            )
    return _result(
        "resolved",
        date=on,
        closed=False,
        reason="No University closure is listed for this date on the Fall 2026 academic calendar.",
        caveats=["Individual office hours and weather closures are not covered by the calendar."],
    )


def classes_meet_on(
    on: str,
    session: str = "main",
    cal: Calendar | None = None,
) -> dict:
    """Do classes meet on this date? Returns known_unknown rather than guessing --
    this is the function that most protects the groundedness metric."""
    cal = cal or Calendar.load()
    day = _d(on)
    relevant = []
    for r in cal.active(day):
        p = r["payload"]
        if p["session"] not in (session, "all", "main"):
            continue
        start = _d(p["date_start"])
        end = _d(p["date_end"]) if p.get("date_end") else start
        if start <= day <= end and p["affects_classes"] != "not-applicable":
            relevant.append(r)

    for r in relevant:
        if r["payload"]["affects_classes"] == "no":
            return _result("resolved", date=on, classes_meet=False,
                           reason=r["payload"]["title"], citation=_cite(r))
    for r in relevant:
        if r["payload"]["affects_classes"] == "partial":
            return _result("resolved", date=on, classes_meet="partial",
                           reason=r["payload"]["title"],
                           detail=r["payload"].get("notes"), citation=_cite(r))
    for r in relevant:
        if r["payload"]["affects_classes"] == "unstated":
            return _result(
                "known_unknown",
                date=on,
                message=(
                    f"The calendar lists {r['payload']['title']} on "
                    f"{_d(r['payload']['date_start']).strftime('%A, %B %-d')}, but it does not "
                    "say whether classes meet."
                ),
                event=_event_view(r, day),
                escalate=_escalate(
                    r, "Calendar does not state whether classes meet; must not be inferred."
                ),
                citation=_cite(r),
            )

    if day.weekday() >= 5:
        return _result("resolved", date=on, classes_meet=False,
                       reason="Weekend - no regularly scheduled weekday classes.",
                       caveats=["Some weekend and online sections may still meet."])
    return _result("resolved", date=on, classes_meet=True,
                   reason="No closure, recess, or schedule exception is listed for this date.")


def refund_schedule(
    withdrawal_date: str,
    session: str = "main",
    cal: Calendar | None = None,
) -> dict:
    """Compute the tuition/fee refund for a withdrawal on a given date.

    Where the published table contradicts itself, this returns `ambiguous` and
    escalates rather than picking whichever row it read last.
    """
    cal = cal or Calendar.load()
    wd = _d(withdrawal_date)

    meta = cal.session_meta.get(session)
    if not meta:
        return _result("no_coverage", message=f"Unknown session '{session}'.",
                       escalate=_escalate(None, f"Unknown session {session}"))

    table = cal.refund_tables.get(meta["refund_table"])
    if not table:
        return _result("no_coverage", message="Refund table not found.",
                       escalate=_escalate(None, "Missing refund table"))

    first_day = _d(meta["first_day_of_instruction"])
    last_add = _d(meta["last_day_to_add"])

    if wd < first_day:
        return _result(
            "resolved", withdrawal_date=withdrawal_date, session=session,
            tuition_refund_pct=100, fees_refund_pct=100,
            rule_applied="Pre-registration to Last Day to Add Classes",
            explanation="The withdrawal is before the first day of instruction.",
            citation=_cite(table),
        )

    days = (wd - first_day).days
    on_or_before_add = wd <= last_add

    # The published overlap: the 100% row runs through the Last Day to Add, but
    # the 80%/60% rows are already in force by then. Do not resolve this.
    if on_or_before_add and days > 6:
        return _result(
            "ambiguous",
            withdrawal_date=withdrawal_date,
            session=session,
            session_label=SESSION_LABELS.get(session, session),
            days_since_first_instruction=days,
            message=(
                "The published refund schedule gives two different answers for this date. "
                "The first row refunds 100% of tuition and fees through the Last Day to Add "
                f"Classes ({last_add.strftime('%B %-d')}), but the day-count rows put this "
                f"date ({days} calendar days after instruction began) at a 60% tuition refund "
                "with no fee refund. I'm not going to guess which one applies to your account."
            ),
            conflicting_outcomes=[
                {"rule": "Pre-registration to Last Day to Add Classes",
                 "tuition_refund_pct": 100, "fees_refund_pct": 100},
                {"rule": "Nine Calendar Days or less",
                 "tuition_refund_pct": 60, "fees_refund_pct": 0},
            ],
            escalate=_escalate(
                table,
                "Published refund schedule rows overlap for this date; a person must confirm "
                "the tuition and fee refund before the student relies on it.",
            ),
            citation=_cite(table),
        )

    ctx = {"days_since_first_instruction": days,
           "on_or_before_last_day_to_add": on_or_before_add}
    for rule in table["payload"]["rules"]:
        if _eval_condition(rule["condition"], ctx):
            return _result(
                "resolved",
                withdrawal_date=withdrawal_date,
                session=session,
                session_label=SESSION_LABELS.get(session, session),
                days_since_first_instruction=days,
                rule_applied=rule["label"],
                tuition_refund_pct=rule["outcome"]["tuition_refund_pct"],
                fees_refund_pct=rule["outcome"]["fees_refund_pct"],
                caveats=[
                    "The published table does not state whether the first day of instruction "
                    "counts as day 0 or day 1; this calculation treats it as day 0. Student "
                    "Accounts confirms the final amount.",
                    "A $10 processing fee applies per withdrawn course.",
                ],
                citation=_cite(table),
                escalate=_escalate(
                    table,
                    "Refund amounts are advisory until confirmed by Student Accounts.",
                ),
            )

    return _result("no_coverage", message="No refund rule matched.",
                   escalate=_escalate(table, "Refund rule fall-through"))


def _eval_condition(cond: dict, ctx: dict) -> bool:
    op = cond.get("op")
    if op == "always":
        return True
    val = ctx.get(cond["field"])
    if val is None:
        return False
    tgt = cond["value"]
    return {
        "<=": val <= tgt, "<": val < tgt, ">=": val >= tgt, ">": val > tgt,
        "==": val == tgt,
        "between": tgt <= val <= cond.get("value_max", tgt),
    }.get(op, False)


def session_status(as_of: str | None = None, cal: Calendar | None = None) -> dict:
    """Which sessions are in progress right now, and where each stands.
    Lets the bot infer the likely session before asking about it."""
    cal = cal or Calendar.load()
    today = _today(as_of)
    out = []
    for sess, m in cal.session_meta.items():
        first, last = _d(m["first_day_of_instruction"]), _d(m["last_day_of_classes"])
        out.append({
            "session": sess,
            "label": SESSION_LABELS.get(sess, sess),
            "first_day_of_instruction": m["first_day_of_instruction"],
            "last_day_of_classes": m["last_day_of_classes"],
            "status": ("in-progress" if first <= today <= last
                       else "upcoming" if today < first else "ended"),
            "day_of_session": (today - first).days + 1 if first <= today <= last else None,
        })
    return _result("resolved", as_of=today.isoformat(), sessions=out)


# --------------------------------------------------------------------------
# Provider-neutral function-calling schemas
# --------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "find_events",
        "description": (
            "Look up Delaware State University academic calendar events by keyword, session, "
            "or type. Use for any question about a date, deadline, holiday, break, exam period, "
            "registration window, or residence hall date. Never answer a date question from "
            "memory or from retrieved document text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The student's phrasing, e.g. 'when do the dorms open'."},
                "session": {"type": "string", "enum": ["main", "accelerated-1", "accelerated-2", "winter"],
                            "description": "Omit if unknown; the tool will ask if it matters."},
                "event_type": {"type": "string", "enum": ["deadline", "closure", "instruction-period",
                                                          "registration", "ceremony", "housing", "payment",
                                                          "grading", "evaluation", "administrative", "recess"]},
                "as_of": {"type": "string", "description": "ISO date. Defaults to today."},
                "upcoming_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "deadline_for",
        "description": (
            "Get the deadline for a specific student action, with days remaining and whether it "
            "has already passed. Use for 'can I still drop/withdraw/add', 'when is the deadline "
            "to...', 'did I miss the deadline'."
        ),
        "input_schema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["add", "drop", "withdraw", "audit", "pass-fail",
                                                      "remove-incomplete", "graduation-application"]},
                "session": {"type": "string", "enum": ["main", "accelerated-1", "accelerated-2", "winter"]},
                "as_of": {"type": "string"},
            },
        },
    },
    {
        "name": "upcoming",
        "description": (
            "List calendar events in the next N days, optionally only those requiring student "
            "action. Use for 'what's coming up', 'anything I need to do this month', and for "
            "proactive reminders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "enum": ["main", "accelerated-1", "accelerated-2", "winter"]},
                "as_of": {"type": "string"},
                "within_days": {"type": "integer", "default": 21},
                "action_required_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "default": 8},
            },
        },
    },
    {
        "name": "is_university_closed",
        "description": "Whether the University is closed on a given date, and why.",
        "input_schema": {
            "type": "object",
            "required": ["on"],
            "properties": {"on": {"type": "string", "description": "ISO date."}},
        },
    },
    {
        "name": "classes_meet_on",
        "description": (
            "Whether classes meet on a given date. Returns answer_type 'known_unknown' when the "
            "calendar lists an event but does not say whether classes are cancelled - in that "
            "case you MUST NOT infer an answer. Offer the escalation instead."
        ),
        "input_schema": {
            "type": "object",
            "required": ["on"],
            "properties": {
                "on": {"type": "string"},
                "session": {"type": "string", "enum": ["main", "accelerated-1", "accelerated-2", "winter"],
                            "default": "main"},
            },
        },
    },
    {
        "name": "refund_schedule",
        "description": (
            "Compute the tuition and fee refund for a withdrawal on a given date. Returns "
            "answer_type 'ambiguous' where the published schedule contradicts itself - in that "
            "case present both possibilities and escalate to Student Accounts. All amounts are "
            "advisory; Student Accounts confirms."
        ),
        "input_schema": {
            "type": "object",
            "required": ["withdrawal_date"],
            "properties": {
                "withdrawal_date": {"type": "string", "description": "ISO date."},
                "session": {"type": "string", "enum": ["main", "accelerated-1", "accelerated-2", "winter"],
                            "default": "main"},
            },
        },
    },
    {
        "name": "session_status",
        "description": (
            "Which academic sessions are in progress as of a date, and how far into each we are. "
            "Call this first when a deadline question could apply to more than one session - it "
            "often removes the need to ask the student anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"as_of": {"type": "string"}},
        },
    },
]

DISPATCH = {
    "find_events": find_events,
    "deadline_for": deadline_for,
    "upcoming": upcoming,
    "is_university_closed": is_university_closed,
    "classes_meet_on": classes_meet_on,
    "refund_schedule": refund_schedule,
    "session_status": session_status,
}


def call(name: str, **kwargs) -> dict:
    """Single entry point for the agent runtime."""
    fn = DISPATCH.get(name)
    if not fn:
        return _result("no_coverage", message=f"Unknown tool '{name}'.")
    return fn(**kwargs)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        args = dict(a.split("=", 1) for a in sys.argv[2:])
        print(json.dumps(call(sys.argv[1], **args), indent=2))
    else:
        print(json.dumps([t["name"] for t in TOOL_SCHEMAS], indent=2))
