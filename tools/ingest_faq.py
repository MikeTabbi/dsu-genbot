#!/usr/bin/env python3
"""
Class C ingestion: department-authored Q&A -> enveloped records.

Liaisons author a compact file (see kb/faq/_authoring-template.json). This adds
the envelope, so the department never has to think about tiers, hashes, or
review metadata -- they write questions and answers, which is the only part
they're the expert in.

Usage:
    python3 ingest_faq.py ../kb/faq/records-registration.src.json \
        --out ../kb/faq/records-registration.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def build(src: dict) -> dict:
    meta = src["department_meta"]
    coll = src["collection"]
    records = []

    for item in src["qa"]:
        sid = item.get("id") or slug(item["question"])
        payload = {
            "question": item["question"],
            "answer": item["answer"],
            "paraphrases": item["paraphrases"],
            "references": item.get("references", []),
            "escalation_hint": item.get("escalation_hint"),
            "never_answer_if": item.get("never_answer_if", []),
        }
        records.append({
            "id": f"faq.{coll}.{sid}",
            "kb_class": "qa-pair",
            "collection": coll,
            "payload": payload,
            "source": {
                "type": "authored",
                "title": f"{meta['department']} FAQ",
                "uri": meta.get("uri"),
                "source_updated": src["authored_on"],
                "locator": item["question"][:60],
            },
            "owner": {
                "department": meta["department"],
                "liaison_role": meta["liaison_role"],
                "escalation_queue": meta["escalation_queue"],
            },
            "governance": {
                "data_tier": item.get("tier", 0),
                "audience": item.get("audience", ["student"]),
                # Department FAQ is a restatement, so it loses to the office of
                # record's own words when the two disagree.
                "authority": "derived",
            },
            "temporal": {
                "effective_from": src["authored_on"],
                "effective_to": item.get("effective_to", src.get("effective_to")),
                "supersedes": None,
            },
            "review": {
                "cadence": item.get("cadence", "per-term"),
                "last_reviewed": src["authored_on"],
                "next_due": src["next_review_due"],
                "reviewed_by": meta["liaison_role"],
            },
            "citation": {
                "label": f"{meta['department']}, Delaware State University",
                "url": meta.get("uri"),
            },
            "provenance": {
                "ingested_at": date.today().isoformat() + "T00:00:00Z",
                "ingest_method": "manual-authoring",
                "content_hash": "sha256:" + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32],
                "validation_status": "unvalidated",
            },
        })

    thin = [r["id"] for r in records if len(r["payload"]["paraphrases"]) < 4]
    return {
        "collection": coll,
        "discovery_card": {
            "id": f"card.{coll}",
            "text": src["discovery_text"],
            "answered_by_tool": None,
            "note": "Class C: matched on question embedding with a high similarity floor. "
                    "A near-miss is worse than no match, because the answer is returned "
                    "close to verbatim and reads as authoritative.",
        },
        "retrieval_config": {
            "similarity_floor": 0.82,
            "on_below_floor": "fall through to prose/structured retrieval, then escalate",
            "embed_fields": ["question", "paraphrases"],
        },
        "ingest_summary": {
            "pairs": len(records),
            "thin_paraphrase_coverage": thin,
            "note": "Paraphrase coverage is where containment rate comes from. Pairs with "
                    "fewer than 4 paraphrases will under-match real student phrasings.",
        },
        "records": records,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    doc = build(json.loads(Path(a.src).read_text()))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out}  ({doc['ingest_summary']['pairs']} Q&A pairs)")
    if doc["ingest_summary"]["thin_paraphrase_coverage"]:
        print("  thin paraphrase coverage:",
              ", ".join(doc["ingest_summary"]["thin_paraphrase_coverage"]))


if __name__ == "__main__":
    main()
