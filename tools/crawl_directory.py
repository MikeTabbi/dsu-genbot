#!/usr/bin/env python3
"""
Class D -> Class A: harvest staff/office contacts from desu.edu into KB records.

WHY THIS IS A STOPGAP, STATED UP FRONT
--------------------------------------
The staff pages on desu.edu are a hand-maintained copy of data that already
lives in Entra ID (and Banner). Scraping the copy inherits its staleness
forever. Use this to get the chatbot useful in week one, then run
`import_entra.py` when IT delivers a real export -- it emits the same records
with `supersedes` set, so nothing downstream changes. Every record this script
writes is stamped `source_authority: "web-scrape"`, which the answer layer
surfaces as a freshness caveat.

BEFORE YOU RUN IT
-----------------
Email addresses on these pages are deliberately obfuscated ("jdoe [at]
desu.edu"). That is an anti-harvesting measure by whoever maintains the site.
De-obfuscating it at scale is a decision for the web team and HR, not for a
script -- get sign-off, and pass --no-emails until you have it. Office-level
contacts (phone, department, URL) carry none of that concern, which is another
reason the routing table is the better first deliverable.

  Two-phase by design, because the standard forbids unreviewed extraction:

    1. python3 crawl_directory.py --plan          # what WOULD be fetched
    2. python3 crawl_directory.py --crawl --out ../kb/reference/contacts-scraped.json

  Phase 2 writes the JSON records AND a review CSV. A human reads the CSV,
  fixes what's wrong, and only then does the JSON get indexed.

Requires: requests, beautifulsoup4
Run from inside DSU's network if you also want the hosts that don't resolve
externally (directorysearch.desu.edu, the Banner SSB host).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.robotparser as robotparser
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITEMAP = "https://www.desu.edu/sitemap.xml"
UA = "DSU-Chatbot-KB/0.9 (+Records & Registration; contact: jcoles@desu.edu)"
DELAY = 1.0          # seconds between requests; be a polite guest on your own site
MAIN_LINE = "302.857"  # campus-contacts lists 4-digit extensions off this prefix

# URL substrings that suggest a page carries contacts. Deliberately broad --
# --plan lets you prune before anything is fetched.
CANDIDATE_HINTS = (
    "/staff", "/faculty", "/directory", "/contact", "/administration",
    "/our-team", "/people", "/leadership", "/advisement",
)
EXCLUDE_HINTS = (
    "/news", "/events", "/blog", "/apply", "/give", "/athletics",
    "faculty-research-directory",  # research profiles, not contact routing
)

EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)\s*(?:@|\[\s*at\s*\]|\(\s*at\s*\)|\s+at\s+)\s*"
    r"([A-Za-z0-9.\-]*desu\.edu)", re.I)
PHONE_FULL_RE = re.compile(r"\b(\d{3})[.\-\s)]*\s*(\d{3})[.\-\s]*(\d{4})\b")
PHONE_EXT_RE = re.compile(r"\b(\d{4})\b")
HONORIFIC = r"(?:Dr|Mr|Ms|Mrs|Prof|Rev)\.?"
CREDENTIALS = (r"(?:Ph\.?\s?D|Ed\.?\s?D|M\.?B\.?A|M\.?Ed|M\.?S\.?W|M\.?S|M\.?A|M\.?P\.?A|"
               r"J\.?D|R\.?N|B\.?S|PHR|SPHR|SHRM[\w\-]*|CPA|CFA|LPC|LCSW|PMP|Esq)\.?")
# A person's name, allowing an honorific and a trailing credential list.
NAME_RE = re.compile(
    r"^(?:" + HONORIFIC + r"\s+)?"
    r"([A-Z][A-Za-z'’\-]+"                       # first
    r"(?:\s+[A-Z]\.?)*"                                # middle initials
    r"(?:\s+(?:van|von|de|del|della|di|da|la|le|St\.?)\b)?"
    r"(?:\s+[A-Z][A-Za-z'’\-]+){1,3})"            # surname(s)
    r"(?:\s*,\s*(?:" + CREDENTIALS + r")(?:\s*,\s*(?:" + CREDENTIALS + r"))*)?"
    r"\s*$")

TITLE_WORDS = (
    "director", "vice president", "president", "dean", "chair", "coordinator",
    "manager", "specialist", "assistant", "associate", "registrar", "advisor",
    "adviser", "counselor", "officer", "analyst", "administrator", "provost",
    "professor", "lecturer", "instructor", "technician", "supervisor", "clerk",
)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def _requests():
    try:
        import requests
        return requests
    except ImportError:
        sys.exit("pip install requests beautifulsoup4")


def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


class Fetcher:
    def __init__(self, respect_robots: bool = True):
        self.requests = _requests()
        self.session = self.requests.Session()
        self.session.headers["User-Agent"] = UA
        self.rp = None
        self.last = 0.0
        if respect_robots:
            self.rp = robotparser.RobotFileParser()
            self.rp.set_url("https://www.desu.edu/robots.txt")
            try:
                self.rp.read()
            except Exception:
                self.rp = None  # unreachable robots.txt is not permission

    def allowed(self, url: str) -> bool:
        return self.rp.can_fetch(UA, url) if self.rp else True

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            return None
        gap = DELAY - (time.time() - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()
        try:
            r = self.session.get(url, timeout=25)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  ! fetch failed {url}: {str(e)[:110]}", file=sys.stderr)
            return None


def sitemap_urls(f: Fetcher, sitemap: str = SITEMAP) -> list[str]:
    xml = f.get(sitemap)
    if not xml:
        return []
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    # Follow a sitemap index one level down.
    child = [u for u in urls if u.endswith(".xml")]
    if child:
        out = []
        for c in child:
            out += sitemap_urls(f, c)
        return out
    return urls


def candidates(urls: list[str]) -> list[str]:
    out = []
    for u in urls:
        low = u.lower()
        if any(x in low for x in EXCLUDE_HINTS):
            continue
        if any(h in low for h in CANDIDATE_HINTS):
            out.append(u)
    return sorted(set(out))


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" \t\n\r|·•,;")


def find_email(node, text: str, allow: bool) -> tuple[str | None, list[str]]:
    if not allow:
        return None, []
    flags = []
    # A mailto: link is the reliable path; obfuscated text is the fallback.
    if node is not None:
        for a in node.select('a[href^="mailto:"]'):
            addr = a["href"][7:].split("?")[0].strip()
            if addr:
                return addr.lower(), flags
    if m := EMAIL_RE.search(text):
        if "@" not in m.group(0):
            flags.append("email-obfuscated-in-source")
        return f"{m.group(1)}@{m.group(2)}".lower(), flags
    return None, flags


def find_phone(text: str) -> tuple[str | None, str | None, list[str]]:
    if m := PHONE_FULL_RE.search(text):
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}", None, []
    # campus-contacts style: a bare 4-digit extension off the main line.
    stripped = re.sub(EMAIL_RE, " ", text)
    if m := PHONE_EXT_RE.search(stripped):
        ext = m.group(1)
        return f"{MAIN_LINE}.{ext}", ext, ["extension-only-no-full-number"]
    return None, None, []


def looks_like_title(s: str) -> bool:
    low = s.lower()
    return any(w in low for w in TITLE_WORDS)


def block_lines(node) -> list[str]:
    """The real line structure lives in the DOM -- <br>, <p>, <td>, <li>. These
    pages put the name, title, and email on separate <br>-delimited lines, and
    flattening the text with single spaces destroys exactly the boundary the
    parser needs. get_text("\\n") preserves it."""
    return [clean(x) for x in node.get_text("\n").split("\n") if clean(x)]


def emphasized_name(node) -> str | None:
    """These listings bold the person's name. When markup says which line is
    the name, believe it rather than guessing from a text blob."""
    for sel in ("strong", "b", "h2", "h3", "h4", "h5", ".name", ".person-name"):
        for el in node.select(sel):
            cand = clean(el.get_text(" "))
            if cand and NAME_RE.match(cand) and not looks_like_title(cand):
                return cand
    return None


def strip_contacts(s: str) -> str:
    return clean(re.sub(EMAIL_RE, "", re.sub(PHONE_FULL_RE, "", s)))


def parse_block(node, allow_emails: bool) -> dict | None:
    """Pull one contact out of a table row or card. Returns None if the block
    doesn't plausibly contain one -- a false positive here becomes a wrong
    answer to a student, so the bar is a real name plus at least one channel."""
    text = clean(node.get_text(" ", strip=True))
    if len(text) < 4 or len(text) > 600:
        return None

    email, flags = find_email(node, text, allow_emails)
    phone, ext, pflags = find_phone(text)
    flags += pflags

    lines = block_lines(node)
    name = emphasized_name(node)
    title = None

    for ln in lines:
        bare = strip_contacts(ln)
        if not bare:
            continue
        if name is None and NAME_RE.match(bare) and not looks_like_title(bare):
            name = bare
        elif title is None and looks_like_title(bare) and bare != name:
            title = bare

    # Last resort: the block is one unsplit line containing name then title.
    # Peel the longest leading run of words that parses as a name.
    if name is None:
        bare = strip_contacts(" ".join(lines))
        words = bare.split()
        for cut in range(min(6, len(words)), 1, -1):
            cand = " ".join(words[:cut])
            if NAME_RE.match(cand) and not looks_like_title(cand):
                name, rest = cand, clean(" ".join(words[cut:]))
                if title is None and looks_like_title(rest):
                    title = rest
                flags.append("extraction-uncertain")
                break

    if name is None:
        return None
    if not (email or phone):
        return None
    if title and title.startswith(name):
        title = clean(title[len(name):]) or None

    return {
        "display_name": name,
        "job_title": title,
        "email": email,
        "phone": phone,
        "phone_extension": ext,
        "flags": sorted(set(flags)),
        "raw": text[:300],
    }


def extract_page(html: str, url: str, allow_emails: bool) -> tuple[list[dict], list[str]]:
    soup = _soup(html)
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()

    page_flags = []
    h1 = soup.find(["h1"])
    dept = clean(h1.get_text()) if h1 else clean(urlparse(url).path.split("/")[-1].replace("-", " ")).title()
    dept = re.sub(r"\s*(Staff|Contacts?|Directory|and Contacts)\s*$", "", dept, flags=re.I).strip() or dept

    found, seen = [], set()
    blocks = soup.select("table tr") or []
    blocks += soup.select("div.card, li.person, div.staff, div.profile, article")
    if not blocks:
        blocks = soup.select("main p, article p, div p")
        page_flags.append("extraction-uncertain")

    for b in blocks:
        rec = parse_block(b, allow_emails)
        if not rec:
            continue
        key = (rec["display_name"].lower(), rec["email"], rec["phone"])
        if key in seen:
            continue
        seen.add(key)
        rec["department"] = dept
        rec["source_url"] = url
        found.append(rec)

    # A staff page that yields nothing is a signal, not a non-event: the page is
    # probably JS-rendered or image-based and needs manual authoring.
    if not found:
        page_flags.append("no-contacts-extracted")

    # Every person sharing one number means the page lists a switchboard, not
    # direct lines -- worth telling the student.
    phones = [r["phone"] for r in found if r["phone"]]
    if len(phones) > 3 and len(set(phones)) == 1:
        for r in found:
            r["flags"] = sorted(set(r["flags"] + ["shared-phone-across-many-people"]))

    # An odd row out is usually a source error, not a person without email.
    # (On the real HR page one entry has a phone number typed where the email
    # belongs.) Per-row detection is brittle; the page-level comparison isn't.
    if allow_emails and len(found) >= 4:
        with_email = [r for r in found if r["email"]]
        if len(with_email) / len(found) >= 0.6:
            for r in found:
                if not r["email"]:
                    r["flags"] = sorted(set(r["flags"] + ["malformed-source-row"]))

    return found, page_flags


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------

def envelope(rec: dict, idx: int) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", rec["display_name"].lower()).strip("-")[:50]
    payload = {
        "contact_type": "person",
        "display_name": rec["display_name"],
        "department": rec.get("department"),
        "job_title": rec.get("job_title"),
        "reports_to_office": None,
        "channels": {
            "email": rec.get("email"),
            "phone": rec.get("phone"),
            "phone_extension": rec.get("phone_extension"),
            "fax": None,
            "url": rec["source_url"],
            "ticket_url": None,
            "appointment_url": None,
        },
        "location": None,
        "hours": None,
        "serves_audience": ["student", "faculty", "staff"],
        # The whole point of this field: an Entra import supersedes these.
        "source_authority": "web-scrape",
        "preferred_contact_note": None,
        "aliases": [],
        "do_not_publish": False,
        "data_quality_flags": sorted(set(rec["flags"] + ["needs-owner-confirmation"])),
    }
    today = date.today().isoformat()
    return {
        "id": f"contact.person.{slug}-{idx:03d}",
        "kb_class": "structured-record",
        "collection": "contacts",
        "payload": payload,
        "source": {
            "type": "webpage",
            "title": f"{rec.get('department') or 'DSU'} - staff listing",
            "uri": rec["source_url"],
            "source_updated": today,
            "locator": rec["raw"][:80],
        },
        "owner": {
            "department": rec.get("department") or "Human Resources",
            "liaison_role": "Department KB Liaison",
            "escalation_queue": "it-help-desk",
        },
        "governance": {"data_tier": 0, "audience": ["student", "faculty", "staff"],
                       "authority": "derived"},
        # Short expiry on purpose: a scraped roster that outlives one term is a
        # liability. Let it expire and force a re-source.
        "temporal": {"effective_from": today, "effective_to": "2026-12-31", "supersedes": None},
        "review": {"cadence": "per-term", "last_reviewed": None,
                   "next_due": "2026-10-15", "reviewed_by": "pending-liaison-signoff"},
        "citation": {"label": f"{rec.get('department') or 'DSU'} staff listing, desu.edu",
                     "url": rec["source_url"]},
        "provenance": {
            "ingested_at": today + "T00:00:00Z",
            "ingest_method": "automated-sync",
            "content_hash": "sha256:" + hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32],
            "validation_status": "unvalidated",
        },
    }


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_plan(args):
    f = Fetcher(respect_robots=not args.ignore_robots)
    urls = sitemap_urls(f)
    if not urls:
        sys.exit("Could not read the sitemap. Check network access to www.desu.edu.")
    cands = candidates(urls)
    print(f"sitemap URLs:        {len(urls)}")
    print(f"contact candidates:  {len(cands)}")
    print(f"robots.txt:          {'respected' if f.rp else 'unavailable (treated as allow)'}")
    print(f"\nAt {DELAY:.0f}s/request this crawl takes about "
          f"{len(cands) * DELAY / 60:.0f} minutes.\n")
    for u in cands:
        print("  " + u)
    if args.out:
        Path(args.out).write_text("\n".join(cands) + "\n")
        print(f"\nwrote candidate list -> {args.out}")
        print("Prune it by hand, then: --crawl --urls <that file>")


def cmd_crawl(args):
    f = Fetcher(respect_robots=not args.ignore_robots)
    if args.urls:
        urls = [l.strip() for l in Path(args.urls).read_text().splitlines()
                if l.strip() and not l.startswith("#")]
    else:
        urls = candidates(sitemap_urls(f))
    if args.limit:
        urls = urls[:args.limit]

    allow_emails = not args.no_emails
    if not allow_emails:
        print("email harvesting DISABLED (--no-emails)\n")

    records, rows, page_report = [], [], []
    for i, u in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {u}")
        html = f.get(u)
        if html is None:
            page_report.append({"url": u, "status": "fetch-failed-or-disallowed", "found": 0})
            continue
        found, pflags = extract_page(html, u, allow_emails)
        page_report.append({"url": u, "status": ",".join(pflags) or "ok", "found": len(found)})
        print(f"        -> {len(found)} contact(s){' [' + ','.join(pflags) + ']' if pflags else ''}")
        for rec in found:
            records.append(envelope(rec, len(records)))
            rows.append({
                "review_ok": "",
                "name": rec["display_name"],
                "title": rec.get("job_title") or "",
                "department": rec.get("department") or "",
                "email": rec.get("email") or "",
                "phone": rec.get("phone") or "",
                "flags": ";".join(rec["flags"]),
                "source_url": u,
                "raw_extract": rec["raw"],
            })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "collection": "contacts",
        "discovery_card": {
            "id": "card.contacts",
            "text": ("Contact information for Delaware State University offices and staff: "
                     "phone numbers, email addresses, departments, and which office handles "
                     "which kind of student question."),
            "answered_by_tool": "contacts",
            "note": "Class A: retrieved by tool. Person records sourced by web scrape carry a "
                    "freshness caveat until superseded by a system-of-record import.",
        },
        "harvest_summary": {
            "pages_attempted": len(urls),
            "pages_yielding_contacts": sum(1 for p in page_report if p["found"]),
            "contacts": len(records),
            "emails_harvested": allow_emails,
            "source_authority": "web-scrape",
            "next_step": "Review the CSV, correct it, set reviewed_by, THEN index. "
                         "Replace with import_entra.py output as soon as IT delivers an export.",
        },
        "page_report": page_report,
        "records": records,
    }, indent=2) + "\n")

    csv_path = out.with_suffix(".review.csv")
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else
                           ["review_ok", "name", "title", "department", "email",
                            "phone", "flags", "source_url", "raw_extract"])
        w.writeheader()
        w.writerows(rows)

    empty = [p["url"] for p in page_report if not p["found"]]
    print(f"\nwrote {len(records)} records -> {out}")
    print(f"wrote review sheet   -> {csv_path}")
    if empty:
        print(f"\n{len(empty)} page(s) yielded nothing -- likely JS-rendered, image-based, or "
              "not actually contact pages. These need manual authoring:")
        for u in empty[:15]:
            print("  " + u)
    print("\nNothing is indexed until a human signs off on the CSV. That is the standard, "
          "not a suggestion: an unreviewed extraction gets cited to a student.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="List what would be fetched. Fetches only the sitemap.")
    ap.add_argument("--crawl", action="store_true", help="Fetch and extract.")
    ap.add_argument("--urls", help="File of URLs to crawl (one per line), instead of the sitemap.")
    ap.add_argument("--out", default="../kb/reference/contacts-scraped.json")
    ap.add_argument("--limit", type=int, help="Stop after N pages. Use this first.")
    ap.add_argument("--no-emails", action="store_true",
                    help="Skip email addresses. Use until the web team signs off on de-obfuscation.")
    ap.add_argument("--ignore-robots", action="store_true",
                    help="Only for an internal crawl your web team has explicitly approved.")
    a = ap.parse_args()

    if a.plan:
        cmd_plan(a)
    elif a.crawl:
        cmd_crawl(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
