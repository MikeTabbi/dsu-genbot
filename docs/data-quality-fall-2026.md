# Source Data-Quality Report — Fall 2026 Academic Calendar

**Source:** *Academic Calendar Fall 2026 (202701)*, updated 7/23/2026
**Reviewed:** August 26, 2026, during knowledge-base extraction
**For:** Office of Records & Registration; Office of Student Accounts (§1 only)
**Gate result:** `passed-with-warnings` — 0 hard failures, 115 warnings across 79 records

---

## How to read this

Extraction produced 77 calendar records and 2 refund-schedule records. **Every date and
every published weekday in the PDF was verified against the actual 2026 calendar and all
77 are correct** — no transcription or typesetting errors in the dates themselves.

What follows is different: places where the calendar is *correct but incomplete or
self-contradictory*, in ways a human reader glosses over and an automated assistant
cannot. A student reading the PDF fills these gaps with assumptions. The chatbot is built
not to, which means each gap becomes either an escalation to your office or a permanent
fix here.

Each item is currently handled by escalating to a person. **Resolving them converts
escalations into answers** — which is the containment metric the implementation plan is
built around.

---

## 1. The refund schedule contradicts itself — highest priority

**Owner: Student Accounts, with Records & Registration**

The published table has four rows:

| Row | Tuition | Fees |
|---|---|---|
| Pre-registration to Last Day to Add Classes | 100% | 100% |
| Six Calendar Days or less | 80% | 0% |
| Nine Calendar Days or less | 60% | 0% |
| After Nine Calendar Days | 0% | 0% |

For Fall 2026, the main semester's first day of instruction is **August 25** and the Last
Day to Add is **September 3** — nine calendar days later. So row 1 and rows 2–3 cover the
same dates and give different answers:

> A student withdrawing on **September 1** (7 days in) is entitled to **100% of tuition and
> fees** under row 1, and **60% of tuition and no fees** under row 3.

This is a real money difference on a real student's account, in a window that is open right
now. The same overlap affects Accelerated Session I (starts Aug 25, adds close Sep 3).
Accelerated Session II is unaffected — it starts Oct 19 and closes adds Oct 22, only 3 days.

**Currently:** the tool detects the overlap zone and returns `ambiguous` — it presents both
readings and routes to Student Accounts rather than picking one. Verified by test.

**Needed:** confirm which row governs. If row 1 controls through the Last Day to Add, the
day-count rows should be restated as beginning the day after (e.g. "Days 10–15"). If the
day-count rows control, row 1 should be scoped to pre-registration only.

**Also unstated:** whether the first day of instruction counts as **day 0 or day 1**. This
shifts every boundary by one day. The tool currently treats it as day 0 and says so in the
caveat; a student withdrawing exactly on a boundary gets a different answer depending on
which convention is right.

---

## 2. Events that don't say whether classes meet

**Owner: Records & Registration**

The most common student question about any calendar entry is "do I have class?" These
entries don't answer it:

| Date | Event | Question |
|---|---|---|
| Fri, Sep 11 | Constitution Day (DSU Observed) | "DSU Observed" — are offices closed? Do classes meet? |
| Tue, Sep 15 | Convocation | Are classes cancelled? Is attendance expected? |
| Sat, Oct 10 | Homecoming | Any Friday/Saturday schedule changes? |
| Sat, Nov 7 | Open House | Any impact on weekend classes? |
| Thu, Sep 10 | General Faculty Meeting | Are classes affected? |

**Currently:** the assistant answers *"the calendar lists Convocation on Tuesday, September
15, but it doesn't say whether classes meet — want me to send this to Records &
Registration?"* It will not infer. Verified by test.

**Needed:** one value per event — classes meet / do not meet / partial. This is five short
answers that eliminate a recurring escalation permanently.

For contrast, **Faculty Institute (Thu, Aug 27)** is exactly right: *"No morning classes
held; evening classes only."* The assistant answers that one directly. That's the pattern.

---

## 3. Coverage gaps between sessions

**Owner: Records & Registration; Housing for the residence-hall items**

The validation gate compares sessions against each other and found asymmetries:

- **Accelerated Session I has no census date.** The main semester has one (Oct 30) and
  Accelerated II has one (Oct 29). Is this an omission, or does Accelerated I not have one?
- **Neither accelerated session has residence-hall dates.** Accelerated II runs through
  Dec 11 and spans Thanksgiving; an Accelerated II student in housing has no guidance on
  the Nov 25 close / Nov 29 reopen. Do the main-semester housing dates apply to them?
- **Accelerated Session II has no published class start time.** Accelerated I specifies
  8:00 am; Accelerated II says only "Classes Begin."
- **"Academic Early Alert Period" has a start date but no end date** in all three sessions
  (Sep 7, Sep 7, Nov 2). Is it a single day or an open-ended window?

---

## 4. Exam periods that overlap the last day of classes

**Owner: Records & Registration**

Both accelerated sessions place final examinations *ending on the same day as* the last day
of classes:

| Session | Final Examinations | Last Day of Classes |
|---|---|---|
| Accelerated I | Oct 12–16 | Oct 16 |
| Accelerated II | Dec 7–11 | Dec 11 |

The main semester keeps these separate (classes end Dec 3, Reading Day Dec 4, exams Dec
7–11). If exams during the final week of instruction is intentional for the 8-week format
that's worth stating, because "when is my last class meeting" and "when is my final" have
the same answer and students will assume that's an error.

---

## 5. Minor items

**Owner: Records & Registration**

- **Unmatched parenthesis:** "Effective Date for $10 drop processing fee**)**" (Sep 4).
- **Three entries printed out of chronological order:** Fall Course Evaluations (Nov 16–Dec
  3, printed between Nov 7 and Nov 11); Winter Payment Due Date (Dec 7, printed after the
  Dec 11 entries); Accelerated II Thanksgiving Recess (Nov 26–29, printed after the Nov
  30–Dec 11 evaluation period). No effect on the extracted data — noted in case the PDF is
  regenerated.
- **Winter Payment Due Date (Dec 7)** appears on the Fall calendar. Extracted under the
  winter session with a note. Confirm that's the intent.
- **Two meanings of "Winter Recess":** Dec 11 ("Winter Recess Begins (Students)") and Dec
  24–Jan 1 ("Winter Recess (University Closed)"). Stored as distinct records, since a
  student asking "is the university open on December 15" needs them separated. The
  Accelerated II page labels the Dec 24–Jan 1 range "Winter Recess **Begins** (University
  Closed)" while the main page omits "Begins" — treated as the same closure.
- **"Priority Pre-Registration" (Oct 19–20)** doesn't state who is eligible for priority.
  Students will ask.
- **Canonical citation URL.** Records currently cite the academic calendar landing page.
  A stable HTML page is strongly preferred over a PDF filename — cited answers must remain
  verifiable, and PDF URLs change each term.

---

## Requested actions

| # | Item | Owner | Blocks |
|---|---|---|---|
| 1 | Resolve refund-row overlap + day-0/day-1 convention | Student Accounts | Any refund answer |
| 2 | `affects_classes` for 5 events | Records & Registration | 5 recurring escalations |
| 3 | Accelerated I census date; accelerated housing dates; Accel II start time; Early Alert end dates | Records & Registration / Housing | Accelerated-session coverage |
| 4 | Confirm exam/last-day overlap is intentional | Records & Registration | Nothing; clarity only |
| 5 | Canonical calendar URL for citations | Records & Registration / Web | Citation verifiability |
| 6 | Sign-off on all 79 extracted records | Both offices | Launch |
| 7 | 20 golden-set questions from real inquiry logs | Records & Registration | Measurement |

Items 1–3 and 6 are launch-blocking under the content standard's pre-launch bar of zero
unresolved warnings on Tier 0 content.

---

*Generated by `tools/validate_kb.py`. Reproduce with `python3 tools/validate_kb.py`.*
