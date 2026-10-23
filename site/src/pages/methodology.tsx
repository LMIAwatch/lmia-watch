import type { Context } from "hono";
import { HowToCite } from "../cite";
import { loadStats } from "../data";
import type { AppEnv } from "../env";
import { indicatorLabel, t, tj, type Key } from "../i18n";
import { Badge, Layout, page } from "../layout";
import { pageSeo } from "../seo";

// Table rows as dictionary keys, in display order.
const SOURCES: [Key, Key, Key, Key][] = [
  [
    "methodology.sources.jobbank_requested.source",
    "methodology.sources.jobbank_requested.fields",
    "methodology.sources.jobbank_requested.cadence",
    "methodology.sources.jobbank_requested.lag",
  ],
  [
    "methodology.sources.jobbank_approved.source",
    "methodology.sources.same_fields",
    "methodology.sources.nightly",
    "methodology.sources.jobbank_approved.lag",
  ],
  [
    "methodology.sources.esdc_positive.source",
    "methodology.sources.esdc_positive.fields",
    "methodology.sources.esdc_positive.cadence",
    "methodology.sources.esdc_positive.lag",
  ],
  [
    "methodology.sources.esdc_negative.source",
    "methodology.sources.esdc_negative.fields",
    "methodology.sources.esdc_negative.cadence",
    "methodology.sources.esdc_negative.lag",
  ],
  ["methodology.sources.ircc.source", "methodology.sources.ircc.fields", "methodology.sources.ircc.cadence", "methodology.sources.ircc.lag"],
  [
    "methodology.sources.registry.source",
    "methodology.sources.registry.fields",
    "methodology.sources.registry.cadence",
    "methodology.sources.none",
  ],
  ["methodology.sources.wages.source", "methodology.sources.wages.fields", "methodology.sources.wages.cadence", "methodology.sources.wages.lag"],
  ["methodology.sources.lfs.source", "methodology.sources.lfs.fields", "methodology.sources.lfs.cadence", "methodology.sources.lfs.lag"],
  [
    "methodology.sources.boundaries.source",
    "methodology.sources.boundaries.fields",
    "methodology.sources.boundaries.cadence",
    "methodology.sources.none",
  ],
  [
    "methodology.sources.program.source",
    "methodology.sources.program.fields",
    "methodology.sources.program.cadence",
    "methodology.sources.program.lag",
  ],
];

const STATUS_ROWS: [string, Key, Key][] = [
  ["pending", "methodology.status.pending.assigned", "methodology.status.pending.ends"],
  ["approved", "methodology.status.approved.assigned", "methodology.status.approved.ends"],
  ["refused", "methodology.status.refused.assigned", "methodology.status.never"],
  ["lapsed", "methodology.status.lapsed.assigned", "methodology.status.lapsed.ends"],
  ["finding", "methodology.status.finding.assigned", "methodology.status.finding.ends"],
];

const INDICATOR_ROWS: [string, Key, Key, Key][] = [
  ["newly_incorporated", "methodology.ind.newly_incorporated.rule", "methodology.ind.newly_incorporated.data", "methodology.ind.newly_incorporated.fp"],
  ["repeat_applicant", "methodology.ind.repeat_applicant.rule", "methodology.ind.positive_lists", "methodology.ind.repeat_applicant.fp"],
  ["wage_at_floor", "methodology.ind.wage_at_floor.rule", "methodology.ind.wage_at_floor.data", "methodology.ind.wage_at_floor.fp"],
  [
    "low_wage_high_unemployment",
    "methodology.ind.low_wage_high_unemployment.rule",
    "methodology.ind.low_wage_high_unemployment.data",
    "methodology.ind.low_wage_high_unemployment.fp",
  ],
  ["high_volume", "methodology.ind.high_volume.rule", "methodology.ind.positive_lists", "methodology.ind.high_volume.fp"],
  [
    "refused_then_reposted",
    "methodology.ind.refused_then_reposted.rule",
    "methodology.ind.refused_then_reposted.data",
    "methodology.ind.refused_then_reposted.fp",
  ],
];

const GRADE_ROWS: [Key, Key, Key][] = [
  ["methodology.grade.exact", "methodology.grade.exact.condition", "methodology.grade.exact.shown"],
  ["methodology.grade.probable", "methodology.grade.probable.condition", "methodology.grade.probable.shown"],
  ["methodology.grade.possible", "methodology.grade.possible.condition", "methodology.grade.possible.shown"],
  ["methodology.grade.unmatched", "methodology.grade.unmatched.condition", "methodology.grade.unmatched.shown"],
];

export async function methodologyPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  const rules = stats?.rules_version ?? "0.1";
  return page(
    c,
    <Layout lang={lang} title={t(lang, "nav.methodology")} dataAsOf={stats?.data_as_of ?? null} active="/methodology" seo={pageSeo("methodology", lang)}>
      <div class="doc-layout">
        <nav aria-label={t(lang, "toc.label")} class="toc">
          <span class="toc-title">{t(lang, "toc.title")}</span>
          <a href="#sources">{t(lang, "methodology.toc_sources")}</a>
          <a href="#status">{t(lang, "methodology.toc_status")}</a>
          <a href="#indicators">{t(lang, "col.indicators")}</a>
          <a href="#matching">{t(lang, "methodology.toc_matching")}</a>
          <a href="#exclusions">{t(lang, "methodology.toc_exclusions")}</a>
          <a href="#limits">{t(lang, "methodology.toc_limits")}</a>
          <a href="#versions">{t(lang, "methodology.toc_versions")}</a>
        </nav>
        <div class="doc">
          <h1>{t(lang, "nav.methodology")}</h1>
          <p class="lead">{t(lang, "methodology.lead")}</p>

          <h2 id="sources">{t(lang, "methodology.toc_sources")}</h2>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "col.source")}</th>
                  <th>{t(lang, "methodology.col_fields")}</th>
                  <th>{t(lang, "methodology.col_cadence")}</th>
                  <th>{t(lang, "methodology.col_lag")}</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map((row) => (
                  <tr>{row.map((k) => <td>{t(lang, k)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 id="status">{t(lang, "methodology.toc_status")}</h2>
          <p class="muted">{t(lang, "methodology.status_note")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "col.status")}</th>
                  <th>{t(lang, "methodology.col_assigned")}</th>
                  <th>{t(lang, "methodology.col_ends")}</th>
                </tr>
              </thead>
              <tbody>
                {STATUS_ROWS.map(([status, assigned, ends]) => (
                  <tr><td><Badge status={status} lang={lang} /></td><td>{t(lang, assigned)}</td><td>{t(lang, ends)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 id="indicators">{t(lang, "col.indicators")}</h2>
          <p class="muted">{t(lang, "methodology.indicators_note")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "employer.col_indicator")}</th>
                  <th>{t(lang, "methodology.col_rule")}</th>
                  <th>{t(lang, "methodology.col_data")}</th>
                  <th>{t(lang, "methodology.col_false_positives")}</th>
                </tr>
              </thead>
              <tbody>
                {INDICATOR_ROWS.map(([id, rule, data, fp]) => (
                  <tr><td>{indicatorLabel(lang, id)}</td><td>{t(lang, rule)}</td><td>{t(lang, data)}</td><td>{t(lang, fp)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p class="muted">{t(lang, "methodology.recompute")}</p>

          <h2 id="matching">{t(lang, "methodology.matching")}</h2>
          <p>{t(lang, "methodology.matching_text")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "methodology.col_grade")}</th>
                  <th>{t(lang, "methodology.col_condition")}</th>
                  <th>{t(lang, "methodology.col_shown_as")}</th>
                </tr>
              </thead>
              <tbody>
                {GRADE_ROWS.map((row) => (
                  <tr>{row.map((k) => <td>{t(lang, k)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{t(lang, "methodology.registry_coverage")}</p>

          <h2 id="exclusions">{t(lang, "methodology.toc_exclusions")}</h2>
          <p>{t(lang, "methodology.exclusions_households")}</p>
          <p>{t(lang, "methodology.exclusions_workers")}</p>

          <h2 id="limits">{t(lang, "methodology.toc_limits")}</h2>
          <p>{t(lang, "methodology.limits_text")}</p>

          <h2 id="versions">{t(lang, "methodology.toc_versions")}</h2>
          <p>
            {tj(lang, "methodology.versions_text", {
              rules,
              data: <a href="/data#changelog">{t(lang, "methodology.data_page")}</a>,
            })}
          </p>
          <HowToCite lang={lang} citation={stats?.citation} />
        </div>
      </div>
    </Layout>,
  );
}
