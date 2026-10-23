# Occupation pages

`/occupations` lists every NOC 2021 unit group with records, and
`/occupations/<noc>` shows one. The nightly export writes one JSON file per
page under `occupations/` (`pipeline/lmia_pipeline/places.py`); the Worker
renders it (`site/src/pages/occupations.tsx`), checks every field as it reads
it, and treats a file that fails as missing. Occupations use NOC 2021 only,
so ESDC's lists count from 2024 Q2, when the five-digit codes start. A page
under 20 records (`places.THRESHOLD`) carries `noindex` and stays out of the
sitemap.

Each page shows, in order: a summary and a reading of the figures; approvals
and refusals by quarter; the stream mix of the newest four quarters; wages by
economic region (the median posted minimum of LMIA-flagged postings beside
the Job Bank median and Statistics Canada's average offered wage); what LMIA
postings offered (below); Statistics Canada's vacancies for the occupation;
records by province; the employers with the most recent records; and a link
to Job Bank's live search, since a past LMIA is not a job offer.

## What LMIA postings offered

A section under the wage block, headed "What LMIA Postings Offered" ("Ce que
les offres visées par une EIMT proposaient"), gives the spread of the wages
that flagged Job Bank postings advertised: one table for Canada and one for
each economic region that holds enough postings, each with a monthly series.
The code is `pipeline/lmia_pipeline/offered.py`; `places.py` calls it while it
reads the postings and writes the result into each occupation file.

### What is counted

- A posting counts when a nightly pass saw it with an LMIA flag, requested or
  approved, which is when it enters `jobbank_observations`. A flag that
  lapsed later (the posting's `flag_current` is now `gone`) does not take it
  out: the tables describe what postings offered while flagged.
- It counts once, in the month (UTC) of its `first_seen`. A posting seen on
  many nights, or again in a later month, stays one posting in its first
  month. The series runs from the month of the archive's first night to the
  month of its newest, every month listed, empty ones included.
- It belongs to an occupation only once its posting page has been read and
  gave a five-digit NOC 2021 code (a few hundred pages are read a night), and
  to an economic region when its postal area places it in one through
  `fsa_regions`, as for the wage block.

### Figures

- Quartiles (25th percentile, median, 75th percentile) of the posted minimum
  and of the posted maximum, by linear interpolation between ranks
  (`statistics.quantiles(..., method="inclusive")`, the method of a
  spreadsheet's QUARTILE.INC), rounded to the cent. A posting that states one
  figure has it as both minimum and maximum.
- The monthly series gives, for each month, the postings first seen in it,
  how many were hourly, and the median hourly posted minimum.
- Each table sits beside the Job Bank median and Statistics Canada's average
  offered wage for the same occupation and area, read as in the wage block
  (the regional figure where published, else the province, then Canada).
  The bases differ: an advertised range on flagged postings, wages in the
  occupation, and the wage offered on all vacancies. The page says so under
  the tables.
- The page links Job Bank's wage search for the prevailing wage. Job Bank's
  wage report for an occupation sits under an internal id the records do not
  carry, so the link opens the search with the NOC code to type.

### Units

Only hourly postings enter the quartiles. A posting stated in another unit is
counted under that unit and never converted, because the hours a week and the
weeks a year are not on the posting and a conversion would invent them. The
units are the ones the parser stores: for the list pages it maps the salary
text to `HOUR`, `YEAR`, `WEEK`, `BIWEEK`, `SEMIMONTH`, `MONTH` or `DAY`,
reading "bi-weekly" and "semi-monthly" before "week" and "month"; the posting
pages give schema.org's `unitText`, which spells two of them `WEEKLY` and
`BIWEEKLY`. Those two are counted as `WEEK` and `BIWEEK`, so one unit is not
split across two counts.
An unknown unit is counted under its own name. A posting with no wage, a
wage of zero or no unit is counted as unstated.

### Threshold of 10

`offered.THRESHOLD` is 10 postings, separate from the page threshold of 20.

- A table, or a month within it, with fewer than 10 hourly postings shows its
  counts and withholds its quartiles or median ("withheld"; "n/a" where there
  is no hourly posting at all).
- A regional table is written only once the economic region holds 10
  postings of the occupation, in any unit. Until then those postings count
  in the Canada table alone, and the page states how many postings that is.
  So national tables publish now for occupations with 10 hourly postings or
  more, and regional tables appear as the archive grows.

### Fields of the occupation file

`offered` is an object:

| Field | Holds |
|---|---|
| `threshold` | 10 |
| `since` | the first month of the series, `YYYY-MM`, or null before the first night |
| `national` | the table for Canada |
| `regions` | one table per economic region with 10 postings or more, busiest first |

Each table:

| Field | Holds |
|---|---|
| `postings` | flagged postings with the occupation's code |
| `hourly_n` | of which hourly, with a wage |
| `other` | `[unit, postings]` for each other unit, most postings first |
| `unstated` | postings with no usable wage or unit |
| `min`, `max` | `[25th, median, 75th]` of the hourly posted minimum and maximum, or null when `hourly_n` is under 10 |
| `months` | `[YYYY-MM, postings, hourly postings, median hourly posted minimum or null]`, oldest first |

A regional table adds `er` (economic region code), `name`, `prov`, and
`jobbank` and `statcan`, the references for its own area in the shape the
wage block uses. The occupations index (`occupations/index.json`) does not
carry a column from these tables: it is the largest file the pages read
(123 KB) and any column would widen it.

### Source and licence

Job Bank postings are Government of Canada material published on canada.ca,
used with attribution. These tables are statistics computed from them; no
posting text is reproduced, and the Data page carries the attribution.
