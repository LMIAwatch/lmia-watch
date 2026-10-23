# Hosted search database

The nightly workflow keeps a copy of the search rows in a D1 database of its
own, `lmia-watch-search` (binding `SEARCH` in `site/wrangler.jsonc`), so the
search page can later query it instead of loading large files in the
browser. This is step 1 of hosted search: the database is filled and kept
current every night, and nothing on the site reads it yet. The code is
`pipeline/lmia_pipeline/search_db.py`, the schema `pipeline/search_schema.sql`
and the step "Sync the search database" in `.github/workflows/nightly.yml`.

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
`search_rows`. Seven ordinary indexes serve the queries step 2 will run
(newest first, by status, by province, by year, by employer, by occupation,
by name).

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
2. Wrangler applies `search_schema.sql` (every statement `IF NOT EXISTS`, so
   it changes nothing on a database that has it), then each batch in order.
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
| First load or full reload | 224 MB of SQL in 46 batches (459 bytes a row) | about 5 million: each row writes itself, its eight index entries and its full-text entries |
| A night | a few thousand changed rows, one batch | tens of thousands |
| A new ESDC quarter | about 15,000 new rows, two batches | about 150,000 |
| The count check | one read of the table | about 490,000 rows read a night, 15 million a month |

Loaded, the database takes about 285 MB (the scaled copy in SQLite, tables,
indexes and full-text index together). A full reload uses about
a tenth of a month's included writes, and the automatic ones come at most
weekly, so even a month of failing nights stays inside the allowance.

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
