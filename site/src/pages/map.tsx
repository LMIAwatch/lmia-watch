import type { Context } from "hono";
import { html } from "hono/html";
import { loadStats } from "../data";
import type { AppEnv } from "../env";
import { clientStrings, numberLocale, t, type Key, type Lang } from "../i18n";
import { Badge, ClientData, Layout, noDataPage, page, periodLabel } from "../layout";
import { pageSeo } from "../seo";

// Every string map.js draws, handed over in the page's JSON block.
export const MAP_CLIENT_KEYS: readonly Key[] = [
  "status.pending", "status.approved", "status.refused", "status.lapsed",
  "col.status", "col.employer", "col.job", "col.date",
  "map.area_title", "map.area_summary", "map.cluster_title", "map.cluster_label",
];

export function mapClientData(lang: Lang) {
  return { lang, locale: numberLocale(lang), strings: clientStrings(lang, MAP_CLIENT_KEYS) };
}

export async function mapPage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env);
  if (!stats) return noDataPage(c, "nav.map");
  const fsa = (c.req.query("fsa") ?? "").toUpperCase().slice(0, 3);
  const head = html`<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" />`;
  return page(
    c,
    <Layout lang={lang} title={t(lang, "nav.map")} dataAsOf={stats.data_as_of} active="/map" head={head} seo={pageSeo("map", lang)}>
      <div class="map-controls" id="map-controls" data-fsa={/^[A-Z]\d[A-Z]$/.test(fsa) ? fsa : ""}>
        <label class="check"><input type="checkbox" name="status" value="pending" checked /> <Badge status="pending" lang={lang} /></label>
        <label class="check"><input type="checkbox" name="status" value="approved" checked /> <Badge status="approved" lang={lang} /></label>
        <label class="check"><input type="checkbox" name="status" value="refused" /> <Badge status="refused" lang={lang} /></label>
        <label for="period" class="muted">{t(lang, "map.period")}</label>
        <select id="period" name="period">
          <option value="latest">{t(lang, "search.date_any", { period: periodLabel(stats.esdc_latest_period, lang) })}</option>
          <option value="since_2023q4">{t(lang, "map.period_long", { period: periodLabel(stats.search_from_period, lang) })}</option>
        </select>
        <button type="button" class="btn" id="locate">{t(lang, "map.locate")}</button>
      </div>
      <div id="map" class="map" role="application" aria-label={t(lang, "map.aria")}></div>
      <p class="muted small">{t(lang, "map.note")}</p>
      <section class="card" id="area-panel" aria-live="polite">
        <h2 id="area-title">{t(lang, "map.select")}</h2>
        <p class="muted small" id="area-summary">{t(lang, "map.select_hint")}</p>
        <div class="table-wrap">
          <table class="restack">
            <thead>
              <tr>
                <th>{t(lang, "col.status")}</th>
                <th>{t(lang, "col.employer")}</th>
                <th>{t(lang, "col.job")}</th>
                <th>{t(lang, "col.date")}</th>
              </tr>
            </thead>
            <tbody id="area-rows"></tbody>
          </table>
        </div>
        <a href="/search" id="area-list-link" class="small">{t(lang, "map.open_list")}</a>
      </section>
      <ClientData id="i18n" data={mapClientData(lang)} />
      <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
      <script src="/map.js"></script>
    </Layout>,
  );
}
