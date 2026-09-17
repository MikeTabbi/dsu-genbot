# DSU GenBot: Project Guide

**Last updated:** September 2026
**Status:** Knowledge base built, chatbot not built yet

This is the front door for the project. It explains what we are building, the
decisions that have been made, how the pieces fit together, and how to work on
it. Detailed rules live in other documents, and this guide links to them instead
of repeating them. One fact, one home.

---

## 1. What this is

A chatbot on Delaware State University's main website that answers general
questions from students, prospective students, and parents. Questions like when
classes start, whether it is too late to drop a course, what the refund
percentage is, and which office to call about a hold.

**What it does**

- Answers only from DSU sources that have been checked and approved
- Cites the page or office each answer came from
- Says when it does not know, and hands the person to the right office
- Answers dates, fees, and contacts from validated records rather than guessing

**What it does not do**

- Look up anything about a specific student (no grades, balances, or schedules)
- Require a login, which keeps the project clear of student record rules
- Give advice that a human adviser should give

---

## 2. Decisions made

| Decision | Choice | Notes |
|---|---|---|
| Who hosts it | DSU IT | The project is handed off to DSU, not run personally |
| Cloud | Azure | DSU's environment |
| Model | Claude in Microsoft Foundry | Approved by DSU IT |
| Who pays | DSU IT | Budget alert should be set on the subscription |
| Where it lives | DSU's main website | Public audience, no login |
| Who maintains it | Students and staff | Maintainers rotate, so simple beats clever |
| Answer style | Sourced or escalated | No unsourced answers, ever |

The decision to answer only from approved sources is the one that matters most.
A wrong tuition deadline is worse than no answer, because a student can miss a
payment because of it.

---

## 3. How it works

The system is two separate jobs.

**Building the knowledge base (runs on a schedule)**

DSU web pages and PDFs are pulled in, cleaned, split into records, checked by an
automated gate, and stored. Every record carries who owns it, where it came
from, when it was checked, and when it expires.

**Answering a question (runs every time someone asks)**

A question goes from the website widget to the API. The API decides what kind of
question it is, gets the facts, and asks Claude to write an answer using only
those facts. The answer comes back with its source.

The key idea is that questions about dates, fees, and contacts are answered by
code looking up validated records, not by the model reading a document and
interpreting it. Only policy explanations and general questions use search.

### Content classes

| Class | What it is | How it gets answered |
|---|---|---|
| A | Structured records: calendar dates, fees, office contacts | Code looks up the record and returns the exact value |
| B | Prose: policy text, program descriptions | Search finds relevant chunks, Claude explains them with citations |
| C | Question and answer pairs from departments | Matched directly to the question |
| D | Pages that change often | Synced from the website on a schedule |

### Answer types

Every response is one of these, and the type controls what the bot is allowed to
say:

- **Resolved:** the fact is known and checked, so it can be stated plainly
- **Ambiguous:** the answer depends on something unknown, so ask which session or
  campus the person means
- **Known unknown:** the source is unclear or contradicts itself, so do not guess
  and hand off to the office that owns it
- **No coverage:** nothing in the knowledge base covers this, so route the person
  to a human

Full rules: [`docs/kb-content-standard.md`](kb-content-standard.md)

---

## 4. Tech stack

| Layer | Choice |
|---|---|
| Model | Claude in Microsoft Foundry |
| Search | Azure AI Search (prose and question-answer records) |
| Structured lookups | Python tools called as Claude tools |
| API | FastAPI in a container on Azure |
| Website widget | Script tag that loads the chat in an iframe |
| Content storage | JSON records in this repo, validated by the gate |
| CI | GitHub Actions running the tests and the gate |
| Infrastructure | Bicep (planned) |

All model calls go through one adapter module so the provider can be changed
without touching the rest of the code.

---

## 5. Repo map

```
docs/       This guide, the content standard, the sourcing guide, the data quality report
kb/         The knowledge base records: calendar, faq, reference
schemas/    JSON Schemas every record must satisfy
tools/      Ingestion, validation, and retrieval scripts
tests/      Golden set and routing tests
```

Tools worth knowing:

- `validate_kb.py` is the gate. It fails on broken records and warns on data
  problems that block launch but not indexing.
- `calendar_tool.py` answers date and deadline questions directly from records.
- `render.py` shows the answer contract end to end.
- `web_sync.py`, `ingest_faq.py`, `ingest_prose.py`, `crawl_directory.py`, and
  `import_entra.py` bring content in.

Run it locally:

```bash
pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 tools/validate_kb.py
```

---

## 6. How we work

**Branches.** `main` is protected and always works. Every task gets its own short
branch off `main`, named `type/issue-number-short-description`, for example
`feat/14-claude-adapter`. Types are `feat`, `fix`, `docs`, `chore`, `infra`, and
`content` for knowledge base records.

**Pull requests.** Every change merges through a pull request that says
`Closes #<issue>` in the description. CI has to pass. Merges use squash, so each
issue becomes one commit, and branches delete themselves afterward.

**CI.** On every pull request, GitHub installs the dependencies, runs the tests,
and runs the gate. The gate runs even when tests fail, so all problems show at
once.

**Tracking.** Work lives on the GitHub Projects board, grouped into milestones.
Anything waiting on a DSU office is labeled `needs-dsu`.

---

## 7. Roadmap

| Milestone | What it covers | Status |
|---|---|---|
| M0 Repo foundation | Cleanup, CI, branch protection, core docs | Mostly done |
| M1 Content launch blockers | Source data problems that need DSU offices | Not started |
| M2 Chatbot backend | API, Claude connection, tools, search, answer contract | Not started |
| M3 Website and deployment | Widget, accessibility, rate limiting, logging, Azure, handoff | Not started |

M1 is the one with outside dependencies, so those requests should go out early
even while backend work continues.

---

## 8. Known gaps

- **The Implementation Plan v1.0 (Aug 11, 2026) is not in this repo.** The content
  standard refers to it for the phase definitions. Tracked as issue #4.
- **Content data has launch blockers.** The refund schedule contradicts itself,
  some event records do not say whether classes meet, and office phone numbers
  are unpopulated. See
  [`docs/data-quality-fall-2026.md`](data-quality-fall-2026.md).
- **Content access is undecided.** Whether DSU gives a direct export or the
  content is scraped is still open. See
  [`docs/sourcing-guide.md`](sourcing-guide.md).
- **Calendar records cover Fall 2026 only.** Adding a term is a documented path,
  not a rewrite.

---

## 9. Where to look next

| Question | Document |
|---|---|
| How is content structured and validated? | [`docs/kb-content-standard.md`](kb-content-standard.md) |
| Where does content come from? | [`docs/sourcing-guide.md`](sourcing-guide.md) |
| What is wrong with the current data? | [`docs/data-quality-fall-2026.md`](data-quality-fall-2026.md) |
| What work is planned? | The GitHub Projects board |
