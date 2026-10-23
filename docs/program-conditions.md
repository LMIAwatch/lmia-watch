# Program conditions

The `/program` page ("Program conditions" / "Conditions du programme") shows
what the Temporary Foreign Worker Program's own pages state is in force, and
every edition of those pages the site has read. The nightly run reads three
pages on canada.ca, stores each edition in the database, and writes
`program/index.json` for the page. The page is not in the navigation; the
Trends notes and the Data page link to it.

Code: `pipeline/lmia_pipeline/sources/program.py` (fetch, parse, store),
`pipeline/lmia_pipeline/conditions.py` (the JSON file and the sitemap entry),
`site/src/pages/program.tsx` (the page). Tests:
`pipeline/tests/test_program.py`, `site/test/program.test.ts`, with trimmed
copies of the three pages in `pipeline/tests/fixtures/program_*.html`.

## What is tracked

| Series | Source page | What an edition is | Cadence at the source |
|---|---|---|---|
| `processing_times` | LMIA application processing times: https://www.canada.ca/en/employment-social-development/services/foreign-workers/labour-market-impact-assessment-processing-times.html (French: https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/delais-traitement-demandes-evaluation-impact-marche-travail.html) | the month named in the table's caption and the average business days for each stream (Global Talent Stream, agricultural stream, Seasonal Agricultural Worker Program, high-wage, low-wage, permanent resident) | monthly, about five weeks after the month begins (September 2026 was published 2026-10-07) |
| `cma_refusal` | Refusal to process a Labour Market Impact Assessment application: https://www.canada.ca/en/employment-social-development/services/foreign-workers/refusal.html (French: https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/refus.html) | one column of the table "Unemployment rates by CMA and period": the dates it is in force, the cut-off the page states (6 percent), and each census metropolitan area's rate | every three months since 2024-09-26 (the update of 2026-10-09 is in force to 2027-01-07; the next is announced for 2027-01-08) |
| `wage_thresholds` | Hire a temporary foreign worker in a high-wage or low-wage position: https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage.html (French: https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/salaire-moyen.html) | one column of the table "Hourly wage threshold by province or territory": the date it took effect, the last day where the page states one, and the thirteen thresholds (the median hourly wage plus 20 percent) | yearly so far (2025-06-27 and 2026-07-17 on the page as read on 2026-10-22) |

Processing times exclude the advertising period: ESDC's page says the
minimum advertising (14 days to 8 weeks before an application, depending on
the stream) is not factored into them, and the site's page says so.

## Licence

All three pages are Government of Canada content published by Employment and
Social Development Canada, reproduced under the canada.ca terms and
conditions: non-commercial reproduction is allowed with the title, the
author and the source address given
(https://www.canada.ca/en/transparency/terms.html, French
https://www.canada.ca/fr/transparence/avis.html). The page names each source
page, links it in the reader's language, and links the terms. The Data page
lists the source among the site's other sources.

## How the stages run

Three stages of the nightly `run`, after `vacancies` and before the
indicators: `program_times`, `program_cma`, `program_thresholds` (one CLI
flag, `--program`, runs all three). Each:

- reads its page at most once every 20 hours (the date of the last read is
  kept in `meta` as `program_<series>_checked_at`, because the runner starts
  each night with an empty download cache), asking with the cached copy's
  ETag when there is one;
- finds the table by its caption or headings rather than by its id, reads
  the dates in the headings ("from October 9, 2026, to January 7, 2027",
  "as of July 17, 2026") and the figures, and checks the shape: the caption
  must still say business days, at least three streams must have a figure,
  each CMA column must carry at least 20 rates, each threshold column all
  thirteen provinces and territories, and the refusal page must still state
  its cut-off;
- stores an edition only when its figures differ from the newest stored for
  the same period (the hash covers the period, dates, cut-off and figures,
  not the row names), so a re-read adds nothing and a correction ESDC makes
  later becomes a new edition beside the old one. Nothing is overwritten;
- on a page whose layout no longer matches, raises: the stage is recorded as
  failed in the run log (an attention item for the workflow and the daily
  check), the stored editions stay as they were, the cached copy is dropped
  so the next night downloads the page again, and the other stages go on.

CMA rows are keyed by the 2021 Census CMA code taken from each row's link to
Statistics Canada's map (the DGUID `2021S0503<code>`); a row without a link
(Ottawa-Gatineau, 505) is found by its name. Rates ESDC does not publish for
an area leave it out of that column, as the page treats it.

## Tables

`program_editions` (one row per edition: series, period, in_force_to,
threshold, published, source_url, read_at, sha256, items) and
`program_figures` (edition_id, key, label, value). Columns are documented in
`pipeline/schema.sql`.

## What "in force" means

For the CMA list and the wage thresholds, an edition is in force on a date
when it took effect on or before that date, the page states no last day
before it, and no later edition has taken effect. One that has not taken
effect yet is upcoming; the others are past. The export works this out for
its own date (`as_of` in the file, shown on the page), so the page says what
was in force on the night of the latest export. If the newest list's last day
passes before a newer list is read, nothing is shown as in force and the page
says so. Processing times are a measure, not a rule: the newest month is the
latest.

## The low-wage indicator

The low-wage stream indicator (rules 0.3, `indicators.py`) reads the stored
lists. A published list carries Statistics Canada's three-month averages
ending the month before it takes effect (the list of 2026-10-09 carries the
averages ending 2026-09), which is the window the earlier reconstruction
reads. A decision quarter is judged on the published lists when both lists
that could have applied to it are stored (2026 Q3 on, from the read of
2026-10-22), and on the Labour Force Survey table for earlier quarters; one
quarter never mixes the two. The basis sentence names which was used, and
`program/index.json` lists the basis of every quarter from 2025 Q1
(`indicator_bases`).

## The file

`program/index.json`, about 12 KB: `as_of`, then for each series its source
pages in both languages, the date last checked, and its editions newest
first (period, to, threshold, published, source, read, figures, revisions,
status), and `indicator_bases`. Not written until at least one edition is
stored; the page answers 503 ("not read yet") without it, and the sitemap
lists `/program` only once it exists.
