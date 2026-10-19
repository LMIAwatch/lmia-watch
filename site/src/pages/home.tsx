import type { Context } from "hono";
import { loadFacets, loadStats, type SearchRow } from "../data";
import type { AppEnv } from "../env";
import { provinceName, streamLabel, t, tj } from "../i18n";
import { Badge, Layout, fmtInt, noDataPage, page, periodLabel } from "../layout";
import { homeJsonLd, pageSeo } from "../seo";
import { FeedLinks } from "./feeds";

export async function homePage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "common.home");
  // Pending postings by province, from the search facets; fills the space under
  // the week's postings and links each row to the filtered search.
  const facets = await loadFacets(c.env).catch(() => null);
  const pendingByProv = Object.entries(facets?.default.status_prov ?? {})
    .filter(([k, n]) => k.startsWith("pending|") && n > 0)
    .map(([k, n]) => ({ k: k.slice("pending|".length), n }))
    .sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
  const periodText = stats.esdc_latest_period ? periodLabel(stats.esdc_latest_period, lang) : t(lang, "home.latest_quarter");
  const n = (v: number | null | undefined) => fmtInt(v, lang);

  const PostingTable = ({ rows }: { rows: SearchRow[] }) => (
    <div class="table-wrap">
      <table class="restack">
        <thead>
          <tr>
            <th>{t(lang, "col.posted")}</th>
            <th>{t(lang, "col.employer")}</th>
            <th>{t(lang, "col.job")}</th>
            <th>{t(lang, "col.location")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colspan={4} class="muted">{t(lang, "home.no_records_yet")}</td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr>
                <td data-label={t(lang, "col.posted")} class="mono">{r.date ?? ""}</td>
                <td data-label={t(lang, "col.employer")}>
                  <a href={`/employers/${r.employer_id}`}>{r.employer}</a>
                </td>
                <td data-label={t(lang, "col.job")}>{r.job ?? ""}</td>
                <td data-label={t(lang, "col.location")}>
                  {r.city ?? ""}
                  {r.prov ? `, ${r.prov}` : ""}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );

  const Bars = ({ rows, label, href, limit = 6 }: { rows: { k: string; n: number }[]; label: (k: string) => string; href?: (k: string) => string; limit?: number }) => {
    const max = Math.max(1, ...rows.map((r) => r.n));
    return (
      <div class="bars">
        {rows.slice(0, limit).map((r) => (
          <div class="bar-row">
            <span class="bar-label">{href ? <a href={href(r.k)}>{label(r.k)}</a> : label(r.k)}</span>
            <span class="bar-track">
              <span class="bar-fill" style={`width:${Math.max(1, Math.round((r.n / max) * 100))}%`}></span>
            </span>
            <span class="mono bar-value">{n(r.n)}</span>
          </div>
        ))}
        {rows.length === 0 ? <p class="muted">{t(lang, "home.no_list_rows")}</p> : null}
      </div>
    );
  };

  return page(
    c,
    <Layout lang={lang} title={t(lang, "common.home")} dataAsOf={stats.data_as_of} active="/" seo={pageSeo("home", lang, { jsonLd: [homeJsonLd(lang)] })}
      head={<FeedLinks lang={lang} />}>
      <section class="hero">
        <h1>{t(lang, "home.h1")}</h1>
        <p class="lead">{t(lang, "home.lead")}</p>
        <form action="/search" method="get" class="search-form" role="search">
          <label for="q" class="visually-hidden">{t(lang, "search.button")}</label>
          <input id="q" name="q" type="search" placeholder={t(lang, "search.placeholder")} maxlength={100} />
          <button type="submit" class="btn btn-primary">{t(lang, "search.button")}</button>
        </form>
        <div class="quick-links">
          <span class="muted">{t(lang, "home.quick")}</span>
          <a href="/search?status=pending">{t(lang, "home.quick_pending")}</a>
          <a href="/search?status=approved">{t(lang, "home.quick_approved")}</a>
          <a href="/search?status=refused">{t(lang, "home.quick_refused")}</a>
          <a href="/map">{t(lang, "nav.map")}</a>
        </div>
      </section>

      <section class="tiles" aria-label={t(lang, "home.tiles_label")}>
        <div class="tile">
          <Badge status="pending" lang={lang} />
          <span class="tile-value">{n(stats.counts.pending)}</span>
          <span class="tile-note">
            {tj(lang, "home.tile_pending", { date: <span class="nw">{stats.data_as_of ?? t(lang, "common.na")}</span> })}
          </span>
        </div>
        <div class="tile">
          <Badge status="approved" lang={lang} />
          <span class="tile-value">{n(stats.counts.approved_records)}</span>
          <span class="tile-note">
            {t(lang, "home.tile_approved", { positions: n(stats.counts.approved_positions), period: periodText })}
            {stats.esdc_latest_published ? t(lang, "home.tile_approved_published", { date: stats.esdc_latest_published }) : ""}
          </span>
        </div>
        <div class="tile">
          <Badge status="refused" lang={lang} />
          <span class="tile-value">{n(stats.counts.refused_records)}</span>
          <span class="tile-note">{t(lang, "home.tile_refused", { period: periodText })}</span>
        </div>
        <div class="tile">
          <Badge status="finding" lang={lang} />
          <span class="tile-value">{n(stats.counts.findings)}</span>
          <span class="tile-note">{t(lang, "home.tile_findings")}</span>
        </div>
      </section>

      <section class="two-col">
        <div>
          <div class="section-head">
            <h2>{t(lang, "home.applying")}</h2>
            <a href="/search?status=pending">{t(lang, "home.all_pending", { n: n(stats.counts.pending) })}</a>
          </div>
          <p class="muted small">{t(lang, "home.week_caption")}</p>
          <PostingTable rows={stats.recent_pending} />
          {pendingByProv.length ? (
            <>
              <p class="muted small top-gap">{t(lang, "home.pending_by_prov", { n: n(stats.counts.pending) })}</p>
              <Bars rows={pendingByProv} label={(k) => provinceName(lang, k)} href={(k) => `/search?status=pending&province=${k}`} limit={8} />
            </>
          ) : null}
        </div>
        <div>
          <div class="section-head">
            <h2>{t(lang, "home.recent_approved")}</h2>
            <a href="/search?status=approved">{t(lang, "home.all_approved")}</a>
          </div>
          <p class="muted small">{t(lang, "home.recent_approved_note")}</p>
          <PostingTable rows={stats.recent_approved} />
          <p class="muted small top-gap">{t(lang, "home.largest", { period: periodText })}</p>
          <div class="table-wrap">
            <table class="restack">
              <thead>
                <tr>
                  <th>{t(lang, "col.employer")}</th>
                  <th>{t(lang, "col.location")}</th>
                  <th>{t(lang, "col.stream")}</th>
                  <th class="num">{t(lang, "col.positions")}</th>
                </tr>
              </thead>
              <tbody>
                {stats.top_approvals.map((r) => (
                  <tr>
                    <td data-label={t(lang, "col.employer")}>
                      <a href={`/employers/${r.employer_id}`}>{r.employer}</a>
                    </td>
                    <td data-label={t(lang, "col.location")}>
                      {r.city ?? ""}
                      {r.prov ? `, ${r.prov}` : ""}
                    </td>
                    <td data-label={t(lang, "col.stream")}>{r.stream ? streamLabel(lang, r.stream) : ""}</td>
                    <td data-label={t(lang, "col.positions")} class="mono num">{n(r.positions)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p class="small top-gap"><a href="/releases">{t(lang, "rel.home_link")}</a></p>
        </div>
      </section>

      <section class="two-col">
        <div>
          <h2>{t(lang, "home.by_stream", { period: periodText })}</h2>
          <Bars rows={stats.by_stream} label={(k) => streamLabel(lang, k)} />
        </div>
        <div>
          <h2>{t(lang, "home.by_province", { period: periodText })}</h2>
          <Bars rows={stats.by_province} label={(k) => (k === "XX" ? provinceName(lang, "XX") : k)} />
        </div>
      </section>

      <section class="panel">
        <h2>{t(lang, "home.how")}</h2>
        <p>{t(lang, "home.how_pending")}</p>
        <p>{t(lang, "home.how_indicators")}</p>
        <p>
          {tj(lang, "home.how_reply", {
            methodology: <a href="/methodology">{t(lang, "nav.methodology")}</a>,
            corrections: <a href="/corrections">{t(lang, "home.how_reply_corrections")}</a>,
          })}
        </p>
      </section>
    </Layout>,
  );
}
