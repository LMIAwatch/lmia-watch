import type { Context } from "hono";
import { type Area, esdcSource, loadJson, loadProfile, loadStats, type Profile } from "../data";
import type { AppEnv } from "../env";
import { basisText, indicatorLabel, indicatorStateLabel, streamLabel, t, tj, tn, type Key, type Lang } from "../i18n";
import { Badge, Layout, fmtInt, fmtWage, noDataPage, page, periodLabel } from "../layout";
import { sourceLabel } from "./search";
import { WATCH_MAX } from "./watchlist";
import { MiniMap } from "../minimap";
import { profileSeo } from "../seo";

const REPORT_URL = "https://www.canada.ca/en/employment-social-development/services/foreign-workers/report-abuse.html";

const ENTITY_TYPE: Record<string, Key> = {
  BC: "entity.BC", SP: "entity.SP", GP: "entity.GP", LP: "entity.LP", ULC: "entity.ULC", S: "entity.S",
  A: "entity.A", C: "entity.C", CBCA: "entity.CBCA",
  CIE: "entity.CIE", SENC: "entity.SENC", SEC: "entity.SEC", APE: "entity.APE", COP: "entity.COP",
};
const REGISTRY_NAME: Record<string, Key> = {
  bc_orgbook: "registry.bc_orgbook",
  corporations_canada: "registry.corporations_canada",
  quebec_req: "registry.quebec_req",
};
const REGISTRY_URL: Record<string, string> = {
  bc_orgbook: "https://orgbook.gov.bc.ca/",
  corporations_canada: "https://ised-isde.canada.ca/cc/lgcy/fdrlCrpSrch.html",
  quebec_req: "https://www.registreentreprises.gouv.qc.ca/",
};
// Registry status words the pipeline stores in English, shown in the page's language.
const REGISTRY_STATUS: Record<string, Key> = { ACT: "employer.active", Active: "employer.active", "Struck off": "employer.struck_off" };

const registryName = (lang: Lang, registry: string) => (REGISTRY_NAME[registry] ? t(lang, REGISTRY_NAME[registry]) : registry);

// Text that exists only in English in the source data (IRCC's list as the
// pipeline stores it, an indicator basis the dictionary does not know) is
// marked lang="en" on a French page so screen readers pronounce it right.
const enOnly = (lang: Lang) => (lang === "fr" ? "en" : undefined);

// An employer with a long history (health authorities, large consultancies)
// keeps the page quick: the newest rows render open, the rest collapsed.
const RECORDS_OPEN = 100;

const EsdcRecordRow = ({ r, lang }: { r: Profile["esdc"][number]; lang: Lang }) => (
  <tr>
    <td class="mono">{periodLabel(r.period, lang)}</td>
    <td><Badge status={r.list === "positive" ? "approved" : "refused"} lang={lang} /></td>
    <td>
      {t(lang, "employer.esdc_record", {
        stream: r.stream ? streamLabel(lang, r.stream) : "",
        lmias: r.lmias ?? t(lang, "common.na"),
        place: `${r.city ? `, ${r.city}` : ""}${r.postal_code ? ` ${r.postal_code}` : ""}`,
      })}
    </td>
    <td>{r.noc_code ?? ""} {r.noc_title ?? ""}</td>
    <td class="mono">{t(lang, "common.na")}</td>
    <td class="mono num">{fmtInt(r.positions, lang)}</td>
    <td>
      <a href={esdcSource(r.list, r.resource_id)} class="mono" rel="nofollow noopener">
        {sourceLabel(lang, { kind: "esdc", ref: r.id, status: r.list === "positive" ? "approved" : "refused", period: r.period })}
      </a>
    </td>
    <td class="mono">{r.published ?? ""}</td>
  </tr>
);

interface ResponseRow { received_at: string; statement: string; contact_name: string | null }
interface CorrectionRow { received_at: string; record_ref: string | null; request: string; resolution: string | null; resolved_at: string | null }

export function periodEnd(period: string): string {
  const m = /^(\d{4})Q(\d)(?:-Q(\d))?$/.exec(period);
  if (!m) return /^\d{4}$/.test(period) ? `${period}-12-31` : period;
  const q = Number(m[3] ?? m[2]);
  return `${m[1]}-${["03-31", "06-30", "09-30", "12-31"][q - 1]}`;
}

function gradeText(lang: Lang, grade: string): string {
  if (grade === "exact") return t(lang, "employer.grade_exact");
  if (grade === "probable") return t(lang, "employer.grade_probable");
  return t(lang, "employer.grade_possible");
}

async function siteRows(c: Context<AppEnv>, id: string): Promise<{ responses: ResponseRow[]; corrections: CorrectionRow[] }> {
  if (!c.env.DB) return { responses: [], corrections: [] };
  try {
    const [responses, corrections] = await c.env.DB.batch([
      c.env.DB.prepare("SELECT received_at, statement, contact_name FROM employer_responses WHERE employer_id = ? AND published = 1 ORDER BY received_at DESC").bind(id),
      c.env.DB.prepare("SELECT received_at, record_ref, request, resolution, resolved_at FROM corrections WHERE employer_id = ? AND published = 1 ORDER BY received_at DESC").bind(id),
    ]);
    return {
      responses: (responses.results ?? []) as unknown as ResponseRow[],
      corrections: (corrections.results ?? []) as unknown as CorrectionRow[],
    };
  } catch {
    return { responses: [], corrections: [] };
  }
}

export async function employerPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const id = c.req.param("id") ?? "";
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "employer.title");
  const profile: Profile | null = await loadProfile(c.env, id);
  if (!profile) {
    return page(
      c,
      <Layout lang={lang} title={t(lang, "employer.not_found")} dataAsOf={stats.data_as_of}>
        <h1>{t(lang, "employer.not_found")}</h1>
        <p><a href="/search">{t(lang, "employer.search_records")}</a>.</p>
      </Layout>,
      404,
    );
  }
  const { employer, postings, esdc, registry, indicators, findings, names } = profile;
  const { responses, corrections } = await siteRows(c, id);
  const best = registry[0];
  // The area file holds the postal area's centroid for the location card's map; a
  // missing file (no record in the latest scope) means no map, not an error.
  const fsa = employer.postal_code ? employer.postal_code.slice(0, 3).toUpperCase() : "";
  const area = /^[A-Z][0-9][A-Z]$/.test(fsa) ? await loadJson<Area>(c.env, `areas/${fsa}.json`).catch(() => null) : null;
  const pendingPosting = postings.find((p) => p.flag_current === "requested");
  const na = t(lang, "common.na");
  const n = (v: number | null | undefined) => fmtInt(v, lang);
  const positions = (v: number) => tn(lang, "employer.positions_paren_one", "employer.positions_paren_many", v, { n: n(v) });

  const events: { date: string; text: string; kind: string }[] = [];
  for (const r of registry) {
    if (r.registered_on) {
      events.push({
        date: r.registered_on,
        kind: "registry",
        text: t(lang, "employer.ev_registered", { name: r.legal_name ?? r.registry_id, registry: registryName(lang, r.registry) }),
      });
    }
  }
  for (const p of postings) {
    if (p.date_posted) {
      events.push({
        date: p.date_posted,
        kind: "pending",
        text: t(lang, "employer.ev_published", {
          id: p.posting_id,
          title: p.title ?? t(lang, "employer.untitled"),
          wage: p.wage_min !== null ? `, ${fmtWage(p.wage_min, p.wage_max, p.wage_unit, lang)}` : "",
        }),
      });
    }
    events.push({ date: p.first_seen.slice(0, 10), kind: "pending", text: t(lang, "employer.ev_first_seen", { id: p.posting_id }) });
    if (p.approved_seen_at) events.push({ date: p.approved_seen_at.slice(0, 10), kind: "approved", text: t(lang, "employer.ev_approved", { id: p.posting_id }) });
    if (p.valid_through) events.push({ date: p.valid_through, kind: "future", text: t(lang, "employer.ev_closes", { id: p.posting_id }) });
  }
  for (const r of esdc) {
    events.push({
      date: periodEnd(r.period),
      kind: r.list === "positive" ? "approved" : "refused",
      text: t(lang, r.list === "positive" ? "employer.ev_positive" : "employer.ev_negative", {
        period: periodLabel(r.period, lang),
        noc: `${r.noc_code ?? ""} ${r.noc_title ?? ""}`,
        positions: n(r.positions),
        published: r.published ? t(lang, "employer.ev_list_published", { date: r.published }) : "",
      }),
    });
  }
  for (const f of findings) {
    if (f.decision_date) {
      events.push({
        date: f.decision_date,
        kind: "finding",
        text: t(lang, "employer.ev_finding", { penalty: f.penalty ?? "", status: f.status ? `(${f.status})` : "" }),
      });
    }
  }
  // Newest first, so a long record opens on what happened last.
  events.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

  const statusNote =
    employer.current_status === "pending" && pendingPosting
      ? t(lang, "employer.under_review", { date: pendingPosting.last_seen.slice(0, 10) })
      : employer.status_changed_at
        ? t(lang, "employer.since", { date: employer.status_changed_at.slice(0, 10) })
        : "";
  const location = [employer.street, employer.city, employer.province, employer.postal_code].filter(Boolean).join(", ") || t(lang, "employer.no_location");
  const recordsHead = (
    <thead>
      <tr>
        <th>{t(lang, "col.date")}</th>
        <th>{t(lang, "col.status")}</th>
        <th>{t(lang, "employer.col_record")}</th>
        <th>{t(lang, "employer.col_occupation")}</th>
        <th>{t(lang, "col.wage")}</th>
        <th class="num">{t(lang, "col.positions")}</th>
        <th>{t(lang, "col.source")}</th>
        <th>{t(lang, "employer.col_pulled")}</th>
      </tr>
    </thead>
  );

  return page(
    c,
    <Layout lang={lang} title={employer.display_name} dataAsOf={stats.data_as_of} seo={profileSeo(profile, lang)}>
      <nav aria-label={t(lang, "employer.breadcrumb")} class="breadcrumb">
        <a href="/">{t(lang, "common.home")}</a> / <a href={`/search?province=${employer.province ?? ""}`}>{employer.province ?? t(lang, "employer.all_provinces")}</a> / {t(lang, "employer.title")}
      </nav>
      <section class="profile-head">
        <div>
          <h1>{employer.display_name}</h1>
          <p class="muted">{tj(lang, "employer.id_line", { location, id: <span class="mono id">{employer.id}</span> })}</p>
          <p>
            <Badge status={employer.current_status} lang={lang} />{" "}
            <span class="muted">{statusNote}</span>
          </p>
        </div>
        <div class="actions">
          {/* Shown by watchlist.js when this browser can store the list; the list never leaves the browser. */}
          <button type="button" class="btn" id="watch-toggle" data-employer={employer.id} data-max={String(WATCH_MAX)}
            data-label-off={t(lang, "watch.watch")} data-label-on={t(lang, "watch.watching")}
            data-label-full={t(lang, "watch.full", { max: WATCH_MAX })} title={t(lang, "watch.button_title")}
            aria-pressed="false" style="display:none">{t(lang, "watch.watch")}</button>
          <a href={`/employers/${employer.id}/respond`} class="btn">{t(lang, "employer.respond")}</a>
          <a href={`/corrections?employer=${employer.id}`} class="btn">{t(lang, "employer.correct")}</a>
          <a href={REPORT_URL} class="btn btn-active" rel="noopener">{t(lang, "employer.report")}</a>
        </div>
      </section>

      <section class="cards">
        <div class="card">
          <h2>{t(lang, "employer.registry")}</h2>
          {best ? (
            <dl>
              <dt>{t(lang, "employer.legal_name")}</dt><dd>{best.legal_name ?? na}</dd>
              <dt>{t(lang, "employer.number")}</dt><dd class="mono id">{best.registry_id}</dd>
              <dt>{t(lang, "employer.type")}</dt><dd>{ENTITY_TYPE[best.entity_type ?? ""] ? t(lang, ENTITY_TYPE[best.entity_type ?? ""]) : best.entity_type ?? na}</dd>
              <dt>{t(lang, "col.status")}</dt><dd>{REGISTRY_STATUS[best.status ?? ""] ? t(lang, REGISTRY_STATUS[best.status ?? ""]) : best.status ?? na}</dd>
              <dt>{t(lang, "employer.registered")}</dt><dd class="mono">{best.registered_on ?? na}</dd>
              <dt>{t(lang, "employer.match")}</dt><dd>{gradeText(lang, best.grade)}</dd>
              <dt>{t(lang, "employer.names_seen")}</dt><dd>{names.map((nm) => nm.name).join("; ")}</dd>
            </dl>
          ) : (
            <>
              <p class="muted">{t(lang, "employer.no_registry")}</p>
              {names.length ? (
                <dl>
                  <dt>{t(lang, "employer.names_seen")}</dt><dd>{names.map((nm) => nm.name).join("; ")}</dd>
                </dl>
              ) : null}
            </>
          )}
          {best ? (
            <a href={REGISTRY_URL[best.registry] ?? "#"} class="small" rel="noopener">
              {t(lang, "employer.view_on", { registry: registryName(lang, best.registry) })}
            </a>
          ) : null}
        </div>
        <div class="card">
          <h2>{t(lang, "employer.location")}</h2>
          <dl>
            <dt>{t(lang, "employer.street")}</dt><dd>{employer.street ?? t(lang, "employer.street_none")}</dd>
            <dt>{t(lang, "employer.city")}</dt><dd>{[employer.city, employer.province].filter(Boolean).join(", ") || na}</dd>
            <dt>{t(lang, "employer.postal_code")}</dt><dd class="mono">{employer.postal_code ?? na}</dd>
            <dt>{t(lang, "col.source")}</dt>
            <dd>
              {employer.street_source === "ircc"
                ? t(lang, "employer.source_finding")
                : postings[0]
                ? t(lang, "employer.source_posting", { id: postings[0].posting_id })
                : esdc[0]
                  ? t(lang, "employer.source_list", { period: periodLabel(esdc[0].period, lang) })
                  : na}
            </dd>
          </dl>
          {area ? <MiniMap lat={area.lat} lon={area.lon} label={t(lang, "employer.minimap_aria", { fsa: area.fsa })} /> : null}
          <p class="small">
            <a href={`/map${employer.postal_code ? `?fsa=${employer.postal_code.slice(0, 3)}` : ""}`}>{t(lang, "employer.nearby")}</a>
            {area ? <span class="muted minimap-credit"> {t(lang, "employer.map_credit")}</span> : null}
          </p>
        </div>
        <div class="card">
          <h2>{t(lang, "employer.summary")}</h2>
          <dl>
            <dt>{t(lang, "employer.pending_postings")}</dt><dd class="mono">{n(employer.pending_count)}</dd>
            <dt>{t(lang, "employer.positions_requested")}</dt>
            <dd class="mono">{n(postings.filter((p) => p.flag_current === "requested").reduce((s, p) => s + (p.vacancies ?? 0), 0))}</dd>
            <dt>{t(lang, "employer.approved_lmias")}</dt>
            <dd class="mono">{n(employer.approved_lmias)} <span class="muted">{positions(employer.approved_positions)}</span></dd>
            <dt>{t(lang, "employer.refused_lmias")}</dt>
            <dd class="mono">{n(employer.refused_lmias)} <span class="muted">{positions(employer.refused_positions)}</span></dd>
            <dt>{t(lang, "employer.findings_count")}</dt><dd class="mono">{n(employer.finding_count)}</dd>
            <dt>{t(lang, "employer.response")}</dt>
            <dd>
              {responses.length
                ? tn(lang, "employer.published_one", "employer.published_many", responses.length, { n: responses.length })
                : t(lang, "employer.none_received")}
            </dd>
          </dl>
        </div>
      </section>

      <section>
        <div class="section-head">
          <h2>{t(lang, "employer.indicators")}</h2>
          <a href="/methodology#indicators" class="small">{t(lang, "employer.indicator_link")}</a>
        </div>
        <p class="muted small">{t(lang, "employer.indicator_note")}</p>
        <div class="table-wrap bordered">
          <table>
            <thead>
              <tr>
                <th>{t(lang, "employer.col_indicator")}</th>
                <th>{t(lang, "employer.col_state")}</th>
                <th>{t(lang, "employer.col_basis")}</th>
              </tr>
            </thead>
            <tbody>
              {indicators.length === 0 ? <tr><td colspan={3} class="muted">{t(lang, "employer.not_computed")}</td></tr> : indicators.map((i) => {
                const basis = basisText(lang, i.basis);
                return (
                  <tr>
                    <td>{indicatorLabel(lang, i.indicator)}</td>
                    <td><span class={`badge state-${i.state}`}>{indicatorStateLabel(lang, i.state)}</span></td>
                    <td lang={basis.translated ? undefined : enOnly(lang)}>{basis.text}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {findings.length ? (
        <section>
          <h2>{t(lang, "employer.findings")}</h2>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "employer.col_decision")}</th>
                  <th>{t(lang, "employer.col_operating_name")}</th>
                  <th>{t(lang, "employer.legal_name")}</th>
                  <th>{t(lang, "employer.col_address")}</th>
                  <th>{t(lang, "employer.col_reasons")}</th>
                  <th>{t(lang, "employer.col_penalty")}</th>
                  <th>{t(lang, "col.status")}</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f) => (
                  <tr>
                    <td class="mono">{f.decision_date ?? ""}</td><td>{f.operating_name ?? ""}</td><td>{f.legal_name ?? ""}</td>
                    <td>{f.address ?? ""}</td><td lang={enOnly(lang)}>{f.reasons ?? ""}</td>
                    <td lang={enOnly(lang)}>{f.penalty ?? ""}</td><td lang={enOnly(lang)}>{f.status ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section>
        <h2>{t(lang, "employer.timeline")}</h2>
        <ol class="timeline">
          {employer.current_status === "pending" ? (
            <li class="tl-future"><span class="mono">{t(lang, "employer.pending_label")}</span> {t(lang, "employer.ev_decision")}</li>
          ) : null}
          {events.map((e) => (
            <li class={`tl-${e.kind}`}><span class="mono">{e.date}</span> {e.text}</li>
          ))}
          {events.length === 0 ? <li class="muted">{t(lang, "employer.no_dated")}</li> : null}
        </ol>
      </section>

      <section>
        <h2>{t(lang, "employer.records")}</h2>
        {esdc.length > RECORDS_OPEN ? (
          <p class="muted small">
            {tj(lang, "employer.records_newest", {
              shown: RECORDS_OPEN,
              total: n(esdc.length),
              json: <a href={`/api/employers/${employer.id}`}>{t(lang, "employer.profile_json")}</a>,
            })}
          </p>
        ) : null}
        <div class="table-wrap bordered">
          <table>
            {recordsHead}
            <tbody>
              {postings.map((p) => (
                <tr>
                  <td class="mono">{p.date_posted ?? p.first_seen.slice(0, 10)}</td>
                  <td><Badge status={p.flag_current === "requested" ? "pending" : p.flag_current === "approved" ? "approved" : "lapsed"} lang={lang} /></td>
                  <td>{p.title ?? t(lang, "employer.posting")}{p.valid_through ? t(lang, "employer.open_until", { date: p.valid_through }) : ""}</td>
                  <td>{p.noc_code ? t(lang, "employer.noc", { code: p.noc_code }) : na}</td>
                  <td class="mono">{fmtWage(p.wage_min, p.wage_max, p.wage_unit, lang)}</td>
                  <td class="mono num">{p.vacancies === null ? t(lang, "common.see_posting") : n(p.vacancies)}</td>
                  <td><a href={p.url} class="mono" rel="nofollow noopener">{t(lang, "search.source_jobbank", { ref: p.posting_id })}</a></td>
                  <td class="mono">{p.last_seen.slice(0, 10)}</td>
                </tr>
              ))}
              {esdc.slice(0, RECORDS_OPEN).map((r) => <EsdcRecordRow r={r} lang={lang} />)}
              {postings.length + esdc.length === 0 ? <tr><td colspan={8} class="muted">{t(lang, "common.no_records")}</td></tr> : null}
            </tbody>
          </table>
        </div>
        {esdc.length > RECORDS_OPEN ? (
          <details class="top-gap">
            <summary>{t(lang, "employer.show_all", { n: n(esdc.length) })}</summary>
            <div class="table-wrap bordered">
              <table>
                {recordsHead}
                <tbody>{esdc.slice(RECORDS_OPEN).map((r) => <EsdcRecordRow r={r} lang={lang} />)}</tbody>
              </table>
            </div>
          </details>
        ) : null}
      </section>

      <section class="cards two">
        <div class="card panel">
          <h2>{t(lang, "employer.response_h")}</h2>
          {responses.length ? responses.map((r) => (
            <blockquote>
              <p>{r.statement}</p>
              <footer class="muted small">
                {t(lang, "employer.received", { date: r.received_at.slice(0, 10), contact: r.contact_name ? `, ${r.contact_name}` : "" })}
              </footer>
            </blockquote>
          )) : (
            <p class="muted">{t(lang, "employer.no_response")}</p>
          )}
          <a href={`/employers/${employer.id}/respond`}>{t(lang, "employer.submit_response")}</a>
        </div>
        <div class="card panel">
          <h2>{t(lang, "employer.corrections_log")}</h2>
          {corrections.length ? (
            <ul>
              {corrections.map((r) => (
                <li>
                  <span class="mono">{r.received_at.slice(0, 10)}</span> {r.record_ref ? `${r.record_ref}: ` : ""}{r.request}
                  {r.resolution ? t(lang, "employer.resolution", { date: (r.resolved_at ?? "").slice(0, 10), text: r.resolution }) : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p class="muted">{t(lang, "employer.no_corrections")}</p>
          )}
          <a href={`/corrections?employer=${employer.id}`}>{t(lang, "employer.correct")}</a>
        </div>
      </section>

      <section class="panel bordered">
        <h2>{t(lang, "employer.info")}</h2>
        <p>{tj(lang, "employer.info_report", { form: <a href={REPORT_URL} rel="noopener">{t(lang, "employer.info_form")}</a> })}</p>
        <p>{t(lang, "employer.info_rights")}</p>
      </section>
      <script src="/watchlist.js"></script>
    </Layout>,
  );
}
