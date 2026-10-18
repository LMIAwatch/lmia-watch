import type { Context } from "hono";
import { html } from "hono/html";
import type { FC, PropsWithChildren } from "hono/jsx";
import type { AppEnv } from "./env";
import { indicatorLabel, indicatorStateLabel, t, type Key, type Lang } from "./i18n";
import {
  type Seo, X_ACCOUNT_URL, X_HANDLE, absoluteUrl, alternates, canonicalUrl, defaultDescription, pageTitle,
} from "./seo";

// The formatting helpers live with the dictionary; pages import them from here.
export { fmtInt, fmtWage, periodLabel } from "./i18n";

export const STATUS_LABEL: Record<string, Key> = {
  pending: "status.pending",
  approved: "status.approved",
  refused: "status.refused",
  lapsed: "status.lapsed",
  finding: "status.finding",
  none: "status.none",
};

export const Badge: FC<{ status: string; lang: Lang }> = ({ status, lang }) => {
  const key = STATUS_LABEL[status] ?? "status.none";
  return <span class={`badge badge-${status}`}>{t(lang, key)}</span>;
};

export const Chip: FC<PropsWithChildren> = ({ children }) => <span class="chip">{children}</span>;

const INDICATOR_IDS = [
  "newly_incorporated",
  "repeat_applicant",
  "wage_at_floor",
  "low_wage_high_unemployment",
  "high_volume",
  "refused_then_reposted",
];
const INDICATOR_STATES = ["triggered", "not_triggered", "not_applicable", "not_evaluated"];

// English labels; indicatorLabel(lang, id) and indicatorStateLabel(lang, state)
// in i18n.ts give either language.
export const INDICATOR_LABEL: Record<string, string> = Object.fromEntries(INDICATOR_IDS.map((i) => [i, indicatorLabel("en", i)]));
export const INDICATOR_STATE_LABEL: Record<string, string> = Object.fromEntries(
  INDICATOR_STATES.map((s) => [s, indicatorStateLabel("en", s)]),
);

// Strings for a client script, as a JSON data block the script reads by id.
// A JSON block is never executed, so the script-src policy is untouched.
// Escaping < > & and the two line separators keeps the text from closing the
// element or being read as markup. The JSON-LD blocks in the head use the
// same escaper.
export function scriptJson(data: unknown): string {
  return JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

export const ClientData: FC<{ id: string; data: unknown }> = ({ id, data }) => (
  <script type="application/json" id={id} dangerouslySetInnerHTML={{ __html: scriptJson(data) }}></script>
);

// The site mark: a two-column register with one entry cell filled. Drawn on a
// 16 px grid inside a 32-unit box so it stays crisp at 1 unit per pixel; the
// viewBox crops to the ink (24 by 20 units) and the fill is currentColor, which
// the stylesheet sets to navy (.brand-mark). Every coordinate is even, so the
// mark also stays crisp at 1.5 units per pixel. The same path is in
// public/favicon.svg and scripts/make-icons.py.
export const MARK_PATH = "M4 6h24v20H4z M6 8h6v4H6z M14 8h12v4H14z M6 14h6v4H6z M6 20h6v4H6z M14 20h12v4H14z";

// The project's X account, linked from the footer (defined in seo.ts, which
// also names it in the structured data).
export { X_ACCOUNT_URL };

// X's logo as a single path, drawn in the current text colour.
const XMark: FC = () => (
  <svg class="x-mark" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
    <path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

export const BrandMark: FC = () => (
  <svg class="brand-mark" viewBox="4 6 24 20" width="24" height="20" aria-hidden="true">
    <path fill="currentColor" fill-rule="evenodd" d={MARK_PATH} />
  </svg>
);

// Search and social metadata. A page without an Seo object (errors, the
// thank-you page) gets only the site description: no canonical, no cards.
const MetaTags: FC<{ seo?: Seo; lang: Lang; title: string }> = ({ seo, lang, title }) => {
  if (!seo) return <meta name="description" content={defaultDescription(lang)} />;
  if (seo.noindex) {
    return (
      <>
        <meta name="description" content={seo.description} />
        <meta name="robots" content="noindex" />
      </>
    );
  }
  const url = canonicalUrl(seo.path, lang);
  const socialTitle = seo.socialTitle ?? title;
  const image = seo.image;
  return (
    <>
      <meta name="description" content={seo.description} />
      <link rel="canonical" href={url} />
      {alternates(seo.path).map((a) => (
        <link rel="alternate" hreflang={a.hreflang} href={a.href} />
      ))}
      <meta property="og:site_name" content={t(lang, "site.name")} />
      <meta property="og:type" content="website" />
      <meta property="og:url" content={url} />
      <meta property="og:title" content={socialTitle} />
      <meta property="og:description" content={seo.description} />
      <meta property="og:locale" content={lang === "fr" ? "fr_CA" : "en_CA"} />
      <meta property="og:locale:alternate" content={lang === "fr" ? "en_CA" : "fr_CA"} />
      {image ? (
        <>
          <meta property="og:image" content={absoluteUrl(image.path)} />
          <meta property="og:image:type" content="image/png" />
          <meta property="og:image:width" content={String(image.width)} />
          <meta property="og:image:height" content={String(image.height)} />
          <meta property="og:image:alt" content={image.alt(lang)} />
        </>
      ) : null}
      <meta name="twitter:card" content={image && image.width > image.height ? "summary_large_image" : "summary"} />
      <meta name="twitter:site" content={X_HANDLE} />
      <meta name="twitter:title" content={socialTitle} />
      <meta name="twitter:description" content={seo.description} />
      {image ? (
        <>
          <meta name="twitter:image" content={absoluteUrl(image.path)} />
          <meta name="twitter:image:alt" content={image.alt(lang)} />
        </>
      ) : null}
      {(seo.jsonLd ?? []).map((data) => (
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: scriptJson(data) }}></script>
      ))}
    </>
  );
};

export const Layout: FC<
  PropsWithChildren<{ lang: Lang; title: string; dataAsOf: string | null; active?: string; head?: unknown; seo?: Seo }>
> = (props) => {
  const { lang, active } = props;
  const nav = [
    ["/search", "nav.search"],
    ["/map", "nav.map"],
    ["/methodology", "nav.methodology"],
    ["/data", "nav.data"],
    ["/support", "nav.support"],
  ] as const;
  const title = props.seo?.title ?? pageTitle(props.title);
  return (
    <html lang={lang}>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{title}</title>
        <link rel="stylesheet" href="/styles.css?v=8" />
        <script src="/theme.js"></script>
        <link rel="preload" href="/fonts/public-sans-latin-var.woff2" as="font" type="font/woff2" crossorigin="anonymous" />
        <link rel="icon" href="/favicon.ico" sizes="48x48" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <MetaTags seo={props.seo} lang={lang} title={props.title} />
        {props.head as any}
      </head>
      <body>
        <header class="site-header">
          <div class="header-top">
            <div class="container header-row">
              <a href="/" class="brand">
                <BrandMark />
                <span class="brand-name">{t(lang, "site.name")}</span>
              </a>
              <span class="tagline">{t(lang, "site.tagline")}</span>
              <div class="header-meta">
                <span class="mono">
                  {t(lang, "nav.data_as_of")} {props.dataAsOf ?? t(lang, "common.na")}
                </span>
                <button type="button" class="theme-toggle">
                  <span class="when-light">{t(lang, "nav.dark")}</span>
                  <span class="when-dark">{t(lang, "nav.light")}</span>
                </button>
                <a href={`?lang=${lang === "fr" ? "en" : "fr"}`} class="lang-toggle" rel="nofollow">
                  {t(lang, "nav.lang")}
                </a>
              </div>
            </div>
          </div>
          <nav aria-label={t(lang, "nav.main_label")} class="main-nav">
            <div class="container">
              <ul>
                {nav.map(([href, key]) => (
                  <li>
                    <a href={href} class={active === href ? "active" : undefined} aria-current={active === href ? "page" : undefined}>
                      {t(lang, key)}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        </header>
        <main class="container">{props.children}</main>
        <footer class="site-footer">
          <div class="container footer-row">
            <span>{t(lang, "footer.sources")}</span>
            <a href="/data#downloads">{t(lang, "footer.download")}</a>
            <a href="/corrections">{t(lang, "footer.corrections")}</a>
            <a href="/support">{t(lang, "footer.support")}</a>
            <a href={X_ACCOUNT_URL} class="footer-x" rel="noopener" aria-label={t(lang, "footer.x")} title={t(lang, "footer.x")}>
              <XMark />
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
};

export function page(c: Context<AppEnv>, body: unknown, status = 200): Response | Promise<Response> {
  c.header("Cache-Control", status === 200 ? "public, max-age=300" : "no-store");
  return c.html(html`<!doctype html>${body as any}`, status as any);
}

// Shown while the data files have not been published yet (before the first
// nightly run, or on a dev checkout without `npm run data:local`).
export function noDataPage(c: Context<AppEnv>, title: Key): Response | Promise<Response> {
  const lang = c.get("lang") ?? "en";
  return page(
    c,
    <Layout lang={lang} title={t(lang, title)} dataAsOf={null}>
      <h1>{t(lang, "error.no_data")}</h1>
      <p>{t(lang, "error.no_data_text")}</p>
    </Layout>,
    503,
  );
}
