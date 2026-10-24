import type { Context } from "hono";
import { loadFacets, loadStats, type SearchRow } from "../data";
import type { AppEnv } from "../env";
import { provinceName, streamLabel, t, tj, tn } from "../i18n";
import { Badge, Layout, fmtInt, noDataPage, page, periodLabel } from "../layout";
import { homeJsonLd, pageSeo } from "../seo";
import { isListOf, isNum, isObj, isStr, isStrOrNull } from "../valid";
import { FeedLinks } from "./feeds";
import { isBilingual } from "./places";

// The lists of stats.json that only this page reads, checked here rather than
// in loadStats so a malformed row costs this page, not every page. Each field
// is checked as the tables below render it, and allows null wherever the
// export can write it: a posting's title, date, city and province, and a top
// employer's city, province and stream.
const isPostingRow = (r: unknown): boolean => isObj(r) && isStr(r.employer_id) && isStr(r.employer) && isStrOrNull(r.date) &&
  isStrOrNull(r.job) && isStrOrNull(r.city) && isStrOrNull(r.prov) && (r.flagged === undefined || isStr(r.flagged));
const isTopRow = (r: unknown): boolean => isObj(r) && isStr(r.employer_id) && isStr(r.employer) && isStrOrNull(r.city) &&
  isStrOrNull(r.prov) && isStrOrNull(r.stream) && isNum(r.positions);
// The export writes "Unknown" where the quarter's rows have no stream or province, so a key is never null.
const isCountRow = (r: unknown): boolean => isObj(r) && isStr(r.k) && isNum(r.n);
// A pending-by-occupation row: a five-digit NOC 2021 code, its count and its titles.
const isNocRow = (r: unknown): boolean => isObj(r) && isStr(r.k) && /^[0-9]{5}$/.test(r.k) && isNum(r.n) && isBilingual(r.title);
// NOC titles join gendered forms with a slash ("Cuisiniers/cuisinières"),
// which leaves a phone's narrow label column no place to break the line.
const slashBreaks = (s: string) => s.split("/").flatMap((part, i) => (i ? ["/", <wbr />, part] : [part]));

export async function homePage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (
    !stats || !isListOf(stats.recent_pending, isPostingRow) || !isListOf(stats.recent_approved, isPostingRow) ||
    !isListOf(stats.top_approvals, isTopRow) || !isListOf(stats.by_stream, isCountRow) || !isListOf(stats.by_province, isCountRow)
  ) return noDataPage(c, "common.home");
  // Pending postings by province, from the search facets, beside the week's
  // postings in the pending row; each row links to the filtered search.
  const facets = await loadFacets(c.env).catch(() => null);
  const pendingByProv = Object.entries(facets?.default.status_prov ?? {})
    .filter(([k, n]) => k.startsWith("pending|") && n > 0)
    .map(([k, n]) => ({ k: k.slice("pending|".length), n }))
    .sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
  // Pending postings by occupation, below the province bars. Optional: a stats
  // file from before it, or one whose list or total fails the check, leaves
  // the chart out and the page as it was.
  const withNoc = stats.counts.pending_with_noc;
  const pendingByNoc = withNoc !== undefined && isListOf(stats.pending_by_noc, isNocRow) ? stats.pending_by_noc : [];
  const nocTitle = new Map(pendingByNoc.map((r) => [r.k, r.title[lang]]));
  const byFlag = stats.recent_pending.length > 0 && stats.recent_pending.every((r) => typeof r.flagged === "string" && r.flagged !== "");
  const periodText = stats.esdc_latest_period ? periodLabel(stats.esdc_latest_period, lang) : t(lang, "home.latest_quarter");
  const n = (v: number | null | undefined) => fmtInt(v, lang);
  const { grant_employers: grantEmployers, grant_agreements: grantAgreements } = stats.counts;

  // The pending table ranks by the day the flag was first seen once the export
  // carries it (every row), and shows the posting date under it; an older stats
  // file, without the field, lists by posting date as before.
  const PostingTable = ({ rows, byFlag = false }: { rows: SearchRow[]; byFlag?: boolean }) => (
    <div class="table-wrap">
      <table class="restack">
        <thead>
          <tr>
            <th>{t(lang, byFlag ? "col.flagged" : "col.posted")}</th>
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
                {/* One element in the flagged cell, so the phone's restack grid keeps both lines in the value column. */}
                {byFlag ? (
                  <td data-label={t(lang, "col.flagged")} class="mono">
                    <span>
                      {r.flagged}
                      {r.date ? <><br /><span class="muted small">{t(lang, "home.posted_on", { date: r.date })}</span></> : null}
                    </span>
                  </td>
                ) : (
                  <td data-label={t(lang, "col.posted")} class="mono">{r.date ?? ""}</td>
                )}
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

  const Bars = ({ rows, label, href, lead, limit = 6 }: {
    rows: { k: string; n: number }[]; label: (k: string) => string; href?: (k: string) => string; lead?: (k: string) => string; limit?: number;
  }) => {
    const max = Math.max(1, ...rows.map((r) => r.n));
    return (
      <div class="bars">
        {rows.slice(0, limit).map((r) => (
          <div class="bar-row">
            <span class="bar-label">
              {lead ? <><span class="mono muted">{lead(r.k)}</span> </> : null}
              {href ? <a href={href(r.k)}>{slashBreaks(label(r.k))}</a> : slashBreaks(label(r.k))}
            </span>
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
          {/* Search covers every year; the last-quarter window is what these two name. */}
          <a href="/search?status=approved&date=last_quarter">{t(lang, "home.quick_approved")}</a>
          <a href="/search?status=refused&date=last_quarter">{t(lang, "home.quick_refused")}</a>
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
        {/* Left out until a run has matched an agreement (or by a stats file from before these counts). */}
        {grantEmployers !== undefined && grantEmployers > 0 && grantAgreements !== undefined ? (
          <div class="tile">
            <span class="badge badge-neutral">{t(lang, "home.tile_grants_label")}</span>
            <span class="tile-value">{n(grantEmployers)}</span>
            <span class="tile-note">
              <a href="/data#public-records">{tn(lang, "home.tile_grants_one", "home.tile_grants_many", grantAgreements, { agreements: n(grantAgreements) })}</a>
            </span>
          </div>
        ) : null}
      </section>

      {/* Below the tiles, one row per subject: a full-width head carrying the
          status tag, the count and the link to the full list, then the records
          on the left and the breakdowns on the right. */}
      <section class="topic">
        <div class="topic-head">
          <h2>
            <Badge status="pending" lang={lang} /> {t(lang, "home.topic_pending")}{" "}
            <span class="topic-count">{t(lang, "home.topic_pending_count", { n: n(stats.counts.pending) })}</span>
          </h2>
          <a href="/search?status=pending">{t(lang, "home.all_pending", { n: n(stats.counts.pending) })}</a>
        </div>
        <div class="two-col">
          <div>
            <h3 class="sub">{t(lang, "home.applying")}</h3>
            <p class="muted small">{t(lang, byFlag ? "home.week_caption_flagged" : "home.week_caption")}</p>
            <PostingTable rows={stats.recent_pending} byFlag={byFlag} />
          </div>
          <div>
            {pendingByProv.length ? (
              <>
                <h3 class="sub">{t(lang, "home.by_province")}</h3>
                <Bars rows={pendingByProv} label={(k) => provinceName(lang, k)} href={(k) => `/search?status=pending&province=${k}`} limit={8} />
              </>
            ) : null}
            {pendingByNoc.length && withNoc !== undefined ? (
              <>
                <h3 class="sub">{t(lang, "home.by_occupation")}</h3>
                <p class="muted small">{tn(lang, "home.pending_by_noc_one", "home.pending_by_noc_many", withNoc, { n: n(withNoc) })}</p>
                <Bars rows={pendingByNoc} label={(k) => nocTitle.get(k) || k} lead={(k) => k} href={(k) => `/search?status=pending&noc=${k}`} />
              </>
            ) : null}
          </div>
        </div>
      </section>

      <section class="topic">
        <div class="topic-head">
          <h2>
            <Badge status="approved" lang={lang} /> {t(lang, "home.topic_approved", { period: periodText })}{" "}
            <span class="topic-count">
              {t(lang, "home.topic_approved_count", { records: n(stats.counts.approved_records), positions: n(stats.counts.approved_positions) })}
            </span>
          </h2>
          <a href="/search?status=approved">{t(lang, "home.all_approved")}</a>
        </div>
        <div class="two-col">
          <div>
            <h3 class="sub">{t(lang, "home.recent_approved")}</h3>
            <p class="muted small">{t(lang, "home.recent_approved_note")}</p>
            <PostingTable rows={stats.recent_approved} />
            <p class="links">
              <a href="/releases">{t(lang, "rel.home_link")}</a>
              <a href="/trends">{t(lang, "trends.home_link")}</a>
            </p>
          </div>
          <div>
            <h3 class="sub">{t(lang, "home.by_stream")}</h3>
            <Bars rows={stats.by_stream} label={(k) => streamLabel(lang, k)} />
            <h3 class="sub">{t(lang, "home.by_province")}</h3>
            <Bars rows={stats.by_province} label={(k) => (k === "XX" ? provinceName(lang, "XX") : k)} />
            <h3 class="sub">{t(lang, "home.largest", { period: periodText })}</h3>
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
          </div>
        </div>
      </section>

      <section class="panel">
        <h2>{t(lang, "home.how")}</h2>
        <p>{t(lang, "home.how_pending")}</p>
        <p>
          {tj(lang, "home.how_profile", {
            jobbank: <a href="/methodology#sources">{t(lang, "home.how_profile_jobbank")}</a>,
            esdc: <a href="/methodology#sources">{t(lang, "home.how_profile_esdc")}</a>,
            ircc: <a href="/methodology#sources">{t(lang, "home.how_profile_ircc")}</a>,
            registry: <a href="/methodology#matching">{t(lang, "home.how_profile_registry")}</a>,
            grants: <a href="/data#public-records">{t(lang, "home.how_profile_grants")}</a>,
            alberta: <a href="/data#public-records">{t(lang, "home.how_profile_alberta")}</a>,
            carrier: <a href="/data#public-records">{t(lang, "home.how_profile_carrier")}</a>,
          })}
        </p>
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
