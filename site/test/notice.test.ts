// TEMPORARY: the Express Entry notice bar (NOTICE_EE_URL in src/i18n.ts).
// Delete this file with the bar.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { NOTICE_EE_URL, t } from "../src/i18n";
import { fakeAssets, testEnv } from "./assets";

const EM_DASH = String.fromCharCode(0x2014);
const FEED_PATH = "/data/feeds/canada/pending.xml";
const FEED = `<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom"><title>New pending postings</title></feed>\n`;

// The shared fixtures plus one Atom feed, served the way the asset server does.
const withFeed = {
  fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    if (new URL(req.url).pathname === FEED_PATH) {
      return new Response(FEED, { headers: { "content-type": "application/atom+xml", etag: '"feed-1"' } });
    }
    return fakeAssets.fetch(req);
  },
} as unknown as Fetcher;

const get = (path: string) => app.request(path, {}, testEnv(withFeed));

function bar(html: string): string {
  const m = html.match(/<div class="notice-ee">([\s\S]*?)<\/div>/);
  expect(m, "notice bar missing").not.toBeNull();
  return m![1];
}

describe("Express Entry notice bar", () => {
  for (const lang of ["en", "fr"] as const) {
    for (const path of ["/", "/employers/emp-a000000001"]) {
      it(`sits between the nav and the content on ${path} in ${lang}`, async () => {
        const res = await get(lang === "fr" ? `${path}?lang=fr` : path);
        expect(res.status).toBe(200);
        const html = await res.text();
        expect(html.match(/class="notice-ee"/g)?.length).toBe(1);
        expect(html.indexOf('class="notice-ee"')).toBeGreaterThan(html.indexOf("</header>"));
        expect(html.indexOf('class="notice-ee"')).toBeLessThan(html.indexOf("<main"));
        const inner = bar(html);
        expect(inner).toContain(t(lang, "notice_ee.text"));
        expect(inner).toContain(`<a href="${NOTICE_EE_URL[lang]}" rel="noopener">${t(lang, "notice_ee.link")}</a>`);
        expect(inner).not.toContain(EM_DASH);
      });
    }
  }

  it("links each language to its own canada.ca page and keeps the English off French pages", async () => {
    expect(NOTICE_EE_URL.en).toMatch(/^https:\/\/www\.canada\.ca\/en\/immigration-refugees-citizenship\/news\/2026\/10\//);
    expect(NOTICE_EE_URL.fr).toMatch(/^https:\/\/www\.canada\.ca\/fr\/immigration-refugies-citoyennete\/nouvelles\/2026\/10\//);
    const fr = await (await get("/?lang=fr")).text();
    expect(fr).not.toContain(t("en", "notice_ee.text"));
    expect(fr).not.toContain(NOTICE_EE_URL.en);
    expect(bar(fr)).toContain("EIMT");
    expect(bar(await (await get("/")).text())).toContain("LMIA");
  });

  // One line on a desktop screen.
  it("stays short enough for one line", () => {
    const len = (lang: "en" | "fr") => t(lang, "notice_ee.text").length + 1 + t(lang, "notice_ee.link").length;
    expect(len("en")).toBeLessThanOrEqual(115);
    expect(len("fr")).toBeLessThanOrEqual(125);
  });

  it("stays out of feeds, JSON and XML responses", async () => {
    const feed = await get(FEED_PATH);
    expect(feed.status).toBe(200);
    expect(feed.headers.get("content-type")).toContain("application/atom+xml");
    const xml = await feed.text();
    expect(xml).toContain("<feed");

    const api = await get("/api/employers/emp-a000000001");
    expect(api.status).toBe(200);
    expect(api.headers.get("content-type")).toContain("application/json");
    const json = await api.text();
    JSON.parse(json);

    const stats = await (await get("/api/stats")).text();
    const sitemap = await get("/sitemap.xml");
    expect(sitemap.status).toBe(200);
    const map = await sitemap.text();

    for (const body of [xml, json, stats, map]) {
      expect(body).not.toContain("notice-ee");
      for (const lang of ["en", "fr"] as const) {
        expect(body).not.toContain(t(lang, "notice_ee.text"));
        expect(body).not.toContain(NOTICE_EE_URL[lang]);
      }
    }
  });
});
