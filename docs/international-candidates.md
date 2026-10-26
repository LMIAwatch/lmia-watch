# Postings open to international candidates

From 3 November 2026 a job offer used for Express Entry points, or for the
Federal Skilled Worker and Federal Skilled Trades job-offer requirement, needs
no LMIA (IRCC news release of 16 October 2026). Those offers leave the LMIA
record the rest of the site reads. The nearest public trace is a Job Bank
posting whose employer chose "Canadians and international candidates" as the
people who may apply. The site reads those postings, grades them against
IRCC's list of high-wage occupations, and shows them on `/international` and
on employer profiles. They are signals: a posting does not show that a job
offer was made, and the page and the methodology say so on every row.

Code: `pipeline/lmia_pipeline/sources/jobbank_intl.py` (the crawl),
`pipeline/lmia_pipeline/intl.py` (grades and export),
`pipeline/lmia_pipeline/sources/high_wage.py` and
`pipeline/scripts/build_high_wage_list.py` (IRCC's list),
`site/src/pages/international.tsx` (the page), the `#express-entry` block in
`site/src/pages/methodology.tsx`.

## Sources

- Job Bank search, intended applicants "Canadians and international
  candidates": the search parameter `fglo=1`
  (`https://www.jobbank.gc.ca/jobsearch/jobsearch?fglo=1`). On 2026-10-25 it
  held 8,039 of about 68,000 postings, 1,086 of them with an LMIA requested
  and 15 with an approved LMIA; the other audience, "Canadians and authorized
  workers" (`fcan=1`), held 34,799. Government of Canada content, canada.ca
  terms, read through the polite client at Job Bank's crawl delay.
- The filter's Atom feed of the last 48 hours:
  `https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?fage=2&fglo=1&sort=D&rows=100`
  (76 entries on 2026-10-25), each with the posting id, title, employer,
  place and salary.
- IRCC, "High-wage occupations and how we assess them":
  https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/high-wage.html
  (French: .../entree-express/verifier-note/salaire-eleve.html). 186 NOC 2021
  unit groups in three HTML tables: 31 at 100 points (median wage at least
  twice the average), 89 at 70 (1.5 to under 2 times), 66 at 50 (1.3 to under
  1.5 times). canada.ca terms. The tier follows the NOC only; the offered wage
  plays no part.

## What is read each night

1. The filter's first search page (one request). The counts it states go to
   `jobbank_facet_counts`, one row per count and UTC day: `total`,
   `lmia_requested`, `lmia_approved`, `last_48h`, `last_30d`, `authorized`.
   This series needs no posting page, so it is complete from its first day.
   The page must show the international-candidates box as checked; when it
   does not (the parameter was renamed or ignored, so the page would list the
   whole site), the stage stops and fails rather than read the wrong set.
2. The 48-hour feed (one request). A feed that comes back with all 100 rows
   is followed by the filter's 48-hour search pages (`fage=2`, at most 12),
   so a busy day is not cut short.
3. Once a week, and on the first night, every page of the filter (about 320
   pages, about 45 minutes at the crawl delay). A sweep is complete when it
   ends on an empty page and lists at least 90 percent of the count its first
   page stated; only then are postings it did not list marked gone
   (`in_facet = 0`, `gone_at`). A posting seen again is brought back. The first
   complete sweep sets the baseline date (`meta.intl_baseline`).
4. Posting pages for postings not read yet, up to `--intl-detail-budget` (400,
   about 55 minutes, inside a 90-minute cap), newest first: by first sighting,
   the feed's finds before the weekly sweep's on the same night, then Job
   Bank's posting date. A posting that appears tonight is graded tonight, and
   the backlog of the first sweep fills in behind it. From each:
   the "Who can apply" block (international, authorized, canadians or
   unknown, with its items as read), the LMIA marker, the NOC code, the terms
   of employment (full-time, permanent), and phrases in the posting's own text
   that name Express Entry, offer help with permanent residence, or say no
   LMIA is needed, each kept as matched (`ee_phrases`, `pr_phrases`,
   `exempt_phrases`). Job Bank's own text (the LMIA notice, the audience block,
   dialogs, the apply section) is removed first, since the LMIA notice itself
   names permanent residents.

Then: a posting the LMIA crawl saw keeps "requested" or "approved"
(`join_lmia`); the employer id is filled only when the employer identity
(name and province, as `upsert_employer` computes it) names an employer that
already exists (`resolve_employers`; no employer row is ever created here);
and every grade is recomputed. Private households are dropped before
anything is written, as on the LMIA crawl (`exclusions.is_private_household`),
and a posting page that names one deletes the row. The pass runs at most once
in 20 hours (`meta.intl_last_run`).

The first sweep stores about 8,000 postings at once; their pages are read over
the following weeks (about 400 a night, less the new postings), newest first,
so the "not graded yet" count falls night by night. New postings from the feed
are read the night they appear.

## Grades

Recomputed every night for every stored posting (`intl.grade_posting`):

| Grade | Rule |
|---|---|
| A | open to international candidates, no LMIA requested, NOC on IRCC's list, full-time and permanent; or wording that names Express Entry on a posting open to international candidates without an LMIA request |
| B | open to international candidates, no LMIA requested, TEER 0 to 3 NOC not on the list, full-time and permanent |
| C | every other posting open to international candidates without an LMIA request |
| none | an LMIA requested or approved (the LMIA treatment stands); the page not read yet; the page no longer says international candidates may apply |

Reason keys stored with each grade (`grade_reasons`, JSON): `intl`, `no_lmia`,
`full_time` or `not_full_time`, `permanent` or `not_permanent` (what the
employer selected), and `high_wage:<points>`, `teer_listed_no:<teer>`,
`teer_low:<teer>`, `no_noc`, `ee_wording`, `pr_wording`, `exempt_wording` (what
the site inferred). An employer's LMIA history is shown beside its postings
as context and is never an input.

## IRCC's list: adopted automatically

No person has to act when IRCC changes the list. Each night the `highwage`
stage (before the international-candidates pass) reads the page, revalidated
with its ETag. When it parses cleanly and passes the checks (120 to 400
five-digit codes, exactly the three tiers 100, 70 and 50, no code in two tiers)
and differs from the version in use, it is adopted: stored as a new edition in
`high_wage_editions` with the date it was first read, used for grading from
that night (the grades are recomputed at once), published with that date on
`/international` and the methodology page, and reported in one notice naming
the codes added, removed and moved. Before any edition exists, the committed
file `pipeline/lmia_pipeline/data/high_wage_nocs.json` (186 codes as read on
2026-10-25, written by `pipeline/scripts/build_high_wage_list.py`) is the
version in use and stays the fallback. A page that cannot be read or fails
the checks is a notice the night that starts and again the night it ends,
never a failed stage; grading carries on with the last good version and the
page says the check failed (`high_wage.stale`).

## Export

- `international/index.json` (an optional export section; not written before
  the first pass): `as_of`, `baseline`, `change_date`, the list version, live
  totals, counts by grade, province and NOC (top 15), the daily series by
  posting date from 60 days before the baseline (`BACKFILL_DAYS`; the page
  draws the baseline as a line and says the days before it undercount, since
  postings that closed before the first sweep were never seen), the facet's
  own daily counts from the baseline, the 100
  newest graded postings with reasons and phrases, and the designated-employer
  lists (`docs/designated-employers.md`).
- Profiles: `intl`, the employer's postings (newest 20), only when there are any.
- `stats.json`: `counts.intl_live`, `intl_no_lmia`, `intl_grade_a`,
  `designated_employers`.
- The daily X and Bluesky text gains "n new postings open to international
  candidates, no LMIA" (feed finds of the night with no LMIA request), dropped
  before the province line when the text runs long. The card is unchanged.
- `/international` is in the sitemap once a pass has run.

## Run status

`status.json` carries `international` (last run, last sweep, baseline, live
and unread counts, whether the last read of IRCC's page worked) and `notices`
(information for LAST_RUN.md and the daily check's email, never an item
needing attention).
LAST_RUN.md gains the stage's one-line summary. A failure (facet not applied,
feed unreadable, an incomplete sweep, Job Bank not answering) fails the stage
like the LMIA crawl.

## Limits

No rule requires an employer to advertise a job offer used for Express Entry;
offers to existing staff are seldom posted; counts are a floor; the
international-candidates filter predates the change and also serves
LMIA-exempt permits, planned LMIAs and recruiters; employers choose their own
NOC; Express Entry wording can be a recruitment scam. Indeed, LinkedIn,
Glassdoor and similar boards are not read (their terms forbid automated
reading); Adzuna's API was assessed and left out for now (its terms reserve
commercial analysis and either party may end access).
