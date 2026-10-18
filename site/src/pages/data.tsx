import type { Context } from "hono";
import { loadStats } from "../data";
import type { AppEnv } from "../env";
import { t, tj, type Key } from "../i18n";
import { Layout, fmtInt, noDataPage, page, periodLabel } from "../layout";
import { datasetJsonLd, pageSeo } from "../seo";

export const DOWNLOADS: { file: string; contents: Key }[] = [
  { file: "pending_observations.csv", contents: "data.file.pending_observations" },
  { file: "approved_quarterly.csv", contents: "data.file.approved_quarterly" },
  { file: "refused_quarterly.csv", contents: "data.file.refused_quarterly" },
  { file: "employers.csv", contents: "data.file.employers" },
  { file: "indicators.csv", contents: "data.file.indicators" },
  { file: "findings.csv", contents: "data.file.findings" },
  { file: "esdc_resources.csv", contents: "data.file.esdc_resources" },
];

const API_ROWS: [string, Key][] = [
  ["GET /api/stats", "data.api.stats"],
  ["GET /api/employers/{id}", "data.api.employer"],
  ["GET /api/pending?since=YYYY-MM-DD", "data.api.pending"],
  ["GET /api/clusters?scope=latest|since_2023q4", "data.api.clusters"],
  ["GET /api/area/{fsa}", "data.api.area"],
  ["GET /api/search/facets", "data.api.facets"],
  ["GET /data/search/latest/all.json, /data/search/latest/prov/{PROV}.json, /data/search/long/{PROV}/{YEAR}.json", "data.api.files"],
];

const LIST_NAME: Record<string, Key> = { positive: "data.list.positive", negative: "data.list.negative" };

export async function dataPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "nav.data");
  const na = t(lang, "common.na");
  // English shows the period code as stored (2026Q1); French shows the label.
  const latestPeriod = lang === "fr" ? periodLabel(stats.esdc_latest_period, lang) : stats.esdc_latest_period;

  return page(
    c,
    <Layout
      lang={lang}
      title={t(lang, "nav.data")}
      dataAsOf={stats.data_as_of}
      active="/data"
      seo={pageSeo("data", lang, {
        jsonLd: [datasetJsonLd(DOWNLOADS.map((d) => ({ file: d.file, contents: t(lang, d.contents) })), stats.data_as_of, lang)],
      })}
    >
      <div class="doc-layout">
        <nav aria-label={t(lang, "toc.label")} class="toc">
          <span class="toc-title">{t(lang, "toc.title")}</span>
          <a href="#downloads">{t(lang, "data.toc_downloads")}</a>
          <a href="#api">{t(lang, "data.toc_api")}</a>
          <a href="#licence">{t(lang, "data.toc_licence")}</a>
          <a href="#changelog">{t(lang, "data.toc_changelog")}</a>
          <a href="#reply">{t(lang, "data.toc_reply")}</a>
          <a href="#about">{t(lang, "data.toc_about")}</a>
        </nav>
        <div class="doc">
          <h1>{t(lang, "nav.data")}</h1>
          <p class="lead">{t(lang, "data.lead")}</p>

          <h2 id="downloads">{t(lang, "data.toc_downloads")}</h2>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "data.col_file")}</th>
                  <th>{t(lang, "data.col_contents")}</th>
                  <th>{t(lang, "data.col_updated")}</th>
                </tr>
              </thead>
              <tbody>
                {DOWNLOADS.map((d) => (
                  <tr>
                    <td><a href={`/downloads/${d.file}`} class="mono">{d.file}</a></td>
                    <td>{t(lang, d.contents)}</td>
                    <td class="mono">{stats.data_as_of ?? na}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p class="muted small">
            {tj(lang, "data.mirror", { mirror: <a href="/downloads/mirror/SHA256SUMS" class="mono">mirror/</a> })}
          </p>

          <h3>{t(lang, "data.esdc_files")}</h3>
          <div class="table-wrap bordered scroll-y">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "data.col_list")}</th>
                  <th>{t(lang, "data.col_period")}</th>
                  <th>{t(lang, "data.col_published")}</th>
                  <th class="num">{t(lang, "data.col_rows")}</th>
                  <th>{t(lang, "data.col_loaded")}</th>
                </tr>
              </thead>
              <tbody>
                {stats.resources.length === 0 ? <tr><td colspan={5} class="muted">{t(lang, "data.no_files")}</td></tr> : stats.resources.map((r) => (
                  <tr>
                    <td>{LIST_NAME[r.dataset] ? t(lang, LIST_NAME[r.dataset]) : r.dataset}</td>
                    <td class="mono">{r.period}</td>
                    <td class="mono">{r.published ?? ""}</td>
                    <td class="mono num">{fmtInt(r.rows_loaded, lang)}</td>
                    <td class="mono">{r.loaded_at.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 id="api">{t(lang, "data.toc_api")}</h2>
          <p>{t(lang, "data.api_text")}</p>
          <p class="muted small">{t(lang, "data.api_limits")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "data.col_endpoint")}</th>
                  <th>{t(lang, "data.col_returns")}</th>
                </tr>
              </thead>
              <tbody>
                {API_ROWS.map(([endpoint, returns]) => (
                  <tr><td class="mono">{endpoint}</td><td>{t(lang, returns)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 id="licence">{t(lang, "data.licence")}</h2>
          <p>{t(lang, "data.licence_text")}</p>
          <p class="muted small">{t(lang, "data.code_licence")}</p>
          <p>{t(lang, "data.crawl_text")}</p>

          <h2 id="changelog">{t(lang, "data.toc_changelog")}</h2>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "col.date")}</th>
                  <th>{t(lang, "data.col_change")}</th>
                  <th>{t(lang, "data.col_recomputed")}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="mono nw">2026-10-12</td>
                  <td>{t(lang, "data.change_drafted", { rules: stats.rules_version ?? "0.1", period: latestPeriod })}</td>
                  <td>{t(lang, "data.recomputed_all")}</td>
                </tr>
                <tr>
                  <td class="mono nw">{t(lang, "data.planned")}</td>
                  <td>{t(lang, "data.change_planned")}</td>
                  <td>{t(lang, "data.recomputed_planned")}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <h3>{t(lang, "data.runs")}</h3>
          <div class="table-wrap bordered scroll-y">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "data.col_run")}</th>
                  <th>{t(lang, "data.col_stage")}</th>
                  <th>{t(lang, "data.col_detail")}</th>
                  <th class="num">{t(lang, "data.col_new_rows")}</th>
                  <th>{t(lang, "data.col_ok")}</th>
                </tr>
              </thead>
              <tbody>
                {stats.runs.length === 0 ? <tr><td colspan={5} class="muted">{t(lang, "data.no_runs")}</td></tr> : stats.runs.map((r) => (
                  <tr>
                    <td class="mono">{r.run_at}</td>
                    <td>{r.source}</td>
                    <td class="small">{(r.detail ?? "").slice(0, 160)}</td>
                    <td class="mono num">{fmtInt(r.rows_new, lang)}</td>
                    <td>{r.ok ? t(lang, "common.yes") : t(lang, "common.no")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 id="reply">{t(lang, "data.toc_reply")}</h2>
          <div class="cards two">
            <div class="card">
              <h3>{t(lang, "data.reply")}</h3>
              <p class="muted">{t(lang, "data.reply_text")}</p>
              <p>{t(lang, "data.reply_how", { button: t(lang, "employer.respond") })}</p>
            </div>
            <div class="card">
              <h3>{t(lang, "footer.corrections")}</h3>
              <p class="muted">{t(lang, "data.corrections_text")}</p>
              <p><a href="/corrections" class="btn">{t(lang, "employer.correct")}</a></p>
            </div>
          </div>

          <h2 id="about">{t(lang, "data.toc_about")}</h2>
          <p>{t(lang, "data.about_records")}</p>
          <p>{t(lang, "data.about_enforcement")}</p>
          <p>{tj(lang, "data.about_contact", { form: <a href="/corrections">{t(lang, "data.about_form")}</a> })}</p>
        </div>
      </div>
    </Layout>,
  );
}
