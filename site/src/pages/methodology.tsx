import type { Context } from "hono";
import type { FC } from "hono/jsx";
import { HowToCite } from "../cite";
import { loadStats } from "../data";
import type { AppEnv } from "../env";
import { indicatorLabel, t, tj, type Key, type Lang } from "../i18n";
import { Badge, Layout, page } from "../layout";
import { pageSeo } from "../seo";
import { isListOf, isObj, isNum, isStrOrNull } from "../valid";
import { blockedText, isRegister, programName, registerPlace, snapshotRows, snapshotSentence, type RegisterRow } from "./international";

// The high-wage list in use, as stats.json states it; anything else reads as absent.
type ListVersion = { read_on: string | null; page_modified: string | null; count: number };
function listVersion(v: unknown): ListVersion | null {
  return isObj(v) && isStrOrNull(v.read_on) && isStrOrNull(v.page_modified) && isNum(v.count) && v.read_on
    ? (v as ListVersion)
    : null;
}

// IRCC's pages on the November 3, 2026 change, in each language. The
// announcement is also the temporary notice bar's link (NOTICE_EE_URL in
// i18n.ts); kept here on its own so the section outlives the bar.
export const EE_LINKS: Record<"announcement" | "joboffer" | "list", Record<Lang, string>> = {
  announcement: {
    en: "https://www.canada.ca/en/immigration-refugees-citizenship/news/2026/10/canada-refocusing-express-entry-on-top-talent-that-drives-economic-growth.html",
    fr: "https://www.canada.ca/fr/immigration-refugies-citoyennete/nouvelles/2026/10/le-canada-reoriente-le-systeme-entree-express-vers-les-travailleurs-qualifies-qui-stimulent-leconomie.html",
  },
  joboffer: {
    en: "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/job-offer.html",
    fr: "https://www.canada.ca/fr/immigration-refugies-citoyennete/services/immigrer-canada/entree-express/documents/offre-emploi.html",
  },
  list: {
    en: "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/high-wage.html",
    fr: "https://www.canada.ca/fr/immigration-refugies-citoyennete/services/immigrer-canada/entree-express/verifier-note/salaire-eleve.html",
  },
};

const EE_GRADES: Key[] = ["methodology.ee_grade_a", "methodology.ee_grade_b", "methodology.ee_grade_c", "methodology.ee_grade_none"];
const EE_LIMITS: Key[] = [
  "methodology.ee_limit_advertise", "methodology.ee_limit_staff", "methodology.ee_limit_floor", "methodology.ee_limit_facet",
  "methodology.ee_limit_boards", "methodology.ee_limit_signal",
];

// A list whose site blocks automated readers, as a line of the limits.
function blockedLimit(lang: Lang, r: RegisterRow): string {
  const state = blockedText(lang, r);
  return t(lang, "methodology.ee_limit_blocked", {
    program: programName(lang, r.program), where: registerPlace(lang, r), state: state.charAt(0).toLowerCase() + state.slice(1),
  });
}

// The highlighted block at the top of the page (anchor express-entry), which
// the notice bar and the international-candidates page link to. The lists'
// states (stats.json) add the lists loaded by hand to the lists paragraph and
// the lists whose sites block automated readers to the limits.
export const ExpressEntryBlock: FC<{ lang: Lang; version?: ListVersion | null; registers?: RegisterRow[] }> = (
  { lang, version, registers = [] },
) => (
  <section class="ee-block" id="express-entry" aria-labelledby="express-entry-h">
    <h2 id="express-entry-h">{t(lang, "methodology.ee_h")}</h2>
    <p>
      {tj(lang, "methodology.ee_intro", {
        announcement: <a href={EE_LINKS.announcement[lang]} rel="noopener">{t(lang, "methodology.ee_announced")}</a>,
        list: <a href={EE_LINKS.list[lang]} rel="noopener">{t(lang, "intl.list_link")}</a>,
        rules: <a href={EE_LINKS.joboffer[lang]} rel="noopener">{t(lang, "methodology.ee_rules")}</a>,
      })}
    </p>
    <h3>{t(lang, "methodology.ee_records_h")}</h3>
    <p>{t(lang, "methodology.ee_records")}</p>
    <h3>{t(lang, "methodology.ee_grades_h")}</h3>
    <p>{t(lang, "methodology.ee_grades_intro")}</p>
    <ul>{EE_GRADES.map((k) => <li>{t(lang, k)}</li>)}</ul>
    <p>{t(lang, "methodology.ee_grade_notes")}</p>
    {version ? (
      <p>
        {t(lang, "methodology.ee_list", {
          read: version.read_on ?? "", modified: version.page_modified ?? t(lang, "common.na"), count: version.count,
        })}
      </p>
    ) : null}
    <h3>{t(lang, "methodology.ee_registers_h")}</h3>
    <p>{tj(lang, "methodology.ee_registers", { data: <a href="/data#registers">{t(lang, "places.sources_link")}</a> })}</p>
    {snapshotRows(registers).map((r) => <p>{snapshotSentence(lang, r)} {t(lang, "intl.reg_snapshot_check")}</p>)}
    <h3>{t(lang, "methodology.ee_limits_h")}</h3>
    <ul>
      {EE_LIMITS.map((k) => <li>{t(lang, k)}</li>)}
      {registers.filter((r) => r.state === "blocked").map((r) => <li>{blockedLimit(lang, r)}</li>)}
    </ul>
    <p>{tj(lang, "methodology.ee_page", { page: <a href="/international">{t(lang, "intl.crumb")}</a> })}</p>
  </section>
);

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
  // Public records shown on profiles; the matching paragraph below says how they are joined.
  ["methodology.sources.grants.source", "methodology.sources.grants.fields", "methodology.sources.grants.cadence", "methodology.sources.profiles_only"],
  ["methodology.sources.alberta.source", "methodology.sources.alberta.fields", "methodology.sources.alberta.cadence", "methodology.sources.profiles_only"],
  ["methodology.sources.fmcsa.source", "methodology.sources.fmcsa.fields", "methodology.sources.fmcsa.cadence", "methodology.sources.profiles_only"],
  // The November 3 change: postings open to international candidates, IRCC's list, the designated-employer lists.
  [
    "methodology.sources.jobbank_intl.source",
    "methodology.sources.jobbank_intl.fields",
    "methodology.sources.jobbank_intl.cadence",
    "methodology.sources.jobbank_intl.lag",
  ],
  [
    "methodology.sources.high_wage.source",
    "methodology.sources.high_wage.fields",
    "methodology.sources.high_wage.cadence",
    "methodology.sources.high_wage.lag",
  ],
  [
    "methodology.sources.registers.source",
    "methodology.sources.registers.fields",
    "methodology.sources.registers.cadence",
    "methodology.sources.profiles_only",
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
  // The lists' states, checked here as on the Data page: a list that fails leaves them out.
  const registers: RegisterRow[] = stats && isListOf(stats.registers, isRegister) ? stats.registers : [];
  return page(
    c,
    <Layout lang={lang} title={t(lang, "nav.methodology")} dataAsOf={stats?.data_as_of ?? null} active="/methodology" seo={pageSeo("methodology", lang)}>
      <div class="doc-layout">
        <nav aria-label={t(lang, "toc.label")} class="toc">
          <span class="toc-title">{t(lang, "toc.title")}</span>
          <a href="#express-entry">{t(lang, "methodology.toc_ee")}</a>
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
          <ExpressEntryBlock lang={lang} version={listVersion(stats?.high_wage)} registers={registers} />

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
          <p id="public-records">{t(lang, "methodology.public_records_matching")}</p>

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
