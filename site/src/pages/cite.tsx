import type { Context } from "hono";
import { HowToCite, STYLE_LABEL, datasetBibtex, datasetRis, isoDate, validCitation, websiteCitations } from "../cite";
import { loadStats } from "../data";
import type { AppEnv } from "../env";
import { t, type Key, type Lang } from "../i18n";
import { Layout, noDataPage, page } from "../layout";
import { pageSeo } from "../seo";

// How to cite the website and the Zenodo deposit of its files. The citations
// name the data date from stats.json and today's UTC date as the date of
// access (the page is cached at the edge for five minutes, like the others).
// cite.js adds a copy button under each block; without it every block is
// still plain text a reader can select.

const Block = ({ id, label, body, lang }: { id: string; label: Key; body: unknown; lang: Lang }) => (
  <>
    <h3 id={`cite-${id}`}>{t(lang, label)}</h3>
    <pre class="cite-block">{body}</pre>
  </>
);

export async function citePage(c: Context<AppEnv>): Promise<Response> {
  const lang = c.get("lang");
  const stats = await loadStats(c.env).catch(() => null);
  const dataAsOf = isoDate(stats?.data_as_of);
  if (!stats || !dataAsOf) return noDataPage(c, "cite.title");
  const accessed = new Date().toISOString().slice(0, 10);
  const deposit = validCitation(stats.citation);
  return page(
    c,
    <Layout lang={lang} title={t(lang, "cite.title")} dataAsOf={dataAsOf} seo={pageSeo("cite", lang)}>
      <h1>{t(lang, "cite.title")}</h1>
      <div class="cite-page" data-copy={t(lang, "citepage.copy")} data-copied={t(lang, "citepage.copied")}>
        <p class="lead">{t(lang, "citepage.lead", { date: dataAsOf })}</p>
        <p>{t(lang, "citepage.page_note")}</p>

        <h2 id="website">{t(lang, "citepage.website")}</h2>
        {websiteCitations(lang, dataAsOf, accessed).map(({ style, body }) => (
          <Block id={style} label={STYLE_LABEL[style]} body={body} lang={lang} />
        ))}

        {deposit && (
          <>
            <h2 id="data">{t(lang, "citepage.data")}</h2>
            <HowToCite lang={lang} citation={deposit} heading={false} />
            <Block id="data-bibtex" label={STYLE_LABEL.bibtex} body={datasetBibtex(deposit)} lang={lang} />
            <Block id="data-ris" label={STYLE_LABEL.ris} body={datasetRis(deposit)} lang={lang} />
          </>
        )}
      </div>
      <script src="/cite.js" defer></script>
    </Layout>,
  );
}
