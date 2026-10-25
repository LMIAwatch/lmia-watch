# Traffic limits

Nothing a visitor does can produce a Cloudflare bill on the Free plan: Workers
stop at 100,000 requests a day, D1 stops at its daily caps, R2 reads are capped
by the Worker cap, and R2 charges nothing for egress. What a flood can do is
use up the day's Worker requests and take the pages down until midnight UTC.
Static files under `/data/` and `/fonts/` are served before the Worker runs,
so they neither count nor go down. The Atom feeds under `/data/feeds/` are
the exception: the Worker runs first for them so their polls are counted
(`docs/search-engines.md`, section 6), and they have a cap of their own
inside the Worker (below), wide enough for a feed service that polls many
feeds from one address.

Three layers keep abusive traffic off the Worker.

## 1. Edge rate-limiting rule (dashboard, once)

The Free plan includes one rate-limiting rule, enforced before the Worker
runs, so blocked requests cost nothing. The API token used by the project
cannot create it, so it is set in the dashboard:

1. Cloudflare dashboard, the lmiawatch.ca zone, Security, WAF, Rate limiting
   rules, Create rule.
2. Name: `Per-address cap on Worker paths`.
3. When incoming requests match, use the expression editor and paste:

   ```
   (http.host in {"lmiawatch.ca" "www.lmiawatch.ca"} and not starts_with(http.request.uri.path, "/data/") and not starts_with(http.request.uri.path, "/fonts/") and not cf.client.bot)
   ```

   `cf.client.bot` is true for a crawler Cloudflare has verified (Googlebot,
   Bingbot and the other search engines). Without that clause the cap counts
   them like anyone else, and a crawler rendering pages fetches the stylesheet
   and scripts with each page, so a burst from one of its addresses answers
   429 and the search engine slows its crawl (seen 2026-10-25 as Googlebot
   requests blocked at the edge).

4. Characteristics: IP (the Free plan adds the data centre itself).
5. Requests: 40 per 10 seconds. Action: Block. Duration: 10 seconds (the only
   choice on the Free plan).
6. Deploy.

A page view fetches about ten files, so a reader never reaches 40 Worker
requests in 10 seconds. A script fetching four pages a second is blocked;
a verified crawler is not.

## 2. Caps inside the Worker

`site/src/limits.ts`, keyed on the address Cloudflare saw, per minute:

| Bucket | Paths | Limit |
|---|---|---|
| Pages | everything else | 120 |
| Feeds | `/data/feeds/*` | 600 |
| API | `/api/*` | 60 |
| Downloads | `/downloads/*` | 10 |
| Forms | `POST /corrections`, `POST /employers/<id>/respond` | 5 |

Above the cap the site answers 429 with `Retry-After: 60`. These run inside
the Worker, so they count toward the daily total; their job is to protect the
database and the downloads from a single address, not to replace the edge
rule.

## 3. Emergency switch

Security, Settings, Under Attack Mode challenges every visitor at the edge
for the time it is on. Turn it on during a flood, off afterwards. Bot Fight
Mode is left off: it would also block legitimate scripted use of the API and
the downloads.
