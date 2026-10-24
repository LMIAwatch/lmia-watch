import type { Context } from "hono";
import { searchDataDate } from "../api";
import { INDICATORS, PAGE_SIZE as FIRST_PAGE_SIZE, PROVINCES, STREAMS } from "../constants";
import { loadFacets, loadFirst, loadSearchCounts, loadStats, type SearchRow } from "../data";
import type { AppEnv, Env } from "../env";
import {
  clientStrings, indicatorLabel, indicatorShortLabel, numberLocale, provinceName, streamLabel, t, tj, tn, type Key, type Lang,
} from "../i18n";
import { Badge, Chip, ClientData, Layout, fmtInt, fmtWage, noDataPage, page, periodLabel, slashBreaks } from "../layout";
import {
  PAGE_SIZE, STATUSES, YEAR_MIN, parseQuery, runSearch, type Facets, type SearchQuery, type SearchResult,
} from "../search_db";
import { pageSeo } from "../seo";
import { FeedLinks } from "./feeds";

// The first view is rendered here, so the page works without JavaScript and a
// shared URL shows the filters it names. With the search database it is the
// search itself (runSearch, the same query the API runs): rows, total, facet
// counts and a link to the next page. Without it (no binding, a failed query,
// or a table the sync has not filled) it is the page as it was before hosted
// search, the newest rows from search/first.json, with one sentence saying
// so. search.js then answers every change through /api/search.

// The fallback serves at most this many pages of search/first.json.
const SSR_PAGES = 20;

// Every string search.js draws, handed over in the page's JSON block.
export const SEARCH_CLIENT_KEYS: readonly Key[] = [
  "status.pending", "status.approved", "status.refused", "status.lapsed",
  "ind.newly_incorporated", "ind.repeat_applicant", "ind.wage_at_floor", "ind.low_wage_high_unemployment",
  "ind.high_volume", "ind.refused_then_reposted",
  "ind_short.newly_incorporated", "ind_short.wage_at_floor", "ind_short.low_wage_high_unemployment",
  "ind_short.refused_then_reposted",
  "col.status", "col.employer", "places.col_occupation", "col.location", "col.wage", "col.date", "col.positions",
  "col.indicators", "col.source",
  "common.na", "common.see_posting",
  "period.quarter", "period.range",
  "wage.range", "wage.single", "wage.unit.HOUR", "wage.unit.YEAR", "wage.unit.WEEK", "wage.unit.MONTH",
  "wage.unit.DAY", "wage.unit.BIWEEK", "wage.unit.WEEKLY", "wage.unit.BIWEEKLY", "wage.unit.SEMIMONTH",
  "search.records_one", "search.records_many", "search.records_capped", "search.total_capped", "search.note_all",
  "search.no_match", "search.showing", "search.page_of", "search.page",
  "search.source_jobbank", "search.source_positive", "search.source_negative", "search.source_jobbank_short",
  "search.source_esdc_short",
  "search.unavailable", "search.unavailable_kept",
];

export function searchClientData(lang: Lang) {
  return { lang, locale: numberLocale(lang), strings: clientStrings(lang, SEARCH_CLIENT_KEYS) };
}

export function sourceLabel(lang: Lang, r: Pick<SearchRow, "kind" | "ref" | "status" | "period">): string {
  if (r.kind === "posting") return t(lang, "search.source_jobbank", { ref: r.ref });
  return t(lang, r.status === "refused" ? "search.source_negative" : "search.source_positive", { period: r.period ?? "" });
}

// The location cell shows the city, province and postal code. A street, when
// the row has one, goes in the cell's title with the full address (the
// employer page shows it too).
export function placeLabel(r: Pick<SearchRow, "city" | "prov" | "postal">): string {
  return [r.city, r.prov].filter(Boolean).join(", ") + (r.postal ? ` ${r.postal}` : "");
}

export function addressLabel(r: Pick<SearchRow, "street" | "city" | "prov" | "postal">): string {
  return [r.street, r.city, r.prov].filter(Boolean).join(", ") + (r.postal ? ` ${r.postal}` : "");
}

// Each cell carries its column header as data-label, so on a phone the row
// restacks as a labelled block. search.js builds the same row with the same
// labels, short forms and titles; keep the two in step with the table
// header below.
export const SearchRowView = ({ r, lang }: { r: SearchRow; lang: Lang }) => (
  <tr>
    <td data-label={t(lang, "col.status")}>
      <Badge status={r.status} lang={lang} />
    </td>
    <td data-label={t(lang, "col.employer")}>
      <a href={`/employers/${r.employer_id}`}>{r.employer}</a>
    </td>
    <td data-label={t(lang, "places.col_occupation")}>
      {r.kind === "esdc" && r.noc ? `${r.noc} ` : ""}
      {slashBreaks(r.job ?? "")}
    </td>
    <td data-label={t(lang, "col.location")} title={r.street ? addressLabel(r) : undefined}>
      {placeLabel(r)}
    </td>
    <td data-label={t(lang, "col.wage")} class="mono">
      {r.kind === "posting" ? fmtWage(r.wage_min, r.wage_max, r.unit, lang) : t(lang, "common.na")}
    </td>
    <td data-label={t(lang, "col.date")} class={r.kind === "posting" ? "mono" : "mono period"}>
      {r.kind === "posting" ? r.date ?? "" : periodLabel(r.period ?? "", lang)}
    </td>
    <td data-label={t(lang, "col.positions")} class="mono">
      {r.positions === null ? t(lang, "common.see_posting") : fmtInt(r.positions, lang)}
    </td>
    <td data-label={t(lang, "col.indicators")}>
      {r.ind.length ? (
        <span class="chips">
          {r.ind.map((i) => {
            const short = indicatorShortLabel(lang, i);
            const full = indicatorLabel(lang, i);
            return <Chip title={short === full ? undefined : full}>{short}</Chip>;
          })}
        </span>
      ) : null}
    </td>
    <td data-label={t(lang, "col.source")}>
      <a href={r.source} class="mono" rel="nofollow noopener" title={sourceLabel(lang, r)}>
        {t(lang, r.kind === "posting" ? "search.source_jobbank_short" : "search.source_esdc_short")}
      </a>
    </td>
  </tr>
);

const DEFAULT_QUERY: SearchQuery = {
  q: "", status: [], province: [], stream: [], nocCode: null, nocText: "", wageMin: null, wageMax: null, yearFrom: null,
  yearTo: null, date: "any", indicator: null, sort: "newest", cursor: null,
};

// The URL's filters as the API reads them. A cursor this site did not issue
// (edited by hand, or cut short when the link was copied) gives the first
// page of the same filters rather than an error page.
export function readSearchUrl(url: URL, now: Date = new Date()): { query: SearchQuery; ignored: string[] } {
  const parsed = parseQuery(url, now);
  if (parsed.ok) return { query: parsed.query, ignored: parsed.ignored };
  const clean = new URL(url);
  clean.searchParams.delete("cursor");
  const again = parseQuery(clean, now);
  return again.ok ? { query: again.query, ignored: [...again.ignored, "cursor"] } : { query: DEFAULT_QUERY, ignored: ["cursor"] };
}

// The URL parameters of a query, in the order search.js writes them, so a
// link carries exactly the filters the page applied: a value the API dropped
// is not carried on.
export function searchParamsOf(q: SearchQuery, ignored: readonly string[] = []): URLSearchParams {
  const p = new URLSearchParams();
  if (q.q && !ignored.includes("q")) p.set("q", q.q);
  for (const s of q.status) p.append("status", s);
  for (const pr of q.province) p.append("province", pr);
  for (const s of q.stream) p.append("stream", s);
  const noc = q.nocCode ?? q.nocText;
  if (noc) p.set("noc", noc);
  if (q.wageMin !== null) p.set("wage_min", String(q.wageMin));
  if (q.wageMax !== null) p.set("wage_max", String(q.wageMax));
  if (q.date !== "any") p.set("date", q.date);
  if (q.yearFrom !== null) p.set("year_from", String(q.yearFrom));
  if (q.yearTo !== null) p.set("year_to", String(q.yearTo));
  if (q.indicator) p.set("indicator", q.indicator);
  if (q.sort !== "newest") p.set("sort", q.sort);
  return p;
}

function searchHref(base: URLSearchParams, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams(base);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const s = p.toString();
  return s ? `/search?${s}` : "/search";
}

// The search for the URL, or null when the page must fall back. A first page
// with no row is either a filter nothing matches or a table the sync has not
// filled yet (a new database, or a full reload under way); one row read
// tells them apart, and an empty table falls back like a missing one rather
// than answering "no records" to every visitor.
async function searchFirstView(env: Env, q: SearchQuery): Promise<SearchResult | null> {
  if (!env.SEARCH) return null;
  const counts = await loadSearchCounts(env);
  const result = await runSearch(env, q, searchDataDate(counts), counts);
  if (!result || q.cursor || result.rows.length) return result;
  try {
    return (await env.SEARCH.prepare("SELECT 1 AS one FROM search_rows LIMIT 1").first()) ? result : null;
  } catch {
    return null;
  }
}

// What the results column shows, from the database or from the fallback.
interface View {
  mode: "db" | "static";
  rows: SearchRow[] | null; // null: nothing to show on the server
  emptyText: string;
  count: string;
  note: string;
  facets: Facets | null;
  range: string;
  pageLabel: string;
  prev: string | null;
  next: string | null;
  // Pagination buttons the server cannot fill stay enabled for search.js.
  buttonsEnabled: boolean;
  unavailable: boolean;
  data: Record<string, string>;
}

export async function searchPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "nav.search");
  const { query, ignored } = readSearchUrl(new URL(c.req.url));
  const pageParam = Math.max(1, Math.min(10000, Number(c.req.query("page") ?? 1) || 1));
  const n = (v: number) => fmtInt(v, lang);
  const result = await searchFirstView(c.env, query);
  const cursorText = c.req.query("cursor") ?? "";
  // A page number beside a cursor counts the database's pages of 50, which
  // the fallback's pages of 25 do not match: it starts from its first page.
  const view = result
    ? databaseView(lang, query, ignored, result, pageParam, cursorText)
    : await fallbackView(c.env, lang, stats.esdc_latest_period, query, cursorText ? 1 : pageParam);

  const drop = new Set(ignored);
  const textValue = (name: string, v: string | number | null) => (drop.has(name) || v === null ? "" : String(v));
  // The year range offers every year from the first list to the data's year,
  // and never past the last year the API accepts (a damaged date cannot
  // make the list long).
  const asOf = typeof stats.data_as_of === "string" ? stats.data_as_of : "";
  const thisYear = new Date().getUTCFullYear();
  const dataYear = /^\d{4}/.test(asOf) ? Math.min(Number(asOf.slice(0, 4)), thisYear + 1) : thisYear;
  const lastYear = Math.max(dataYear, query.yearFrom ?? 0, query.yearTo ?? 0);
  const years: number[] = [];
  for (let y = lastYear; y >= YEAR_MIN; y--) years.push(y);

  // The filter groups the URL sets (not the text search or the sort, which
  // sit outside the fold), for the fold's line on a phone. A link that names
  // filters opens the fold, so the visitor sees what is applied.
  const activeFilters = [
    query.status.length > 0, query.province.length > 0, query.stream.length > 0, !!(query.nocCode ?? query.nocText),
    query.wageMin !== null || query.wageMax !== null, query.date !== "any", query.yearFrom !== null || query.yearTo !== null,
    !!query.indicator,
  ].filter(Boolean).length;

  const count = (kind: "status" | "prov", key: string) => (view.facets ? n(view.facets[kind][key] ?? 0) : "");
  // Each filter label holds its input, the label text in a .lbl box and, for
  // statuses and provinces, the count search.js keeps current, so the counts
  // line up in a column on the right.
  const check = (name: string, value: string, label: unknown, checked: boolean, countKey?: "status" | "prov") => (
    <label class="check">
      <input type="checkbox" name={name} value={value} checked={checked} />
      <span class="lbl">{label}</span>
      {countKey ? <span class="mono muted" data-count={`${name}:${value}`}> {count(countKey, value)}</span> : null}
    </label>
  );
  const yearSelect = (name: "year_from" | "year_to", picked: number | null) => (
    <select id={name} name={name}>
      <option value="">{t(lang, "search.year_any")}</option>
      {years.map((y) => (
        <option value={String(y)} selected={picked === y}>{y}</option>
      ))}
    </select>
  );

  const res = await page(
    c,
    <Layout lang={lang} title={t(lang, "nav.search")} dataAsOf={stats.data_as_of} active="/search" seo={pageSeo("search", lang)}
      head={<FeedLinks lang={lang} />}>
      <form action="/search" method="get" class="search-page" id="search-form">
        <div class="search-form top-gap">
          <label for="q" class="visually-hidden">{t(lang, "search.button")}</label>
          <input id="q" name="q" type="search" value={textValue("q", query.q)} placeholder={t(lang, "search.placeholder")} maxlength={100} />
          <button type="submit" class="btn btn-primary">{t(lang, "search.button")}</button>
        </div>
        <div class="search-layout">
          <aside class="filters" aria-label={t(lang, "search.filters")}>
            {/* A fold for phones in CSS alone (the page runs no inline script):
                the checkbox has no name, so it is never submitted and search.js
                never reads it. Wider screens hide both and show the rail. */}
            <input type="checkbox" id="filters-open" class="filters-toggle" checked={activeFilters > 0} />
            <label for="filters-open" class="filters-summary">
              {activeFilters
                ? tn(lang, "search.filters_active_one", "search.filters_active_many", activeFilters, { n: activeFilters })
                : t(lang, "search.filters")}
            </label>
            <div class="filters-body">
            <fieldset>
              <legend>{t(lang, "col.status")}</legend>
              {STATUSES.map((s) => check("status", s, <Badge status={s} lang={lang} />, query.status.includes(s), "status"))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.province")}</legend>
              {PROVINCES.map((pr) => check("province", pr, provinceName(lang, pr), query.province.includes(pr), "prov"))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.stream_legend")}</legend>
              <p class="muted small filter-hint">{t(lang, "search.stream_hint")}</p>
              {STREAMS.map((s) => check("stream", s, streamLabel(lang, s), query.stream.includes(s)))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.noc")}</legend>
              <label for="noc" class="visually-hidden">{t(lang, "search.noc_label")}</label>
              <input id="noc" name="noc" type="text" value={textValue("noc", query.nocCode ?? query.nocText)}
                placeholder={t(lang, "search.noc_placeholder")} maxlength={60} />
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.wage")}</legend>
              <div class="inline-fields">
                <label for="wage_min">{t(lang, "search.min")}</label>
                <input id="wage_min" name="wage_min" type="number" step="0.01" min="0" value={textValue("wage_min", query.wageMin)} />
                <label for="wage_max">{t(lang, "search.max")}</label>
                <input id="wage_max" name="wage_max" type="number" step="0.01" min="0" value={textValue("wage_max", query.wageMax)} />
              </div>
            </fieldset>
            <fieldset>
              <legend>{t(lang, "col.date")}</legend>
              {(
                [
                  ["any", t(lang, "search.date_any", { year: YEAR_MIN })],
                  ["7d", t(lang, "search.date_7d")],
                  ["last_quarter", t(lang, "search.date_last_quarter", { period: periodLabel(stats.esdc_latest_period, lang) })],
                ] as const
              ).map(([v, label]) => (
                <label class="check">
                  <input type="radio" name="date" value={v} checked={query.date === v} />
                  <span class="lbl">{label}</span>
                </label>
              ))}
              <p class="muted small filter-hint">{t(lang, "search.year_hint")}</p>
              <div class="inline-fields">
                <label for="year_from">{t(lang, "search.year_from")}</label>
                {yearSelect("year_from", query.yearFrom)}
                <label for="year_to">{t(lang, "search.year_to")}</label>
                {yearSelect("year_to", query.yearTo)}
              </div>
            </fieldset>
            <fieldset>
              <legend>{t(lang, "col.indicators")}</legend>
              <label class="check">
                <input type="radio" name="indicator" value="" checked={!query.indicator} />
                <span class="lbl">{t(lang, "search.any_state")}</span>
              </label>
              {INDICATORS.map((i) => (
                <label class="check">
                  <input type="radio" name="indicator" value={i} checked={query.indicator === i} />
                  <span class="lbl">{indicatorLabel(lang, i)}</span>
                </label>
              ))}
            </fieldset>
            <p class="filter-actions">
              <a href="/search" class="btn-link">{t(lang, "search.clear")}</a>
              <a href="#results" class="btn show-results">{t(lang, "search.show_results")}</a>
            </p>
            </div>
          </aside>

          <div class="results" id="results" {...view.data}>
            <div class="results-head">
              <p id="results-count">
                <strong>{view.count}</strong>{" "}
                <span class="muted" id="results-note">{view.note}</span>
              </p>
              <div class="results-tools">
                <span class="muted">{t(lang, "search.view")}</span>
                <span class="btn btn-active">{t(lang, "search.list")}</span>
                <a href="/map" class="btn">{t(lang, "nav.map")}</a>
                <label for="sort" class="muted">{t(lang, "search.sort")}</label>
                <select id="sort" name="sort">
                  <option value="newest" selected={query.sort === "newest"}>{t(lang, "search.sort_newest")}</option>
                  <option value="positions" selected={query.sort === "positions"}>{t(lang, "col.positions")}</option>
                  <option value="name" selected={query.sort === "name"}>{t(lang, "search.sort_name")}</option>
                </select>
              </div>
            </div>
            {view.unavailable ? <p class="panel bordered" id="search-unavailable" role="status">{t(lang, "search.unavailable")}</p> : null}
            <div class="table-wrap bordered">
              <table class="restack">
                <thead>
                  <tr>
                    <th>{t(lang, "col.status")}</th>
                    <th>{t(lang, "col.employer")}</th>
                    <th>{t(lang, "places.col_occupation")}</th>
                    <th>{t(lang, "col.location")}</th>
                    <th>{t(lang, "col.wage")}</th>
                    <th>{t(lang, "col.date")}</th>
                    <th>{t(lang, "col.positions")}</th>
                    <th>{t(lang, "col.indicators")}</th>
                    <th>{t(lang, "col.source")}</th>
                  </tr>
                </thead>
                <tbody id="results-body">
                  {view.rows ? (
                    view.rows.length ? view.rows.map((r) => <SearchRowView r={r} lang={lang} />) : (
                      <tr>
                        <td colspan={9} class="muted">{view.emptyText}</td>
                      </tr>
                    )
                  ) : (
                    <tr>
                      <td colspan={9} class="muted">
                        <noscript>
                          {tj(lang, "search.noscript", { downloads: <a href="/data#downloads">{t(lang, "common.downloads_link")}</a> })}
                        </noscript>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <nav aria-label={t(lang, "search.pagination")} class="pagination">
              <span class="muted" id="page-range">{view.range}</span>
              <span class="pages">
                {view.prev ? <a href={view.prev} class="btn" id="page-prev">{t(lang, "search.prev")}</a> : <button type="button" class="btn" id="page-prev" disabled={!view.buttonsEnabled}>{t(lang, "search.prev")}</button>}
                <span class="mono" id="page-label">{view.pageLabel}</span>
                {view.next ? <a href={view.next} class="btn" id="page-next">{t(lang, "search.next")}</a> : <button type="button" class="btn" id="page-next" disabled={!view.buttonsEnabled}>{t(lang, "search.next")}</button>}
              </span>
              <button type="button" class="btn-link" id="csv-download">{t(lang, "search.csv")}</button>
            </nav>
            <p class="muted small">
              {tj(lang, "search.footnote", {
                year: YEAR_MIN,
                downloads: <a href="/data#downloads">{t(lang, "common.downloads_link")}</a>,
              })}
            </p>
            <p class="small">
              {tj(lang, "places.browse", {
                occupations: <a href="/occupations">{t(lang, "places.browse_occupations")}</a>,
                places: <a href="/places">{t(lang, "places.browse_places")}</a>,
              })}
            </p>
          </div>
        </div>
      </form>
      <ClientData id="i18n" data={searchClientData(lang)} />
      <script src="/search.js"></script>
    </Layout>,
  );
  // The fallback is a passing state: a browser must not keep it for five
  // minutes once the database answers again, as it would a normal page.
  if (view.mode === "static") res.headers.set("Cache-Control", "no-store");
  return res;
}

// The search's own answer. A later page knows its number only from the URL
// (keyset pages carry no offset), so a cursor without one shows no range.
function databaseView(lang: Lang, q: SearchQuery, ignored: string[], result: SearchResult, pageParam: number, cursorText: string): View {
  const n = (v: number) => fmtInt(v, lang);
  const total = result.total;
  const shown = total === null ? "" : result.capped ? t(lang, "search.total_capped", { n: n(total) }) : n(total);
  const pageNo = q.cursor ? (pageParam >= 2 ? pageParam : null) : 1;
  const pages = total !== null && !result.capped ? Math.max(1, Math.ceil(total / PAGE_SIZE)) : null;
  const base = searchParamsOf(q, ignored);
  const from = pageNo ? (pageNo - 1) * PAGE_SIZE + 1 : 0;
  return {
    mode: "db",
    rows: result.rows,
    emptyText: t(lang, "search.no_match"),
    count: total === null ? ""
      : result.capped ? t(lang, "search.records_capped", { n: n(total) })
      : tn(lang, "search.records_one", "search.records_many", total, { n: shown }),
    note: t(lang, "search.note_all", { year: YEAR_MIN }),
    facets: result.facets ?? null,
    range: pageNo && total !== null && result.rows.length
      ? t(lang, "search.showing", { from: n(from), to: n(from + result.rows.length - 1), total: shown })
      : "",
    pageLabel: pageNo ? (pages ? t(lang, "search.page_of", { page: pageNo, pages }) : t(lang, "search.page", { page: pageNo })) : "",
    // Without a page number the way back is the browser's: only page 2
    // knows its previous page is the first.
    prev: pageNo === 2 ? searchHref(base) : null,
    next: result.next ? searchHref(base, pageNo ? { cursor: result.next, page: String(pageNo + 1) } : { cursor: result.next }) : null,
    buttonsEnabled: false,
    unavailable: false,
    data: {
      "data-mode": "db",
      "data-ssr": "1",
      "data-since": String(YEAR_MIN),
      "data-cursor": q.cursor ? cursorText : "",
      "data-next": result.next ?? "",
      "data-page": pageNo ? String(pageNo) : "",
      "data-total": total === null ? "" : String(total),
      "data-capped": result.capped ? "1" : "0",
    },
  };
}

// The page as it was before hosted search: the newest rows of
// search/first.json by page number, counted from search/facets.json, whatever
// the filters say (nothing on the server can filter without the database,
// and the sentence above the table says what is shown). Filter counts appear
// only for the unfiltered view, as before.
async function fallbackView(env: Env, lang: Lang, latestPeriod: string, q: SearchQuery, pageNo: number): Promise<View> {
  const n = (v: number) => fmtInt(v, lang);
  const facets = await loadFacets(env);
  let rows: SearchRow[] | null = null;
  let total = facets?.default.total ?? 0;
  if (pageNo <= SSR_PAGES) {
    const first = await loadFirst(env);
    if (first) {
      rows = first.slice((pageNo - 1) * FIRST_PAGE_SIZE, pageNo * FIRST_PAGE_SIZE);
      if (!facets) total = first.length;
    }
  }
  const pages = Math.max(1, Math.ceil(total / FIRST_PAGE_SIZE));
  const plain = !q.q && !q.nocCode && !q.nocText && q.wageMin === null && q.wageMax === null && q.date === "any" && !q.indicator &&
    q.sort === "newest" && !q.status.length && !q.province.length && !q.stream.length && q.yearFrom === null && q.yearTo === null;
  return {
    mode: "static",
    rows,
    emptyText: t(lang, "common.no_records"),
    count: rows ? tn(lang, "search.records_one", "search.records_many", total, { n: n(total) }) : t(lang, "search.loading"),
    note: rows ? t(lang, "search.note_latest", { period: periodLabel(latestPeriod, lang) }) : "",
    facets: plain ? { status: facets?.default.status ?? {}, prov: facets?.default.prov ?? {} } : null,
    range: rows && total
      ? t(lang, "search.showing", {
        from: n((pageNo - 1) * FIRST_PAGE_SIZE + 1),
        to: n(Math.min(total, pageNo * FIRST_PAGE_SIZE)),
        total: n(total),
      })
      : "",
    pageLabel: rows ? t(lang, "search.page_of", { page: pageNo, pages }) : "",
    prev: rows && pageNo > 1 ? `/search?page=${pageNo - 1}` : null,
    next: rows && pageNo < pages ? `/search?page=${pageNo + 1}` : null,
    buttonsEnabled: !rows,
    unavailable: !!rows,
    data: { "data-mode": "static", "data-ssr": rows ? "1" : "0", "data-since": String(YEAR_MIN) },
  };
}
