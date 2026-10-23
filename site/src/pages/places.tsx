// Place pages (/places, /places/<pp>, /places/<pp>/<slug>) and the parts the
// occupation pages share with them. Each page renders one small JSON file the
// nightly export writes (pipeline/lmia_pipeline/places.py) and adds its own
// reading of the figures: the change since the previous quarter, the share of
// the national total, and posted wages against the Job Bank median and
// Statistics Canada's offered wage. A page under the record threshold is
// marked noindex and is left out of the sitemap.

import type { Context } from "hono";
import { loadJson, loadStats } from "../data";
import type { AppEnv } from "../env";
import { decimal, fmtInt, periodLabel, provinceName, streamLabel, t, tj, tn, type Key, type Lang } from "../i18n";
import { Badge, Layout, noDataPage, page } from "../layout";
import { DESCRIPTION_MAX, SITE_ORIGIN, SOCIAL_CARD, absoluteUrl, pageTitle, type Seo } from "../seo";
import { isListOf, isNum, isNumOrNull, isObj, isStr, isStrOrNull, optional } from "../valid";

// -- shapes of the exported files -----------------------------------------------------

export type Quarter = [string, number, number, number, number]; // period, approved rows, positions, refused rows, positions

export interface Totals {
  records: number; approved: number; positions: number; refused: number; refused_positions: number;
  pending: number; postings: number; employers: number;
}

export interface Posted { hourly: number | null; hourly_n: number; annual: number | null; annual_n: number }

export interface JobBankRef { median: number; annual: number; level: string; area: string; reference: string | null }

export interface StatcanRef {
  level: string; area: string; name: string | null;
  wage?: number; wage_quarter?: string; wage_quality?: string | null;
  vacancies?: number; vac_quarter?: string; vac_quality?: string | null; vacancies_year_before?: number;
}

export type SeriesRow = [string, number | null, string | null, number | null, string | null];

export interface Recent {
  id: string; name: string; city: string | null; prov: string | null; date: string; period: string | null;
  status: string; positions: number | null; noc: string | null;
}

export interface Bilingual { en: string; fr: string }

export interface WageRow {
  posted: Posted; jobbank: JobBankRef | null; statcan: StatcanRef | null;
}

export interface NationalLatest { period: string; approved: number; positions: number; refused: number }

interface PlaceOccupation extends WageRow {
  noc: string; title: Bilingual; records: number; positions: number; refused: number;
}

interface ChildPlace { slug: string; name: string; records: number; uid?: string; indexed?: boolean }

export interface PlaceFile {
  kind: "province" | "cma" | "city";
  prov: string;
  slug: string;
  name: string;
  latest: string;
  occ_from: string | null;
  updated: string | null;
  totals: Totals;
  quarters: Quarter[];
  streams: [string | null, number, number][];
  stream_periods: string[];
  region: { er: string; name: string } | null;
  occupations: PlaceOccupation[];
  context: StatcanRef | null;
  statcan_series: SeriesRow[];
  national_latest: NationalLatest;
  employers: Recent[];
  wage_table: { revision: string | null; name: string } | null;
  statcan_latest: string | null;
  threshold: number;
  cmas?: ChildPlace[];
  cities?: ChildPlace[];
  cma?: { slug: string; name: string; prov: string } | null;
  cma_uid?: string;
  lfs?: { month: string; rate: number } | null;
}

interface PlacesIndex {
  latest: string;
  threshold: number;
  updated: string | null;
  provinces: {
    prov: string; records: number; positions: number; latest_positions: number; indexed: boolean; cities: number;
    top_cities: ChildPlace[]; cmas: ChildPlace[];
  }[];
}

// -- checks ----------------------------------------------------------------------------

// Each file is checked field by field as the page reads it, and one that
// fails is treated like a missing one. The parts shared with the occupation
// pages are exported for occupations.tsx.

export const tuple = (v: unknown, ...checks: ((x: unknown) => boolean)[]): boolean =>
  Array.isArray(v) && v.length === checks.length && checks.every((check, i) => check(v[i]));

export const isBilingual = (v: unknown): v is Bilingual => isObj(v) && isStr(v.en) && isStr(v.fr);

const isTotals = (v: unknown): v is Totals => isObj(v) &&
  (["records", "approved", "positions", "refused", "refused_positions", "pending", "employers"] as const).every((k) => isNum(v[k]));

const isQuarter = (v: unknown): boolean => tuple(v, isStr, isNum, isNum, isNum, isNum);
const isStreamRow = (v: unknown): boolean => tuple(v, isStrOrNull, isNum, isNum);
const isSeriesRow = (v: unknown): boolean => tuple(v, isStr, isNumOrNull, isStrOrNull, isNumOrNull, isStrOrNull);

const isRecent = (v: unknown): v is Recent => isObj(v) && isStr(v.id) && isStr(v.name) && isStrOrNull(v.city) &&
  isStrOrNull(v.prov) && isStr(v.date) && isStrOrNull(v.period) && isStr(v.status) && isNumOrNull(v.positions) && isStrOrNull(v.noc);

const isPosted = (v: unknown): v is Posted =>
  isObj(v) && isNumOrNull(v.hourly) && isNum(v.hourly_n) && isNumOrNull(v.annual) && isNum(v.annual_n);

export const isJobBank = (v: unknown): v is JobBankRef => isObj(v) && isNum(v.median) && isNum(v.annual) && isStr(v.level) && isStr(v.area);

// The wage and vacancy figures are each present only when Statistics Canada published them.
export const isStatcan = (v: unknown): v is StatcanRef => isObj(v) && isStr(v.level) && isStr(v.area) && isStrOrNull(v.name) &&
  optional(v.wage, isNum) && optional(v.wage_quarter, isStr) && optional(v.wage_quality, isStrOrNull) &&
  optional(v.vacancies, isNum) && optional(v.vac_quarter, isStr) && optional(v.vac_quality, isStrOrNull) &&
  optional(v.vacancies_year_before, isNum);

export const isWageRow = (v: unknown): v is WageRow => isObj(v) && isPosted(v.posted) &&
  (v.jobbank === null || isJobBank(v.jobbank)) && (v.statcan === null || isStatcan(v.statcan));

// What an occupation file and a place file both carry.
export function hasSharedParts(v: Record<string, any>): boolean {
  return isTotals(v.totals) && isNum(v.threshold) && isListOf(v.quarters, isQuarter) && isListOf(v.streams, isStreamRow) &&
    isListOf(v.stream_periods, isStr) && isObj(v.national_latest) && isStr(v.national_latest.period) &&
    isNum(v.national_latest.positions) && isListOf(v.employers, isRecent) && isListOf(v.statcan_series, isSeriesRow) &&
    (v.wage_table === null || (isObj(v.wage_table) && isStrOrNull(v.wage_table.revision))) && isStrOrNull(v.statcan_latest);
}

const isChildPlace = (v: unknown): v is ChildPlace => isObj(v) && isStr(v.slug) && isStr(v.name) && isNum(v.records);

const isPlaceOccupation = (v: unknown): v is PlaceOccupation =>
  isObj(v) && isStr(v.noc) && isBilingual(v.title) && isNum(v.records) && isNum(v.positions) && isWageRow(v);

// cmas and cities are written for provinces only, cma for cities, lfs for
// census metropolitan areas and cities.
function isPlaceFile(v: unknown): v is PlaceFile {
  return isObj(v) && (v.kind === "province" || v.kind === "cma" || v.kind === "city") && isStr(v.prov) && isStr(v.slug) &&
    isStr(v.name) && isStrOrNull(v.occ_from) && hasSharedParts(v) &&
    (v.region === null || (isObj(v.region) && isStr(v.region.name))) &&
    (v.context === null || isStatcan(v.context)) && isListOf(v.occupations, isPlaceOccupation) &&
    (v.cmas == null || isListOf(v.cmas, isChildPlace)) && (v.cities == null || isListOf(v.cities, isChildPlace)) &&
    (v.cma == null || (isObj(v.cma) && isStr(v.cma.slug) && isStr(v.cma.name) && isStr(v.cma.prov))) &&
    (v.lfs == null || (isObj(v.lfs) && isStr(v.lfs.month) && isNum(v.lfs.rate)));
}

const isProvinceRow = (v: unknown): boolean => isObj(v) && isStr(v.prov) && isNum(v.records) && isNum(v.positions) &&
  isNum(v.latest_positions) && isNum(v.cities) && isListOf(v.top_cities, isChildPlace) && isListOf(v.cmas, isChildPlace);

const isPlacesIndex = (v: unknown): v is PlacesIndex =>
  isObj(v) && isNum(v.threshold) && isStr(v.latest) && isListOf(v.provinces, isProvinceRow);

// -- small formats -------------------------------------------------------------------

// Statistics Canada's French names for the economic regions whose English name
// differs (the same list i18n.ts keeps for the indicator sentences), plus the
// survey's combined regions and the census metropolitan areas with a French name.
const PLACE_FR: Record<string, string> = {
  "South Coast--Burin Peninsula": "Côte-sud--Burin Peninsula",
  "West Coast--Northern Peninsula--Labrador": "Côte-ouest--Northern Peninsula--Labrador",
  "Prince Edward Island": "Île-du-Prince-Édouard",
  "North Shore": "Côte-nord",
  Southern: "Sud",
  Northeast: "Nord-est",
  Northwest: "Nord-ouest",
  Southeast: "Sud-est",
  "South Central": "Centre sud",
  Southwest: "Sud-ouest",
  "North Central": "Centre nord",
  North: "Nord",
  Northern: "Nord",
  "Vancouver Island and Coast": "Île de Vancouver et la côte",
  "Lower Mainland--Southwest": "Lower Mainland--Sud-ouest",
  "North Coast": "Côte-nord",
  "Northwest Territories": "Territoires du Nord-Ouest",
  "Greater Sudbury": "Grand Sudbury",
  "Greater Sudbury / Grand Sudbury": "Grand Sudbury",
  "South Central and North Central": "Centre sud et Centre nord",
  "Parklands and North": "Parklands et Nord",
  "Prince Albert and Northern": "Prince Albert et Nord",
  "North Coast and Nechako": "Côte-nord et Nechako",
  "Côte-Nord and Nord-du-Québec": "Côte-Nord et Nord-du-Québec",
};

export function placeName(lang: Lang, name: string | null | undefined): string {
  if (!name) return "";
  return lang === "fr" ? PLACE_FR[name] ?? name : name;
}

export function money(value: number | null | undefined, annual: boolean, lang: Lang): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return t(lang, "common.na");
  const amount = annual ? fmtInt(Math.round(value), lang) : decimal(lang, value.toFixed(2));
  return `${t(lang, "money", { amount })}${t(lang, annual ? "wage.unit.YEAR" : "wage.unit.HOUR")}`;
}

export function pct(value: number, lang: Lang): string {
  return decimal(lang, (Math.round(value * 10) / 10).toFixed(1));
}

export function clip(text: string, max = DESCRIPTION_MAX): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max / 2 ? cut.slice(0, space) : cut).replace(/[\s,.;:]+$/, "")}…`;
}

// The newest two quarters with a plain quarterly label.
function lastTwo(quarters: Quarter[]): [Quarter | null, Quarter | null] {
  const q = quarters.filter((r) => /^\d{4}Q[1-4]$/.test(r[0]));
  return [q[q.length - 1] ?? null, q[q.length - 2] ?? null];
}

function areaLabel(lang: Lang, ref: { level: string; area: string; name?: string | null }, names: Record<string, string> = {}): string {
  if (ref.level === "canada") return "Canada";
  if (ref.level === "province") return provinceName(lang, PRUID[ref.area] ?? ref.area);
  return t(lang, "places.region_of", { name: placeName(lang, ref.name ?? names[ref.area] ?? ref.area) });
}

const PRUID: Record<string, string> = {
  "10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC", "35": "ON", "46": "MB", "47": "SK", "48": "AB",
  "59": "BC", "60": "YT", "61": "NT", "62": "NU",
};

function quality(lang: Lang, letter: string | null | undefined) {
  return letter === "E" ? <abbr title={t(lang, "places.quality_e")}> E</abbr> : null;
}

// -- shared analysis -----------------------------------------------------------------

// The change since the previous quarter, refusals, and the share of the national
// total, as sentences. Every figure comes from the page's own file.
export function trendLines(lang: Lang, quarters: Quarter[], national: NationalLatest | null): string[] {
  const [now, prev] = lastTwo(quarters);
  if (!now) return [];
  const n = (v: number) => fmtInt(v, lang);
  const lines: string[] = [];
  const vars = { period: periodLabel(now[0], lang), prev: prev ? periodLabel(prev[0], lang) : "", rows: n(now[1]), pos: n(now[2]), prevpos: prev ? n(prev[2]) : "0" };
  if (!prev || (now[2] === 0 && prev[2] === 0)) {
    lines.push(t(lang, now[2] ? "places.trend_only" : "places.trend_none", vars));
  } else if (prev[2] === 0) {
    lines.push(t(lang, "places.trend_new", vars));
  } else {
    const change = ((now[2] - prev[2]) / prev[2]) * 100;
    const key: Key = Math.abs(change) < 0.05 ? "places.trend_same" : change > 0 ? "places.trend_up" : "places.trend_down";
    lines.push(t(lang, key, { ...vars, pct: pct(Math.abs(change), lang) }));
  }
  if (prev) lines.push(t(lang, "places.trend_refused", { ...vars, refused: n(now[3]), prevrefused: n(prev[3]) }));
  if (national && national.period === now[0] && national.positions > 0 && now[2] > 0) {
    lines.push(t(lang, "places.trend_share", { share: pct((now[2] / national.positions) * 100, lang), period: vars.period }));
  }
  return lines;
}

// Posted wages against the two references, as one sentence, or null when
// nothing can be compared.
export function wageLine(lang: Lang, row: WageRow): string | null {
  const jb = row.jobbank;
  const sc = row.statcan;
  const annual = jb?.annual === 1;
  const posted = annual ? row.posted.annual : row.posted.hourly;
  const count = annual ? row.posted.annual_n : row.posted.hourly_n;
  const parts: string[] = [];
  if (posted !== null && count > 0) {
    parts.push(tn(lang, "places.wage_posted_one", "places.wage_posted_many", count, { n: fmtInt(count, lang), wage: money(posted, annual, lang) }));
  }
  if (jb) {
    const diff = posted !== null && count > 0 ? ((posted - jb.median) / jb.median) * 100 : null;
    parts.push(t(lang, diff === null ? "places.wage_jobbank" : Math.abs(diff) < 0.05 ? "places.wage_jobbank_same" : diff > 0 ? "places.wage_jobbank_above" : "places.wage_jobbank_below", {
      median: money(jb.median, annual, lang), area: areaLabel(lang, jb), pct: diff === null ? "" : pct(Math.abs(diff), lang),
    }));
  }
  if (sc?.wage !== undefined) {
    const hourly = row.posted.hourly;
    const diff = hourly !== null && row.posted.hourly_n > 0 ? ((hourly - sc.wage) / sc.wage) * 100 : null;
    parts.push(t(lang, diff === null ? "places.wage_statcan" : Math.abs(diff) < 0.05 ? "places.wage_statcan_same" : diff > 0 ? "places.wage_statcan_above" : "places.wage_statcan_below", {
      wage: money(sc.wage, false, lang), area: areaLabel(lang, sc), period: periodLabel(sc.wage_quarter ?? "", lang),
      pct: diff === null ? "" : pct(Math.abs(diff), lang),
    }));
  }
  if (sc?.vacancies !== undefined) {
    const before = sc.vacancies_year_before;
    parts.push(t(lang, before === undefined ? "places.vacancies" : "places.vacancies_year", {
      n: fmtInt(sc.vacancies, lang), area: areaLabel(lang, sc), period: periodLabel(sc.vac_quarter ?? "", lang),
      before: before === undefined ? "" : fmtInt(before, lang),
    }));
  }
  return parts.length ? parts.join(" ") : null;
}

// -- shared sections -----------------------------------------------------------------

// Approved positions as bars (newest last) and every figure in a table; a long
// history shows the newest rows open and the rest collapsed.
export const QuarterSection = ({ lang, quarters, open = 12 }: { lang: Lang; quarters: Quarter[]; open?: number }) => {
  const n = (v: number) => fmtInt(v, lang);
  const recent = quarters.slice(-open);
  const max = Math.max(1, ...recent.map((q) => q[2]));
  const rows = [...quarters].reverse();
  const head = (
    <thead>
      <tr>
        <th>{t(lang, "places.col_quarter")}</th>
        <th class="num">{t(lang, "places.col_approved")}</th>
        <th class="num">{t(lang, "places.col_approved_positions")}</th>
        <th class="num">{t(lang, "places.col_refused")}</th>
        <th class="num">{t(lang, "places.col_refused_positions")}</th>
      </tr>
    </thead>
  );
  const line = (q: Quarter) => (
    <tr>
      <td class="mono">{periodLabel(q[0], lang)}</td>
      <td class="mono num">{n(q[1])}</td>
      <td class="mono num">{n(q[2])}</td>
      <td class="mono num">{n(q[3])}</td>
      <td class="mono num">{n(q[4])}</td>
    </tr>
  );
  return (
    <section>
      <h2>{t(lang, "places.by_quarter")}</h2>
      <p class="muted small">{t(lang, "places.bars_caption", { n: recent.length })}</p>
      <div class="bars" aria-hidden="true">
        {recent.map((q) => (
          <div class="bar-row">
            <span class="bar-label mono">{periodLabel(q[0], lang)}</span>
            <span class="bar-track"><span class="bar-fill" style={`width:${q[2] ? Math.max(1, Math.round((q[2] / max) * 100)) : 0}%`}></span></span>
            <span class="mono bar-value">{n(q[2])}</span>
          </div>
        ))}
      </div>
      <div class="table-wrap bordered top-gap">
        <table>
          {head}
          <tbody>{rows.slice(0, open).map(line)}</tbody>
        </table>
      </div>
      {rows.length > open ? (
        <details class="top-gap">
          <summary>{t(lang, "places.older_quarters", { n: rows.length - open })}</summary>
          <div class="table-wrap bordered">
            <table>
              {head}
              <tbody>{rows.slice(open).map(line)}</tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  );
};

export const StreamSection = ({ lang, streams, periods }: { lang: Lang; streams: [string | null, number, number][]; periods: string[] }) => {
  const total = streams.reduce((s, r) => s + r[2], 0);
  const max = Math.max(1, ...streams.map((r) => r[2]));
  const span = periods.length ? t(lang, "places.span", { from: periodLabel(periods[0], lang), to: periodLabel(periods[periods.length - 1], lang) }) : "";
  return (
    <section>
      <h2>{t(lang, "places.streams")}</h2>
      <p class="muted small">{t(lang, "places.streams_note", { span })}</p>
      {streams.length === 0 ? <p class="muted">{t(lang, "places.streams_none")}</p> : (
        <div class="bars">
          {streams.map(([k, rows, positions]) => (
            <div class="bar-row">
              <span class="bar-label">{k ? streamLabel(lang, k) : t(lang, "places.stream_unstated")}</span>
              <span class="bar-track"><span class="bar-fill" style={`width:${Math.max(1, Math.round((positions / max) * 100))}%`}></span></span>
              <span class="mono bar-value" title={tn(lang, "places.records_one", "places.records_many", rows, { n: fmtInt(rows, lang) })}>
                {t(lang, "places.pct", { pct: total ? pct((positions / total) * 100, lang) : "0" })}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};

// The two reference cells, shared with the occupation pages' table of what
// postings offered so both tables state the references the same way: the
// Job Bank median in the unit Job Bank uses for the occupation, Statistics
// Canada's figure hourly, each marked when it is not the area's own.
export function jobBankCell(lang: Lang, jb: JobBankRef | null) {
  return (
    <td data-label={t(lang, "places.col_jobbank")} class="mono">
      <span>{jb ? <>{money(jb.median, jb.annual === 1, lang)}{jb.level !== "region" ? <span class="muted"> ({t(lang, jb.level === "province" ? "places.level_province" : "places.level_canada")})</span> : null}</> : t(lang, "common.na")}</span>
    </td>
  );
}

export function statcanCell(lang: Lang, sc: StatcanRef | null) {
  return (
    <td data-label={t(lang, "places.col_statcan_wage")} class="mono">
      <span>{sc?.wage !== undefined ? <>{money(sc.wage, false, lang)}{quality(lang, sc.wage_quality)}{sc.level !== "region" ? <span class="muted"> ({t(lang, sc.level === "province" ? "places.level_province" : "places.level_canada")})</span> : null}</> : t(lang, "common.na")}</span>
    </td>
  );
}

export function wageCells(lang: Lang, row: WageRow) {
  const jb = row.jobbank;
  const sc = row.statcan;
  const annual = jb?.annual === 1;
  const posted = annual ? row.posted.annual : row.posted.hourly;
  const count = annual ? row.posted.annual_n : row.posted.hourly_n;
  return [
    <td data-label={t(lang, "places.col_posted")} class="mono">
      <span>{posted !== null && count ? <>{money(posted, annual, lang)} <span class="muted">({fmtInt(count, lang)})</span></> : t(lang, "common.na")}</span>
    </td>,
    jobBankCell(lang, jb),
    statcanCell(lang, sc),
    <td data-label={t(lang, "places.col_vacancies")} class="mono num">
      <span>{sc?.vacancies !== undefined ? <>{fmtInt(sc.vacancies, lang)}{quality(lang, sc.vac_quality)}</> : t(lang, "common.na")}</span>
    </td>,
  ];
}

export const WageHead = ({ lang }: { lang: Lang }) => (
  <>
    <th>{t(lang, "places.col_posted")}</th>
    <th>{t(lang, "places.col_jobbank")}</th>
    <th>{t(lang, "places.col_statcan_wage")}</th>
    <th class="num">{t(lang, "places.col_vacancies")}</th>
  </>
);

export const WageNote = ({ lang, wageTable, statcanLatest }: { lang: Lang; wageTable: PlaceFile["wage_table"]; statcanLatest: string | null }) => (
  <p class="muted small">
    {t(lang, "places.wage_note", {
      table: wageTable?.revision ?? t(lang, "common.na"),
      quarter: statcanLatest ? periodLabel(statcanLatest, lang) : t(lang, "common.na"),
    })}
  </p>
);

export const EmployerSection = ({ lang, employers, showOccupation }: { lang: Lang; employers: Recent[]; showOccupation: boolean }) => (
  <section>
    <h2>{t(lang, "places.employers")}</h2>
    <p class="muted small">{t(lang, "places.employers_note")}</p>
    <div class="table-wrap bordered">
      <table class="restack">
        <thead>
          <tr>
            <th>{t(lang, "col.employer")}</th>
            <th>{t(lang, "col.location")}</th>
            {showOccupation ? <th>{t(lang, "places.col_occupation")}</th> : null}
            <th>{t(lang, "places.col_latest")}</th>
            <th>{t(lang, "col.status")}</th>
            <th class="num">{t(lang, "col.positions")}</th>
          </tr>
        </thead>
        <tbody>
          {employers.length === 0 ? <tr><td colspan={showOccupation ? 6 : 5} class="muted">{t(lang, "common.no_records")}</td></tr> : employers.map((e) => (
            <tr>
              <td data-label={t(lang, "col.employer")}><a href={`/employers/${e.id}`}>{e.name}</a></td>
              <td data-label={t(lang, "col.location")}>{[e.city, e.prov].filter(Boolean).join(", ")}</td>
              {showOccupation ? <td data-label={t(lang, "places.col_occupation")}>{e.noc ? <a href={`/occupations/${e.noc}`} class="mono">{e.noc}</a> : t(lang, "common.na")}</td> : null}
              <td data-label={t(lang, "places.col_latest")} class="mono">{e.period ? periodLabel(e.period, lang) : e.date}</td>
              <td data-label={t(lang, "col.status")}><Badge status={e.status} lang={lang} /></td>
              <td data-label={t(lang, "col.positions")} class="mono num">{e.positions === null ? t(lang, "common.see_posting") : fmtInt(e.positions, lang)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </section>
);

// A past LMIA is not a job offer: said on every page, with Job Bank's own live
// search for the occupation or place (a link only; no posting is reproduced).
export const JobSeekerNote = ({ lang, href, what }: { lang: Lang; href: string; what: string }) => (
  <section class="panel bordered">
    <h2>{t(lang, "places.seeker_h")}</h2>
    <p>{t(lang, "places.seeker_text")}</p>
    <p><a href={href} rel="noopener">{t(lang, "places.seeker_link", { what })}</a></p>
  </section>
);

export const SourcesNote = ({ lang }: { lang: Lang }) => (
  <p class="muted small top-gap">
    {tj(lang, "places.sources", {
      data: <a href="/data#licence">{t(lang, "places.sources_link")}</a>,
      method: <a href="/methodology">{t(lang, "nav.methodology")}</a>,
    })}
  </p>
);

export function jobBankSearch(lang: Lang, params: Record<string, string>): string {
  const base = lang === "fr" ? "https://www.guichetemplois.gc.ca/jobsearch/rechercheemplois" : "https://www.jobbank.gc.ca/jobsearch/jobsearch";
  return `${base}?${new URLSearchParams(params).toString()}`;
}

// Mirrors the visible trail, as the profile pages do.
export function breadcrumbJsonLd(items: { name: string; path?: string }[]): object {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((it, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: it.name,
      ...(it.path ? { item: it.path === "/" ? `${SITE_ORIGIN}/` : absoluteUrl(it.path) } : {}),
    })),
  };
}

export function sectionSeo(path: string, title: string, description: string, crumbs: { name: string; path?: string }[], noindex: boolean): Seo {
  return {
    path,
    title: pageTitle(title),
    socialTitle: title,
    description: clip(description),
    image: SOCIAL_CARD,
    jsonLd: [breadcrumbJsonLd(crumbs)],
    noindex,
  };
}

export function notFound(c: Context<AppEnv>, lang: Lang, dataAsOf: string | null, title: Key, back: string, backKey: Key): Response | Promise<Response> {
  return page(
    c,
    <Layout lang={lang} title={t(lang, title)} dataAsOf={dataAsOf}>
      <h1>{t(lang, title)}</h1>
      <p><a href={back}>{t(lang, backKey)}</a>.</p>
    </Layout>,
    404,
  );
}

// The canonical form of a place path is lower case; anything else is sent there.
function lowerRedirect(c: Context<AppEnv>, path: string): Response | null {
  const url = new URL(c.req.url);
  if (url.pathname === path) return null;
  return c.redirect(`${path}${url.search}`, 301);
}

// -- /places ----------------------------------------------------------------------

export async function placesIndex(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "places.index_title");
  // An unreadable index reads like a missing one: "not published", as the
  // release, ranking and trend indexes answer.
  const idx = await loadJson<unknown>(c.env, "places/index.json");
  if (!isPlacesIndex(idx)) return noDataPage(c, "places.index_title");
  const n = (v: number) => fmtInt(v, lang);
  const provinces = idx.provinces;
  const title = t(lang, "places.index_title");
  const seo = sectionSeo("/places", t(lang, "places.index_seo_title"), t(lang, "places.index_description"),
    [{ name: t(lang, "common.home"), path: "/" }, { name: title }], provinces.length === 0);
  return page(
    c,
    <Layout lang={lang} title={title} dataAsOf={stats.data_as_of} seo={seo}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / {title}
      </nav>
      <h1>{title}</h1>
      <p class="lead">{t(lang, "places.index_lead", { threshold: idx.threshold })}</p>
      <p><a href="/occupations">{t(lang, "places.to_occupations")}</a></p>
      {provinces.length === 0 ? <p class="muted">{t(lang, "places.not_published")}</p> : (
        <>
          <h2>{t(lang, "places.provinces")}</h2>
          <div class="table-wrap bordered">
            <table class="restack">
              <thead>
                <tr>
                  <th>{t(lang, "search.province")}</th>
                  <th class="num">{t(lang, "places.col_records")}</th>
                  <th class="num">{t(lang, "places.col_approved_positions")}</th>
                  <th class="num">{t(lang, "places.col_latest_positions", { period: periodLabel(idx.latest, lang) })}</th>
                  <th class="num">{t(lang, "places.col_city_pages")}</th>
                </tr>
              </thead>
              <tbody>
                {provinces.map((p) => (
                  <tr>
                    <td data-label={t(lang, "search.province")}><a href={`/places/${p.prov.toLowerCase()}`}>{provinceName(lang, p.prov)}</a></td>
                    <td data-label={t(lang, "places.col_records")} class="mono num">{n(p.records)}</td>
                    <td data-label={t(lang, "places.col_approved_positions")} class="mono num">{n(p.positions)}</td>
                    <td data-label={t(lang, "places.col_latest_positions", { period: periodLabel(idx.latest, lang) })} class="mono num">{n(p.latest_positions)}</td>
                    <td data-label={t(lang, "places.col_city_pages")} class="mono num">{n(p.cities)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>{t(lang, "places.cmas")}</h2>
          <p class="muted small">{t(lang, "places.cmas_note")}</p>
          <ul class="quick-links">
            {provinces.flatMap((p) => p.cmas.map((m) => (
              <li><a href={`/places/${p.prov.toLowerCase()}/${m.slug}`}>{placeName(lang, m.name)}</a> <span class="muted mono">{n(m.records)}</span></li>
            )))}
          </ul>
          <h2>{t(lang, "places.cities")}</h2>
          <p class="muted small">{t(lang, "places.cities_note", { threshold: idx.threshold })}</p>
          {provinces.filter((p) => p.top_cities.length).map((p) => (
            <>
              <h3>{provinceName(lang, p.prov)}</h3>
              <ul class="quick-links">
                {p.top_cities.map((city) => (
                  <li><a href={`/places/${p.prov.toLowerCase()}/${city.slug}`}>{city.name}</a> <span class="muted mono">{n(city.records)}</span></li>
                ))}
              </ul>
              {p.cities > p.top_cities.length ? (
                <p class="small"><a href={`/places/${p.prov.toLowerCase()}#cities`}>{t(lang, "places.all_cities", { n: n(p.cities), province: provinceName(lang, p.prov) })}</a></p>
              ) : null}
            </>
          ))}
        </>
      )}
      <SourcesNote lang={lang} />
    </Layout>,
  );
}

// -- /places/<pp> and /places/<pp>/<slug> ------------------------------------------

export async function provincePage(c: Context<AppEnv>): Promise<Response> {
  const raw = c.req.param("prov") ?? "";
  if (!/^[A-Za-z]{2}$/.test(raw)) return c.notFound();
  const redirect = lowerRedirect(c, `/places/${raw.toLowerCase()}`);
  if (redirect) return redirect;
  return renderPlace(c, `places/${raw.toLowerCase()}.json`);
}

export async function placePage(c: Context<AppEnv>): Promise<Response> {
  const raw = c.req.param("prov") ?? "";
  const slug = c.req.param("slug") ?? "";
  if (!/^[A-Za-z]{2}$/.test(raw) || slug.length > 90 || !/^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/.test(slug)) return c.notFound();
  const redirect = lowerRedirect(c, `/places/${raw.toLowerCase()}/${slug.toLowerCase()}`);
  if (redirect) return redirect;
  return renderPlace(c, `places/${raw.toLowerCase()}/${slug.toLowerCase()}.json`);
}

async function renderPlace(c: Context<AppEnv>, file: string): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "places.index_title");
  const p = await loadJson<unknown>(c.env, file);
  if (!isPlaceFile(p)) return notFound(c, lang, stats.data_as_of, "places.not_found", "/places", "places.back_index");
  const n = (v: number) => fmtInt(v, lang);
  const provName = provinceName(lang, p.prov);
  const name = p.kind === "province" ? provName : placeName(lang, p.name);
  const heading = p.kind === "province" ? name : p.kind === "cma" ? t(lang, "places.cma_heading", { name }) : `${name}, ${p.prov}`;
  const where = p.kind === "province" ? name : `${name}, ${provName}`;
  const path = p.kind === "province" ? `/places/${p.slug}` : `/places/${p.prov.toLowerCase()}/${p.slug}`;
  const indexed = p.totals.records >= p.threshold;
  const crumbs = [
    { name: t(lang, "common.home"), path: "/" },
    { name: t(lang, "places.index_title"), path: "/places" },
    ...(p.kind === "province" ? [{ name: provName }] : [{ name: provName, path: `/places/${p.prov.toLowerCase()}` }, { name: heading }]),
  ];
  const description = t(lang, "places.description", {
    place: p.kind === "cma" ? heading : where, approved: n(p.totals.approved), refused: n(p.totals.refused), pending: n(p.totals.pending),
  });
  const seo = sectionSeo(path, t(lang, "places.seo_title", { place: p.kind === "cma" ? heading : where }), description, crumbs, !indexed);
  const core = p.name.split(" - ")[0].split(" / ")[0];
  const searchHref = p.kind === "province"
    ? `/search?province=${p.prov}&date=since_2023q4`
    : `/search?province=${p.prov}&q=${encodeURIComponent(core)}&date=since_2023q4`;
  const jobBank = jobBankSearch(lang, { locationstring: p.kind === "province" ? provName : `${core}, ${p.prov}` });
  const regionName = p.region ? placeName(lang, p.region.name) : null;
  const ctx = p.context;
  const top = p.occupations[0];

  const analysis = trendLines(lang, p.quarters, p.national_latest);
  if (top) analysis.push(t(lang, "places.top_occupation", { title: top.title[lang], noc: top.noc, n: n(top.records), from: periodLabel(p.occ_from ?? "", lang) }));
  if (ctx?.vacancies !== undefined) {
    analysis.push(t(lang, ctx.wage !== undefined ? "places.context_wage" : "places.context", {
      n: n(ctx.vacancies), area: areaLabel(lang, ctx), period: periodLabel(ctx.vac_quarter ?? "", lang),
      wage: ctx.wage !== undefined ? money(ctx.wage, false, lang) : "",
    }));
    if (ctx.vacancies_year_before !== undefined) {
      analysis.push(t(lang, "places.context_year", { before: n(ctx.vacancies_year_before) }));
    }
  }
  if (p.lfs) {
    analysis.push(t(lang, "places.lfs", {
      name: placeName(lang, p.kind === "cma" ? p.name : p.cma?.name ?? ""), rate: decimal(lang, p.lfs.rate.toFixed(1)), month: p.lfs.month,
    }));
    if (p.lfs.rate >= 6) analysis.push(t(lang, "places.lfs_rule"));
  }

  return page(
    c,
    <Layout lang={lang} title={heading} dataAsOf={stats.data_as_of} seo={seo}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / <a href="/places">{t(lang, "places.index_title")}</a> /{" "}
        {p.kind === "province" ? provName : <><a href={`/places/${p.prov.toLowerCase()}`}>{provName}</a> / {heading}</>}
      </nav>
      <h1>{heading}</h1>
      <p class="lead">
        {p.kind === "province" ? t(lang, "places.lead_province", { place: name })
          : p.kind === "cma" ? t(lang, "places.lead_cma", { place: name })
          : t(lang, "places.lead_city", { place: where })}
      </p>
      {p.kind === "city" && p.cma ? (
        <p>{tj(lang, "places.in_cma", { cma: <a href={`/places/${p.cma.prov.toLowerCase()}/${p.cma.slug}`}>{placeName(lang, p.cma.name)}</a> })}</p>
      ) : null}
      {!indexed ? <p class="muted small">{t(lang, "places.thin", { n: n(p.totals.records), threshold: p.threshold })}</p> : null}

      <section class="cards">
        <div class="card">
          <h2>{t(lang, "places.summary")}</h2>
          <dl>
            <dt>{t(lang, "places.sum_records")}</dt><dd class="mono">{n(p.totals.records)}</dd>
            <dt>{t(lang, "places.col_approved")}</dt><dd class="mono">{n(p.totals.approved)} <span class="muted">{tn(lang, "employer.positions_paren_one", "employer.positions_paren_many", p.totals.positions, { n: n(p.totals.positions) })}</span></dd>
            <dt>{t(lang, "places.col_refused")}</dt><dd class="mono">{n(p.totals.refused)} <span class="muted">{tn(lang, "employer.positions_paren_one", "employer.positions_paren_many", p.totals.refused_positions, { n: n(p.totals.refused_positions) })}</span></dd>
            <dt>{t(lang, "employer.pending_postings")}</dt><dd class="mono">{n(p.totals.pending)}</dd>
            <dt>{t(lang, "places.sum_employers")}</dt><dd class="mono">{n(p.totals.employers)}</dd>
          </dl>
        </div>
        <div class="card">
          <h2>{t(lang, "places.reading")}</h2>
          {analysis.length ? analysis.map((line) => <p class="small">{line}</p>) : <p class="muted small">{t(lang, "places.reading_none")}</p>}
        </div>
      </section>

      <QuarterSection lang={lang} quarters={p.quarters} />
      <StreamSection lang={lang} streams={p.streams} periods={p.stream_periods} />

      <section>
        <h2>{t(lang, "places.occupations")}</h2>
        <p class="muted small">
          {t(lang, "places.occupations_note", {
            from: periodLabel(p.occ_from ?? "", lang),
            area: regionName ? t(lang, "places.region_of", { name: regionName }) : provName,
          })}
        </p>
        <div class="table-wrap bordered">
          <table class="restack">
            <thead>
              <tr>
                <th>{t(lang, "places.col_occupation")}</th>
                <th class="num">{t(lang, "places.col_records")}</th>
                <th class="num">{t(lang, "places.col_approved_positions")}</th>
                <WageHead lang={lang} />
              </tr>
            </thead>
            <tbody>
              {p.occupations.length === 0 ? <tr><td colspan={7} class="muted">{t(lang, "places.occupations_none")}</td></tr> : p.occupations.map((o) => (
                <tr>
                  <td data-label={t(lang, "places.col_occupation")}><span><a href={`/occupations/${o.noc}`}>{o.title[lang]}</a> <span class="mono muted">{o.noc}</span></span></td>
                  <td data-label={t(lang, "places.col_records")} class="mono num">{n(o.records)}</td>
                  <td data-label={t(lang, "places.col_approved_positions")} class="mono num">{n(o.positions)}</td>
                  {wageCells(lang, o)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <WageNote lang={lang} wageTable={p.wage_table} statcanLatest={p.statcan_latest} />
      </section>

      <EmployerSection lang={lang} employers={p.employers} showOccupation={true} />

      {p.kind === "province" && (p.cmas?.length || p.cities?.length) ? (
        <section id="cities">
          {p.cmas?.length ? (
            <>
              <h2>{t(lang, "places.cmas")}</h2>
              <ul class="quick-links">
                {p.cmas.map((m) => <li><a href={`/places/${p.slug}/${m.slug}`}>{placeName(lang, m.name)}</a> <span class="muted mono">{n(m.records)}</span></li>)}
              </ul>
            </>
          ) : null}
          {p.cities?.length ? (
            <>
              <h2>{t(lang, "places.cities")}</h2>
              <p class="muted small">{t(lang, "places.cities_note", { threshold: p.threshold })}</p>
              <ul class="quick-links">
                {p.cities.map((m) => <li><a href={`/places/${p.slug}/${m.slug}`}>{m.name}</a> <span class="muted mono">{n(m.records)}</span></li>)}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}

      <p class="top-gap"><a href={searchHref} class="btn">{t(lang, p.kind === "cma" ? "places.search_core" : "places.search", { place: p.kind === "cma" ? core : where })}</a></p>
      <JobSeekerNote lang={lang} href={jobBank} what={p.kind === "province" ? provName : p.kind === "cma" ? core : name} />
      <SourcesNote lang={lang} />
    </Layout>,
  );
}
