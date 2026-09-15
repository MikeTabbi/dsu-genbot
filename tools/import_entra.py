#!/usr/bin/env python3
"""
Entra ID / Microsoft Graph -> the same contact records the scraper produces.

This file is the reason the scrape is safe to do. It takes a Graph /users
export and emits records in the identical shape, stamped
`source_authority: "system-of-record"`, with `supersedes` pointing at the
scraped record for the same person. Swapping the source is one command;
nothing downstream -- tools, tests, answer templates -- changes.

WHAT TO ASK IT FOR
------------------
No Graph app registration needed on your side if IT can run it once. The
whole ask is a CSV or JSON of these fields for licensed employees:

    displayName, jobTitle, department, mail, businessPhones,
    officeLocation, accountEnabled, userType

Graph equivalent (delegated User.Read.All or app Directory.Read.All):

    GET https://graph.microsoft.com/v1.0/users
        ?$select=displayName,jobTitle,department,mail,businessPhones,
                 officeLocation,accountEnabled,userType
        &$filter=accountEnabled eq true and userType eq 'Member'
        &$top=999

Or, in the Azure portal, Microsoft Entra ID -> Users -> Download users.

Note what is deliberately NOT requested: mobilePhone, employeeId, manager,
onPremisesSamAccountName, anything about students. Ask for the minimum and the
approval moves faster.

USAGE
-----
    python3 import_entra.py users.json  --out ../kb/reference/contacts-staff.json \\
        --supersede ../kb/reference/contacts-scraped.json
    python3 import_entra.py users.csv   --out ../kb/reference/contacts-staff.json

Accepts a Graph JSON response ({"value":[...]}) , a bare JSON array, or a CSV
with the portal's column headers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

# Departments whose staff should not be surfaced to students by this pipeline.
# Tier 3 in the plan's model: the protection is that the records are never
# created, not that a prompt discourages naming them.
EXCLUDE_DEPARTMENTS = re.compile(
    r"counsel|title\s*ix|human\s*resources\s*investigat|payroll|police|public\s*safety",
    re.I)

# Student-facing offices get a routing-friendly alias set.
OFFICE_ALIASES = {
    "records": ["the registrar", "registrar's office", "records office"],
    "student accounts": ["the bursar", "bursar's office", "billing office", "student billing"],
    "financial aid": ["fafsa office", "aid office", "financial aid office"],
    "information technology": ["it help desk", "help desk", "tech support", "IT"],
    "housing": ["res life", "residence life", "housing office", "dorm office"],
    "advisement": ["advising", "academic advising", "my advisor"],
}

CSV_ALIASES = {
    "displayname": "displayName", "display name": "displayName", "name": "displayName",
    "jobtitle": "jobTitle", "job title": "jobTitle", "title": "jobTitle",
    "department": "department", "mail": "mail", "email": "mail",
    "email address": "mail", "userprincipalname": "userPrincipalName",
    "businessphones": "businessPhones", "business phones": "businessPhones",
    "telephonenumber": "businessPhones", "phone": "businessPhones",
    "officelocation": "officeLocation", "office location": "officeLocation",
    "office": "officeLocation", "accountenabled": "accountEnabled",
    "usertype": "userType",
}


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


def norm_phone(v) -> str | None:
    if isinstance(v, list):
        v = v[0] if v else None
    if not v:
        return None
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[0:3]}.{digits[3:6]}.{digits[6:]}"
    if len(digits) == 4:
        return f"302.857.{digits}"
    return str(v).strip() or None


def load_users(path: Path) -> list[dict]:
    raw = path.read_text()
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(raw.splitlines()))
        out = []
        for r in rows:
            u = {}
            for k, v in r.items():
                key = CSV_ALIASES.get((k or "").strip().lower())
                if key:
                    u[key] = v
            out.append(u)
        return out
    data = json.loads(raw)
    if isinstance(data, dict):
        return data.get("value", data.get("users", []))
    return data


def truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y") if v is not None else True


def build(users: list[dict], superseded: dict[str, str]) -> tuple[list[dict], dict]:
    today = date.today().isoformat()
    records, skipped = [], {"disabled": 0, "guest": 0, "no_channel": 0,
                            "no_name": 0, "excluded_department": 0}
    seen: set[str] = set()

    for u in users:
        name = (u.get("displayName") or "").strip()
        if not name:
            skipped["no_name"] += 1
            continue
        if not truthy(u.get("accountEnabled", True)):
            skipped["disabled"] += 1
            continue
        if (u.get("userType") or "Member").strip().lower() == "guest":
            skipped["guest"] += 1
            continue

        dept = (u.get("department") or "").strip() or None
        if dept and EXCLUDE_DEPARTMENTS.search(dept):
            skipped["excluded_department"] += 1
            continue

        email = (u.get("mail") or u.get("userPrincipalName") or "").strip().lower() or None
        phone = norm_phone(u.get("businessPhones"))
        if not (email or phone):
            skipped["no_channel"] += 1
            continue

        base = slugify(name)
        rid = f"contact.person.{base}"
        n = 2
        while rid in seen:
            rid, n = f"contact.person.{base}-{n}", n + 1
        seen.add(rid)

        aliases = []
        if dept:
            for key, al in OFFICE_ALIASES.items():
                if key in dept.lower():
                    aliases = al
                    break

        flags = []
        if not email:
            flags.append("needs-owner-confirmation")
        if not phone:
            flags.append("extension-only-no-full-number")

        payload = {
            "contact_type": "person",
            "display_name": name,
            "department": dept,
            "job_title": (u.get("jobTitle") or "").strip() or None,
            "reports_to_office": None,
            "channels": {
                "email": email,
                "phone": phone,
                "phone_extension": phone.split(".")[-1] if phone else None,
                "fax": None,
                "url": None,
                "ticket_url": None,
                "appointment_url": None,
            },
            "location": ({"building": (u.get("officeLocation") or "").strip() or None,
                          "room": None, "campus": "dover", "mailing_address": None}
                         if u.get("officeLocation") else None),
            "hours": None,
            "serves_audience": ["student", "faculty", "staff"],
            "source_authority": "system-of-record",
            "preferred_contact_note": None,
            "aliases": aliases,
            "do_not_publish": False,
            "data_quality_flags": flags,
        }

        records.append({
            "id": rid,
            "kb_class": "structured-record",
            "collection": "contacts",
            "payload": payload,
            "source": {
                "type": "api",
                "title": "Microsoft Entra ID directory (Graph /users)",
                "uri": "https://graph.microsoft.com/v1.0/users",
                "source_updated": today,
                "locator": email or name,
            },
            "owner": {
                "department": dept or "Human Resources",
                "liaison_role": "Human Resources KB Liaison",
                "escalation_queue": "it-help-desk",
            },
            "governance": {"data_tier": 0, "audience": ["student", "faculty", "staff"],
                           "authority": "authoritative"},
            "temporal": {"effective_from": today, "effective_to": None,
                         "supersedes": superseded.get(name.lower())},
            "review": {"cadence": "on-change", "last_reviewed": today,
                       "next_due": _plus_quarter(today), "reviewed_by": "automated-sync"},
            "citation": {"label": "Delaware State University staff directory",
                         "url": "https://www.desu.edu/about/campus-contacts"},
            "provenance": {
                "ingested_at": today + "T00:00:00Z",
                "ingest_method": "api",
                "content_hash": "sha256:" + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32],
                "validation_status": "unvalidated",
            },
        })

    return records, skipped


def _plus_quarter(iso: str) -> str:
    y, m, d = map(int, iso.split("-"))
    m += 3
    if m > 12:
        m -= 12
        y += 1
    return f"{y:04d}-{m:02d}-{min(d, 28):02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Graph JSON response, JSON array, or portal CSV export.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--supersede", help="Path to contacts-scraped.json; matched people "
                                        "get supersedes set so the scraped record retires.")
    a = ap.parse_args()

    users = load_users(Path(a.input))
    if not users:
        sys.exit("No users found in the input.")

    superseded: dict[str, str] = {}
    if a.supersede and Path(a.supersede).exists():
        for r in json.loads(Path(a.supersede).read_text()).get("records", []):
            superseded[r["payload"]["display_name"].strip().lower()] = r["id"]

    records, skipped = build(users, superseded)
    matched = sum(1 for r in records if r["temporal"]["supersedes"])

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "collection": "contacts",
        "discovery_card": {
            "id": "card.contacts",
            "text": ("Contact information for Delaware State University offices and staff: "
                     "phone numbers, email addresses, departments, office locations, and "
                     "which office handles which kind of student question."),
            "answered_by_tool": "contacts",
            "note": "Class A, sourced from the system of record. No freshness caveat needed.",
        },
        "import_summary": {
            "users_in_export": len(users),
            "records_written": len(records),
            "superseding_scraped_records": matched,
            "skipped": skipped,
            "excluded_departments_note": (
                "Staff in counseling, Title IX, HR investigations, payroll, and public safety "
                "are excluded by design. Those are Tier 3 topics in the implementation plan; "
                "the bot routes to them by published office contact, never by naming an "
                "individual."),
        },
        "records": records,
    }, indent=2) + "\n")

    print(f"wrote {len(records)} records -> {out}")
    print(f"  from {len(users)} exported users")
    if matched:
        print(f"  {matched} supersede a scraped record (retire those on next index build)")
    for k, v in skipped.items():
        if v:
            print(f"  skipped {v} ({k.replace('_', ' ')})")


if __name__ == "__main__":
    main()
