# Site

Cloudflare Worker (TypeScript, Hono) that renders the pages and the JSON API
from the static JSON the pipeline exports. The data ships with the Worker as
static assets, so page views cost nothing per row and the site fits the free
plan. D1 holds only what visitors submit (responses and corrections); R2 holds
the downloads.

## Local development
```
npm install
npm run db:local      # schema + sample form rows into the local D1 emulator
npm run data:local    # copy ../data/out/static into public/data (run the pipeline's export first)
npm run dev           # http://localhost:8787
npm run typecheck
npm test              # vitest: fixture JSON through a fake assets binding, local D1 for the forms
```
Without `npm run data:local` every page answers "Data not published yet" (503),
which is also what a fresh deployment shows before its first nightly run.

## How the search page stays quick
A plain visit is rendered on the server from the newest 500 records with
precomputed counts, so it shows rows with no JavaScript and no dataset
download. `search.js` then fetches the default scope once in the background
(about 0.6 MB compressed) and answers every filter, sort and page change from
memory; no filter change ever waits on the network. A deep link with filters
renders first from the smallest slice that answers it. The long scope (since
2023 Q4) loads only when asked, with a size notice and a CSV alternative above
2 MB, and is then answered from memory too.

## How data gets in
The pipeline writes `data/out/static/` (see the pipeline README for the file
layout). The scheduled workflow copies it to `site/public/data/` and runs
`wrangler deploy`; only files whose content changed are uploaded. That run is
the only deploy path: it fires once a day at midnight UTC, cannot be started by
hand or by a push, and nothing on the site can trigger it. Code merged to
`main` goes live with the next run.

The forms insert into `employer_responses` and `corrections` with
`published = 0`; nothing a visitor submits appears until the operator sets
`published = 1` (the profile page then shows it). Published rows are read with
`npx wrangler d1 execute lmia-watch --remote --command "SELECT ..."` and
published the same way; that is the only operator action the site has.

## One-time setup (about 30 minutes)
Accounts first. Both providers need a sign-in address, but neither address is
ever public and no new mailbox is required: a plus-alias of an existing
address (`name+lmia@domain`) is a distinct sign-in that lands in the existing
inbox. What the public sees is the GitHub username and the `workers.dev`
subdomain, so choose both as neutral words with no link to a person or company.
Reusing an existing GitHub account ties the repository and its workflow runs
to that account; reusing an existing Cloudflare account puts that account's
`workers.dev` subdomain in the site's public address. The site itself needs no email:
the user agent and the About page point at the corrections form.

1. **GitHub.** Create the account, then an empty public repository (public
   repositories get unlimited Actions minutes; the nightly run uses
   about 45 to 55, so it fits with room to spare, and nobody can see the
   account name. Push this repo to it with the new account's credential, never
   a personal one:
   `git remote add origin https://<username>@github.com/<username>/lmia-watch.git`
   then `git push -u origin main` (the username in the URL keeps the credential
   separate from any other GitHub login on the machine).
2. **Cloudflare.** From `site/`, with `CLOUDFLARE_API_TOKEN` in the
   environment: `npx wrangler d1 create lmia-watch` (paste the printed id into
   `wrangler.jsonc` as `database_id` and commit it),
   `npx wrangler r2 bucket create lmia-watch-data`,
   `npx wrangler d1 execute lmia-watch --remote --file=../pipeline/schema.sql`
   (run it again after any change to the site-owned tables; every statement
   is `IF NOT EXISTS`),
   `npm run deploy`. `wrangler.jsonc` sets `workers_dev: false`, so the Worker
   has no address until a domain is attached; it is never published under the
   account's `workers.dev` subdomain.
   **Domain.** Register one (a neutral name) and bring it into the same
   Cloudflare account as a zone: through Cloudflare Registrar the zone appears
   automatically, with WHOIS redacted; through another registrar, add the site
   in the dashboard on the free plan and point the registrar's nameservers at
   the two Cloudflare gives. Then add to `wrangler.jsonc`
   `"routes": [{ "pattern": "<domain>", "custom_domain": true },
   { "pattern": "www.<domain>", "custom_domain": true }]` and run
   `npm run deploy` again; wrangler creates the DNS records and the certificate.
   The site answers at `https://<domain>` with "Data not published yet". The
   API token needs Zone / DNS / Edit and Zone / Workers Routes / Edit on that
   zone for this step.
3. **API token.** In the Cloudflare dashboard create a token with Workers
   Scripts (edit), D1 (edit) and R2 (edit) on this account only, and note the
   account id from the Workers overview page.
4. **Repository settings.** Secrets: `CLOUDFLARE_API_TOKEN`,
   `CLOUDFLARE_ACCOUNT_ID`. Variables: `SITE_URL` (the address from step 2),
   `CONTACT` (`<SITE_URL>/corrections`). Under Actions, allow workflows to
   read and write repository contents (the run records its date in
   `LAST_RUN.md`, which keeps the schedule enabled).
5. **Wait for midnight UTC.** The first run builds everything from the sources
   (about two hours: the ESDC history, the federal corporations extract, one
   Job Bank pass, the export, the deploy). There is no way, and no need, to
   start it by hand. After that the site refreshes itself every night.

## Where things live
| Path | Holds |
|---|---|
| `src/index.tsx` | routes, security headers, language cookie, downloads, 404 and error pages |
| `src/data.ts` | the JSON file shapes and the loaders (assets binding) |
| `src/layout.tsx` | page shell, badges, formatting helpers, the "not published yet" page |
| `src/pages/*.tsx` | one file per page; their copy, Methodology and Data included, is keys into `src/i18n.ts` |
| `src/api.ts` | JSON endpoints, all views over the static files |
| `src/i18n.ts` | every UI string in English and French, the number, wage and quarter formats, and the French forms of the pipeline's indicator sentences; `test/i18n.test.ts` fails on a key with no French |
| `src/support.ts`, `src/pages/support.tsx` | Support page: every cost, tier and support figure in one file (support received is updated each quarter), then the page; `DONATE_URL` in `wrangler.jsonc` turns on the donate button |
| `public/styles.css`, `public/search.js`, `public/map.js` | the only stylesheet and the two client scripts; the scripts read their words from the page's `<script type="application/json" id="i18n">` block |
| `seed/dev_seed.sql` | sample form rows for local work and tests |
| `test/fixtures/` | sample JSON standing in for the pipeline's export |

## Copy rules
No em-dashes. Records are records, indicators are not findings, and the IRCC
list is shown separately from indicators.
