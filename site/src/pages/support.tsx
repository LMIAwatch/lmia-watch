import type { Context } from "hono";
import type { FC } from "hono/jsx";
import { loadStats } from "../data";
import type { AppEnv, Env } from "../env";
import { t, tj, tn, type Key, type Lang } from "../i18n";
import { Layout, fmtInt, page, periodLabel } from "../layout";
import { pageSeo } from "../seo";
import {
  ACTIONS_CENTS_PER_MONTH,
  COSTS_TODAY_CENTS,
  DOMAIN_CAD_PER_YEAR,
  DOMAIN_CENTS_PER_MONTH,
  ESDC_HISTORY_START_YEAR,
  EXAMPLE_GIFT_CAD,
  FREE_PAGE_VIEWS_PER_DAY,
  HOSTING_CENTS_PER_MONTH,
  RESERVE_GOAL_CENTS,
  RESERVE_GOAL_MONTHS,
  STORAGE_CENTS_PER_GB_MONTH,
  STORAGE_FREE_GB,
  TARGET_CENTS_PER_MONTH,
  X_POST_CENTS_PER_MONTH,
  X_POST_USD_EACH,
  WORKERS_PAID_LIST_CENTS,
  WORKERS_PAID_USD_PER_MONTH,
  barWidth,
  budgetMet,
  cardFeeText,
  feeSplit,
  fmtCents,
  fmtUsd,
  refreshTimeText,
  tierCoverage,
  tierName,
  tierUnlocks,
  toCents,
  type TierStatus,
} from "../support";
import { loadSupport } from "../support_data";

export const DEFAULT_DONATE_LABEL = t("en", "support.donate_default");

// The donate button appears only for an https address set in the Worker's
// DONATE_URL variable; anything else (unset, empty, malformed, another
// scheme) leaves donations closed rather than rendering a bad link. The
// button text is DONATE_LABEL in English and DONATE_LABEL_FR in French, each
// falling back to the dictionary's default.
export function donateLink(
  env: Pick<Env, "DONATE_URL" | "DONATE_LABEL" | "DONATE_LABEL_FR">,
  lang: Lang = "en",
): { href: string; label: string } | null {
  const raw = (env.DONATE_URL ?? "").trim();
  if (!raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "https:") return null;
  const label = lang === "fr" ? env.DONATE_LABEL_FR : env.DONATE_LABEL;
  return { href: url.href, label: (label ?? "").trim() || t(lang, "support.donate_default") };
}

// Whole dollars for figures the copy already calls approximate.
const aboutDollars = (cents: number, lang: Lang) => t(lang, "money", { amount: Math.round(cents / 100) });
// Drops ".00" in running text ("a $10 gift"), keeps cents otherwise.
const prose = (cents: number, lang: Lang) =>
  cents % 100 === 0 ? t(lang, "money", { amount: cents / 100 }) : fmtCents(cents, lang);
const months = (lang: Lang, n: number) => tn(lang, "support.months_one", "support.months_many", n, { n });
const cents = (lang: Lang, n: number) => tn(lang, "support.cents_one", "support.cents_many", n, { n });

const TIER_STATUS: Record<TierStatus, Key> = {
  Funded: "support.status.funded",
  "Partly funded": "support.status.partly",
  "Not yet funded": "support.status.not_yet",
};

type BarRow = { label: string; cents: number; total?: boolean };

// Same markup and classes as the home page bars, with money values and no
// minimum sliver for a zero amount.
const CostBars: FC<{ rows: BarRow[]; lang: Lang }> = ({ rows, lang }) => {
  const max = Math.max(0, ...rows.map((r) => r.cents));
  return (
    <div class="bars narrow">
      {rows.map((r) => (
        <div class={r.total ? "bar-row bar-total" : "bar-row"}>
          <span class="bar-label">{r.label}</span>
          <span class="bar-track">
            <span class="bar-fill" style={`width:${barWidth(r.cents, max)}%`}></span>
          </span>
          <span class="mono bar-value">{fmtCents(r.cents, lang)}</span>
        </div>
      ))}
    </div>
  );
};

export async function supportPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  // The page renders without the data files; the stats fill in counts and
  // periods where they exist.
  const stats = await loadStats(c.env).catch(() => null);
  const donate = donateLink(c.env, lang);
  const split = feeSplit(toCents(EXAMPLE_GIFT_CAD));
  const sup = await loadSupport(c.env.DB, new Date());
  const tiers = tierCoverage(sup.monthlySupportCents);
  const met = budgetMet(sup.monthlySupportCents, sup.reserveMonths);
  const latest = stats?.esdc_latest_period ? periodLabel(stats.esdc_latest_period, lang) : null;
  const from = stats?.search_from_period ? periodLabel(stats.search_from_period, lang) : null;
  const employers = stats?.counts?.employers;
  const money = (v: number) => fmtCents(v, lang);
  const goal = months(lang, RESERVE_GOAL_MONTHS);
  const downloads = <a href="/data#downloads">{t(lang, "common.downloads_link")}</a>;

  return page(
    c,
    <Layout lang={lang} title={t(lang, "support.title")} dataAsOf={stats?.data_as_of ?? null} active="/support" seo={pageSeo("support", lang)}>
      <div class="doc-layout">
        <nav aria-label={t(lang, "toc.label")} class="toc">
          <span class="toc-title">{t(lang, "toc.title")}</span>
          <a href="#holds">{t(lang, "support.toc_holds")}</a>
          <a href="#costs">{t(lang, "support.toc_costs")}</a>
          <a href="#tiers">{t(lang, "support.toc_tiers")}</a>
          <a href="#beyond">{t(lang, "support.toc_beyond")}</a>
          <a href="#donation">{t(lang, "support.toc_donation")}</a>
          <a href="#give">{t(lang, "support.toc_give")}</a>
          <a href="#transparency">{t(lang, "support.toc_transparency")}</a>
          <a href="#law">{t(lang, "support.toc_law")}</a>
        </nav>
        <div class="doc">
          <h1>{t(lang, "support.title")}</h1>
          <p class="lead">{t(lang, "support.lead")}</p>

          <h2 id="holds">{t(lang, "support.toc_holds")}</h2>
          <ul>
            <li>
              {t(lang, "support.holds_lists", {
                year: ESDC_HISTORY_START_YEAR,
                through: latest ? t(lang, "support.holds_through", { period: latest }) : "",
              })}
            </li>
            <li>
              {t(lang, "support.holds_profiles", {
                count: employers ? t(lang, "support.holds_employers", { n: fmtInt(employers, lang) }) : "",
              })}
            </li>
            <li>
              {t(lang, "support.holds_search", {
                scope: from ? t(lang, "support.holds_since", { period: from }) : t(lang, "support.holds_longer"),
              })}
            </li>
            <li>
              {tj(lang, "support.holds_older", {
                older: from ? t(lang, "support.holds_before", { period: from }) : t(lang, "support.holds_older_records"),
                downloads,
              })}
            </li>
            <li>{t(lang, "support.holds_matched")}</li>
            <li>{t(lang, "support.holds_refresh", { time: refreshTimeText(undefined, lang) })}</li>
          </ul>
          <h3>{t(lang, "support.limits")}</h3>
          <ul>
            <li>{t(lang, "support.limit_views", { n: fmtInt(FREE_PAGE_VIEWS_PER_DAY, lang) })}</li>
            <li>{t(lang, "support.limit_search")}</li>
            <li>{t(lang, "support.limit_storage", { n: STORAGE_FREE_GB })}</li>
          </ul>

          <h2 id="costs">{t(lang, "support.toc_costs")}</h2>
          <p>{t(lang, "support.costs_note")}</p>
          <CostBars
            lang={lang}
            rows={[
              { label: t(lang, "support.bar_domain"), cents: DOMAIN_CENTS_PER_MONTH },
              { label: t(lang, "support.bar_hosting"), cents: HOSTING_CENTS_PER_MONTH },
              { label: t(lang, "support.bar_github"), cents: ACTIONS_CENTS_PER_MONTH },
              { label: t(lang, "support.bar_x"), cents: X_POST_CENTS_PER_MONTH },
              { label: t(lang, "support.bar_total"), cents: COSTS_TODAY_CENTS, total: true },
            ]}
          />
          <p class="muted small top-gap">
            {t(lang, "support.costs_detail", {
              domain: prose(toCents(DOMAIN_CAD_PER_YEAR), lang),
              github: money(ACTIONS_CENTS_PER_MONTH),
              usd: fmtUsd(X_POST_USD_EACH, lang),
              monthly: money(X_POST_CENTS_PER_MONTH),
            })}{" "}
            {t(lang, "support.bluesky_free")}
          </p>

          <h2 id="tiers">{t(lang, "support.toc_tiers")}</h2>
          <p>
            {t(lang, "support.tiers_summary", {
              target: money(TARGET_CENTS_PER_MONTH),
              support: money(sup.monthlySupportCents),
              months: sup.reserveMonths,
              goal,
            })}
          </p>
          <p class="muted small">{t(lang, "support.tiers_note")}</p>
          <div class="table-wrap bordered">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "support.col_tier")}</th>
                  <th class="num">{t(lang, "support.col_monthly_cost")}</th>
                  <th>{t(lang, "support.col_pays_for")}</th>
                  <th>{t(lang, "support.col_against")}</th>
                  <th>{t(lang, "col.status")}</th>
                </tr>
              </thead>
              <tbody>
                {tiers.map((tier) => (
                  <tr data-tier={tier.id}>
                    <td>{tierName(lang, tier.id)}</td>
                    <td class="mono num">{money(tier.costCents)}</td>
                    <td>{tierUnlocks(lang, tier.id)}</td>
                    <td class="tier-funding">
                      <span class="bar-track">
                        <span class="bar-fill" style={`width:${tier.width}%`}></span>
                      </span>
                      <span class="mono small">
                        {t(lang, "support.of", {
                          part: money(Math.min(sup.monthlySupportCents, tier.cumulativeCents)),
                          whole: money(tier.cumulativeCents),
                        })}
                      </span>
                    </td>
                    <td class="tier-status">{t(lang, TIER_STATUS[tier.status])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p class="top-gap">{t(lang, "support.reserve_goal", { goal, about: aboutDollars(RESERVE_GOAL_CENTS, lang) })}</p>
          <p class="muted small">
            {t(lang, "support.estimates", {
              usd: fmtUsd(WORKERS_PAID_USD_PER_MONTH, lang),
              cad: money(WORKERS_PAID_LIST_CENTS),
              cents: cents(lang, STORAGE_CENTS_PER_GB_MONTH),
            })}
          </p>

          <h2 id="beyond">{t(lang, "support.toc_beyond")}</h2>
          {met ? (
            <p>
              <strong>{t(lang, "support.met", { goal })}</strong>
            </p>
          ) : null}
          <p>{t(lang, "support.beyond_text", { goal })}</p>

          <h2 id="donation">{t(lang, "support.toc_donation")}</h2>
          <p>{t(lang, "support.gift_split", { gift: prose(split.giftCents, lang) })}</p>
          <span
            class="bar-track bar-stack"
            role="img"
            aria-label={t(lang, "support.split_aria", { fee: money(split.feeCents), net: money(split.netCents) })}
          >
            <span class="bar-fill bar-fill-light" style={`width:${split.feeTenths / 10}%`}></span>
            <span class="bar-fill" style={`width:${split.netTenths / 10}%`}></span>
          </span>
          <ul class="bar-legend">
            <li>
              <span class="swatch swatch-light" aria-hidden="true"></span>
              {t(lang, "support.fee_line", { fee: money(split.feeCents), rate: cardFeeText(lang) })}
            </li>
            <li>
              <span class="swatch swatch-dark" aria-hidden="true"></span>
              {t(lang, "support.net_line", { net: money(split.netCents) })}
            </li>
          </ul>

          <h2 id="give">{t(lang, "support.toc_give")}</h2>
          {donate ? (
            <>
              <p>
                <a class="btn btn-primary" href={donate.href} rel="noopener">
                  {donate.label}
                </a>
              </p>
              <p class="muted small">{t(lang, "support.card_note")}</p>
            </>
          ) : (
            <p>{t(lang, "support.closed")}</p>
          )}

          <h2 id="transparency">{t(lang, "support.toc_transparency")}</h2>
          <div class="table-wrap bordered narrow">
            <table>
              <thead>
                <tr>
                  <th>{t(lang, "support.col_quarter")}</th>
                  <th class="num">{t(lang, "support.col_monthly_cost")}</th>
                  <th class="num">{t(lang, "support.col_received")}</th>
                  <th class="num">{t(lang, "support.col_spent")}</th>
                  <th class="num">{t(lang, "support.col_reserve")}</th>
                </tr>
              </thead>
              <tbody>
                {sup.donations === 0 ? (
                  <tr>
                    <td colspan={5} class="muted">{t(lang, "support.no_donations")}</td>
                  </tr>
                ) : (
                  sup.ledger.map((r) => (
                    <tr>
                      <td class="mono">{lang === "fr" ? periodLabel(r.quarter.replace(" ", ""), lang) : r.quarter}</td>
                      <td class="mono num">{money(r.monthlyCostCents)}</td>
                      <td class="mono num">{money(r.receivedCents)}</td>
                      <td class="mono num">{money(r.spentCents)}</td>
                      <td class="mono num">{money(r.reserveCents)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <p class="top-gap">{t(lang, "support.transparency_text")}</p>

          <h2 id="law">{t(lang, "support.toc_law")}</h2>
          <p>{t(lang, "support.law_text")}</p>
        </div>
      </div>
    </Layout>,
  );
}
