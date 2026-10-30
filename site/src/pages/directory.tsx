// The employer directory: for each province and territory, an A to Z list of
// every employer with a profile there, 200 to a page, at /places/<pp>/employers
// (page 1) and /places/<pp>/employers/<n>; /places/other/employers lists the
// employers with a head office outside Canada or no province. A profile's
// other inbound links are its sitemap entry and the related lists of a few
// other profiles, so this is the link every profile can count on.
//
// A page reads two small files the nightly export writes
// (pipeline/lmia_pipeline/directory.py): the directory's index (counts, each
// page's first and last name, the page on which each initial starts) and the
// page's own rows. directory/index.json sums every directory for the links on
// the place pages.

import type { Context } from "hono";
import { EMPLOYER_ID_RE, loadJson, loadStats } from "../data";
import { DIRECTORY_CODES, OTHER, directoryPath } from "../crosslinks";
import type { AppEnv } from "../env";
import { fmtInt, provinceName, t, type Lang } from "../i18n";
import { Layout, noDataPage, page } from "../layout";
import { canonicalUrl } from "../seo";
import { isListOf, isNum, isObj, isStr, isStrOrNull, optional } from "../valid";
import { lowerRedirect, notFound, sectionSeo, tuple } from "./places";

// -- files --------------------------------------------------------------------------

export interface DirectoryRow { id: string; name: string; city: string | null; records: number; prov?: string | null }

interface DirectoryIndex {
  code: string; employers: number; pages: number; page_size: number;
  ranges: [string, string][]; letters: [string, number][]; updated: string | null;
}

const isCount = (v: unknown): v is number => isNum(v) && Number.isInteger(v) && v >= 0;

// A row is rendered as a link to the profile, so its id must be an employer id.
const isRow = (v: unknown): v is DirectoryRow => isObj(v) && isStr(v.id) && EMPLOYER_ID_RE.test(v.id) && isStr(v.name) &&
  isStrOrNull(v.city) && isCount(v.records) && optional(v.prov, isStrOrNull);

function isIndex(v: unknown, code: string): v is DirectoryIndex {
  if (!isObj(v) || v.code !== code || !isCount(v.employers) || !isCount(v.pages) || !isCount(v.page_size) || !isStrOrNull(v.updated)) return false;
  const pages = v.pages;
  return isListOf(v.ranges, (r) => tuple(r, isStr, isStr)) && v.ranges.length === pages &&
    isListOf(v.letters, (l) => tuple(l, isStr, (n) => isCount(n) && n >= 1 && n <= pages));
}

const isPage = (v: unknown, code: string, n: number): v is { rows: DirectoryRow[] } =>
  isObj(v) && v.code === code && v.page === n && isListOf(v.rows, isRow) && v.rows.length > 0;

// -- the page -------------------------------------------------------------------------

function where(lang: Lang, code: string): string {
  return code === OTHER ? t(lang, "directory.other_name") : provinceName(lang, code.toUpperCase());
}

export function directoryHeading(lang: Lang, code: string): string {
  return code === OTHER ? t(lang, "directory.heading_other") : t(lang, "directory.heading", { province: where(lang, code) });
}

function rowPlace(lang: Lang, code: string, row: DirectoryRow): string {
  if (code !== OTHER) return row.city ?? "";
  const prov = row.prov === "XX" ? provinceName(lang, "XX") : t(lang, "directory.no_province");
  return [row.city, prov].filter(Boolean).join(", ");
}

export async function directoryPage(c: Context<AppEnv>): Promise<Response> {
  const raw = c.req.param("prov") ?? "";
  const rawPage = c.req.param("page");
  const code = raw.toLowerCase();
  if (!DIRECTORY_CODES.includes(code)) return c.notFound();
  if (rawPage !== undefined && !/^[0-9]{1,6}$/.test(rawPage)) return c.notFound();
  const n = rawPage === undefined ? 1 : Number(rawPage);
  if (n < 1) return c.notFound();
  // Lower case, no leading zeros, and page 1 without its number.
  const redirect = lowerRedirect(c, directoryPath(code, n));
  if (redirect) return redirect;

  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "directory.crumb");
  const idx = await loadJson<unknown>(c.env, `directory/${code}/index.json`);
  if (!isIndex(idx, code)) return noDataPage(c, "directory.crumb");
  const fmt = (v: number) => fmtInt(v, lang);
  const heading = directoryHeading(lang, code);
  const placeName = where(lang, code);
  const provHref = code === OTHER ? null : `/places/${code}`;
  const places = t(lang, "places.index_title");
  const lead = code === OTHER
    ? t(lang, "directory.lead_other", { n: fmt(idx.employers), size: fmt(idx.page_size) })
    : t(lang, "directory.lead", { province: placeName, n: fmt(idx.employers), size: fmt(idx.page_size) });

  // A province with no employer yet: the page says so and stays out of the index.
  if (idx.pages === 0) {
    if (n !== 1) return notFound(c, lang, stats.data_as_of, "directory.not_found", directoryPath(code), "directory.back");
    const none = code === OTHER ? t(lang, "directory.none_other") : t(lang, "directory.none", { province: placeName });
    const crumbs = [
      { name: t(lang, "common.home"), path: "/" }, { name: places, path: "/places" },
      ...(provHref ? [{ name: placeName, path: provHref }] : []), { name: t(lang, "directory.crumb") },
    ];
    return page(
      c,
      <Layout lang={lang} title={heading} dataAsOf={stats.data_as_of} seo={sectionSeo(directoryPath(code), heading, none, crumbs, true)}>
        <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
          <a href="/">{t(lang, "common.home")}</a> / <a href="/places">{places}</a> /{" "}
          {provHref ? <><a href={provHref}>{placeName}</a> / </> : null}{t(lang, "directory.crumb")}
        </nav>
        <h1>{heading}</h1>
        <p class="lead">{none}</p>
      </Layout>,
    );
  }
  if (n > idx.pages) return notFound(c, lang, stats.data_as_of, "directory.not_found", directoryPath(code), "directory.back");
  const file = await loadJson<unknown>(c.env, `directory/${code}/${n}.json`);
  if (!isPage(file, code, n)) return noDataPage(c, "directory.crumb");

  const rows = file.rows;
  const [first, last] = idx.ranges[n - 1];
  const title = t(lang, "directory.title", { heading, n: fmt(n), pages: fmt(idx.pages) });
  const path = directoryPath(code, n);
  const description = code === OTHER
    ? t(lang, "directory.description_other", { n: fmt(n), pages: fmt(idx.pages), first, last })
    : t(lang, "directory.description", { province: placeName, n: fmt(n), pages: fmt(idx.pages), first, last });
  const crumbs = [
    { name: t(lang, "common.home"), path: "/" },
    { name: places, path: "/places" },
    ...(provHref ? [{ name: placeName, path: provHref }] : []),
    ...(n === 1 ? [{ name: t(lang, "directory.crumb") }] : [{ name: t(lang, "directory.crumb"), path: directoryPath(code) }, { name: t(lang, "search.page", { page: fmt(n) }) }]),
  ];
  const prev = n > 1 ? directoryPath(code, n - 1) : null;
  const next = n < idx.pages ? directoryPath(code, n + 1) : null;
  // The neighbouring pages in the head as well as in the pager, each in the
  // page's own language, as the canonical URL is.
  const head = (
    <>
      {prev ? <link rel="prev" href={canonicalUrl(prev, lang)} /> : null}
      {next ? <link rel="next" href={canonicalUrl(next, lang)} /> : null}
    </>
  );
  const cityHead = code === OTHER ? t(lang, "col.location") : t(lang, "employer.city");

  return page(
    c,
    <Layout lang={lang} title={title} dataAsOf={stats.data_as_of} seo={sectionSeo(path, title, description, crumbs, false)} head={head}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / <a href="/places">{places}</a> /{" "}
        {provHref ? <><a href={provHref}>{placeName}</a> / </> : null}
        {n === 1 ? t(lang, "directory.crumb") : <><a href={directoryPath(code)}>{t(lang, "directory.crumb")}</a> / {t(lang, "search.page", { page: fmt(n) })}</>}
      </nav>
      <h1>{title}</h1>
      <p class="lead">{lead}</p>
      <p class="muted small">{t(lang, "directory.records_note")}</p>
      <nav aria-label={t(lang, "directory.letters")}>
        <ul class="quick-links">
          {idx.letters.map(([letter, at]) => (
            <li><a href={directoryPath(code, at)} aria-current={at === n ? "page" : undefined}>{letter}</a></li>
          ))}
        </ul>
      </nav>
      <p class="small top-gap">{t(lang, "directory.range", { first, last })}</p>
      <div class="table-wrap bordered">
        <table class="restack">
          <thead>
            <tr>
              <th>{t(lang, "col.employer")}</th>
              <th>{cityHead}</th>
              <th class="num">{t(lang, "places.col_records")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr>
                <td data-label={t(lang, "col.employer")}><a href={`/employers/${r.id}`}>{r.name}</a></td>
                <td data-label={cityHead}>{rowPlace(lang, code, r) || <span class="muted">{t(lang, "common.na")}</span>}</td>
                <td data-label={t(lang, "places.col_records")} class="mono num">{fmt(r.records)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav aria-label={t(lang, "search.pagination")} class="pagination">
        <span class="muted">{t(lang, "search.page_of", { page: fmt(n), pages: fmt(idx.pages) })}</span>
        <span class="pages">
          {prev ? <a href={prev} class="btn" rel="prev">{t(lang, "search.prev")}</a> : null}
          {next ? <a href={next} class="btn" rel="next">{t(lang, "search.next")}</a> : null}
        </span>
      </nav>
      {idx.pages > 1 ? (
        <nav aria-label={t(lang, "directory.pages")}>
          <h2>{t(lang, "directory.pages")}</h2>
          <ul class="quick-links">
            {idx.ranges.map(([from, to], i) => (
              <li>
                {i + 1 === n
                  ? <span class="mono" aria-current="page">{fmt(i + 1)}</span>
                  : <a href={directoryPath(code, i + 1)} class="mono" title={`${from} … ${to}`}>{fmt(i + 1)}</a>}
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </Layout>,
  );
}
