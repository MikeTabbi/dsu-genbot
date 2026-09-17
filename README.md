# DSU Chatbot — Knowledge Base

Content repository, ingestion pipeline, and retrieval tools for the DSU student
chatbot. Content and tools stay platform-neutral. Phase 0 is decided (Sept 2026):
DSU hosts on Azure, with Claude in Microsoft Foundry as the model.

**Start here:** [`docs/kb-content-standard.md`](docs/kb-content-standard.md) — the
standard everything else implements.
**Adding content?** [`docs/sourcing-guide.md`](docs/sourcing-guide.md) — where to get it
from, in priority order, with the requests to send.

## Quick start

```bash
pip install jsonschema                      # gate; add requests beautifulsoup4 for web sync

python3 -m unittest discover -s tests -v    # 34 golden-set tests
python3 tools/validate_kb.py                # the gate
python3 tools/render.py                     # answer contract, end to end
```

Ask the calendar something directly:

```bash
python3 tools/calendar_tool.py deadline_for action=withdraw session=accelerated-1
python3 tools/calendar_tool.py refund_schedule withdrawal_date=2026-09-01 session=main
python3 tools/calendar_tool.py classes_meet_on on=2026-09-15
```

## What's here

```
docs/kb-content-standard.md     The standard: four content classes, the envelope,
                                retrieval per class, the validation gate
docs/sourcing-guide.md          Where content comes from, in priority order. What
                                desu.edu actually exposes; the asks to send IT and Web
docs/data-quality-fall-2026.md  Findings from the Fall 2026 calendar, for the Registrar
                                and Student Accounts

schemas/                        JSON Schema. The standard, machine-enforced.

kb/calendar/fall-2026.json      77 records: main semester + both accelerated sessions
kb/reference/refund-schedule.json   2 records: the refund tables as evaluable rules
kb/reference/routing.json       42 student topics -> office -> queue, + 6 office contacts
kb/faq/records-registration.json    5 Q&A pairs, demonstrating cross-references

tools/calendar_tool.py          Class A retrieval. 7 functions + provider-neutral
                                function-calling schemas
tools/render.py                 The answer contract: what each answer_type may become
tools/validate_kb.py            The gate. Run in CI on every content PR
tools/extract_calendar_fall2026.py   One-time PDF extraction (already run)
tools/build_routing.py          Authors the routing table + office contacts
tools/crawl_directory.py        Sitemap-driven contact harvest. --plan, then --crawl
tools/import_entra.py           Graph /users -> the same records, superseding the scrape
tools/ingest_prose.py           Class B chunker for catalog/handbook/policy
tools/ingest_faq.py             Class C loader for department FAQ
tools/web_sync.py               Class D fetch + change detection

tests/test_golden_set.py        Calendar golden set + the answer contract
tests/test_routing.py           Routing/contact invariants, incl. negative tests that
                                corrupt a record and assert the gate rejects it
```

## The one idea

Date and fee questions are not answered by retrieving text and letting the model
reason over it. They are answered by **deterministic tool calls against validated
structured data**, because the right answer depends on today's date, which of three
concurrent sessions the student is in, and arithmetic — and a model reading a
retrieved PDF chunk gets those wrong while sounding certain.

Every tool returns an explicit `answer_type`:

| `answer_type` | Meaning | Renderer may state a fact? |
|---|---|---|
| `resolved` | A fact, with citation | yes |
| `needs_clarification` | Session unknown and it matters | no — ask once |
| `known_unknown` | The source genuinely doesn't say | **no** — offer escalation |
| `ambiguous` | The source contradicts itself | **no** — show both, escalate |
| `no_coverage` | Nothing matches | no — escalate |

`AnswerContract` in the test suite enforces that the renderer never asserts on a
non-resolved result. That test is the groundedness guarantee; if it goes red, the
≥95% target is at risk.

## Current status

- Gate: **0 hard failures**, 917 checks over 132 records.
- Tests: **62 passing.**
- All 77 published weekdays verified against the real 2026 calendar.
- Launch-blocking: refund-table contradiction, 5 events missing `affects_classes`,
  accelerated-session coverage gaps, unpopulated office phone numbers, liaison sign-off.
  See the data-quality report and `office-contact-unpopulated` flags.

## Sourcing content: the one-line version

Go to where the data is *entered*, not where you can *see* it. The staff pages on
desu.edu are a hand-maintained copy of Entra ID and Banner; the calendar PDF is a
render of the Registrar's calendar. Ask for the upstream data, scrape only as a
stamped-and-expiring stopgap, and never save pages as PDFs — that destroys the table
structure that makes contact data queryable in the first place. Full reasoning and the
requests to send are in the sourcing guide.

## Adding the next source

The 8-step path is in §10 of the standard. The short version: find the office of
record, classify each part (§2.1), extract to the envelope, run the gate, write up
the source's ambiguities for the owning office, get sign-off, write 20 golden-set
questions, index and watch the escalations for two weeks.

Steps 5–7 are the ones schedule pressure removes. They are the ones that produce
the groundedness number.
