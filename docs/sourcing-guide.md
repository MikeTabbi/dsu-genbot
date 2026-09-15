# Getting Web-Only Content Into the Knowledge Base

**A sourcing playbook for the DSU chatbot**
Version 1.0 · September 2, 2026 · Companion to the *KB Content Standard*

---

## The short answer

Don't download 50 pages as PDFs. It is the most work and produces the worst data.

A staff page is a *table* — name, title, email, phone in known columns. That structure is
exactly what makes it Class A content the bot can query. Printing it to PDF flattens the
table into a text blob, destroying the structure, and then someone has to pay to rebuild
it. You'd be converting good data into bad data by hand, fifty times.

Source content in this order. Stop at the first one you can get.

| | Path | Effort | Freshness | Data quality |
|---|---|---|---|---|
| **1** | **System of record** (Entra ID, Banner, Ellucian Ethos) | One request to IT | Self-maintaining | Authoritative |
| **2** | **CMS export** from whoever runs the website | One request to Web/Comms | Re-export on demand | Good, structured |
| **3** | **Scrape**, with permission | ~30 min of crawling | Manual re-runs | Fair, needs review |
| **4** | ~~Save each page as PDF~~ | Days | Frozen the moment you save | Worst possible |

The gap between rows 1 and 4 isn't a small optimization. It's the difference between a
directory that stays correct by itself and one that's wrong by November.

---

## What your site actually exposes

I checked before recommending anything. Findings specific to DSU:

**Your staff directory already has a system of record.** One of the search results for the
DSU directory is:

```
bnrhvprod-ssb.desu.edu/PROD/bwpkedir.P_NameDirectory
```

`bwpkedir` is Ellucian Banner's employee directory package. The staff pages on desu.edu are
a hand-maintained *copy* of data that already lives in Banner — and, since DSU is a
Microsoft shop, almost certainly in Entra ID as well. Scraping the copy means inheriting
its staleness permanently.

**About 80 department phone numbers are on one page.** `desu.edu/about/campus-contacts` is
a single page containing the primary campus address, DSU @ Wilmington, nine residence
halls, ~80 departments with phone and fax, and emergency contacts. That one page probably
answers more student questions than all fifty staff pages combined, and it is one fetch.

**Your sitemap is public and complete.** `desu.edu/sitemap.xml` lists roughly 650 URLs
with no child sitemaps. A crawl doesn't need to guess at URLs or click through navigation.

**Two directory hosts aren't reachable from outside DSU.** `directorysearch.desu.edu`
times out and the Banner SSB host fails TLS negotiation from an external network. If you
want those, the crawl has to run on campus — which is a point in favor of running the
tooling yourself rather than from a cloud sandbox.

**Departmental staff pages share one consistent structure.** Name (often with credentials),
job title, obfuscated email, phone — in table rows. Consistent structure means one
extractor handles all of them. Content is also spread across subdomains (`cast.desu.edu`,
`business.desu.edu` have their own faculty profiles), which is much of why it's 50+ pages.

**Two cautions the pages themselves raise:**

- **Emails are deliberately obfuscated** as `jdoe [at] desu.edu`. That is an
  anti-harvesting measure by whoever maintains the site. De-obfuscating it at scale is a
  decision for the web team and HR — not for a script. `crawl_directory.py` takes
  `--no-emails` for exactly this reason; use it until someone signs off. Office-level
  contacts carry none of that concern.
- **The HR page has a data error.** One entry has a phone number typed where the email
  belongs. The crawler catches it by comparing the row against its siblings, but it's a
  good illustration of what you inherit when you treat the website as the source: you get
  the website's mistakes, and you get them silently.

---

## What I'd do, in order

### This week — no approvals needed

**1. Populate the routing table.** Already built: `kb/reference/routing.json` has 42 student
topics mapped to the six pilot departments, with escalation queues and per-topic answer
guidance. Phone numbers are deliberately `null` and flagged — fill them from the
campus-contacts page:

```bash
echo "https://www.desu.edu/about/campus-contacts" > one-page.txt
python3 tools/crawl_directory.py --crawl --urls one-page.txt --no-emails \
    --out kb/reference/contacts-offices.json
```

Check the review CSV it writes alongside, paste confirmed numbers into `routing.json`, clear
the `office-contact-unpopulated` flags. **Roughly two hours for the highest-value contact
content in the whole knowledge base.**

This matters more than the roster, because students ask *"who do I talk to about a hold on
my account"*, not *"what is Jane Doe's extension"*. That mapping exists on no page on your
site. It's institutional knowledge, and writing it down is most of what makes the bot feel
like a front desk rather than a search box.

**2. Send the two asks below.** They're small and specific, which is what gets them
answered fast. A vague request ("can I get staff data?") sits in a queue; a request naming
seven fields and a filter gets done in an afternoon.

### Meanwhile — the stopgap, run honestly

```bash
python3 tools/crawl_directory.py --plan --out candidates.txt   # review first, fetches only the sitemap
python3 tools/crawl_directory.py --crawl --urls candidates.txt --no-emails --limit 5
python3 tools/crawl_directory.py --crawl --urls candidates.txt --no-emails
```

Every record it writes is stamped `source_authority: "web-scrape"` with a **December 31
expiry** and a `needs-owner-confirmation` flag. The expiry is deliberate: a scraped roster
that outlives one term is a liability, so it's built to expire and force a re-source. The
answer layer surfaces the provenance as a freshness caveat.

### When the export lands

```bash
python3 tools/import_entra.py users.json \
    --out kb/reference/contacts-staff.json \
    --supersede kb/reference/contacts-scraped.json
```

Same record shape, `source_authority: "system-of-record"`, `supersedes` pointing at each
scraped record so it retires cleanly. **Nothing downstream changes** — not the tools, not
the tests, not the answer templates. That's what makes doing the scrape now safe rather
than a decision you regret.

The importer also excludes counseling, Title IX, HR investigations, payroll, and public
safety staff by construction. Those are Tier 3 topics; the bot routes to them by published
office contact and never by naming an individual. That protection is the absence of the
records, not a prompt asking the model to be careful.

---

## The two asks, ready to send

### To IT / Identity

> **Subject: Small data request for the student chatbot project — Entra ID staff attributes**
>
> Hi — for the student assistant project I need a one-time export (ideally a repeatable
> one) of staff directory attributes from Entra ID. Scoped as narrowly as I can make it:
>
> **Fields:** `displayName`, `jobTitle`, `department`, `mail`, `businessPhones`,
> `officeLocation`, `accountEnabled`, `userType`
>
> **Filter:** `accountEnabled eq true and userType eq 'Member'` — active employees only
>
> **Format:** CSV or JSON, whichever is easier. Portal export (Entra ID → Users →
> Download users) is fine.
>
> Graph equivalent if that's simpler:
> ```
> GET https://graph.microsoft.com/v1.0/users
>   ?$select=displayName,jobTitle,department,mail,businessPhones,officeLocation,accountEnabled,userType
>   &$filter=accountEnabled eq true and userType eq 'Member'
>   &$top=999
> ```
>
> Deliberately **not** requesting: `mobilePhone`, `employeeId`, `manager`,
> `onPremisesSamAccountName`, or anything about students. All of it is directory
> information already published on desu.edu — this is the same data, from the authoritative
> source instead of hand-maintained web pages.
>
> If a recurring nightly or weekly pull is feasible later, that solves staff-directory
> freshness permanently and I can stop maintaining a copy. One-time is a fine start.

### To Web / Communications

> **Subject: Can you export the staff directory content type?**
>
> Hi — I'm building the knowledge base for the student chatbot and need staff/office
> contact content from the site. Before I crawl ~50 pages, two questions:
>
> 1. Are the departmental staff listings a structured content type in the CMS (fields for
>    name, title, email, phone) rather than hand-written HTML? If so, could you export
>    them — CSV or JSON? That's better data than I can get by scraping, and re-exportable
>    when things change.
> 2. Emails are obfuscated as `name [at] desu.edu`, which I take as an intentional
>    anti-harvesting measure. Two things: (a) are you OK with the chatbot surfacing staff
>    emails to authenticated DSU students, and (b) is there a directory API or feed I
>    should use instead of parsing pages?
>
> If neither is available I'll crawl the public pages politely — one request per second,
> respecting robots.txt, from `DSU-Chatbot-KB/0.9`. Wanted to ask before rather than after.

---

## The general rule for any future content

Before adding **any** source, ask in this order:

1. **Where does this data actually live?** Not "where do I see it" — where is it *entered*?
   A web page, a PDF, and a printed flyer are usually three views of one upstream system.
   Go upstream. The academic calendar PDF is the Registrar's calendar system; the staff
   page is Entra/Banner; the fee schedule is Student Accounts' billing config.
2. **Is it already structured?** Tables, directories, and lists are Class A and want a
   tool, not an embedding. Only genuine prose belongs in vector search.
3. **Who owns it, and will they re-send it?** A source with no owner has no update path,
   and content with no update path is a future wrong answer. This is a hard gate in the
   standard, not a formality.
4. **What's the smallest ask that gets it?** Name the fields. Name the filter. Say what
   you're *not* asking for. Small specific requests get answered; broad ones get queued.
5. **Only then:** if 1–4 all fail, scrape — with permission, with an expiry, with
   provenance stamped on every record, and with a documented migration path to the real
   source.

Applied to what's left on your list:

| Content | Where it really lives | Recommended path |
|---|---|---|
| Staff & office contacts | Entra ID / Banner | Ask IT (§ asks above); scrape as stopgap |
| Department FAQs | Nowhere yet — staff heads and ticket queues | Author with liaisons. Mine your ITSM tickets for real phrasings |
| Topic routing | Nowhere. Institutional knowledge | Author it. Already started — 42 topics |
| Academic catalog | Catalog system / Registrar | Wait for the updated edition. Ask for the source doc, not the published PDF |
| Fee schedules | Student Accounts billing config | Ask Student Accounts for the table, not the web page |
| Office hours | Departmental, scattered | Collect during the 4-week department onboarding — it's a form field, not a document |
| Forms library | CMS | CMS export of the forms list (title, URL, owning office, purpose) |

Note the pattern in the middle three rows: **the highest-value content doesn't exist
anywhere yet.** Routing, FAQs, and office hours can't be harvested at any quality, from any
source, because nobody has written them down. That's the real content bottleneck — not the
50 pages.

---

## What not to do, and why

- **Don't save pages as PDFs.** Destroys structure, freezes the data, and creates work.
- **Don't scrape without asking.** You work there. A one-line heads-up to the web team
  costs nothing and prevents your crawler from looking like an attack in someone's logs.
- **Don't index an unreviewed extraction.** The crawler writes a review CSV next to the
  JSON precisely so a human signs off first. An unreviewed extraction gets cited to a
  student as fact.
- **Don't let a scraped record live without an expiry.** The gate hard-fails this now.
- **Don't build the roster before the routing.** The roster is more work, goes stale
  faster, carries more privacy surface, and answers fewer questions.

---

*Tooling: `tools/crawl_directory.py`, `tools/import_entra.py`, `tools/build_routing.py`.
Governance: `docs/kb-content-standard.md`. Verified by `tests/test_routing.py`.*
