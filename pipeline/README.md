# Pipeline

Collects the public LMIA records, merges them by employer, computes the
indicators and exports everything the site reads.

## Install and test
```
cd pipeline
pip install -e .[dev]
pytest
```
Tests are offline and run against trimmed fixtures in `tests/fixtures/`
(regenerate them with `python tests/fixtures/make_fixtures.py` after
refreshing the raw downloads under `data/raw/`).

## Run
```
python -m lmia_pipeline run --db ../data/lmia.sqlite            # every stage
python -m lmia_pipeline run --esdc                               # one stage
python -m lmia_pipeline run --jobbank --limit 1 --detail-budget 2  # dev-sized Job Bank run
python -m lmia_pipeline run --intl --limit 1 --intl-detail-budget 3  # dev-sized pass over postings open to international candidates
python -m lmia_pipeline run --highwage --registers                  # IRCC's high-wage list check, designated-employer lists
python -m lmia_pipeline run --notices                               # IRCC and ESDC news feeds (four requests)
python scripts/build_high_wage_list.py                              # rebuild the fallback copy data/high_wage_nocs.json (optional)
python -m lmia_pipeline run --export                             # csv, mirror and static JSON
python -m lmia_pipeline search-sync --db ../data/lmia.sqlite     # search database: changed rows as SQL batches
python -m lmia_pipeline search-check --manifest ../data/out/search/manifest.json --count 487547
python -m lmia_pipeline search-synced --db ../data/lmia.sqlite --manifest ../data/out/search/manifest.json
python -m lmia_pipeline post-digest --dry-run                    # print the daily X post, send nothing
python -m lmia_pipeline post-bluesky --dry-run                   # print the daily Bluesky post, send nothing
python -m lmia_pipeline deposit-zenodo --dry-run                 # list what a Zenodo deposit would hold
```
`post-digest` posts one message a day to X from the postings first seen on the
latest Job Bank pass, when `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` and
`X_ACCESS_TOKEN_SECRET` are set. It records the posted date in `meta`, so a
re-run posts nothing; it exits 1 when the post failed or X never confirmed it, and the workflow carries on. Setup: `../docs/x-account.md`.
`post-bluesky` posts the same digest to Bluesky, with the link, when
`BSKY_HANDLE` and `BSKY_APP_PASSWORD` are set; its own date in `meta` keeps
it to one post per pass. Setup: `../docs/bluesky-account.md`.
`deposit-zenodo` deposits the OGL CSVs as a new version of the Zenodo record
when a new ESDC quarter is loaded, when `ZENODO_TOKEN` is set
(`ZENODO_SANDBOX=true` for the sandbox). Setup: `../docs/zenodo.md`.
Both write their outcome under `data/out/` and exit 1 on a failure, for the
workflow's run status; neither raises.
`search-sync` writes the rows of the hosted search database (D1
`lmia-watch-search`) whose content changed since the ledger in the SQLite file
as SQL batches plus `manifest.json` (`--full` drops and recreates the tables
first and sends every row); the workflow applies them with Wrangler, reads
the row count back for `search-check`, and only then runs `search-synced`,
which records the ledger. Operator guide: `../docs/hosted-search.md`.
Stage order: esdc, ircc, jobbank, highwage (IRCC's list, adopted when it
changes), intl (postings open to international candidates), registry (BC,
federal, Quebec), grants, alberta, fmcsa, registers (designated-employer lists),
notices (IRCC and ESDC news that names the programs), wages, lfs, vacancies,
program (processing times, CMA list, wage thresholds), geography, indicators
and status, export.
A stage records information that is not a failure (IRCC's list adopted after
a change or unreadable from tonight, a designated-employer list or a news feed
that stops being read or is read again, a government notice first listed that
night) as a notice on its `sources_log` row (`log_run(..., notice=...)`, up to
`db.NOTICE_MAX_CHARS`, 3,000 characters, per row): the run status lists it
under `notices`, LAST_RUN.md and the daily check's email carry it (one line
each, `nightly notices`), and it is never an item needing attention: the last
step passes, no issue opens, the run stays ok and no retry follows.
Before any stage, `run` compares `meta.normalize_version` with
`normalize.NORMALIZE_VERSION` and, when the database is older, re-derives every
employer id once (`migrate.py`).
The esdc stage likewise compares each loaded file's
`esdc_resources.parser_version` with `esdc.PARSER_VERSION` and parses an older
one again once, from the download cache (`esdc.reload_outdated`). Rows are
matched by row hash, so a row read correctly before keeps its id; bump the
version after any parser change that alters what a loaded file yields.
`--limit` caps Job Bank list pages per facet and also disables the "gone"
marking, because a capped run has not seen the whole feed.

## Stages
| Module | Does |
|---|---|
| `sources/esdc.py` | discovers every quarterly file through CKAN, downloads and parses it (CSV to 2020 Q3, XLSX after), records provenance and the parser version in `esdc_resources`; in the 2016 to 2019 Q2 files gives each continuation row (blank employer, an occupation and a count) to the employer row above it and carries the stream and province down their blocks |
| `household.py` | keeps private households (a person's name with a home child care or home support occupation) out of the ESDC rows, at load and in a nightly cleanup of rows already loaded |
| `sources/jobbank.py` | pages both LMIA facets, upserts postings, logs each observation, fetches new posting pages within a budget, drops private-household postings before storage |
| `sources/jobbank_intl.py` | postings open to "Canadians and international candidates" (search filter `fglo=1`): each night the filter's first search page (its counts into `jobbank_facet_counts`), the 48-hour Atom feed (followed by the 48-hour search pages when the feed comes back full), and the pages of postings not read yet within `--intl-detail-budget` (400 by default, newest first, inside a 90-minute cap: who may apply, LMIA marker, NOC, terms, matched phrases); weekly a sweep of every page, which marks postings that left the filter gone and sets the baseline date on its first complete run; at most once in 20 hours; no employer row is ever created (`../docs/international-candidates.md`) |
| `intl.py` | the grades of those postings (A, B, C, with reason keys), recomputed every night, and `international/index.json`, the profile rows and the stats counts |
| `sources/high_wage.py` | IRCC's list of high-wage occupations: read nightly and, when it changed and passes the checks (120 to 400 codes, the three tiers, none in two), adopted into `high_wage_editions` and used for grading from that night (one notice); the committed `data/high_wage_nocs.json` is the fallback before any edition and the parser is shared with `scripts/build_high_wage_list.py` |
| `sources/registers.py` | the published designated-employer lists (Atlantic Immigration Program by province, the Rural and Francophone Community Immigration Pilots by community): a registry of 24 lists with address, format and terms; HTML, JSON and PDF lists (pypdf, layout text, a rule per list) read nightly with their last good rows kept when a read fails or looks broken (under 5 rows, or a drop of more than 60 percent); notices on a change of state only; matched to employers by name and place within the list's province (`../docs/designated-employers.md`) |
| `sources/notices.py` | government notices: the Canada.ca news feeds of IRCC and ESDC in English and French (api.io.canada.ca, Atom, the last 12 months), one request each a night; an item is kept when its title or summary in either language contains one of 18 program terms; the two languages are paired on the feed's timestamp (then type, then feed order), the summary's dateline is left out, and the item stored in `gov_notices` under an id from its canada.ca URL; a feed that cannot be read keeps its items (a notice on the change of state only), each item first listed is a notice of its own (five a night, a count for the rest; the first night is one line); `notices.json` for `/notices` and the home page |
| `normalize.py` | name identity (`split_trade_name`, `norm_name`), addresses, dates, codes |
| `migrate.py` | re-derives employer ids, merges duplicates and rewrites every referencing table after a normalization change |
| `sources/ircc.py` | parses the non-compliant employers JSON and the reason legend from the page, links findings by legal name first, and copies a finding's street and names onto its employer |
| `sources/registry_bc.py` | OrgBook BC lookups for BC employers, most useful first, graded matches |
| `sources/registry_federal.py` | Corporations Canada bulk extract, matched by normalized name |
| `sources/registry_quebec.py` | Registraire des entreprises du Québec bulk extract, loaded weekly, matched by normalized name |
| `sources/grants.py` | federal grants and contributions (proactive disclosure, 2.3 GB CSV streamed to disk once a quarter), kept for employer names and federal business numbers, matched by business number or by name and postal area |
| `sources/alberta_records.py` | Alberta Employer Records workbook (workers' compensation injury figures), listing checked monthly, kept for Alberta employer names, matched by name and city |
| `sources/fmcsa.py` | US FMCSA Company Census, Canadian rows only through the API, read monthly, matched by name and postal code |
| `sources/matching.py` | the rules those three share: the person test, the common-name test, the place keys and the exact and probable grades |
| `sources/wages.py` | Job Bank wages by occupation and area (the prevailing-wage reference), newest two yearly tables |
| `sources/lfs.py` | Labour Force Survey unemployment rate by census metropolitan area |
| `sources/vacancies.py` | Statistics Canada job vacancies and average offered wage by NOC 2021 unit group and economic region (table 14-10-0444-01), newest eight quarters; NOC 2021 titles and definitions in English and French |
| `sources/program.py` | the program's own pages on canada.ca: LMIA processing times by stream, the low-wage refusal-to-process list by census metropolitan area, the provincial and territorial wage thresholds; one stage per page, every edition kept (`../docs/program-conditions.md`) |
| `sources/geography.py` | 2021 Census boundaries; places every forward sortation area in an economic region and a census metropolitan area (`fsa_regions`) |
| `indicators.py` | the rules (version in `RULES_VERSION`) |
| `status.py` | employer rollups, the status lifecycle, meta counters |
| `export.py` | CSV files and the raw-file mirror with checksums |
| `export_static.py` | the JSON files the site serves |
| `places.py` | the occupation and place pages: one JSON file per page, and their sitemap entries |
| `directory.py` | every employer A to Z by province and territory, 200 to a page (`directory/`), with each page's lastmod kept in the `directory_pages` ledger; the related employers on each profile (same city, then same most common NOC in the province, nearest in record count) |
| `offered.py` | what LMIA-flagged postings offered, for the occupation pages: quartiles of the hourly posted minimum and maximum, other units counted, a monthly series, nationally and by economic region, withheld under 10 postings (`docs/occupations.md`) |
| `conditions.py` | the program conditions page: `program/index.json`, what is in force on the export date and every edition read |
| `search_db.py` | the hosted search database (`../pipeline/search_schema.sql`): its rows, the content-hash ledger, the nightly batches and manifest, the ledger record after the apply (separate `search-sync`, `search-check` and `search-synced` commands) |
| `social.py` | the daily X digest: compose, save to `data/out/social/`, post (separate `post-digest` command) |
| `social_card.py` | the card image attached to the digest, drawn with Pillow from the day's figures |
| `bluesky.py` | the same digest and card on Bluesky over the AT Protocol, with a link facet (separate `post-bluesky` command) |
| `zenodo.py` | the citable release: a new Zenodo version of the OGL CSVs per ESDC quarter, DOIs into `meta` (separate `deposit-zenodo` command) |
| `views_rollup.py`, `search_console.py`, `views_report.py` | the audience record kept in R2 (`../docs/search-engines.md` section 6): the nightly roll-up of the Worker's counts (people and bots apart, daily unique visitors from the visitor code), Search Console's daily figures and top queries (a service account JWT signed with the standard library), and the monthly report |
| `nightly.py` | the workflow's restore, verify, status and pack commands (pack writes the R2 backup: a `VACUUM INTO` copy without the secondary indexes, checked, gzipped, refused above Wrangler's 300 MiB upload cap), `site-bundle-check` for the site-only deploy (`docs/site-deploy.md`), and `indexnow`, which after the deploy sends the pages changed since the run's start to IndexNow (`indexnow.py`; `--dry-run` lists them; `../docs/search-engines.md` section 5) |

## Outputs
```
data/lmia.sqlite        the database (schema: ../pipeline/schema.sql)
data/out/csv/           files the Data page offers
data/out/mirror/        raw ESDC files plus SHA256SUMS
data/out/static/        the JSON the site serves as static assets (see export_static.py):
                          stats.json, search/first.json and search/facets.json (the
                          search page's fallback), search/counts.json (the search
                          API's totals), search/latest/status/pending.json (/api/pending),
                          clusters/*.json, areas/<FSA>.json, profiles/<abc>.json,
                          aliases/<abc>.json (retired employer id to live id),
                          occupations/*.json, places/**/*.json (places.py),
                          directory/**/*.json (directory.py, every employer A to Z by province),
                          program/index.json (conditions.py),
                          international/index.json (intl.py, with the designated-employer lists)
                          notices.json (sources/notices.py, the last 12 months, each feed's state)
data/out/search/        written by `search-sync`: batch-0001.sql and on (at most 5 MB or
                        5,000 statements each, up to 100 rows per upsert statement),
                        manifest.json, last_outcome.txt
data/out/indexnow/      written by `nightly indexnow`: urls.txt (the pages selected),
                        last_outcome.txt
data/out/intl/, data/out/registers/, data/out/notices/
                        last_outcome.txt: the stage's one-line summary for LAST_RUN.md
```
The static export is deterministic (sorted keys and rows), so an unchanged file
keeps its bytes and the deploy skips it. Each file stays under the 25 MiB
static-asset limit; the search page reads the hosted search database rather
than large files (`../docs/hosted-search.md`).

## Employer identity
An employer is its normalized legal name plus its province
(`normalize.norm_name`, `employer_id`). The part of a name before a trade-name
marker (dba, d/b/a, o/a, t/a, operating as, doing business as, trading as,
carrying on business as, c.o.b., faisant affaire sous, f.a.s.) is the legal
name; the part after it is recorded in `employer_names` as an operating name.
Normalization folds case and accents, removes dots inside abbreviations and
apostrophes inside words, drops other punctuation and "and"/"et", joins runs
of single letters, spells the jurisdiction of a numbered company one way, and
strips legal suffixes. Changing any of this means bumping `NORMALIZE_VERSION`;
the next run then re-derives ids (`migrate.py`), records each retired id in
`employer_aliases`; the search database needs nothing extra, since the
employer id is part of each search row's hash and the next `search-sync`
sends every row whose id changed. An ESDC file read again under a newer parser
records an alias too, when a row it files under a new id (a province read
from its block) leaves the old employer with nothing. The static export writes
the aliases, chains followed to the live id, as `aliases/<abc>.json`, sharded
on the retired id like the profiles.

## Registries
`sources/registry_bc.py` queries OrgBook BC per employer (BC only). It takes
up to 700 lookups a night within 15 minutes at one request a second, ordered:
a pending posting, then a record on the latest ESDC quarter, then an IRCC
finding, then the rest; an employer is looked up again after 180 days, under
its legal name.
`sources/registry_federal.py` downloads the Corporations Canada open-data CSVs
(active and inactive CBCA corporations, about 260 MB, cached a week), loads them
into the local `federal_corporations` table and matches every employer by
normalized name; a match is exact when the province or postal code agrees,
probable otherwise.
`sources/registry_quebec.py` downloads the Registraire des entreprises du
Québec's open-data ZIP (Données Québec, CC BY-NC-SA 4.0, 269 MB, refreshed
twice a month) at most once a week, keeps only the names that normalize like a
Quebec employer's (sole proprietorships are skipped), and grades like the
federal matcher; a match on a name the enterprise operates under is probable.
The other provinces publish no free bulk file or API (see the Methodology
page).

## Public records on profiles
Three sources add records to employer profiles and nothing else; none feeds
the indicators. Each has a page under `docs/` with its source, licence, join
rule and what a record does not mean.

| Module | Source | Licence | Fetched | Join |
|---|---|---|---|---|
| `sources/grants.py` | Proactive Disclosure of Grants and Contributions, https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013 (`docs/grants.md`) | Open Government Licence, Canada | once a quarter, streamed to `data/raw/grants/` and deleted after reading | business number of the matched federal corporation, else name and postal area (exact) or province (probable) |
| `sources/alberta_records.py` | Alberta Employer Records, https://open.alberta.ca/opendata/employer-records (`docs/alberta-employer-records.md`) | Open Government Licence, Alberta | listing every 30 days; workbook when it changes or is 91 days old | name and city (exact) or name alone within Alberta (probable) |
| `sources/fmcsa.py` | FMCSA Company Census, data.transportation.gov dataset az4n-8mr2 (`docs/fmcsa.md`) | public domain (US government work) | monthly, `phy_country='CA'` only, selected columns only | name and postal code (exact) or province (probable) |
| `sources/registers.py` | designated-employer lists of the Atlantic Immigration Program and the community pilots, HTML, JSON and PDF (`docs/designated-employers.md`) | each publisher's website terms; none is an open licence | nightly, one request a list | name and the row's place or the pilot community (exact) or province (probable) |

Rules shared in `sources/matching.py`: a record whose legal name reads as a
person (`household.reads_as_person` with "law" read as a surname) is never
stored, nor an individual or sole proprietorship by the source's own flag; a
name alone never matches, and a one-word or generic name needs the place key.
Each load keeps only the records whose name could be an employer's, so the
database stays small; an employer first seen after a load is matched at the
next one. The match tables (`grant_matches`, `alberta_matches`,
`fmcsa_matches`) are rebuilt every night and after an id migration, and the
export writes `grants` (newest 20), `grants_total`, `alberta` and `us_carrier`
into each profile, and `designated` (the matched listings, `designated_matches`)
and `intl` (postings open to international candidates whose employer identity
names the profile, newest 20) only when there are any. The federal corporations extract now keeps each
corporation's business number (`federal_corporations.business_number`); a
file loaded by the older parser is read again once.

## Reference tables for the wage and unemployment indicators
Downloaded into the cache under `data/raw/cache/` like the other open data and
loaded into pipeline-local tables; none of it is committed.

| Table | Source | Licence | Fetched |
|---|---|---|---|
| `wage_tables`, `jobbank_wages` | Wages, ESDC (Job Bank), one CSV a year, about 18 MB (the 2025 file is revised 2025-11-19): low, median and high wage per NOC 2021 occupation for Canada, each province and territory and each economic region. Dataset: https://open.canada.ca/data/en/dataset/adad580f-76b0-4502-bd05-20c125de9116 | Open Government Licence, Canada | listing checked monthly; each yearly file downloaded once; the newest two kept |
| `lfs_unemployment` | Statistics Canada table 14-10-0459-01, Labour force characteristics by census metropolitan area, three-month moving average (the unadjusted series is kept, which is what ESDC's refusal table shows). Table: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410045901, download: https://www150.statcan.gc.ca/n1/tbl/csv/14100459-eng.zip (about 4 MB) | Statistics Canada Open Licence | at most monthly, revalidated by ETag |
| `statcan_vacancies`, `noc_titles` | Statistics Canada table 14-10-0444-01, Job vacancies and average offered hourly wage by occupation (unit group), quarterly, unadjusted for seasonality (Job Vacancy and Wage Survey). Table: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410044401, download: https://www150.statcan.gc.ca/n1/tbl/csv/14100444-eng.zip (about 100 MB zipped, 1.2 GB unzipped, read as a stream; the WDS API would need hundreds of requests for its 137,000 series). The newest eight quarters of the unit groups and the all-occupations total are kept; a region published only combined with a neighbour is stored under both codes. Titles: NOC 2021 Version 1.0 classification structure, https://www.statcan.gc.ca/en/subjects/standard/noc/2021/indexV1 (English and French CSVs) | Statistics Canada Open Licence | table at most monthly, an unchanged file not parsed again; titles once |
| `program_editions`, `program_figures` | Three ESDC pages on canada.ca, read as HTML: LMIA processing times (https://www.canada.ca/en/employment-social-development/services/foreign-workers/labour-market-impact-assessment-processing-times.html), refusal to process with the unemployment rate by CMA (https://www.canada.ca/en/employment-social-development/services/foreign-workers/refusal.html), hourly wage thresholds (https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage.html). One row per edition, never overwritten | canada.ca terms and conditions (non-commercial reproduction with attribution) | each page at most once every 20 hours |
| `fsa_regions` | Statistics Canada 2021 Census cartographic boundary files: economic regions, census metropolitan areas, forward sortation areas (https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm). The zipped files there sit behind a browser challenge, so the same layers come from Statistics Canada's map service, https://geo.statcan.gc.ca/geo_wa/rest/services/2021/Cartographic_boundary_files/MapServer (layers 2, 6 and 14), as JSON, one request per province per layer, about 40 MB in all | Statistics Canada Open Licence | once; cached for good |

`fsa_regions` gives each forward sortation area one point: the GeoNames
centroid when it lies inside the area's own 2021 boundary, otherwise an
interior point of that boundary (158 of 1,664 areas). The point is placed in
an economic region (offshore points take the nearest within 10 km) and, when
it falls inside one, a census metropolitan area. An area that straddles a
boundary goes wholly to one side; about 2 percent of areas change region
depending on which point is used, which bounds how many can be misplaced.
The table is rebuilt only when the cached boundary responses, the centroids
or `DERIVATION_VERSION` change. The map service answers some requests with
HTTP 500 and the next attempt succeeds, so that stage uses a client with
eight attempts. First load takes about two minutes; later nights read the
cache in seconds.

## Politeness
`http.PoliteClient` spaces requests per host (5 s for Job Bank, from its
robots.txt), retries with backoff, stops the stage after five failed requests
in a row, and caches open-data downloads with ETag revalidation. The user
agent names the project and its mailbox, read from `LMIAWATCH_SITE_URL` and
`LMIAWATCH_CONTACT`.

## Forward sortation area centroids
`scripts/build_fsa_centroids.py` writes `lmia_pipeline/data/fsa_centroids.csv`
from the GeoNames postal dataset (CC BY 4.0). The pipeline loads that file on
every run. Map points sit at area centroids, never at an address.

## Province boundaries for the daily card
`scripts/build_province_boundaries.py` writes `lmia_pipeline/data/provinces_2021.json`,
the outlines the daily card's map is drawn from: Statistics Canada's 2021 cartographic
boundary file for provinces and territories, read from the same map service as the
other boundaries and cut down for a 1200-pixel card (small islands dropped,
Douglas-Peucker on the rest). The three Maritime provinces keep finer detail because
the card's inset enlarges them. The file is committed and read at render time; rerun
the script only for a new Statistics Canada edition. The Methodology and Data pages
carry the credit.
