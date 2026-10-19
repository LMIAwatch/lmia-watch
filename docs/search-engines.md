# Search engines and traffic counts

Three things tell the operator how people find and use the site, and none of
them adds a cookie or a script to the pages:

1. Google Search Console and Bing Webmaster Tools: which searches show the
   site, how often people click, and which pages the engines have indexed.
   Each needs one DNS record to prove the domain is ours.
2. Cloudflare's Crawler Hints, which tells the engines that take IndexNow
   (Bing and others, not Google) when pages change.
3. The Worker's own counts in Workers Analytics Engine (`site/src/views.ts`):
   one data point per response, holding the route template, the page
   language, the country code Cloudflare's edge attaches, the referring
   site's host name and the status code. No IP address, user agent, cookie,
   full referrer or raw path is written. The Data page says so in both
   languages.

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

Search Console keeps 16 months of search data, so its history covers what
the Analytics Engine counts (three months) cannot.

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

## 5. Crawler Hints (IndexNow)

1. The zone, Caching, Configuration, Crawler Hints: On.
2. Cloudflare then tells the search engines that take IndexNow when content
   it serves changes, so they recrawl sooner. Google does not take IndexNow
   and is unaffected. It costs nothing.

The site's pages change every night, so the hints mostly help new employer
profiles reach Bing quickly.

## 6. Reading the counts

### What one data point holds

| Column | Holds | Example |
|---|---|---|
| `index1` | the route template (the sampling key) | `/employers/:id` |
| `blob1` | the route template | `/employers/:id` |
| `blob2` | the kind: `page`, `api`, `download`, `form`, `hook`, `file` or `other` | `page` |
| `blob3` | the page language | `fr` |
| `blob4` | the country code from Cloudflare's edge, empty when absent (`T1` is Tor) | `CA` |
| `blob5` | the referring site's host name, empty when none | `news.google.com` |
| `blob6` | the request method | `GET` |
| `double1` | the status code | `200` |

A path that matches no route is stored as `other`, never as written, since a
mistyped or pasted address could hold anything. Downloads keep their file
name (the list is fixed). Static files under `/data/` and `/fonts/` never
reach the Worker and are not counted, and neither is a request the
per-address limits answer with 429. The dataset is `lmia_watch_views`.

Limits: 100,000 data points a day on the Workers Free plan, the same as the
Worker's request allowance, so one point per response cannot exceed it;
10,000 read queries a day; data kept for three months.

### The dashboard

Workers & Pages, `lmia-watch`, Metrics shows requests, errors and CPU time
for the Worker with no setup. The per-route, per-language and per-referrer
counts are only in Analytics Engine, read through the SQL API below.

### A read-only token

The workflow's `CLOUDFLARE_API_TOKEN` cannot read analytics and should not
be given that permission. Make a second token for reading only:

1. Cloudflare dashboard, My Profile, API Tokens, Create Token, Custom token.
2. Name `analytics read`. Permissions: Account, Account Analytics, Read.
   Account resources: the project account only. No zone permissions.
3. Keep it in the project account's own password manager, not in the
   repository and not as a repository secret.

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

Server errors, last 7 days (should be empty):

```
SELECT blob1 AS route, double1 AS status, SUM(_sample_interval) AS n
FROM lmia_watch_views
WHERE double1 >= 500 AND timestamp > NOW() - INTERVAL '7' DAY
GROUP BY route, status ORDER BY n DESC
```

The answer is JSON (`data` holds the rows). Add `FORMAT TabSeparated` at the
end of a query for plain text.

### Keeping more than three months

Analytics Engine drops data points after three months. Two ways to keep a
longer history without a monthly manual export, neither built yet:

- A nightly workflow step that queries the previous day's totals through
  the SQL API and saves them to R2 as one small CSV per day. It needs a token
  with Account Analytics Read in the repository secrets.
- The newer Analytics SQL binding, which lets the Worker's daily check run
  the same query with no token at all. It needs Wrangler 4.145 or later; the
  site pins 4.105 for its test pool.

## Sources (read 2026-10-18)

- Analytics Engine binding, SQL API and the Account Analytics Read
  permission: `developers.cloudflare.com/analytics/analytics-engine/get-started/`
- Limits (20 blobs, one index of 96 bytes, 250 points per invocation, three
  months' retention): `developers.cloudflare.com/analytics/analytics-engine/limits/`
- Free plan allowance (100,000 points written and 10,000 queries a day):
  `developers.cloudflare.com/analytics/analytics-engine/pricing/`
