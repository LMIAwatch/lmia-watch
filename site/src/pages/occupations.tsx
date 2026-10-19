// Occupation pages (/occupations, /occupations/<noc>): one NOC 2021 unit group
// each, rendered from one small JSON file the nightly export writes
// (pipeline/lmia_pipeline/places.py). NOC 2021 only: ESDC's lists carry the
// five-digit codes from 2024 Q2 on, and the four-digit NOC 2011 codes before
// that do not map one to one onto them, so earlier quarters are not shown.

import type { Context } from "hono";
import { loadJson, loadStats } from "../data";
import type { AppEnv } from "../env";
import { fmtInt, periodLabel, provinceName, t, tn, type Lang } from "../i18n";
import { Layout, noDataPage, page } from "../layout";
import {
  type Bilingual, type NationalLatest, type Posted, type Quarter, type Recent, type SeriesRow, type StatcanRef,
  type Totals, type WageRow, EmployerSection, JobSeekerNote, QuarterSection, SourcesNote, StreamSection, WageHead,
  WageNote, jobBankSearch, money, notFound, placeName, sectionSeo, trendLines, wageCells, wageLine, wellFormed,
} from "./places";

interface RegionRow extends WageRow {
  er: string; name: string; prov: string | null; records: number; positions: number; refused: number;
}

interface OccupationFile {
  noc: string;
  title: Bilingual;
  definition: Bilingual | null;
  category: string;
  category_title: Bilingual | null;
  teer: string;
  from: string | null;
  latest: string;
  updated: string | null;
  totals: Totals;
  quarters: Quarter[];
  streams: [string | null, number, number][];
  stream_periods: string[];
  provinces: [string, number, number, number][];
  national: WageRow;
  statcan_series: SeriesRow[];
  regions: RegionRow[];
  national_latest: NationalLatest;
  employers: Recent[];
  wage_table: { revision: string | null; name: string } | null;
  statcan_latest: string | null;
  threshold: number;
}

interface OccupationIndex {
  from: string | null;
  latest: string;
  threshold: number;
  categories: Record<string, Bilingual>;
  rows: {
    noc: string; title: Bilingual; records: number; approved: number; positions: number; refused: number;
    pending: number; latest_positions: number; indexed: boolean;
  }[];
}

const NOC_RE = /^[0-9]{5}$/;
const OCC_LISTS = ["quarters", "streams", "provinces", "regions", "employers", "statcan_series"] as const;

// The first sentence of the published definition: enough to say what the
// occupation is without copying the classification text.
function firstSentence(text: string | null | undefined): string {
  if (!text) return "";
  const m = /^(.+?[.!?])(\s|$)/.exec(text.trim());
  return (m ? m[1] : text.trim()).slice(0, 400);
}

export async function occupationsIndex(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "occ.index_title");
  const idx = await loadJson<OccupationIndex>(c.env, "occupations/index.json");
  const rows = idx && Array.isArray(idx.rows) ? idx.rows : [];
  const n = (v: number) => fmtInt(v, lang);
  const title = t(lang, "occ.index_title");
  const from = periodLabel(idx?.from ?? "", lang);
  const seo = sectionSeo("/occupations", t(lang, "occ.index_seo_title"), t(lang, "occ.index_description"),
    [{ name: t(lang, "common.home"), path: "/" }, { name: title }], rows.length === 0);
  const groups = new Map<string, OccupationIndex["rows"]>();
  for (const r of rows) {
    const key = r.noc[0];
    const list = groups.get(key) ?? [];
    list.push(r);
    groups.set(key, list);
  }
  const latest = periodLabel(idx?.latest ?? "", lang);
  return page(
    c,
    <Layout lang={lang} title={title} dataAsOf={stats.data_as_of} seo={seo}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / {title}
      </nav>
      <h1>{title}</h1>
      <p class="lead">{t(lang, "occ.index_lead", { from })}</p>
      <p class="muted small">{t(lang, "occ.noc_note", { from })}</p>
      <p><a href="/places">{t(lang, "occ.to_places")}</a></p>
      {rows.length === 0 ? <p class="muted">{t(lang, "places.not_published")}</p> : [...groups.entries()].sort().map(([key, list]) => (
        <section>
          <h2>{idx?.categories?.[key]?.[lang] ?? key}</h2>
          <div class="table-wrap bordered">
            <table class="restack">
              <thead>
                <tr>
                  <th>{t(lang, "places.col_occupation")}</th>
                  <th class="num">{t(lang, "places.col_records")}</th>
                  <th class="num">{t(lang, "places.col_approved_positions")}</th>
                  <th class="num">{t(lang, "places.col_latest_positions", { period: latest })}</th>
                  <th class="num">{t(lang, "employer.pending_postings")}</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr>
                    <td data-label={t(lang, "places.col_occupation")}><span><span class="mono muted">{r.noc}</span> <a href={`/occupations/${r.noc}`}>{r.title[lang]}</a></span></td>
                    <td data-label={t(lang, "places.col_records")} class="mono num">{n(r.records)}</td>
                    <td data-label={t(lang, "places.col_approved_positions")} class="mono num">{n(r.positions)}</td>
                    <td data-label={t(lang, "places.col_latest_positions", { period: latest })} class="mono num">{n(r.latest_positions)}</td>
                    <td data-label={t(lang, "employer.pending_postings")} class="mono num">{n(r.pending)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
      <SourcesNote lang={lang} />
    </Layout>,
  );
}

export async function occupationPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const code = c.req.param("noc") ?? "";
  if (!NOC_RE.test(code)) return c.notFound();
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "occ.index_title");
  const raw = await loadJson<OccupationFile>(c.env, `occupations/${code}.json`);
  if (!wellFormed(raw, OCC_LISTS) || !(raw as OccupationFile).title) {
    return notFound(c, lang, stats.data_as_of, "occ.not_found", "/occupations", "occ.back_index");
  }
  const o = raw as OccupationFile;
  const n = (v: number) => fmtInt(v, lang);
  const title = o.title[lang] || o.title.en;
  const heading = t(lang, "occ.heading", { title, noc: o.noc });
  const from = periodLabel(o.from ?? "", lang);
  const indexed = o.totals.records >= o.threshold;
  const crumbs = [
    { name: t(lang, "common.home"), path: "/" },
    { name: t(lang, "occ.index_title"), path: "/occupations" },
    { name: heading },
  ];
  const seo = sectionSeo(
    `/occupations/${o.noc}`,
    t(lang, "occ.seo_title", { title, noc: o.noc }),
    t(lang, "occ.description", { title, noc: o.noc, approved: n(o.totals.approved), refused: n(o.totals.refused), from }),
    crumbs,
    !indexed,
  );
  const analysis = trendLines(lang, o.quarters, o.national_latest);
  const national = wageLine(lang, o.national);
  if (national) analysis.push(national);
  const topRegion = o.regions[0];
  if (topRegion) {
    analysis.push(t(lang, "occ.top_region", {
      name: placeName(lang, topRegion.name), prov: topRegion.prov ? provinceName(lang, topRegion.prov) : "",
      n: n(topRegion.records), share: o.totals.records ? String(Math.round((topRegion.records / o.totals.records) * 100)) : "0",
    }));
  }
  const definition = firstSentence(o.definition?.[lang]);
  const posted = o.national.posted as Posted;
  const statcan = o.national.statcan as StatcanRef | null;

  return page(
    c,
    <Layout lang={lang} title={heading} dataAsOf={stats.data_as_of} seo={seo}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / <a href="/occupations">{t(lang, "occ.index_title")}</a> / <span class="mono">{o.noc}</span>
      </nav>
      <h1>{heading}</h1>
      {definition ? <p class="lead">{definition} <span class="small">{t(lang, "occ.definition_source")}</span></p> : null}
      <p class="muted small">
        {o.category_title ? t(lang, "occ.category", { category: o.category_title[lang], teer: o.teer }) : t(lang, "occ.teer", { teer: o.teer })}
      </p>
      <p class="muted small">{t(lang, "occ.noc_note", { from })}</p>
      {!indexed ? <p class="muted small">{t(lang, "places.thin", { n: n(o.totals.records), threshold: o.threshold })}</p> : null}

      <section class="cards">
        <div class="card">
          <h2>{t(lang, "places.summary")}</h2>
          <dl>
            <dt>{t(lang, "occ.sum_records", { from })}</dt><dd class="mono">{n(o.totals.records)}</dd>
            <dt>{t(lang, "places.col_approved")}</dt><dd class="mono">{n(o.totals.approved)} <span class="muted">{tn(lang, "employer.positions_paren_one", "employer.positions_paren_many", o.totals.positions, { n: n(o.totals.positions) })}</span></dd>
            <dt>{t(lang, "places.col_refused")}</dt><dd class="mono">{n(o.totals.refused)} <span class="muted">{tn(lang, "employer.positions_paren_one", "employer.positions_paren_many", o.totals.refused_positions, { n: n(o.totals.refused_positions) })}</span></dd>
            <dt>{t(lang, "employer.pending_postings")}</dt><dd class="mono">{n(o.totals.pending)}</dd>
            <dt>{t(lang, "places.sum_employers")}</dt><dd class="mono">{n(o.totals.employers)}</dd>
          </dl>
        </div>
        <div class="card">
          <h2>{t(lang, "places.reading")}</h2>
          {analysis.length ? analysis.map((line) => <p class="small">{line}</p>) : <p class="muted small">{t(lang, "places.reading_none")}</p>}
        </div>
      </section>

      <QuarterSection lang={lang} quarters={o.quarters} />
      <StreamSection lang={lang} streams={o.streams} periods={o.stream_periods} />

      <section>
        <h2>{t(lang, "occ.wages")}</h2>
        <p class="muted small">{t(lang, "occ.wages_note")}</p>
        <div class="table-wrap bordered">
          <table class="restack">
            <thead>
              <tr>
                <th>{t(lang, "occ.col_area")}</th>
                <th class="num">{t(lang, "places.col_records")}</th>
                <WageHead lang={lang} />
              </tr>
            </thead>
            <tbody>
              <tr>
                <td data-label={t(lang, "occ.col_area")}><strong>Canada</strong></td>
                <td data-label={t(lang, "places.col_records")} class="mono num">{n(o.totals.records)}</td>
                {wageCells(lang, o.national)}
              </tr>
              {o.regions.map((r) => (
                <tr>
                  <td data-label={t(lang, "occ.col_area")}><span>{placeName(lang, r.name)}{r.prov ? <span class="muted">, {r.prov}</span> : null}</span></td>
                  <td data-label={t(lang, "places.col_records")} class="mono num">{n(r.records)}</td>
                  {wageCells(lang, r)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <WageNote lang={lang} wageTable={o.wage_table} statcanLatest={o.statcan_latest} />
        {posted.hourly_n + posted.annual_n === 0 ? <p class="muted small">{t(lang, "occ.no_posted")}</p> : null}
      </section>

      {o.statcan_series.length ? (
        <section>
          <h2>{t(lang, "occ.series")}</h2>
          <p class="muted small">{t(lang, "occ.series_note")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "places.col_quarter")}</th>
                  <th class="num">{t(lang, "places.col_vacancies")}</th>
                  <th class="num">{t(lang, "places.col_statcan_wage")}</th>
                </tr>
              </thead>
              <tbody>
                {[...o.statcan_series].reverse().map(([q, v, vq, w, wq]) => (
                  <tr>
                    <td class="mono">{periodLabel(q, lang)}</td>
                    <td class="mono num">{v === null ? t(lang, "common.na") : `${n(v)}${vq === "E" ? " E" : ""}`}</td>
                    <td class="mono num">{w === null ? t(lang, "common.na") : `${money(w, false, lang)}${wq === "E" ? " E" : ""}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {statcan?.vacancies !== undefined ? null : <p class="muted small">{t(lang, "occ.series_none")}</p>}
        </section>
      ) : null}

      {o.provinces.length ? (
        <section>
          <h2>{t(lang, "occ.provinces")}</h2>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "search.province")}</th>
                  <th class="num">{t(lang, "places.col_records")}</th>
                  <th class="num">{t(lang, "places.col_approved_positions")}</th>
                  <th class="num">{t(lang, "places.col_refused")}</th>
                </tr>
              </thead>
              <tbody>
                {o.provinces.map(([prov, records, positions, refused]) => (
                  <tr>
                    <td>{/^[A-Z]{2}$/.test(prov) && prov !== "XX" ? <a href={`/places/${prov.toLowerCase()}`}>{provinceName(lang, prov)}</a> : provinceName(lang, prov)}</td>
                    <td class="mono num">{n(records)}</td>
                    <td class="mono num">{n(positions)}</td>
                    <td class="mono num">{n(refused)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <EmployerSection lang={lang} employers={o.employers} showOccupation={false} />

      <p class="top-gap"><a href={`/search?noc=${o.noc}&date=since_2023q4`} class="btn">{t(lang, "occ.search", { noc: o.noc })}</a></p>
      <JobSeekerNote lang={lang} href={jobBankSearch(lang, { fn21: o.noc })} what={title} />
      <SourcesNote lang={lang} />
    </Layout>,
  );
}
