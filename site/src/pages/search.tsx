import type { Context } from "hono";
import { INDICATORS, PAGE_SIZE, PROVINCES, STATUSES, STREAMS } from "../constants";
import { loadFacets, loadFirst, loadStats, type SearchRow } from "../data";
import type { AppEnv } from "../env";
import {
  clientStrings, indicatorLabel, numberLocale, provinceName, streamLabel, t, tj, tn, type Key, type Lang,
} from "../i18n";
import { Badge, Chip, ClientData, Layout, fmtInt, fmtWage, noDataPage, page, periodLabel } from "../layout";
import { pageSeo } from "../seo";
import { FeedLinks } from "./feeds";

// A plain visit (no filters, newest first, an early page) is rendered here from
// search/first.json, so it needs no JavaScript and no dataset download. Every
// other view is filled in by search.js from the smallest slice that answers it.
const SSR_PAGES = 20;

// Every string search.js draws, handed over in the page's JSON block.
export const SEARCH_CLIENT_KEYS: readonly Key[] = [
  "status.pending", "status.approved", "status.refused", "status.lapsed",
  "ind.newly_incorporated", "ind.repeat_applicant", "ind.wage_at_floor", "ind.low_wage_high_unemployment",
  "ind.high_volume", "ind.refused_then_reposted",
  "col.status", "col.employer", "col.job_or_occupation", "col.location", "col.wage", "col.date", "col.positions",
  "col.indicators", "col.source",
  "common.na", "common.see_posting",
  "period.quarter", "period.range",
  "wage.range", "wage.single", "wage.unit.HOUR", "wage.unit.YEAR", "wage.unit.WEEK", "wage.unit.MONTH",
  "wage.unit.DAY", "wage.unit.BIWEEK",
  "size.mb",
  "search.records_one", "search.records_many", "search.so_far", "search.note_latest", "search.note_since",
  "search.no_match", "search.showing", "search.page_of",
  "search.source_jobbank", "search.source_positive", "search.source_negative",
  "search.gate_long", "search.gate_loading", "search.gate_load", "search.gate_csv", "search.gate_waiting",
  "search.gate_progress",
];

export function searchClientData(lang: Lang) {
  return { lang, locale: numberLocale(lang), strings: clientStrings(lang, SEARCH_CLIENT_KEYS) };
}

export function sourceLabel(lang: Lang, r: Pick<SearchRow, "kind" | "ref" | "status" | "period">): string {
  if (r.kind === "posting") return t(lang, "search.source_jobbank", { ref: r.ref });
  return t(lang, r.status === "refused" ? "search.source_negative" : "search.source_positive", { period: r.period ?? "" });
}

// Each cell carries its column header as data-label, so on a phone the row
// restacks as a labelled block. search.js builds the same row with the same
// labels; keep the two in step with the table header below.
export const SearchRowView = ({ r, lang }: { r: SearchRow; lang: Lang }) => (
  <tr>
    <td data-label={t(lang, "col.status")}>
      <Badge status={r.status} lang={lang} />
    </td>
    <td data-label={t(lang, "col.employer")}>
      <a href={`/employers/${r.employer_id}`}>{r.employer}</a>
    </td>
    <td data-label={t(lang, "col.job_or_occupation")}>
      {r.kind === "esdc" && r.noc ? `${r.noc} ` : ""}
      {r.job ?? ""}
    </td>
    <td data-label={t(lang, "col.location")}>
      {[r.street, r.city].filter(Boolean).join(", ")}
      {r.prov ? `, ${r.prov}` : ""}
      {r.postal ? ` ${r.postal}` : ""}
    </td>
    <td data-label={t(lang, "col.wage")} class="mono">
      {r.kind === "posting" ? fmtWage(r.wage_min, r.wage_max, r.unit, lang) : t(lang, "common.na")}
    </td>
    <td data-label={t(lang, "col.date")} class="mono">{r.kind === "posting" ? r.date ?? "" : periodLabel(r.period ?? "", lang)}</td>
    <td data-label={t(lang, "col.positions")} class="mono num">
      {r.positions === null ? t(lang, "common.see_posting") : fmtInt(r.positions, lang)}
    </td>
    <td data-label={t(lang, "col.indicators")}>
      {r.ind.length ? (
        <span class="chips">
          {r.ind.map((i) => (
            <Chip>{indicatorLabel(lang, i)}</Chip>
          ))}
        </span>
      ) : null}
    </td>
    <td data-label={t(lang, "col.source")}>
      <a href={r.source} class="mono" rel="nofollow noopener">
        {sourceLabel(lang, r)}
      </a>
    </td>
  </tr>
);

export async function searchPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "nav.search");
  const facets = await loadFacets(c.env);
  const q = (c.req.query("q") ?? "").slice(0, 100);
  const noc = (c.req.query("noc") ?? "").slice(0, 60);
  const wageMin = c.req.query("wage_min") ?? "";
  const wageMax = c.req.query("wage_max") ?? "";
  const date = c.req.query("date") ?? "any";
  const indicator = c.req.query("indicator") ?? "";
  const sort = c.req.query("sort") ?? "newest";
  const pageNo = Math.max(1, Math.min(10000, Number(c.req.query("page") ?? 1) || 1));
  const picked = (name: string) => c.req.queries(name) ?? [];
  const plain =
    !q && !noc && !wageMin && !wageMax && date === "any" && !indicator && sort === "newest" &&
    picked("status").length === 0 && picked("province").length === 0 && picked("stream").length === 0;
  const n = (v: number) => fmtInt(v, lang);
  const latest = periodLabel(stats.esdc_latest_period, lang);
  const from = periodLabel(stats.search_from_period, lang);

  let ssrRows: SearchRow[] | null = null;
  let total = facets?.default.total ?? 0;
  if (plain && pageNo <= SSR_PAGES) {
    const first = await loadFirst(c.env);
    if (first) {
      ssrRows = first.slice((pageNo - 1) * PAGE_SIZE, pageNo * PAGE_SIZE);
      if (!facets) total = first.length;
    }
  }
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const count = (kind: "status" | "prov", key: string) => facets?.default[kind][key] ?? 0;
  const check = (name: string, value: string, label: unknown, countKey?: "status" | "prov") => (
    <label class="check">
      <input type="checkbox" name={name} value={value} checked={picked(name).includes(value)} />
      {label}
      {countKey ? <span class="mono muted" data-count={`${name}:${value}`}> {plain ? n(count(countKey, value)) : ""}</span> : null}
    </label>
  );

  return page(
    c,
    <Layout lang={lang} title={t(lang, "nav.search")} dataAsOf={stats.data_as_of} active="/search" seo={pageSeo("search", lang)}
      head={<FeedLinks lang={lang} />}>
      <form action="/search" method="get" class="search-page" id="search-form">
        <div class="search-form top-gap">
          <label for="q" class="visually-hidden">{t(lang, "search.button")}</label>
          <input id="q" name="q" type="search" value={q} placeholder={t(lang, "search.placeholder")} maxlength={100} />
          <button type="submit" class="btn btn-primary">{t(lang, "search.button")}</button>
        </div>
        <div class="search-layout">
          <aside class="filters" aria-label={t(lang, "search.filters")}>
            <fieldset>
              <legend>{t(lang, "col.status")}</legend>
              {STATUSES.map((s) => check("status", s, <Badge status={s} lang={lang} />, "status"))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.province")}</legend>
              {PROVINCES.map((pr) => check("province", pr, provinceName(lang, pr), "prov"))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.stream_legend")}</legend>
              <p class="muted small filter-hint">{t(lang, "search.stream_hint")}</p>
              {STREAMS.map((s) => check("stream", s, streamLabel(lang, s)))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.noc")}</legend>
              <label for="noc" class="visually-hidden">{t(lang, "search.noc_label")}</label>
              <input id="noc" name="noc" type="text" value={noc} placeholder={t(lang, "search.noc_placeholder")} maxlength={60} />
            </fieldset>
            <fieldset>
              <legend>{t(lang, "search.wage")}</legend>
              <div class="inline-fields">
                <label for="wage_min">{t(lang, "search.min")}</label>
                <input id="wage_min" name="wage_min" type="number" step="0.01" min="0" value={wageMin} />
                <label for="wage_max">{t(lang, "search.max")}</label>
                <input id="wage_max" name="wage_max" type="number" step="0.01" min="0" value={wageMax} />
              </div>
            </fieldset>
            <fieldset>
              <legend>{t(lang, "col.date")}</legend>
              {(
                [
                  ["any", t(lang, "search.date_any", { period: latest })],
                  ["7d", t(lang, "search.date_7d")],
                  ["last_quarter", t(lang, "search.date_last_quarter", { period: latest })],
                  ["since_2023q4", t(lang, "search.date_long", { period: from, n: n(facets?.long.total ?? 0) })],
                ] as const
              ).map(([v, label]) => (
                <label class="check">
                  <input type="radio" name="date" value={v} checked={date === v} /> {label}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend>{t(lang, "col.indicators")}</legend>
              <label class="check">
                <input type="radio" name="indicator" value="" checked={indicator === ""} /> {t(lang, "search.any_state")}
              </label>
              {INDICATORS.map((i) => (
                <label class="check">
                  <input type="radio" name="indicator" value={i} checked={indicator === i} /> {indicatorLabel(lang, i)}
                </label>
              ))}
            </fieldset>
            <p class="filter-actions">
              <a href="/search" class="btn-link">{t(lang, "search.clear")}</a>
              <a href="#results" class="btn show-results">{t(lang, "search.show_results")}</a>
            </p>
          </aside>

          <div
            class="results"
            id="results"
            data-latest={stats.esdc_latest_period}
            data-from={stats.search_from_period}
            data-years={(stats.search_years ?? []).join(",")}
            data-today={stats.data_as_of ?? ""}
            data-ssr={ssrRows ? "1" : "0"}
          >
            <div class="results-head">
              <p id="results-count">
                <strong>{ssrRows ? tn(lang, "search.records_one", "search.records_many", total, { n: n(total) }) : t(lang, "search.loading")}</strong>{" "}
                <span class="muted" id="results-note">{ssrRows ? t(lang, "search.note_latest", { period: latest }) : ""}</span>
              </p>
              <div class="results-tools">
                <span class="muted">{t(lang, "search.view")}</span>
                <span class="btn btn-active">{t(lang, "search.list")}</span>
                <a href="/map" class="btn">{t(lang, "nav.map")}</a>
                <label for="sort" class="muted">{t(lang, "search.sort")}</label>
                <select id="sort" name="sort">
                  <option value="newest" selected={sort === "newest"}>{t(lang, "search.sort_newest")}</option>
                  <option value="positions" selected={sort === "positions"}>{t(lang, "col.positions")}</option>
                  <option value="name" selected={sort === "name"}>{t(lang, "search.sort_name")}</option>
                </select>
              </div>
            </div>
            <div id="load-gate" class="panel bordered" hidden></div>
            <div class="table-wrap bordered">
              <table class="restack">
                <thead>
                  <tr>
                    <th>{t(lang, "col.status")}</th>
                    <th>{t(lang, "col.employer")}</th>
                    <th>{t(lang, "col.job_or_occupation")}</th>
                    <th>{t(lang, "col.location")}</th>
                    <th>{t(lang, "col.wage")}</th>
                    <th>{t(lang, "col.date")}</th>
                    <th class="num">{t(lang, "col.positions")}</th>
                    <th>{t(lang, "col.indicators")}</th>
                    <th>{t(lang, "col.source")}</th>
                  </tr>
                </thead>
                <tbody id="results-body">
                  {ssrRows ? (
                    ssrRows.length ? ssrRows.map((r) => <SearchRowView r={r} lang={lang} />) : (
                      <tr>
                        <td colspan={9} class="muted">{t(lang, "common.no_records")}</td>
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
              <span class="muted" id="page-range">
                {ssrRows && total
                  ? t(lang, "search.showing", {
                    from: n((pageNo - 1) * PAGE_SIZE + 1),
                    to: n(Math.min(total, pageNo * PAGE_SIZE)),
                    total: n(total),
                  })
                  : ""}
              </span>
              <span class="pages">
                {ssrRows && pageNo > 1 ? <a href={`/search?page=${pageNo - 1}`} class="btn" id="page-prev">{t(lang, "search.prev")}</a> : <button type="button" class="btn" id="page-prev" disabled={!!ssrRows}>{t(lang, "search.prev")}</button>}
                <span class="mono" id="page-label">{ssrRows ? t(lang, "search.page_of", { page: pageNo, pages }) : ""}</span>
                {ssrRows && pageNo < pages ? <a href={`/search?page=${pageNo + 1}`} class="btn" id="page-next">{t(lang, "search.next")}</a> : <button type="button" class="btn" id="page-next" disabled={!!ssrRows}>{t(lang, "search.next")}</button>}
              </span>
              <button type="button" class="btn-link" id="csv-download">{t(lang, "search.csv")}</button>
            </nav>
            <p class="muted small">
              {tj(lang, "search.footnote", {
                period: from,
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
}
