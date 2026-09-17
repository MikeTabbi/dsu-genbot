# DSU Chatbot — Knowledge Base Content Standard

**Version:** 0.9 (draft for IT/implementation team + department liaison review)
**Date:** August 26, 2026
**Status:** Phase 0 deliverable. Platform-neutral by design. Phase 0 concluded (Sept 2026): Azure AI Search, with Claude in Microsoft Foundry as the model.
**Companion:** *DSU Chatbot Implementation Plan* v1.0 (Aug 11, 2026)

---

## 1. Why this document exists

The implementation plan commits to two invariants that live or die on content quality:

> *Every answer grounded (cited) or escalated.*
> *Groundedness ≥ 95% on the golden set.*

Neither is achievable by prompt engineering. They are properties of how content is stored, tagged, and retrieved. A chatbot that reads a PDF of the academic calendar and is asked *"can I still drop a class?"* will produce a confident, cited, and **wrong** answer — because the correct answer depends on today's date, which of three concurrent academic sessions the student is enrolled in, and a fee/refund interaction the PDF states inconsistently.

This standard exists so that the failure above is structurally impossible, not merely discouraged.

**Core premise:** the knowledge base is not a pile of documents. It is a set of typed records, each with a known owner, a known expiry, and a known retrieval path.

---

## 2. The four content classes

Every item entering the KB is classified into exactly one class. **The class determines how the item is retrieved**, which is the single most important decision in the pipeline.

| Class | What it holds | Retrieval path | Why |
|---|---|---|---|
| **A — `structured-record`** | Dates, deadlines, fees, contacts, office hours, refund tiers, routing tables | **Deterministic tool call.** Code queries validated JSON; no embedding in the answer path. | These questions require comparison, arithmetic, and filtering against *today*. LLMs reading retrieved text do this unreliably. |
| **B — `prose`** | Policy language, catalog sections, student handbook, procedure narratives | **Vector RAG** with section-aware chunking | Genuinely semantic. "What's the policy on academic probation" has no lookup key. |
| **C — `qa-pair`** | Department-authored FAQ: one question, one curated answer | **Question-embedding match** with a high similarity floor, answer returned verbatim | Highest-precision path. Department owns the exact wording. Best containment-per-effort. |
| **D — `web-synced`** | desu.edu page content | **Extracted into A, B, or C at ingest.** Never retrieved as raw HTML. | A web page is a *source*, not a class. Sync is a freshness mechanism, not a retrieval strategy. |

### 2.1 The classification rule

> If the correct answer would change depending on **when** it is asked, or requires **counting, comparing, or filtering**, it is Class A. No exceptions.

This is a hard rule because it is the one people get wrong. "Tuition is $X per credit" feels like prose. It is Class A — it has an effective date and it will change.

### 2.2 Discovery cards (how Class A stays findable)

Class A records aren't embedded, which raises a real question: how does the retriever know a calendar tool exists for "when does the semester start"?

Each Class A **collection** (not each record) publishes one short natural-language **discovery card** that *is* embedded — describing what the collection covers and which tool answers it. Retrieval matches the card; the card routes to the tool; the tool returns the fact.

```
Discovery card: academic-calendar
"Academic calendar dates and deadlines for Delaware State University:
 semester start and end dates, add/drop and withdrawal deadlines,
 registration periods, holidays and university closures, exam schedules,
 grade due dates, residence hall open/close dates, payment due dates.
 Covers the main semester and the 8-week accelerated sessions at the
 Dover, Wilmington, and Georgetown campuses.
 → answered by tool: academic_calendar"
```

This keeps facts in one place while keeping them reachable. It also means adding a new semester's calendar requires **no** re-indexing — only new records behind the same card.

---

## 3. The universal envelope

Every record in every class carries the same metadata envelope. Departments author the payload; the envelope is non-negotiable and machine-validated.

```json
{
  "id": "cal.fall2026.main.classes-begin",
  "kb_class": "structured-record",
  "collection": "academic-calendar",

  "payload": { "...class-specific..." },

  "source": {
    "type": "pdf",
    "title": "Academic Calendar Fall 2026 (202701)",
    "uri": "https://www.desu.edu/.../fall_2026.pdf",
    "source_updated": "2026-07-23",
    "locator": "p.1"
  },

  "owner": {
    "department": "Records & Registration",
    "liaison_role": "Registrar's Office KB Liaison",
    "escalation_queue": "records-registration"
  },

  "governance": {
    "data_tier": 0,
    "audience": ["student", "faculty", "staff"],
    "authority": "authoritative"
  },

  "temporal": {
    "effective_from": "2026-07-23",
    "effective_to": "2027-01-31",
    "supersedes": null
  },

  "review": {
    "cadence": "per-term",
    "last_reviewed": "2026-08-26",
    "next_due": "2026-12-01",
    "reviewed_by": "pending-liaison-signoff"
  },

  "citation": {
    "label": "Academic Calendar, Fall 2026 — Office of Records & Registration",
    "url": "https://www.desu.edu/.../fall_2026.pdf"
  },

  "provenance": {
    "ingested_at": "2026-08-26T00:00:00Z",
    "ingest_method": "assisted-extraction",
    "content_hash": "sha256:…",
    "validation_status": "passed-with-warnings"
  }
}
```

### 3.1 Field notes that matter

**`governance.data_tier`** maps to the plan's four-tier model. Phase 1 admits **Tier 0 only**. The tier lives on the record so that the Phase 3 expansion is a filter change, not a re-architecture. Tier is enforced at the retrieval layer — a Tier 1 record is invisible to a session whose SSO claims don't match `audience`.

**`temporal.effective_to` is enforced at retrieval, not in the prompt.** An expired record is not returned at all. This is the single highest-value field in the envelope: it is what prevents the bot from confidently quoting last spring's withdrawal deadline in October. A record with no `effective_to` must justify itself — most content has one.

**`governance.authority`** distinguishes `authoritative` (the office of record's own words) from `derived` (a summary, a rewrite, an FAQ built from a policy). When an authoritative and a derived record conflict, the authoritative one wins and the derived one is flagged for its owner. Never let two records answer the same question with equal standing.

**`owner.escalation_queue`** is on every record because escalation is content-driven, not intent-driven. When the bot can't fully answer from a record, it already knows exactly where the handoff goes — no separate routing model to maintain.

**`review.next_due`** drives a staleness report, not a hope. Content past `next_due` is downgraded: still retrievable, but the answer carries "last verified on ___, confirm with the office" and the liaison gets a notice. Content past `effective_to` is removed from the index outright.

### 3.2 One fact, one home

A deadline must live in exactly one record. If Financial Aid's FAQ says "the add/drop deadline is September 3" and the calendar record says the same thing, they will drift, and the bot will be confidently wrong 50% of the time.

Instead: the FAQ record **references** the calendar record. At answer time the reference resolves to the live value.

```json
{ "kb_class": "qa-pair",
  "payload": {
    "question": "Will I get my money back if I drop a class?",
    "answer": "That depends on when you drop. Through {{ref:cal.fall2026.main.last-day-add-drop}} you can drop with no financial penalty…",
    "references": ["cal.fall2026.main.last-day-add-drop", "ref.refund-schedule.fall-spring"]
  }}
```

Unresolvable references fail the validation gate. This is how you get a knowledge base that stays true without asking six departments to remember to update the same number.

---

## 4. Class-specific rules

### 4.1 Class A — structured-record

**Calendar events** must carry:

- `date` or `date_start`/`date_end` in ISO 8601 — never prose dates
- `weekday` as stated in the source, **validated against the actual date** (catches transcription errors)
- `session` — which academic session this applies to (`main`, `accelerated-1`, `accelerated-2`, `winter`, …). **Required.** This is the field that prevents the most common wrong answer.
- `event_type` — controlled vocabulary: `deadline`, `closure`, `instruction-period`, `registration`, `ceremony`, `housing`, `payment`, `grading`, `evaluation`, `administrative`
- `student_action_required` — boolean. Drives proactive nudges in Phase 4 and answer prioritization now.
- `affects_classes` — do classes meet? `yes` / `no` / `partial` / `unstated`. **`unstated` is a legitimate and important value** — see §6.
- `notes` — source caveats, verbatim

**Reference tables** (refund tiers, fee schedules) are stored as ordered rule lists with explicit boundaries, and are queried by a function that takes the inputs and returns the outcome. A table is never returned to the user as a table for them to interpret — the tool computes their specific answer and cites the table.

### 4.2 Class B — prose

- Chunk on **semantic boundaries** (heading, numbered policy clause), not fixed token windows. Target 300–800 tokens; never split mid-clause.
- Every chunk carries its **heading path** (`Academic Catalog › Grading › Pass-Fail Option`) prepended to the embedded text. Recovers the context that chunking destroys.
- Chunks retain `locator` (page/section) so citations point somewhere a human can verify.
- **Tables inside prose documents are extracted to Class A**, not embedded as text. A table flattened into a token stream is a well-known source of confident nonsense.
- Overlap: 1 sentence, not 200 tokens. Heading paths do the work overlap is usually compensating for.

### 4.3 Class C — qa-pair

- Answers are **≤ 120 words** and written in the persona voice defined in the conversation-design section of the plan.
- Similarity floor is deliberately **high**. A near-miss FAQ is worse than no FAQ, because the answer is returned verbatim and reads as authoritative. Below the floor, fall through to Class B/A or escalate.
- Each pair carries 3–8 `paraphrases` (real student phrasings, harvested from ticket data during department onboarding). This is where containment rate actually comes from.
- Q&A pairs are the pilot departments' **cheapest** high-value contribution. The 4-week onboarding playbook's content sprint should produce these first.

### 4.4 Class D — web-synced

- Fetch → extract → classify → emit A/B/C records. The HTML is never the KB record.
- Store `content_hash` per page. On sync, a changed hash means: re-extract, re-run validation, and **notify the owning liaison** — it does not silently republish. Web pages change without anyone telling the KB team, and silent auto-republish is how unreviewed content reaches students.
- Pages that fail extraction cleanly (heavy JS, PDF-in-iframe, tables-as-images) are flagged for manual authoring rather than ingested badly.
- Respect `robots.txt` and rate limits even on your own domain.

---

## 5. The validation gate

**Nothing enters the index without passing.** The gate is code, run in CI on the content repo, not a checklist someone remembers.

| Check | Failure mode it prevents |
|---|---|
| Envelope schema conformance | Missing owner → no escalation route; missing tier → governance gap |
| Payload schema conformance per class | Prose dates, missing `session`, uncontrolled vocab |
| **Weekday cross-check** | Transcription errors. "September 4 (Friday)" is verified against the real 2026 calendar |
| **Date sanity** | `date_end` before `date_start`; dates outside `effective` window; term boundary violations |
| **Reference resolution** | `{{ref:…}}` pointing at a record that doesn't exist or has expired |
| **Contradiction detection** | Two records asserting different values for the same `(collection, session, event_type)` key |
| **Duplicate-fact detection** | Same date/deadline asserted in more than one authoritative record |
| Citation reachability | Dead source URLs — a cited answer that can't be verified is not grounded |
| Coverage report | Session/event-type combinations with no record (see §7) |
| Staleness report | Records past `review.next_due` or `temporal.effective_to` |

Outcomes are `passed`, `passed-with-warnings`, `failed`. **Warnings do not block indexing but do block launch** — the pre-launch bar is zero unresolved warnings on Tier 0 content.

---

## 6. Ambiguity is escalated, never inferred

This is the rule that most separates a trustworthy campus assistant from a plausible one.

The Fall 2026 calendar lists *Constitution Day (DSU Observed)* on September 11 and *Convocation* on September 15. Neither says whether classes meet. A model asked "do I have class on Convocation day?" will infer — because inference is what models do — and it will sound certain.

The correct behavior:

> "The calendar lists Convocation on Tuesday, September 15, but doesn't say whether classes are cancelled. I don't want to guess on something that affects your attendance. Want me to send this to Records & Registration? They usually respond within one business day."

Mechanically: `affects_classes: "unstated"` causes the tool to return a **known-unknown**, and the answer template for a known-unknown is an escalation offer. The gap is visible in the coverage report, so the liaison can fill it permanently — one student's unanswered question becomes a permanent improvement.

The same pattern covers: contradictory source content, expired records with no successor, and Tier 3 topics (where the escalation is the *only* correct response).

---

## 7. Coverage, not just correctness

Groundedness measures whether answers are supported. It says nothing about the questions you *can't* answer — and those drive the containment metric.

The coverage report enumerates the expected `(session × event_type)` matrix and reports holes. Applied to Fall 2026, it immediately surfaces that Accelerated Session I has no census date and no residence-hall dates while the main semester has both. That's not a bug in the calendar; it's a question for the Registrar — and it's better asked in August than discovered by a student in October.

Every escalation is also a coverage signal. The steady-state quarterly review with each department should open with: *here are the top 20 things students asked you that we couldn't answer.*

---

## 8. Repository layout

Content lives in git. It is reviewed like code, because it carries the same risk.

```
dsu-kb/
├── schemas/                     # JSON Schema — the machine-readable standard
│   ├── envelope.schema.json
│   ├── structured-record.calendar.schema.json
│   ├── structured-record.reference-table.schema.json
│   ├── prose-chunk.schema.json
│   └── qa-pair.schema.json
├── kb/
│   ├── calendar/                # one file per term, owned by Records & Registration
│   │   └── fall-2026.json
│   ├── reference/               # fee/refund/contact tables
│   │   └── refund-schedule-fall-spring.json
│   ├── prose/                   # chunked policy + catalog
│   └── faq/                     # one file per department
├── tools/
│   ├── calendar_tool.py         # the deterministic Class A tool
│   ├── ingest_prose.py          # Class B chunker
│   ├── ingest_faq.py            # Class C loader
│   ├── web_sync.py              # Class D fetch + change detection
│   └── validate_kb.py           # the gate
└── docs/
    ├── kb-content-standard.md   # this document
    └── data-quality-fall-2026.md
```

**Ownership maps to directories.** A department liaison has write access to their own FAQ file and their own collections; the central team owns `schemas/` and `tools/`. Pull requests to content run the gate automatically. This is how the plan's federated model gets teeth: the central team enforces the quality bar through the gate, not through review meetings.

---

## 9. Platform portability

Nothing above names a vendor. Phase 0 concluded (Sept 2026): DSU hosts on Azure and Claude is the approved model, so the Azure column is the one being built. The AWS column stays for reference.

| This standard | Azure | AWS Bedrock |
|---|---|---|
| Class A tool | Claude tool use in Microsoft Foundry → Function App | Bedrock Agent action group → Lambda |
| Class B/C index | Azure AI Search (vector + `filter` on envelope fields) | Bedrock Knowledge Base + metadata filters |
| Content repo | GitHub/Azure Repos + Actions running the gate | Same |
| Envelope fields | Search index facets/filters | KB metadata `.metadata.json` sidecars |
| Tier/audience enforcement | Search filter injected server-side from token claims | Same, in the action-group handler |

The tool functions are plain Python with JSON Schema signatures. Both platforms consume that shape. Migration cost is the adapter layer, not the content.

---

## 10. Adding a new source: the 8-step path

The repeatable process for the next file after this one.

1. **Identify the office of record.** No owner, no ingest. This is a hard gate, not a formality.
2. **Classify** each part of the source (§2.1). One PDF often yields records in three classes — the Fall 2026 calendar yields Class A events *and* a Class A reference table, and its footnotes point at Class B catalog policy.
3. **Extract to the envelope** — assisted extraction is fine; unreviewed extraction is not.
4. **Run the gate.** Fix hard failures.
5. **Triage warnings into a data-quality report** — the source's ambiguities, addressed to the owning office (see the Fall 2026 report for the format).
6. **Liaison sign-off** on the extracted records and the report's resolutions. Set `review.reviewed_by`.
7. **Write the golden-set questions** — 10–20 real student phrasings per source, with expected answers, added to the regression suite. A source without golden questions cannot be measured, so it cannot be launched.
8. **Index and monitor** — watch escalation reasons for that collection for two weeks; they tell you what step 2 got wrong.

Steps 5–7 are the ones under schedule pressure to skip. They are the ones that produce the ≥95% groundedness number.

---

## 11. What this standard deliberately does not do

- **It does not try to make the LLM careful.** Correctness is enforced by tools, schemas, filters, and gates. Prompts are the last line, not the first.
- **It does not centralize content authorship.** Six departments writing their own records with a shared envelope scales; one team writing everyone's content does not.
- **It does not admit Tier 1+ content in Phase 1.** The envelope is ready for it; the pipeline is not, and the plan says Phase 1 is Tier 0 only.
- **It does not treat "the PDF is on the website" as ingestion.** Publishing is not structuring.

---

## Appendix A — Open items for liaison review

| # | Item | Owner |
|---|---|---|
| A1 | Refund schedule tier boundaries are self-contradictory as published — see data-quality report §1 | Student Accounts + Records |
| A2 | `affects_classes` unstated for Constitution Day, Convocation, Homecoming, Open House | Records & Registration |
| A3 | Accelerated I has no census date; no residence-hall dates for either accelerated session | Records & Registration / Housing |
| A4 | Is the Fall 2026 calendar PDF's canonical public URL stable enough to cite? Preferred: cite an HTML page | Web/Comms |
| A5 | Review cadence for calendars: per-term proposed. Confirm who signs off and when | Records & Registration |
| A6 | Golden-set questions for the calendar collection — 20 needed, drawn from real Registrar inquiries | Records & Registration |
