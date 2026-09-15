#!/usr/bin/env python3
"""
Class B ingestion: policy / catalog / handbook prose -> enveloped chunks.

Design choices that matter, per the content standard:

  * Chunk on heading boundaries, never on a fixed token window. A policy clause
    split in half produces two chunks that are each individually misleading.
  * Prepend the heading path to the embedded text. Chunking destroys the context
    that told you "this paragraph is about the Pass-Fail option"; the heading
    path puts it back. This single step does more for retrieval quality than
    any amount of overlap tuning.
  * Detect tables and REFUSE to embed them. A table flattened into a token
    stream is a reliable source of confident nonsense. Flag it for extraction
    into a Class A reference-table record instead.
  * Sentence-level overlap only. Heading paths do the work that large overlaps
    are usually compensating for.

Usage:
    python3 ingest_prose.py input.txt \
        --collection academic-catalog \
        --title "Academic Catalog 2026-2027" \
        --department "Records & Registration" \
        --queue records-registration \
        --uri https://www.desu.edu/... \
        --source-updated 2026-07-01 \
        --out ../kb/prose/academic-catalog.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

TARGET_TOKENS = 550
MAX_TOKENS = 800
MIN_TOKENS = 60

# Heading heuristics, ordered most to least reliable.
H_MARKDOWN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
H_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\.?\s+([A-Z][^\n]{3,90})\s*$")
H_ALLCAPS = re.compile(r"^\s*([A-Z][A-Z0-9 &/,'\-\(\)]{6,80})\s*$")

TABLE_HINTS = (
    re.compile(r"(\S+\s*\|\s*\S+.*\n){2,}"),          # pipe-delimited rows
    re.compile(r"(\S.*\t.*\n){2,}"),                   # tab-delimited rows
    re.compile(r"^\s*\S.*?\.{4,}\s*\S+\s*$", re.M),    # dot-leader rows (calendar/fee style)
    re.compile(r"(\d+%\s+\d+%)"),                      # side-by-side percentages
)


def est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def detect_heading(line: str) -> tuple[int, str] | None:
    if m := H_MARKDOWN.match(line):
        return len(m.group(1)), m.group(2)
    if m := H_NUMBERED.match(line):
        return m.group(1).count(".") + 1, f"{m.group(1)} {m.group(2)}"
    if m := H_ALLCAPS.match(line):
        if not line.strip().endswith("."):
            return 1, m.group(1).strip().title()
    return None


def looks_like_table(text: str) -> bool:
    return any(p.search(text) for p in TABLE_HINTS)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])", text.strip())
    return [p for p in parts if p.strip()]


def sectionize(raw: str) -> list[tuple[list[str], str]]:
    """-> [(heading_path, body_text)]"""
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append(([h for _, h in stack] or ["(untitled)"], body))
        buf.clear()

    for line in raw.splitlines():
        h = detect_heading(line)
        if h:
            flush()
            level, text = h
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
        else:
            buf.append(line)
    flush()
    return sections


def chunk_section(path: list[str], body: str) -> list[dict]:
    """Split a section only if it exceeds MAX_TOKENS, and only at sentence
    boundaries."""
    if est_tokens(body) <= MAX_TOKENS:
        return [{"heading_path": path, "text": body}]

    out, cur = [], []
    for para in re.split(r"\n\s*\n", body):
        for sent in split_sentences(para):
            candidate = cur + [sent]
            if est_tokens(" ".join(candidate)) > TARGET_TOKENS and cur:
                out.append({"heading_path": path, "text": " ".join(cur)})
                cur = [cur[-1], sent]  # one-sentence overlap
            else:
                cur = candidate
    if cur:
        out.append({"heading_path": path, "text": " ".join(cur)})
    return out


def build(args) -> dict:
    raw = Path(args.input).read_text(errors="replace")
    chunks: list[dict] = []
    for path, body in sectionize(raw):
        for c in chunk_section(path, body):
            if est_tokens(c["text"]) < MIN_TOKENS:
                continue
            chunks.append(c)

    slug_base = re.sub(r"[^a-z0-9]+", "-", args.collection.lower()).strip("-")
    records = []
    for i, c in enumerate(chunks):
        flags = []
        if looks_like_table(c["text"]):
            flags.append("table-detected-not-extracted")
        if c["heading_path"] == ["(untitled)"]:
            flags.append("heading-inferred")

        payload = {
            "heading_path": c["heading_path"],
            "text": " › ".join(c["heading_path"]) + "\n\n" + c["text"],
            "chunk_index": i,
            "chunk_total": len(chunks),
            "token_estimate": est_tokens(c["text"]),
            "extracted_tables": [],
            "defines_terms": [],
            "data_quality_flags": flags,
        }
        records.append({
            "id": f"prose.{slug_base}.{i:04d}",
            "kb_class": "prose",
            "collection": args.collection,
            "payload": payload,
            "source": {
                "type": args.source_type,
                "title": args.title,
                "uri": args.uri,
                "source_updated": args.source_updated,
                "locator": " › ".join(c["heading_path"]),
            },
            "owner": {
                "department": args.department,
                "liaison_role": f"{args.department} KB Liaison",
                "escalation_queue": args.queue,
            },
            "governance": {"data_tier": args.tier,
                           "audience": args.audience.split(","),
                           "authority": "authoritative"},
            "temporal": {"effective_from": args.source_updated,
                         "effective_to": args.effective_to, "supersedes": None},
            "review": {"cadence": args.cadence, "last_reviewed": None,
                       "next_due": args.next_due, "reviewed_by": "pending-liaison-signoff"},
            "citation": {"label": f"{args.title} - {args.department}", "url": args.uri},
            "provenance": {
                "ingested_at": date.today().isoformat() + "T00:00:00Z",
                "ingest_method": "assisted-extraction",
                "content_hash": "sha256:" + hashlib.sha256(payload["text"].encode()).hexdigest()[:32],
                "validation_status": "unvalidated",
            },
        })

    tabled = sum(1 for r in records
                 if "table-detected-not-extracted" in r["payload"]["data_quality_flags"])
    return {
        "collection": args.collection,
        "discovery_card": {
            "id": f"card.{slug_base}",
            "text": f"{args.title}. Policy and procedure language from {args.department}.",
            "answered_by_tool": None,
            "note": "Class B: retrieved by vector search over chunk text.",
        },
        "ingest_summary": {
            "chunks": len(records),
            "chunks_with_detected_tables": tabled,
            "action_required": (
                f"{tabled} chunk(s) contain what looks like a table. Extract each into a "
                "Class A reference-table record and link it via extracted_tables before "
                "indexing -- do not leave tables in embedded prose."
            ) if tabled else None,
        },
        "records": records,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--collection", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--department", required=True)
    ap.add_argument("--queue", required=True)
    ap.add_argument("--uri", default=None)
    ap.add_argument("--source-type", default="pdf")
    ap.add_argument("--source-updated", required=True)
    ap.add_argument("--effective-to", default=None)
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--audience", default="student,faculty,staff")
    ap.add_argument("--cadence", default="annual")
    ap.add_argument("--next-due", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = build(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    s = doc["ingest_summary"]
    print(f"wrote {out}  ({s['chunks']} chunks)")
    if s["action_required"]:
        print(f"  ACTION: {s['action_required']}")


if __name__ == "__main__":
    main()
