# Hosted search database

The nightly workflow keeps a copy of the search rows in a D1 database of its
own, `lmia-watch-search` (binding `SEARCH` in `site/wrangler.jsonc`), so the
search page can query it instead of loading large files in the browser.
Step 1 of hosted search fills the database and keeps it current every
night; the code is `pipeline/lmia_pipeline/search_db.py`, the schema
`pipeline/search_schema.sql` and the step "Sync the search database" in
`.github/workflows/nightly.yml`. Step 2 is the search API on top of it,
`GET /api/search` (see *The API* below; `site/src/search_db.ts`), which only
the site's own search page may call for now. The search page itself does not
use it yet; that is step 3.

## What the database holds

One table, `search_rows`, with one row per:

- ESDC list row since 2014, positive and negative (483,021 on 2026-10-23);
- Job Bank posting whose LMIA flag is requested or approved (4,526). A
  posting whose flag is gone from Job Bank leaves the table, as it leaves the
  search page today.

Each row carries the fields the static search files carry (kind, reference,
employer id and name, job or occupation, NOC, address, wages, date or period,
positions, status, stream, source link, sort date) plus:

| Column | Holds |
|---|---|
| `rid` | a stable integer id: the list row's id times 2, or the posting id times 2 plus 1 |
| `key` | `e:<list row id>` or `p:<posting id>` |
| `year` | the list period's year, or the posting's sort date's year |
| `ind` | the employer's triggered indicators, comma separated |
| `name_fold` | the employer name in lower case without accents, for the name sort |
| `hash` | a SHA-1 over every other column, which tells the sync what changed |

A full-text index, `search_fts`, covers the employer name, the job or
occupation title and the city, with accents ignored ("quebec" finds
"Québec"). Triggers on `search_rows` keep it in step, so the sync writes only
`search_rows`. Eleven ordinary indexes serve the API's queries: one per sort
in its order (newest, positions, name), newest within one status and within
one province, and one each for year, stream, indicator set, occupation,
kind and employer. Step 2 replaced four of step 1's indexes (their columns
did not let a page seek to its cursor) under new names, so applying the
schema file again rebuilds nothing; the first night that applies it builds
the new ones once, about 3.8 million index rows written.

The database is separate from `lmia-watch`, which holds what readers submit,
so a full reload here can never touch a response or a correction. It needs
no backup of its own: a full reload rebuilds it from the pipeline database.

## How the nightly sync works

The step runs after "Check the database and the export", when both checks
passed, and before the deploy and the R2 save.

1. `search-sync` reads tonight's rows from the pipeline database and compares
   each row's hash with the ledger, the table `search_sync` in the same
   SQLite file, which records the key and hash of every row as last confirmed
   in D1. New and changed rows become upserts, keys the ledger holds that
   tonight lacks become deletes. It writes them as `data/out/search/batch-0001.sql`
   and on, at most 5 MB or 5,000 statements each, with up to 100 rows in one
   upsert statement and 500 keys in one delete (and no statement above
   64 KiB, well inside D1's 100 KB), and `manifest.json`: the files in order,
   the counts, the number of rows D1 must hold afterwards, and the ledger
   entries to record.
2. Wrangler applies `search_schema.sql` (every statement `IF NOT EXISTS`, or
   `DROP INDEX IF EXISTS` for an index name an earlier version used, so it
   changes nothing on a database that has it), then each batch in order.
   D1 runs each file as one transaction and rolls it back if any statement
   fails, so the step stops at the first failed batch with every earlier one
   applied in full.
3. Wrangler reads `SELECT COUNT(*) FROM search_rows` back, and `search-check`
   compares it with the manifest.
4. Only then does `search-synced` record the manifest's entries in the ledger,
   and the step writes `synced` (or `nothing to send`) in the run status.

Nothing else writes the ledger. A night that stops anywhere leaves it as it
was, and the next night sends the same changes again; every statement gives
the same result when applied twice. The ledger travels to R2 with the
database, which is why the step runs before the save.

A full reload drops both tables, applies the schema again and sends every
row. The sync makes one by itself in two cases, but never twice within seven
days:

- the ledger is empty: the first load, or a database restored without its
  ledger;
- the count read back disagreed with the manifest on an earlier night. A
  resend cannot repair every such case: a row applied on a night whose later
  batch failed, and gone from the data before the retry, is in D1 without
  ever being in the ledger. A full reload removes it.

Between reloads, an empty ledger still sends every row, and a row D1 already
holds with the same hash costs no write.

## What it costs

The Workers Paid plan includes 5 GB of D1 storage, 25 billion rows read and
50 million rows written a month. Figures measured on 2026-10-23 on a copy of
the test data scaled to the real row counts:

| | Size | Rows written (estimate) |
|---|---|---|
| First load or full reload | 224 MB of SQL in 46 batches (459 bytes a row) | about 7 million: each row writes itself, its twelve index entries (eleven indexes and the unique key) and its full-text entries |
| A night | a few thousand changed rows, one batch | tens of thousands |
| A new ESDC quarter | about 15,000 new rows, two batches | about 150,000 |
| The count check | one read of the table | about 490,000 rows read a night, 15 million a month |

Loaded, the database takes about 360 MB (a copy built from the real rows of
2026-10-17 with step 2's indexes, tables, indexes and full-text index
together; 300 MB with step 1's). A full reload uses about a seventh of a
month's included writes, and the automatic ones come at most weekly, so even
a month of failing nights stays inside the allowance. What the API reads is
under *The API*.

## Forcing a full reload

Usually there is no need: a count that disagrees schedules one by itself. To
force one anyway, from the project account's own machine (never a personal
one), with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set, on a copy
of the newest backup (`lmia.sqlite.gz` from R2, or the weekly pull folder)
unpacked to `data/lmia.sqlite`:

```
cd pipeline
python -m lmia_pipeline search-sync --db ../data/lmia.sqlite --full
cd ../site
npx wrangler d1 execute lmia-watch-search --remote --yes --file ../pipeline/search_schema.sql
npx wrangler d1 execute lmia-watch-search --remote --yes --file ../data/out/search/batch-0001.sql
npx wrangler d1 execute lmia-watch-search --remote --yes --file ../data/out/search/batch-0002.sql
...                                  (every batch in manifest.json, in order, stopping at a failure)
npx wrangler d1 execute lmia-watch-search --remote --json --command "SELECT COUNT(*) AS n FROM search_rows"
cd ../pipeline
python -m lmia_pipeline search-check --manifest ../data/out/search/manifest.json --count <n>
```

`batch-0001.sql` drops and recreates the tables, so the search database is
empty until the last batch is applied. A changed column or tokenizer in
`search_schema.sql` reaches D1 only this way, since `IF NOT EXISTS` leaves an
existing table as it is.

`search-synced` is not needed: it would record the ledger in the local copy,
and the ledger that counts is the one in R2's database. The next night
compares its rows with that ledger; the reload sent the backup's rows, so the
night sends only what changed since, and if the two ever disagree the count
check catches it and schedules a reload. Avoid the nightly run's window
(00:00 UTC to about 01:00 UTC), when the workflow writes to the same
database.

## Checking the count

The step log prints `N rows expected afterwards` (from `search-sync`) and
the count D1 answered (from `search-check`). By hand:

```
cd site
npx wrangler d1 execute lmia-watch-search --remote --command "SELECT COUNT(*) FROM search_rows"
```

against the pipeline database:

```
SELECT (SELECT COUNT(*) FROM esdc_records)
     + (SELECT COUNT(*) FROM jobbank_postings WHERE flag_current IN ('requested', 'approved'));
```

The two agree after a night that synced. They differ during a night's run,
and after a night that failed until a later night succeeds.

## When the run status says "failed"

`search_sync: failed` in `status.json` is an attention item: the workflow's
last step lists it (so the run is marked failed and GitHub emails) and the
rest of the run carries on, deploy and R2 save included. It means one of:

- `search-sync` could not read the database or write the batches (the step
  log names the row and column of a value that cannot be written, such as
  text holding a NUL byte);
- Wrangler could not apply the schema or a batch (an API error, a revoked
  token, D1 unavailable). D1 rolled that batch back;
- the count read back disagreed with the manifest. Nothing was recorded, and
  a full reload is scheduled (at most weekly);
- the step reached its 60-minute limit (a first load or full reload on a slow
  night).

In every case the ledger is unchanged and the next night sends the same
changes again. `nothing to send` means no row changed, which also passed the
count check; `not run` means the checks before it failed, so no sync was
attempted.

The Worker's daily check does not yet email on this field; the workflow's
failure email covers it.

## The API

`GET /api/search` answers from this database (`site/src/search_db.ts`, route
in `site/src/api.ts`). Nothing a reader sees uses it yet; step 3 moves the
search page onto it.

### Who may call it

The API is not open to the public yet: the route answers the site's own
search page only. A request is accepted when its `Sec-Fetch-Site` header is
`same-origin` or `same-site`; a browser too old to send that header is
accepted when its `Referer` or `Origin` names the site's own host
(`lmiawatch.ca`, `www.lmiawatch.ca`, or the host the request came to, so a
local run works). Anything else gets 403 with
`{"error": "the search API is not open; the site's search page uses it"}`,
`Cache-Control: private, no-store` and `Vary: Sec-Fetch-Site, Origin, Referer`,
so no shared cache can hand that refusal to the page's own request. These
headers can be forged, so this is a speed bump, not security: the brake is
the per-address API limit (`site/src/limits.ts`, 60 a minute). A keyed route
for programmatic use is a later step and will skip the check (`pageOnly` in
`api.ts`).

### Parameters

Every parameter is optional. A value that fails its check is dropped, never
an error, and the response names the parameter (not the value) in
`ignored`; repeated values beyond the cap and text beyond its length are cut
the same way. The one exception is `cursor`: a cursor the API did not issue
is a 400.

| Parameter | Accepts | Bounds |
|---|---|---|
| `q` | words, matched as word prefixes in the employer name, the job or occupation title and the city, accents ignored | 200 characters after trimming, the first 8 words |
| `status` (repeatable) | `pending`, `approved`, `refused` | 3 values |
| `province` (repeatable) | the thirteen two-letter codes, `XX` (head office outside Canada), `UN` (no province) | 15 values |
| `stream` (repeatable) | `High Wage`, `Low Wage`, `Primary Agriculture`, `Global Talent Stream`, `Permanent Resident Only`, and ESDC's other spellings `Global Talent` and `Talent mondial`; a stream matches every spelling ESDC used for it | 7 values |
| `noc` | 1 to 5 digits: a prefix of the occupation code. Anything else: words matched in the job or occupation title only | 60 characters |
| `wage_min`, `wage_max` | a decimal number (up to 4 decimals): the posting's minimum wage at least, or its maximum wage at most; postings only | 0 to 10,000 |
| `year_from`, `year_to` | a year: the list's period year, or the posting's year | 2014 to next year |
| `date` | `any`, `7d` (postings of the last 7 days), `last_quarter` (postings of the last 92 days and every list row), counted from the data's date | allowlist |
| `indicator` | one of the six indicator keys | allowlist |
| `sort` | `newest` (default), `positions`, `name` | allowlist |
| `cursor` | the `next` value of the previous page, as given | 8,200 characters, checked field by field |

### Response

```
{ "rows": [...], "total": 4279, "capped": false, "facets": {...}, "next": "...", "ignored": ["wage_max"] }
```

- `rows`: up to 50 rows, each shaped as the static search files' rows
  (`SearchRow` in `site/src/data.ts`).
- `next`: present when another page exists; pass it back as `cursor` with
  the same filters and sort. Paging is by keyset, so page 100 costs what
  page 1 does. Rows come newest first by sort date, by positions (largest
  first, rows without a count last) or by name, each with the row's key as
  the tiebreak, so a walk through every page sees each row once.
- `total`: the number of matching rows, at most 10,000, with `capped: true`
  when there are more. `null` on a later page when counting again would
  read rows (the first page carried it).
- `facets`: counts by status and by province, each with every other filter
  applied, when the request filters only on status, province, stream, year
  and indicator.
- 503 `{"error": "search unavailable"}` (not cached) when the database is
  missing or a query fails; step 3's page falls back to the static files.
- Successful answers carry `Cache-Control: public, max-age=300`.

### Totals

Counting is what reads rows, so totals come from the cheapest source that
is exact:

1. `search/counts.json`, written by the export beside the search files: the
   database's rows counted by status, province, stream, year and indicator
   set (about 3,000 cells, 50 KB). A request filtering on nothing else gets
   its total and facets from it with no database read, and a request whose
   status, province, stream, year and indicator filters match no row is
   answered empty without the database.
2. A text query with no other filter: the count the planner reads from the
   full-text index anyway, capped at 10,001.
3. A first page with fewer than 51 rows: its rows are the total.
4. Otherwise `SELECT COUNT(1) FROM (SELECT rid ... LIMIT 10001)` through the
   index that lists the fewest rows.

The counts file ships with the deploy and the database is synced just
before it, so the two agree after a good night. After a night whose sync
failed, totals from the file describe tonight's data while the rows are last
night's, until a sync succeeds.

### How a request is read

Each sort has an index in its order, and a page seeks to its cursor with a
row value such as `(sort_date, key) < (?, ?)`; filters the index cannot
answer are checked as the rows go by. When a filter lists few rows through
an index of its own (one status or province, a year, a stream, an indicator
set, a NOC prefix, the postings a wage or posting-date filter implies, or a
text query), the API reads those rows and sorts them instead: up to 5,000
always, and up to 20,000 when the counts file shows the filters together
match so few rows that reading in order would cost more. Without the counts
file the planner sizes the filters with probes that read at most 5,001
index entries each.

### No SQL injection, nothing a visitor can make expensive

- Every statement is prepared with `?` placeholders and bound values. The
  SQL is assembled from fixed fragments; which fragments appear depends on
  which filters a request uses and how many values each has, never on the
  values. The tests build the SQL for every parameter with injection
  payloads and check that none of the payload text appears in it, and run
  every payload through the route, checking for a 200 (400 for a cursor)
  and an unchanged table.
- Filter values, sort keys and date windows come from allowlists in code.
- Text never reaches `MATCH` as typed: at most 8 words, each stripped to
  letters, digits and apostrophes and written as a quoted FTS5 phrase with a
  prefix star (`"tim"* "horton"*`), so `AND`, `OR`, `NOT`, `NEAR`, column
  filters, parentheses, `^`, `*` and `-` are plain words. A one-letter word
  is matched whole, without the star: a one-letter prefix makes FTS5 merge
  every word starting with that letter (about 28 ms each on the full data).
- The cursor is base64url JSON the API wrote; each sort's cursor has exactly
  its fields, each of its type and within its bounds, or the request is a
  400.
- Pages are 50 rows by keyset, never an offset; counts stop at 10,001.

Measured on a local D1 holding the real rows of 2026-10-17 (478,772 rows),
rows read per request including the probes and the count:

| Request | Rows read |
|---|---|
| No filter, newest, first page (total from counts.json) | 51 |
| No filter, a page deep inside one quarter | 52 |
| One status or one province, newest | 51 |
| Nunavut, by name | 251 |
| Permanent Resident Only, by positions | 9,749 |
| A rare indicator (refused, then reposted), any sort | 1,614 |
| A wage filter | 16,645 |
| `q=tim hortons` | 2,785 |
| A NOC code (63200) | 19,511 |
| `q=inc` (a word in about 220,000 rows) | 230,078 |
| `q=inc` with a rare indicator | 451,799 |

What stays large is a text query whose words match most rows: the full-text
index lists its matches once per statement, one row read each, and a rare
other filter can add a count that reads them again. Checking each row
against the index one at a time instead would read almost nothing but takes
about 4 ms a row in CPU, since FTS5 rebuilds a prefix term's list on every
call; a prefix index on `search_fts` (`prefix='2 3'`, which needs a full
reload) would make that check cheap. Without the counts file, an indicator
filter is checked row by row (481,618 rows for a first page).
