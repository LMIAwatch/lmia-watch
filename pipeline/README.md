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
python -m lmia_pipeline run --export                             # csv, mirror and static JSON
python -m lmia_pipeline run --export --d1 --full                 # paid-plan path: D1 batches too
python -m lmia_pipeline mark-synced                              # after D1 batches were applied
python -m lmia_pipeline post-digest --dry-run                    # print the daily X post, send nothing
```
`post-digest` posts one message a day to X from the postings first seen on the
latest Job Bank pass, when `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN` and
`X_ACCESS_TOKEN_SECRET` are set. It records the posted date in `meta`, so a
re-run posts nothing, and it always exits 0. Setup: `../docs/x-account.md`.
Stage order: esdc, ircc, jobbank, registry, indicators and status, export.
`--limit` caps Job Bank list pages per facet and also disables the "gone"
marking, because a capped run has not seen the whole feed.

## Stages
| Module | Does |
|---|---|
| `sources/esdc.py` | discovers every quarterly file through CKAN, downloads and parses it (CSV to 2020 Q3, XLSX after), records provenance in `esdc_resources` |
| `sources/jobbank.py` | pages both LMIA facets, upserts postings, logs each observation, fetches new posting pages within a budget, drops private-household postings before storage |
| `sources/ircc.py` | parses the non-compliant employers JSON and the reason legend from the page |
| `sources/registry_bc.py` | OrgBook BC lookups for BC employers, graded matches |
| `sources/registry_federal.py` | Corporations Canada bulk extract, matched by normalized name |
| `indicators.py` | the rules (version in `RULES_VERSION`) |
| `status.py` | employer rollups, the status lifecycle, meta counters |
| `export.py` | CSV files, the raw-file mirror with checksums, optional D1 batches |
| `export_static.py` | the JSON files the site serves |
| `social.py` | the daily X digest: compose, save to `data/out/social/`, post (separate `post-digest` command) |
| `social_card.py` | the card image attached to the digest, drawn with Pillow from the day's figures |

## Outputs
```
data/lmia.sqlite        the database (schema: ../pipeline/schema.sql)
data/out/csv/           files the Data page offers
data/out/mirror/        raw ESDC files plus SHA256SUMS
data/out/static/        the JSON the site serves as static assets (see export_static.py):
                          stats.json, search/latest.json, search/pending.json,
                          search/<PROV>/postings.json, search/<PROV>/<YEAR>.json,
                          clusters/*.json, areas/<FSA>.json, profiles/<abc>.json
data/out/d1/            only with `run --export --d1`: batches for a paid D1 database,
                        plus manifest.json and the `mark-synced` command
```
The static export is deterministic (sorted keys and rows), so an unchanged file
keeps its bytes and the deploy skips it. Each file stays under the 25 MiB
static-asset limit because province data is split by year.

## Registries
`sources/registry_bc.py` queries OrgBook BC per employer (BC only, budgeted).
`sources/registry_federal.py` downloads the Corporations Canada open-data CSVs
(active and inactive CBCA corporations, about 260 MB, cached a week), loads them
into the local `federal_corporations` table and matches every employer by
normalized name; a match is exact when the province or postal code agrees,
probable otherwise.

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
