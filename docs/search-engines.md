# Search engines and traffic counts

Three things tell the operator how people find and use the site, and none of
them adds a cookie or a script to the pages:

1. Google Search Console and Bing Webmaster Tools: which searches show the
   site, how often people click, and which pages the engines have indexed.
   Each needs one DNS record to prove the domain is ours.
2. IndexNow, which tells the engines that take it (Bing and others, not
   Google) which pages changed. The nightly run submits them itself after
   each deploy (section 5); Cloudflare's Crawler Hints can stay on beside it.
3. The Worker's own counts in Workers Analytics Engine (`site/src/views.ts`):
   one data point per response, holding the route template, the page
   language, the country code Cloudflare's edge attaches, the referring
   site's host name and the status code, plus, for an Atom feed, the file
   and the subscriber count a feed reader states. No IP address, user agent,
   cookie, full referrer or raw path is written. The Data page says so in
   both languages. The nightly run keeps a daily roll-up in R2 (section 6).

Before any of that, two fixes in the zone, both missing on 2026-10-18: plain
HTTP is served without a redirect, and `www.lmiawatch.ca` serves a full copy
of the site instead of redirecting to `lmiawatch.ca`. Search engines treat
the copies as duplicates, and the canonical tags (which always name
`https://lmiawatch.ca`) only partly make up for it.

Everything below is done in the Cloudflare dashboard, signed in as the
project's Cloudflare account, or in accounts made for the project. The
workflow's API token cannot edit DNS or zone settings, by design, so none of
this can be scripted from the repository.

## 1. Always Use HTTPS

1. Cloudflare dashboard, the `lmiawatch.ca` zone, SSL/TLS, Edge
   Certificates.
2. Turn on Always Use HTTPS. Every `http://` request now gets a 301 to the
   same `https://` address at the edge, before the Worker runs, so the
   redirect costs no Worker request.
3. Leave HSTS off for now. Once the redirect has run for a few weeks without
   trouble, HSTS can be turned on from the same page; it is hard to undo,
   because browsers remember it for its full max-age.

Check: `curl -sI http://lmiawatch.ca/` from a terminal answers `301` with
`Location: https://lmiawatch.ca/`.

## 2. Redirect www to the apex

`www.lmiawatch.ca` is a Worker custom domain (`site/wrangler.jsonc`), so it
has a DNS record and a certificate. Keep both, and send its traffic to the
apex with a redirect rule, which runs at the edge before the Worker.

1. The `lmiawatch.ca` zone, Rules, Overview, Create rule, Redirect Rule. The
   template "Redirect from WWW to root" fills in most of it.
2. Rule name: `www to apex`.
3. When incoming requests match: custom filter expression, field Hostname,
   operator equals, value `www.lmiawatch.ca`.
4. Then: URL redirect, type Dynamic, expression
   `concat("https://lmiawatch.ca", http.request.uri.path)`, status code 301,
   Preserve query string on.
5. Deploy. The Free plan allows ten redirect rules; this uses one.

Check: `curl -sI "https://www.lmiawatch.ca/search?lang=fr"` answers `301`
with `Location: https://lmiawatch.ca/search?lang=fr`.

## 3. Google Search Console

Google needs a Google account. Make one for the project, in the project's
browser profile, never signed in alongside a personal Google account. At the
sign-up page choose "Use your existing email" and give the project's
plus-alias address, so no Gmail mailbox is created. Google may ask for a
phone number. The account name can be `LMIA Watch`; it is not shown on the
site or in search results.

1. Open `search.google.com/search-console`, Add property, choose Domain (not
   URL prefix), enter `lmiawatch.ca`. A domain property covers `http`,
   `https` and `www` at once.
2. Google shows a TXT record that starts `google-site-verification=`. Copy
   the whole value.
3. If Google offers to configure the record for you through Cloudflare,
   decline: that sign-in would grant Google access to the Cloudflare
   account. Add it by hand instead.
4. Cloudflare dashboard, the zone, DNS, Records, Add record: type TXT, name
   `@`, content the copied value, TTL Auto. Save.
5. Back in Search Console, Verify. DNS changes on Cloudflare usually show
   within minutes; if the check fails, wait an hour and try again.
6. Leave the TXT record in place for good. Removing it unverifies the
   property.
7. Sitemaps, in the left menu: enter `sitemap.xml` and Submit. The file is
   the index of the per-part sitemaps the nightly run writes;
   `robots.txt` names it too.

Search Console keeps 16 months of search data. The Worker's own counts last
three months in Analytics Engine and are kept after that by the nightly
roll-up (section 6).

## 4. Bing Webmaster Tools

Bing's index also serves DuckDuckGo, Ecosia and Yahoo.

1. Open `bing.com/webmasters` and sign in with the project's Google account
   from step 3 (Bing accepts Google, Microsoft and Facebook sign-ins), so no
   further account is needed.
2. Once the Google property is verified, choose Import from Google Search
   Console. Bing reads the verified property and its sitemap and needs no
   DNS record of its own. This is the quickest path.
3. Without the import: Add a site, `https://lmiawatch.ca/`, and choose the
   DNS method. Bing shows a CNAME record (a name made of letters and digits,
   pointing to `verify.bing.com`). Add it in the Cloudflare zone with proxy
   status DNS only (the grey cloud): a proxied record answers with
   Cloudflare's addresses and the check fails. Verify, then leave the record
   in place.
4. Sitemaps: Submit sitemap, `https://lmiawatch.ca/sitemap.xml`.

## 5. IndexNow

Bing reads the sitemap, but with about 160,000 employer pages its crawl takes
weeks to come back to a page that changed. IndexNow lets the site name the
changed pages itself, and Bing and the other engines that share the protocol
take that as a cue to crawl them. Google does not take IndexNow and is
unaffected.

### What the nightly run sends

After a deploy that worked and that the smoke test did not find broken, the
workflow step "Tell IndexNow which pages changed" runs

```
python -m lmia_pipeline.nightly indexnow --db data/lmia.sqlite --since <run start> \
  --site-url https://lmiawatch.ca
```

(`pipeline/lmia_pipeline/indexnow.py`). It selects:

- the home, search, trends, occupations, places, releases and program pages,
  which follow the nightly data;
- every employer page whose row changed during the run. `--since` is the
  time in `data/out/run_started.txt`, written as the pipeline step starts.
  The status stage rewrites `employers.updated_at` only when something in an
  employer's summary changed, and a new employer row carries the time it was
  first written.

At most 20,000 URLs a night, the most recently changed first. A night with
more (a new ESDC quarter changes tens of thousands of profiles) leaves the
rest to the sitemap, which lists every profile with its `lastmod`. The list
goes to the shared endpoint, which passes it to every participating engine,
in batches of at most 10,000 URLs:

```
POST https://api.indexnow.org/indexnow
Content-Type: application/json; charset=utf-8
User-Agent: LMIAWatch/<version> (+https://lmiawatch.ca; https://lmiawatch.ca/corrections)

{"host": "lmiawatch.ca", "key": "<key>", "keyLocation": "https://lmiawatch.ca/<key>.txt",
 "urlList": ["https://lmiawatch.ca/", "https://lmiawatch.ca/search", ...]}
```

The step's log gives the counts. On the runner the list sent is in
`data/out/indexnow/urls.txt`, and `--dry-run` writes that list without
sending anything.

### The key

The key is the 32-character text in `INDEXNOW_KEY`
(`pipeline/lmia_pipeline/indexnow.py`). The site serves it at
`https://lmiawatch.ca/<key>.txt` from `site/public/<key>.txt`, a file whose
entire content is the key, with no newline. An engine fetches that file to
check that a submission comes from the site. The key is public by design, so
there is no secret to set, and a pipeline test fails when the code and the
file disagree.

To change the key: 32 new lowercase hex characters, the file renamed and its
content replaced, and `INDEXNOW_KEY` changed, all in one commit. The new key
is in use from the next nightly run, whose deploy publishes the new file.

### Outcomes

The outcome goes to the run status as `indexnow` and to `LAST_RUN.md` as
"IndexNow: <outcome>".

| Outcome | Meaning |
|---|---|
| `submitted <n> URLs` | every batch answered 200 (submitted) or 202 (received, the key check still pending) |
| `rejected (400)`, `rejected (403)`, `rejected (422)` | 400: the request was malformed. 403: the key is not valid (the key file was not found, or it does not hold the key). 422: a URL is not on the host, or the key does not match. Nothing more is sent that night, and the step exits 1 so it shows red |
| `rate limited` | 429, too many requests. Nothing more is sent that night |
| `failed` | no answer, or a 500 to 599, on the first try and on the retry 10 seconds later; or the step could not run (no start time, no database) |
| `off` | the repository variable `INDEXNOW_ENABLED` is `false` |
| `not run` | the step did not run: the deploy failed or the smoke test found it broken |

Only a rejection is an item needing attention ("IndexNow: rejected; check
the key file"). A rate limit or a failure clears by itself, and the pages
stay in the sitemap meanwhile. No outcome stops the run. Pages a night did
not get through are not queued for the next; the sitemap carries them.

### When it reads rejected

The engines could not match the request with the key file, so the key file
is the first thing to check:

1. Open `https://lmiawatch.ca/<key>.txt`, with the key from `INDEXNOW_KEY`.
   It must answer 200 with the key as its entire content.
2. A 404: the file is missing from `site/public` or the last deploy did not
   carry it. Check that it is committed and that the deploy step succeeded.
3. A 403 or a challenge page: a rule in the zone refuses the request. The
   file must be open to crawlers like any page.
4. Another text: the file and `INDEXNOW_KEY` disagree. The pipeline test
   catches this before a push; fix whichever one changed.
5. A 422 with a good key file: the URLs name a host other than the one
   serving the file, usually the repository variable `SITE_URL` (the step
   falls back to `https://lmiawatch.ca` only when the variable is empty).

The next nightly run submits again once the cause is fixed.

### Turning it off

GitHub, the repository, Settings, Secrets and variables, Actions, Variables:
set `INDEXNOW_ENABLED` to `false`. Any other value, or no variable, leaves it
on. While it is off the step writes `off` and sends nothing.

### Cloudflare's Crawler Hints (optional)

1. The zone, Caching, Configuration, Crawler Hints: On.
2. Cloudflare then sends IndexNow notices of its own when content it serves
   changes, handling its side of the protocol itself. It costs nothing.

The operator can leave it on beside the nightly submission; neither depends
on the other.

## 6. Reading the counts

### What one data point holds

| Column | Holds | Example |
|---|---|---|
| `index1` | the route template (the sampling key) | `/employers/:id` |
| `blob1` | the route template | `/employers/:id` |
| `blob2` | the kind: `page`, `api`, `download`, `form`, `feed`, `hook`, `file` or `other` | `page` |
| `blob3` | the page language | `fr` |
| `blob4` | the country code from Cloudflare's edge, empty when absent (`T1` is Tor) | `CA` |
| `blob5` | the referring site's host name, empty when none | `news.google.com` |
| `blob6` | the request method | `GET` |
| `blob7` | feeds only: the feed file, empty when no file was served | `feeds/canada/pending.xml` |
| `double1` | the status code | `200` |
| `double2` | feeds only: the subscriber count the feed reader stated, 0 when none | `12` |

A path that matches no route is stored as `other`, never as written, since a
mistyped or pasted address could hold anything. Downloads keep their file
name (the list is fixed). The dataset is `lmia_watch_views`.

The Atom feeds are the one static file counted. `site/wrangler.jsonc` runs
the Worker first for `/data/feeds/*` (`run_worker_first`), and the Worker
serves the file from the assets binding with the same headers, a five-minute
cache and the reader's conditional request passed on (a reader that has the
file gets a 304). Every feed poll is one point under the template
`/data/feeds/:file` with kind `feed`. Readers that poll for many people say
how many in their user agent, for example
`Feedly/1.0 (+https://feedly.com/poller.html; 12 subscribers; like FeedFetcher-Google)`
or `inoreader.com; 9 subscribers`. The Worker keeps only that number, in
`double2`; the user agent itself is never written. The file name goes in
`blob7` only when the file was served (200 or 304), so a typed path that
found nothing is never stored. Other static files under `/data/` and
`/fonts/` never reach the Worker and are not counted, and neither is a request
the per-address limits answer with 429. Feed polls have their own cap in the
Worker (`FEED_LIMIT`, 600 a minute per address, `site/src/limits.ts`), so a
feed service polling many feeds from one address is not refused.

Limits: data points written match the Worker's requests; 10,000 read queries
a day; data kept for three months.

### The token

The workflow's `CLOUDFLARE_API_TOKEN` cannot read analytics and is not given
that permission. The nightly roll-up reads with a second token that can do
nothing else:

1. Cloudflare dashboard, signed in as the project account: My Profile, API
   Tokens, Create Token, Custom token.
2. Name `analytics read`. Permissions: Account, Account Analytics, Read.
   Account resources: the project account only. No zone permissions, no
   other account permissions. No IP filtering (the GitHub runners' addresses
   change).
3. GitHub, the repository, Settings, Secrets and variables, Actions, New
   repository secret: name `CLOUDFLARE_ANALYTICS_TOKEN`, the token as the
   value.

Until the secret exists, the step logs "no analytics token; nothing rolled
up" and the run status reads `views_rollup: no token`. The first night with
the secret rolls up every day Analytics Engine still holds.

### What the nightly run keeps in R2

The workflow step "Roll up the audience counts" runs
`python -m lmia_pipeline rollup-views` (`pipeline/lmia_pipeline/views_rollup.py`).
It asks the SQL API for every finished UTC day after the newest one in the
summary (normally only yesterday; on the first night, the last 90 days), so
a night that fails is caught up by the next. A day with no data points at all
is not written and is asked again the next night. Files in the
`lmia-watch-data` bucket:

| Key | What it is |
|---|---|
| `views/YYYY-MM-DD.csv` | one file per day, written once and replaced only if that day is rolled up again |
| `views/summary.csv` | one row per day, every day kept so far |

The summary is downloaded, extended and uploaded again each night. A download
that fails for any reason other than "does not exist" stops the step, and a
summary that cannot be read (empty, an unknown column, a row without a date)
fails the roll-up, so a shorter file never replaces it. It can always be
rebuilt from the day files.

A day file, header
`date,section,route,kind,lang,country,referrer,status,feed,responses,subscribers`,
has four kinds of row, named by `section`:

| `section` | Columns filled | Meaning |
|---|---|---|
| `total` | `responses` | every response the Worker counted that day |
| `kind` | `kind`, `responses` | the day's responses of one kind |
| `count` | `route` to `status`, `responses` | responses for one combination of route template, kind, language, country, referring host and status |
| `feed` | `feed`, `responses`, `subscribers` | one feed file: the day's polls, and the largest subscriber count any reader stated (0 when none did); `feed` is empty for polls of a feed path with no file |

`status` is the HTTP status code; `country` and `referrer` are empty when the
request carried none. Counts come from `SUM(_sample_interval)`, so they are
exact while Analytics Engine does not sample and estimates when it does.

The summary, header
`date,responses,pages,api,downloads,forms,feeds,other,feed_subscribers,bluesky_followers,top_routes`:

| Column | Meaning |
|---|---|
| `date` | the UTC day |
| `responses` | every response counted |
| `pages`, `api`, `downloads`, `forms`, `feeds` | responses of kind `page`, `api`, `download`, `form`, `feed` |
| `other` | everything else: the payment hook, `robots.txt`, the sitemaps, the feed index, paths that match no route |
| `feed_subscribers` | the sum over feed files of each file's largest stated subscriber count; a person who follows two feeds counts twice, and a feed read through two services counts only the larger figure |
| `bluesky_followers` | the Bluesky account's follower count when the roll-up ran, on the row for the day before; empty for days caught up later and when the profile could not be read |
| `top_routes` | the five route templates with the most responses below status 400, as `route count` pairs separated by semicolons |

Nothing in either file identifies a visitor: the query can read only what
the Worker writes, and the roll-up blanks any value that does not have the
shape the Worker writes before it is stored.

Bluesky's follower count comes from its public profile endpoint
(`public.api.bsky.app`, `app.bsky.actor.getProfile`), which needs no token;
the handle is the `BSKY_HANDLE` secret, or the site's domain when that is not
set. X is left out: under its pay-per-use API, reading the account's profile
costs credits.

Outcomes in the run status, as `views_rollup`: `rolled up`, `no data` (no
day had a data point), `no token`, or `failed` (the SQL API failed, the
summary could not be downloaded or read, or an upload failed). Only `failed`
is an attention item. The step never stops the run.

To read the files: Cloudflare dashboard, R2, `lmia-watch-data`, folder
`views`, or from `site/` on the project account's machine,
`npx wrangler r2 object get --remote lmia-watch-data/views/summary.csv --file summary.csv`
(without `--remote`, Wrangler reads a local simulated bucket).

Nothing needs doing by hand. To look at one day from a machine anyway (within
the 90 days, with `CLOUDFLARE_ANALYTICS_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`
set in the shell), `python -m lmia_pipeline rollup-views --day YYYY-MM-DD`
writes its file to `data/out/views/`.

### The dashboard

Workers & Pages, `lmia-watch`, Metrics shows requests, errors and CPU time
for the Worker with no setup. The per-route, per-language and per-referrer
counts are only in Analytics Engine, read through the SQL API below or from
the files above.

### The SQL API

Every query goes to one address, with the account id (Workers & Pages,
right-hand column) and the token from above:

```
curl "https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/analytics_engine/sql" \
  --header "Authorization: Bearer <ANALYTICS_TOKEN>" \
  --data "<SQL>"
```

Analytics Engine samples at high volume, so count with
`SUM(_sample_interval)`, never `COUNT()`.

Page views a day, last 30 days:

```
SELECT toStartOfInterval(timestamp, INTERVAL '1' DAY) AS day, SUM(_sample_interval) AS views
FROM lmia_watch_views
WHERE blob2 = 'page' AND double1 < 400 AND timestamp > NOW() - INTERVAL '30' DAY
GROUP BY day ORDER BY day
```

Most viewed routes and the language split, last 7 days:

```
SELECT blob1 AS route, blob3 AS lang, SUM(_sample_interval) AS views
FROM lmia_watch_views
WHERE (blob2 = 'page' OR blob2 = 'download') AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY route, lang ORDER BY views DESC LIMIT 30
```

Other sites that send visitors, last 30 days:

```
SELECT blob5 AS referrer, SUM(_sample_interval) AS views
FROM lmia_watch_views
WHERE blob5 != '' AND blob5 != 'lmiawatch.ca' AND timestamp > NOW() - INTERVAL '30' DAY
GROUP BY referrer ORDER BY views DESC LIMIT 25
```

Countries, last 30 days:

```
SELECT blob4 AS country, SUM(_sample_interval) AS views
FROM lmia_watch_views
WHERE blob2 = 'page' AND timestamp > NOW() - INTERVAL '30' DAY
GROUP BY country ORDER BY views DESC LIMIT 25
```

Feed polls and the largest stated subscriber count per feed, last 7 days:

```
SELECT blob7 AS feed, SUM(_sample_interval) AS polls, MAX(double2) AS subscribers
FROM lmia_watch_views
WHERE blob2 = 'feed' AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY feed ORDER BY polls DESC
```

Server errors, last 7 days (should be empty):

```
SELECT blob1 AS route, double1 AS status, SUM(_sample_interval) AS n
FROM lmia_watch_views
WHERE double1 >= 500 AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY route, status ORDER BY n DESC
```

The answer is JSON (`data` holds the rows). Add `FORMAT TabSeparated` at the
end of a query for plain text.

A later option: the newer Analytics SQL binding would let the Worker run the
same queries with no token at all. It needs Wrangler 4.145 or later; the site
pins 4.105 for its test pool.

## Sources (read 2026-10-18)

- IndexNow protocol (the endpoint, the request body, 10,000 URLs a request,
  the key file at the root, the answers 200, 202, 400, 403, 422 and 429),
  read 2026-10-24: `indexnow.org/documentation`; no published daily limit,
  and only changed URLs to be sent: `indexnow.org/faq`

- Analytics Engine binding, SQL API and the Account Analytics Read
  permission: `developers.cloudflare.com/analytics/analytics-engine/get-started/`
- Limits (20 blobs, one index of 96 bytes, 250 points per invocation, three
  months' retention): `developers.cloudflare.com/analytics/analytics-engine/limits/`
- Free plan allowance (100,000 points written and 10,000 queries a day):
  `developers.cloudflare.com/analytics/analytics-engine/pricing/`
- SQL functions used by the roll-up (`toDateTime` with a unix timestamp,
  `max`, `sum`, `FORMAT JSON`), read 2026-10-22:
  `developers.cloudflare.com/analytics/analytics-engine/sql-reference/`
- `run_worker_first` with a list of patterns (`*` matches deeply, `!`
  excludes), read 2026-10-22:
  `developers.cloudflare.com/workers/static-assets/binding/`
