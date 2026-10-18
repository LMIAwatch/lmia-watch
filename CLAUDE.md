# LMIA Watch, project guide for Claude

> Living reference for AI-assisted work on this repo. Last updated 2026-10-13 (free-tier framework).

## What this is
A public website showing which Canadian employers are applying to hire temporary
foreign workers under a Labour Market Impact Assessment (LMIA), where, and when,
and which applications were approved or refused. Two halves, one schema:

- **`pipeline/`**: Python 3.13. Scrapes Job Bank's LMIA-flagged postings, loads every
  ESDC quarterly positive and negative list, parses IRCC's non-compliant employers,
  matches employers to the BC Registry and the federal corporations extract, merges
  them, computes indicators, and exports CSVs, a checksummed mirror, and the static
  JSON the site serves. Owns a local SQLite file at `data/lmia.sqlite`.
- **`site/`**: Cloudflare Worker (TypeScript, Hono). Pages and the JSON API read the
  pipeline's JSON files, shipped as the Worker's static assets. The search and map
  pages filter in the browser. D1 holds only the two tables the forms write
  (`employer_responses`, `corrections`); R2 holds the downloads and the database.
- **`pipeline/schema.sql`** is the single source of truth for the database. Change
  it in the same commit as the code on both sides.

Dependency is one-way: the site reads what the pipeline produced. Nothing in `site/`
imports from `pipeline/` and nothing in `pipeline/` knows the site exists.

## Rules most costly to get wrong
1. **The operator stays pseudonymous.** Nothing in this repo, its commits, its
   deployed site or its outbound requests names the person behind it. See
   *Operator anonymity* below. Treat a leak as a security bug.
2. **Crawl politely.** Job Bank's robots.txt sets `Crawl-delay: 5`. The HTTP client
   enforces 5 s between requests to jobbank.gc.ca, sends a named user agent whose
   contact is the site's own address, retries with backoff, and aborts a run after
   repeated failures. Never run a national scrape from a dev machine; use `--limit`.
3. **Private individuals are never stored.** Job Bank pending postings include
   household employers (caregivers, nannies, home support) under a personal name.
   They are dropped before anything is written, and only the count is logged.
   ESDC already strips personal-name employers from its lists.
4. **Records are records, indicators are not findings.** Every UI string and doc
   keeps that line. Government findings (IRCC non-compliance) are shown separately
   and never mixed into the indicator table. No accusatory copy anywhere.
5. **One scheduled refresh a day, nothing else.** The workflow's only trigger is
   the midnight UTC schedule: no manual trigger, no push trigger, and no endpoint
   on the site can start a run. The pipeline itself refuses a second Job Bank
   pass within 20 hours unless `--force` is given on a dev machine. Page views
   cost no database reads. Anything that needs a manual action after setup, or a
   paid plan, is a bug. See *Free-tier architecture* and *Automation*. The one
   knowing exception is the optional daily X post (`post-digest`): X's API is
   pay-per-use since 2026-02-06, so that step is opt-in through the repository
   variable `X_POST_ENABLED` and is the only recurring cost if the owner turns
   it on.
6. **No em-dashes** in any prose: docs, UI strings, READMEs, commit messages. Use a
   period, comma, colon or parentheses. Avoid filler and AI-tell vocabulary.
7. **Provenance on every row.** Each record carries the Job Bank posting id or the
   CKAN resource id it came from. Raw ESDC files are kept and checksummed.
8. **The site is public.** Nothing internal (operator notes, scraping budgets,
   unfinished indicators) appears in page copy. Placeholders in square brackets are
   fine during the framework stage and must be gone before launch.

## Operator anonymity
Public untraceability is the goal. Legal untraceability is not achievable (a court
order can reach a registrar or host), so the design assumes a careful pseudonym, not
secrecy from the law.

- **Separate accounts for GitHub and Cloudflare**, created for the project and
  never logged into from the same browser profile as personal accounts. The
  sign-in address is never public, so a plus-alias of an existing address serves
  and no new mailbox is needed; what is public is the GitHub username and the
  `workers.dev` subdomain, so both are neutral words. The site has no email at
  all: the user agent and the About page point at the corrections form. The site
  lives on its own domain (registrar with WHOIS redaction); `workers_dev` is
  false in `site/wrangler.jsonc` because the account's `workers.dev` subdomain
  would name the operator in every URL.
- **Git identity is local to this repo** (`git config --local`): name `LMIA Watch`,
  email `ops@lmiawatch.invalid` until the project mailbox exists. Commit with
  `TZ=UTC` so timestamps carry no timezone. Never push this repo to a personal
  GitHub account or from a session that has personal credentials loaded.
- **No personal data in the tree**: no real names, personal emails, local machine
  paths, or other repos' names in code, comments, fixtures, docs, or commit
  messages. Fixtures are public web pages only.
- **Outbound requests** identify as `LMIAWatch/<version> (+<site url>; <site url>/corrections)`.
- **The site's About page** names the project, not a person. Contact is the project
  mailbox. No analytics, no third-party scripts beyond the map library and tiles.
- Text drafted with an AI assistant carries no information about the account that
  drafted it, so that is not a leak path; writing style is the remaining one, and
  short factual copy minimizes it.

## Free-tier architecture (why the data is static JSON)
The dataset is read-heavy and bulk-loaded: 474k list rows, 166k employers, about a
million indicator rows. On Cloudflare's free plans that rules out serving it from
D1 (100,000 row writes a day, counted per index, so the first load alone would take
weeks; 5 million row reads a day, which a table scan per search would exhaust).
So the pipeline publishes JSON files and the Worker ships them as static assets,
which are free to serve and do not count against the Worker's request allowance:

| File | Purpose | Size (2026-10-13) |
|---|---|---|
| `stats.json` | counts, breakdowns, recent lists, resources, runs | small |
| `search/latest.json` | pending and approved postings plus the latest quarter | 6 MB raw, 0.6 MB compressed |
| `search/<PROV>/<YEAR>.json`, `search/<PROV>/postings.json` | the long scope, loaded by the browser only when asked | up to about 10 MB raw per file |
| `clusters/*.json`, `areas/<FSA>.json` | map counts and per-area listings | small |
| `profiles/<abc>.json` | 4,096 shards keyed by employer id characters 5 to 7, full history | about 130 KB each |

Limits that shaped it: 20,000 files per Worker version, 25 MiB per file (why the
province files are split by year), 10 ms CPU per request on the free plan (why the
Worker never parses a large file; a profile page reads one shard), 100,000 Worker
requests a day. The whole export is about 650 MB raw; `wrangler deploy` uploads
only files whose content hash changed. Downloads and the SQLite file live in R2
(10 GB free). D1 free covers the two form tables many times over. GitHub Actions
gives a private repository 2,000 free minutes a month, which the nightly run fits
under (see *Automation*). A custom domain is the one optional cost.

`export.py` still writes D1 batches when `run --export --d1` is used; that is the
paid-plan path and is not part of the nightly run.

## Performance rules (snappy first, then as much data as asked for)
- **No filter change ever waits on the network.** The search page is rendered on
  the server for a plain visit (from `search/first.json`, the newest 500 rows,
  with counts from `search/facets.json`), then `search.js` fetches the default
  scope once in the background (`search/latest/all.json`, about 0.6 MB
  compressed) and answers every filter, sort and page change from memory. A deep
  link with filters renders first from the smallest slice that answers it
  (`latest/status/<s>`, `latest/prov/<P>`, `latest/prov/<P>/<s>`), then switches
  to the full set silently when it arrives. Text inputs are debounced at 150 ms.
- **The server never parses more than about 300 KB of JSON per request**: one
  profile shard (median 117 KB, max 228 KB) or `first.json`. That keeps every
  page inside the free plan's 10 ms CPU allowance.
- **Big views are served on request, never by surprise.** The long scope (since
  2023 Q4, 190k rows, about 100 MB raw across 60 files) is loaded only when the
  visitor picks it; above 2 MB raw the page states the record count and size
  with a "Load" button and the CSV alternative, then loads file by file with a
  running count. Once loaded it is answered from memory like everything else.
  Switching back to the default scope is instant because that data stays in
  memory.
- **Worst cases checked against the data (2026-10-13):** the busiest employer has
  168 list rows, so a profile page renders the newest 100 open and the rest
  inside a collapsed `<details>` block with the profile JSON linked; every long
  scope row has a province, and rows without one go to a `UN` bucket rather than
  vanishing; a missing slice file reads as "no rows", never an error; a browser
  CSV export above 50,000 rows points at the server-side downloads instead;
  no file exceeds 25 MiB (province data is split by year, largest 12 MB).
- **Traffic ceiling:** 100,000 Worker requests a day on the free plan, counted
  per page render, not per asset. If a news spike ever approaches that, the
  home, methodology and data pages can be pre-rendered as static HTML by the
  nightly run; profile pages cannot (166k of them) and would stay dynamic.

## Traffic limits (the free tier hard-stops; abuse costs uptime, not money)
- Workers Free, D1 Free and the Actions minutes all stop with errors at their caps;
  R2 reads are capped by the Worker cap. Nothing a visitor does can create a bill.
  A flood can take the site down for the rest of the UTC day, so abusive traffic
  is kept away from the Worker: static files under `/data/` and `/fonts/` are
  served before the Worker and never count; the dashboard rate-limiting rule
  (`docs/traffic-limits.md`, Free plan allows one) blocks a hot address at the
  edge; and `site/src/limits.ts` applies per-address caps inside the Worker
  (pages 120/min, API 60/min, downloads 10/min, form posts 5/min, keyed on the
  edge-set `cf-connecting-ip`) through the `ratelimits` bindings in
  `wrangler.jsonc`, answering 429 with `Retry-After`. A missing binding means
  no limit, never an error. Emergency switch: the dashboard's Under Attack
  Mode, which challenges every visitor at the edge.

## Alerts (how the operator hears about maintenance items)
- Two channels, no new accounts. (1) The Worker's daily check (`site/src/watchdog.ts`,
  cron `0 6 * * *`) reads `stats.json`, the backup's timestamp and `status.json` in
  R2 (written by the workflow each run), and emails `ALERT_EMAIL` (a Worker secret)
  from `ALERT_FROM` through the `send_email` binding when data is stale, a backup or
  status is missing or old, a stage failed, or the X post was refused. The
  destination must be verified in the zone's Email Routing (`docs/alerts.md`); with
  no binding or address it only logs. (2) The workflow's last step fails the run on
  the same conditions, so GitHub's failed-workflow email goes out too.

## Automation (how the site keeps itself current)
- `.github/workflows/nightly.yml` on the project's GitHub account has one trigger,
  `schedule: 0 0 * * *` (midnight UTC, which GitHub may delay by some minutes), and
  a concurrency group so two runs never overlap. It restores `data/lmia.sqlite`
  from R2, runs all stages, copies `data/out/static` to `site/public/data`, runs
  `wrangler deploy` from the checked-out `main`, then saves the database, the data
  bundle and the CSV mirror back to R2. Code changes therefore go live with the
  next scheduled run; there is no push-to-deploy job and no `workflow_dispatch`.
  An urgent code fix can be deployed from the project account's own machine with
  `npm run deploy` after `npm run data:local`, never from a personal one.
- Optional X post: after the deploy and before the R2 save, the workflow runs
  `python -m lmia_pipeline post-digest` (`pipeline/lmia_pipeline/social.py`) when
  the repository variable `X_POST_ENABLED` is `true` and the four secrets
  `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` exist. One
  digest per completed Job Bank pass (the date is recorded in `meta`, so a re-run
  never double-posts), `continue-on-error`, never fails the refresh. Setup and
  the cost figures: `docs/x-account.md`. The text carries no link (X bills a
  post with a URL at thirteen times the rate); the attached card image
  (`social_card.py`, Pillow, Public Sans from `brand/fonts/`) carries the site
  address and the breakdown instead. `X_POST_LINK=true` adds the link.
- Donations: the payment page (Ko-fi) posts one notice per payment to
  `POST /hooks/kofi` (`site/src/hooks.ts`), checked against the Worker secret
  `KOFI_VERIFICATION_TOKEN` (`npx wrangler secret put`), stored in the site-owned
  `donations` table as amount, time, kind and transaction id only (no name,
  email or message, ever), repeats ignored. `site/src/support_data.ts` turns the
  rows into the support page's figures: last-30-day support, a quarterly ledger
  from `SITE_START`, spent = monthly cost per month started, reserve = the
  difference floored at zero. No operator-maintained constants remain. Setup:
  `docs/kofi-webhook.md`. After a schema change, re-run the remote
  `d1 execute --file=../pipeline/schema.sql` (idempotent).
- **Every `wrangler r2 object get/put` needs `--remote`.** Wrangler 4 defaults these
  commands to a local simulated bucket under `.wrangler/state`, so without the flag
  a backup "succeeds" into a folder that is thrown away (found 2026-10-18: the first
  night's uploads never reached R2). The workflow and the README commands carry it.
- The pipeline's own guard (`JOBBANK_MIN_HOURS` in `cli.py`) skips the Job Bank
  stage when a pass ran in the last 20 hours, so a re-run of a failed night still
  sends at most one crawl a day. The other stages are cheap and idempotent.
- The last step commits `LAST_RUN.md` with the run date under the project
  identity. GitHub pauses scheduled workflows after 60 days without repository
  activity; this keeps the schedule alive with no human step.
- Secrets: `CLOUDFLARE_API_TOKEN` (Workers, R2, D1 on the project account only),
  `CLOUDFLARE_ACCOUNT_ID`. Variables: `SITE_URL`, `CONTACT`.
- Budget: the repository is private, which gives 2,000 free Actions minutes a
  month. List pages for both facets take about 25 minutes at the crawl delay;
  detail pages are fetched only for postings not seen before, 200 a night (the
  workflow passes `--detail-budget 200`), so the first backfill of about 6,000
  takes a month and a night stays near 45 to 55 minutes. The federal
  corporations extract (260 MB) is re-downloaded weekly. If the monthly cap is
  ever hit, runs fail until the reset and the site keeps its last refresh.

## Data sources (all public)
| Source | How | Cadence |
|---|---|---|
| Job Bank search, facet `fskl=101010` (LMIA requested) and `101020` (approved), `page=N` | HTML scrape, list pages nightly, detail pages for new postings only | nightly |
| ESDC positive list, CKAN dataset `90fed587-1364-4f33-a9ee-208181dc0b97` | `package_show`, English resources, XLSX (2020 Q4 on) and CSV (earlier) | quarterly, 3 to 4 months lag |
| ESDC negative list, CKAN dataset `f82f66f2-a22b-4511-bccf-e1d74db39ae5` | same | same |
| IRCC non-compliant employers | the page's table loads `/content/dam/ircc/documents/json/non_compliant.json`; legend text from the page | as published |
| BC Registry via OrgBook `orgbook.gov.bc.ca/api/v4/search/topic` | name search, graded match, BC employers only | nightly for new BC employers |
| Corporations Canada, Federal Corporations open data (CBCA active and inactive CSVs) | bulk extract loaded locally, matched on normalized name | weekly download |
| GeoNames postal codes (CC BY 4.0) | forward sortation area centroids in `pipeline/lmia_pipeline/data/fsa_centroids.csv` | once |

Licences: ESDC lists and the federal corporations extract are Open Government
Licence, Canada. Job Bank is Government of Canada content reproduced with
attribution. GeoNames is CC BY 4.0. Derived files ship under OGL Canada.

## Run and test
- Pipeline: `cd pipeline && pip install -e .[dev] && pytest`. Dev run:
  `python -m lmia_pipeline run --limit 1 --detail-budget 2 --db ../data/lmia.sqlite`.
  The export stage writes `data/out/{csv,mirror,static}`.
- Site: `cd site && npm install && npm run db:local && npm run data:local && npm run dev`.
  `npm run data:local` copies the pipeline's static export into `site/public/data`
  (git-ignored). Tests: `npm test` (fixtures under `site/test/fixtures` stand in
  for the export; a fake assets binding serves them).
- Deploy is manual at setup time only (`wrangler login` on the project account,
  create the D1 database and the R2 bucket, apply the schema, `npm run deploy`);
  after that the nightly workflow owns both data and deploys.

## Style
- Site style is plain and corporate (direction "Government Register", chosen
  2026-10-17): white ground, a white brand row over a full-width navy (#1c3d6a)
  nav bar, grey rules, tables with no outer border, square corners, no gradients,
  shadows or decoration. Type is Public Sans, self-hosted as one variable woff2
  (latin subset, `site/public/fonts/`, SIL OFL) with the system stack as
  fallback; identifiers (employer ID, registry number) use the system monospace
  via `.id`. Status tags are solid rectangles: pending amber, approved blue,
  refused grey, finding red. Colours differ in lightness, never hue alone, and
  amber means Pending only (a triggered indicator is a neutral outline). Below
  700 px, tables with class `restack` show each row as a labelled block from the
  cells' `data-label` attributes. Bump the `?v=` on the stylesheet link in
  `layout.tsx` after changing `styles.css`. Colours are tokens on `:root`; the
  dark scheme redefines them under `:root[data-theme="dark"]` and, for the
  system setting, `@media (prefers-color-scheme: dark)` guarded by
  `:root:not([data-theme="light"])`. Foreground navy is `--accent` (lightens in
  the dark scheme); `--navy` stays for the nav bar and the primary button. The
  toggle beside FR (`public/theme.js`, loaded in the head so a saved choice
  never flashes) stores the choice in localStorage only. `scrollbar-gutter:
  stable` on `html` keeps short and long pages centred at the same place.
- Site mark (chosen 2026-10-17): the "register grid", a two-column table with one
  filled cell, drawn on a 16 px grid inside a 32-unit box. One path, defined once as
  `MARK_PATH` in `site/src/layout.tsx` (inline in the header, navy via
  `currentColor`) and again in `site/public/favicon.svg`. The raster fallbacks
  `favicon.ico` (16/32/48) and `apple-touch-icon.png` are generated, not drawn:
  `python site/scripts/make-icons.py` after any change to the mark.
- Type hints `X | None`, `list[...]`. Comments explain why, not what.
- Git: single `main`. Commit subjects start with the half they touch: `pipeline:`,
  `site:`, `schema:`, `ci:`.

## Status of the framework (2026-10-13)
Verified locally:
- Pipeline tests green. The full ESDC history loaded from CKAN (39 quarterly files
  per list, 2014 to 2026 Q1: 433,083 positive rows, 41,319 negative rows, 166,497
  merged employers, no parse failures). IRCC list parsed (1,423 findings). A
  dev-sized Job Bank pass stored 45 postings and dropped 5 private-household
  postings. OrgBook matched 5 of 5 BC employers tried. Indicators and status
  computed for every employer. The static export (5,500 files) built in under a
  minute; the federal corporations matcher is tested on fixtures and runs for real
  on the first nightly run.
- Site: typecheck and tests green against fixture JSON and the local D1 emulator.
  Vitest uses the `cloudflareTest` plugin from the pool package (this version has
  no `/config` subpath); wrangler is pinned to the version the pool bundles.

Known gaps, in the order they matter:
1. Wage and unemployment tables for the two placeholder indicators (Job Bank
   prevailing wages by economic region; Labour Force Survey by census area).
2. Turnstile on the two forms (needs the
   account). The Data page no longer carries placeholders.
3. Account setup on the project's own Cloudflare and GitHub accounts (see
   `site/README.md`), then one manual run of the nightly workflow.
4. The long search scope loads several megabytes per province in the browser; a
   compact columnar encoding would halve that if it proves slow on phones.
