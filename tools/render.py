#!/usr/bin/env python3
"""
The answer contract, made concrete.

The tools return an `answer_type`. This module is the reference implementation of
what each one is allowed to become in front of a student. It exists because the
whole design collapses if a renderer treats `known_unknown` or `ambiguous` as
"resolved" -- the tool can be perfectly honest and the bot still confidently
wrong.

In production the LLM writes the prose. This module defines the CONSTRAINTS it
writes under, and doubles as a golden-set oracle: run a question through the
tool, render it here, and you have the expected answer shape to test against.
"""

from __future__ import annotations

AI_DISCLOSURE = "I'm DSU's virtual assistant, so double-check anything important with the office."


def render(result: dict) -> dict:
    """-> {text, citations, escalation_offered, may_state_a_fact}"""
    t = result["answer_type"]
    return {
        "resolved": _resolved,
        "needs_clarification": _clarify,
        "known_unknown": _unknown,
        "ambiguous": _ambiguous,
        "no_coverage": _no_coverage,
    }[t](result)


def _resolved(r: dict) -> dict:
    lines = []
    if "closed" in r:
        lines.append(
            f"Yes - the University is closed ({r['reason']})." if r["closed"]
            else f"No closure is listed for {r['date']}."
        )
    elif "classes_meet" in r:
        cm = r["classes_meet"]
        lines.append(
            f"Classes do not meet ({r['reason']})." if cm is False
            else f"Partial schedule: {r.get('detail') or r['reason']}" if cm == "partial"
            else f"Yes, classes meet. {r['reason']}"
        )
    elif "events" in r and r["events"]:
        e = r["events"][0]
        when = e["date_human"] + (f" at {e['time']}" if e.get("time") else "")
        lines.append(f"{e['title']}: {when}.")
        if e.get("action_summary"):
            lines.append(e["action_summary"])
        if r.get("days_remaining") is not None:
            d = r["days_remaining"]
            lines.append(
                f"That's {d} days from today." if d > 1
                else "That's tomorrow." if d == 1
                else "That's today." if d == 0
                else f"That was {abs(d)} days ago."
            )
    elif "tuition_refund_pct" in r:
        lines.append(
            f"Based on the published schedule, a withdrawal on {r['withdrawal_date']} "
            f"({r['days_since_first_instruction']} calendar days into "
            f"{r.get('session_label', r['session'])}) falls under "
            f"\"{r['rule_applied']}\": {r['tuition_refund_pct']}% of tuition refunded, "
            f"{r['fees_refund_pct']}% of fees."
        )
    for c in r.get("caveats") or []:
        lines.append(c)
    if r.get("alternatives"):
        alts = "; ".join(f"{a['label']}: {a['preview']}" for a in r["alternatives"])
        lines.append(f"If you're in a different session - {alts}.")

    return {
        "text": " ".join(lines),
        "citations": _citations(r),
        "escalation_offered": bool(r.get("escalate")),
        "may_state_a_fact": True,
    }


def _clarify(r: dict) -> dict:
    opts = "  ".join(f"[{o['label']}]" for o in r["options"])
    return {
        "text": f"{r['question']} {opts}",
        "citations": [],
        "escalation_offered": False,
        "may_state_a_fact": False,   # answering before the student picks is a violation
        "awaiting": [o["value"] for o in r["options"]],
    }


def _unknown(r: dict) -> dict:
    esc = r.get("escalate") or {}
    return {
        "text": (
            f"{r['message']} I don't want to guess on something that affects your attendance. "
            f"Want me to send this to {esc.get('department', 'the department')}?"
        ),
        "citations": _citations(r),
        "escalation_offered": True,
        # The hard constraint: the renderer is forbidden from asserting an answer
        # the source does not contain, no matter how confidently the model could.
        "may_state_a_fact": False,
    }


def _ambiguous(r: dict) -> dict:
    both = " / ".join(
        f"{o['rule']}: {o['tuition_refund_pct']}% tuition, {o['fees_refund_pct']}% fees"
        for o in r.get("conflicting_outcomes", [])
    )
    esc = r.get("escalate") or {}
    return {
        "text": (
            f"{r['message']} The two readings are - {both}. "
            f"Let me send this to {esc.get('department', 'the office')} so you get a real number."
        ),
        "citations": _citations(r),
        "escalation_offered": True,
        "may_state_a_fact": False,
    }


def _no_coverage(r: dict) -> dict:
    esc = r.get("escalate") or {}
    return {
        "text": (
            "I don't have that in what I can see. "
            f"I can pass it to {esc.get('department', 'the right office')} with what you've told me."
        ),
        "citations": [],
        "escalation_offered": True,
        "may_state_a_fact": False,
    }


def _citations(r: dict) -> list[dict]:
    out, seen = [], set()
    for c in ([r["citation"]] if r.get("citation") else []) + \
             [e["citation"] for e in r.get("events", []) if e.get("citation")] + \
             ([r["event"]["citation"]] if r.get("event") else []):
        # Dedupe on what the student sees, not on record id -- forty calendar
        # records share one citation label, and the student needs it once.
        key = (c["label"], c.get("url"))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from calendar_tool import call

    demos = [
        ("Do I have class on Convocation day?", dict(name="classes_meet_on", on="2026-09-15")),
        ("Can I still drop a class?", dict(name="deadline_for", action="drop", as_of="2026-08-26")),
        ("Can I still drop? I'm in the main semester.",
         dict(name="deadline_for", action="drop", session="main", as_of="2026-08-26")),
        ("If I withdraw on Sept 1, what do I get back?",
         dict(name="refund_schedule", withdrawal_date="2026-09-01", session="main")),
        ("If I withdraw on Sept 15, what do I get back?",
         dict(name="refund_schedule", withdrawal_date="2026-09-15", session="main")),
        ("Is campus open on Election Day?", dict(name="is_university_closed", on="2026-11-03")),
    ]
    for q, kw in demos:
        res = call(**kw)
        out = render(res)
        print("=" * 78)
        print(f"STUDENT: {q}")
        print(f"  [{res['answer_type']}]  may_state_a_fact={out['may_state_a_fact']}  "
              f"escalation={out['escalation_offered']}")
        print(f"BOT: {out['text']}")
        for c in out["citations"]:
            print(f"  source: {c['label']}")
