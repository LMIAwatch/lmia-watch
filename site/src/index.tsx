import { Hono } from "hono";
import { getCookie, setCookie } from "hono/cookie";
import { html } from "hono/html";
import { secureHeaders } from "hono/secure-headers";
import { api } from "./api";
import { loadStats } from "./data";
import type { AppEnv, Env } from "./env";
import { kofiWebhook } from "./hooks";
import { throttle } from "./limits";
import { runWatchdog } from "./watchdog";
import { langFrom, t, tj } from "./i18n";
import { Layout, page } from "./layout";
import { DOWNLOADS, dataPage } from "./pages/data";
import { employerPage } from "./pages/employer";
import { correctionsForm, correctionsSubmit, respondForm, respondSubmit } from "./pages/forms";
import { homePage } from "./pages/home";
import { mapPage } from "./pages/map";
import { methodologyPage } from "./pages/methodology";
import { searchPage } from "./pages/search";
import { supportPage } from "./pages/support";
import { robotsTxt, sitemapFile } from "./seo";

const app = new Hono<AppEnv>();

// The page loads nothing from third parties except the map library and the
// map tiles, and the policy says exactly that.
app.use(
  "*",
  secureHeaders({
    contentSecurityPolicy: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "https://cdnjs.cloudflare.com"],
      styleSrc: ["'self'", "'unsafe-inline'", "https://cdnjs.cloudflare.com"],
      imgSrc: ["'self'", "data:", "https://*.tile.openstreetmap.org", "https://tile.openstreetmap.org", "https://cdnjs.cloudflare.com"],
      connectSrc: ["'self'"],
      fontSrc: ["'self'"],
      objectSrc: ["'none'"],
      frameAncestors: ["'none'"],
      formAction: ["'self'"],
      baseUri: ["'self'"],
    },
    referrerPolicy: "strict-origin-when-cross-origin",
    xFrameOptions: "DENY",
    crossOriginResourcePolicy: false,
  }),
);

app.use("*", async (c, next) => {
  const q = c.req.query("lang");
  const lang = langFrom(q, getCookie(c, "lang"));
  if (q === "fr" || q === "en") {
    setCookie(c, "lang", lang, { path: "/", maxAge: 60 * 60 * 24 * 365, sameSite: "Lax" });
  }
  c.set("lang", lang);
  await next();
});

// After the language middleware so a 429 page still knows its language later.
app.use("*", throttle);

app.route("/api", api);

app.get("/", homePage);
app.get("/search", searchPage);
app.get("/map", mapPage);
app.get("/methodology", methodologyPage);
app.get("/data", dataPage);
app.get("/support", supportPage);
app.get("/employers/:id", employerPage);
app.get("/employers/:id/respond", (c) => respondForm(c));
app.post("/employers/:id/respond", respondSubmit);
app.get("/corrections", (c) => correctionsForm(c));
app.post("/corrections", correctionsSubmit);
// Payment notices from the donation page; see hooks.ts for what is kept.
app.post("/hooks/kofi", kofiWebhook);
app.get("/robots.txt", robotsTxt);
app.get("/:file{sitemap(?:-[0-9]+)?\\.xml}", sitemapFile);

app.get("/downloads/:file{.+}", async (c) => {
  const file = c.req.param("file");
  const allowed = DOWNLOADS.some((d) => d.file === file) || /^mirror\/[A-Za-z0-9._-]+$/.test(file);
  const object = allowed && c.env.DATA ? await c.env.DATA.get(file.startsWith("mirror/") ? file : `downloads/${file}`) : null;
  if (!object) {
    const stats = await loadStats(c.env);
    const lang = c.get("lang");
    return page(
      c,
      <Layout lang={lang} title={t(lang, "error.file")} dataAsOf={stats?.data_as_of ?? null}>
        <h1>{t(lang, "error.file")}</h1>
        <p>{tj(lang, "error.file_text", { file: <span class="mono">{file}</span> })}</p>
        <p>
          <a href="/data">{t(lang, "error.file_back")}</a>
        </p>
      </Layout>,
      404,
    );
  }
  const headers = new Headers();
  headers.set("Content-Type", file.endsWith(".csv") ? "text/csv; charset=utf-8" : "application/octet-stream");
  headers.set("Content-Disposition", `attachment; filename="${file.split("/").pop()}"`);
  headers.set("Cache-Control", "public, max-age=3600");
  return new Response(object.body, { headers });
});

app.notFound(async (c) => {
  // Sub-app not-found handlers are not consulted, so the API's JSON 404 lives here.
  if (new URL(c.req.url).pathname.startsWith("/api/")) {
    return c.json({ error: "not found" }, 404);
  }
  const stats = await loadStats(c.env).catch(() => null);
  const lang = c.get("lang") ?? "en";
  return page(
    c,
    <Layout lang={lang} title={t(lang, "error.not_found")} dataAsOf={stats?.data_as_of ?? null}>
      <h1>{t(lang, "error.not_found")}</h1>
      <p>
        {tj(lang, "error.not_found_text", {
          home: <a href="/">{t(lang, "error.not_found_home")}</a>,
          search: <a href="/search">{t(lang, "error.not_found_search")}</a>,
        })}
      </p>
    </Layout>,
    404,
  );
});

app.onError((err, c) => {
  console.error(err);
  c.header("Cache-Control", "no-store");
  const lang = c.get("lang") ?? "en";
  return c.html(
    html`<!doctype html>${(
      <Layout lang={lang} title={t(lang, "error.server")} dataAsOf={null}>
        <h1>{t(lang, "error.server")}</h1>
        <p>{t(lang, "error.server_text")}</p>
      </Layout>
    ) as any}`,
    500,
  );
});

export { app };

export default {
  fetch: app.fetch,
  // The cron trigger from wrangler.jsonc: the daily check.
  scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): void {
    ctx.waitUntil(runWatchdog(env));
  },
};
