#!/usr/bin/env python3
"""
Class D: web page sync with change detection.

A web page is a SOURCE, not a KB class. This script fetches, extracts, and hands
off to the Class A/B/C ingesters. It never emits an HTML record.

The important behavior here is what happens on change: a changed page is
re-extracted and queued for the owning liaison, NOT silently republished. Pages
on desu.edu change without anyone telling the KB team, and silent auto-republish
is how unreviewed content reaches students. That single decision is the reason
this file exists rather than a cron job with a curl in it.

State lives in state/web-sync-state.json:
    { "<url>": {"content_hash": "...", "last_seen": "...", "last_approved": "..."} }

Statuses returned per page:
    new              -> never seen; extract and route for authoring
    unchanged        -> nothing to do
    changed          -> re-extract, queue for liaison review, DO NOT auto-publish
    extract-failed   -> flag for manual authoring (JS-rendered, PDF-in-iframe,
                        tables-as-images); do NOT ingest a bad extraction
    fetch-failed     -> transient; retry with backoff, alert after N failures

Requires: requests, beautifulsoup4  (network access; run in CI, not in a
sandbox without egress).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state" / "web-sync-state.json"

# Pages whose extraction we do not trust to automation.
MANUAL_ONLY_HINTS = (
    "tables-as-images", "iframe", "javascript-rendered", "login-required",
)


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2, sort_keys=True) + "\n")


def normalize(html: str) -> str:
    """Strip the volatile parts before hashing, or every page 'changes' daily
    because of a rotating banner or a build id."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit("pip install beautifulsoup4")

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    for sel in ("[data-timestamp]", ".alert-banner", ".announcement", "#csrf"):
        for tag in soup.select(sel):
            tag.decompose()
    main = soup.select_one("main, article, [role=main]") or soup.body or soup
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    return text


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:32]


def classify_extraction(soup_text: str, html: str) -> tuple[bool, list[str]]:
    """Would we trust this extraction? -> (ok, reasons_not_to)"""
    reasons = []
    if len(soup_text) < 200:
        reasons.append("javascript-rendered")
    if "<iframe" in html.lower():
        reasons.append("iframe")
    if re.search(r"<img[^>]+(schedule|table|calendar|fee)", html, re.I):
        reasons.append("tables-as-images")
    if re.search(r"(sign in|log in to view)", soup_text[:500], re.I):
        reasons.append("login-required")
    return (not reasons), reasons


def sync(urls: list[str], dry_run: bool = False) -> list[dict]:
    try:
        import requests
    except ImportError:
        raise SystemExit("pip install requests")

    state = load_state()
    today = date.today().isoformat()
    results = []

    for url in urls:
        try:
            resp = requests.get(url, timeout=20,
                                headers={"User-Agent": "DSU-Chatbot-KB-Sync/0.9 (Records & Registration)"})
            resp.raise_for_status()
        except Exception as e:
            results.append({"url": url, "status": "fetch-failed", "detail": str(e)[:200]})
            continue

        text = normalize(resp.text)
        ok, reasons = classify_extraction(text, resp.text)
        if not ok:
            results.append({
                "url": url, "status": "extract-failed", "reasons": reasons,
                "action": "Route to manual authoring. An unreliable extraction is worse "
                          "than no record -- it will be cited to a student.",
            })
            continue

        h = content_hash(text)
        prev = state.get(url)
        if prev is None:
            status, action = "new", "Extract and classify (A/B/C), then route for liaison authoring."
        elif prev["content_hash"] == h:
            status, action = "unchanged", None
        else:
            status, action = "changed", (
                "Re-extract and queue for liaison review. Do NOT auto-publish: the page "
                "changed without review and may contain content no one has approved."
            )

        if not dry_run:
            state[url] = {
                "content_hash": h,
                "last_seen": today,
                "last_approved": (prev or {}).get("last_approved"),
                "char_count": len(text),
            }
        results.append({"url": url, "status": status, "action": action,
                        "chars": len(text), "hash": h})

    if not dry_run:
        save_state(state)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True, help="File with one URL per line.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    urls = [l.strip() for l in Path(a.urls).read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    for r in sync(urls, a.dry_run):
        print(f"{r['status']:<16} {r['url']}")
        if r.get("action"):
            print(f"                 -> {r['action']}")
        if r.get("reasons"):
            print(f"                 -> reasons: {', '.join(r['reasons'])}")


if __name__ == "__main__":
    main()
