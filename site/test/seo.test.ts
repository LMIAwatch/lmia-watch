import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import type { Profile } from "../src/data";
import { app } from "../src/index";
import { DOWNLOADS } from "../src/pages/data";
import { scriptJson } from "../src/layout";
import { DESCRIPTION_MAX, SOCIAL_CARD, SOCIAL_SQUARE, profileDescription } from "../src/seo";
import { emptyAssets, testEnv } from "./assets";
import profileFixtures from "./fixtures/profiles-a00.json";
import sitemapPart from "./fixtures/sitemap-1.xml?raw";
import sitemapIndex from "./fixtures/sitemap-index.xml?raw";

const profiles = profileFixtures as unknown as Record<string, Profile>;
const get = (path: string, headers: Record<string, string> = {}) => app.request(path, { headers }, testEnv());
const headOf = async (path: string, headers: Record<string, string> = {}) => {
  const html = await (await get(path, headers)).text();
  return html.slice(0, html.indexOf("</head>"));
};

// French text carries narrow and plain no-break spaces; compare with plain ones.
const nbsp = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");
const decode = (s: string) =>
  s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const meta = (head: string, key: string) =>
  decode(head.match(new RegExp(`<meta (?:name|property)="${key.replace(/[:.]/g, "\\$&")}" content="([^"]*)"`))?.[1] ?? "");
const title = (head: string) => decode(head.match(/<title>([^<]*)<\/title>/)?.[1] ?? "");
const canonical = (head: string) => head.match(/<link rel="canonical" href="([^"]*)"/)?.[1];
const alternates = (head: string) =>
  Object.fromEntries([...head.matchAll(/<link rel="alternate" hreflang="([^"]*)" href="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
const jsonLd = (head: string): any[] =>
  [...head.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]));

const PAGES: [string, string, string][] = [
  ["/", "https://lmiawatch.ca/", "LMIA Watch: Who Is Applying to Hire Temporary Foreign Workers"],
  ["/search?status=pending&province=BC&page=2", "https://lmiawatch.ca/search", "Search LMIA Employer Records | LMIA Watch"],
  ["/map?fsa=v0n", "https://lmiawatch.ca/map", "Map of LMIA Records by Postal Area | LMIA Watch"],
  ["/methodology", "https://lmiawatch.ca/methodology", "Methodology: Sources, Status and Indicators | LMIA Watch"],
  ["/data", "https://lmiawatch.ca/data", "LMIA Data Downloads, API and Licence | LMIA Watch"],
  ["/support", "https://lmiawatch.ca/support", "Support the Site | LMIA Watch"],
  ["/cite", "https://lmiawatch.ca/cite", "How to Cite | LMIA Watch"],
  ["/corrections?employer=emp-a000000001", "https://lmiawatch.ca/corrections", "Request a Correction | LMIA Watch"],
  ["/employers/emp-a000000005", "https://lmiawatch.ca/employers/emp-a000000005", "Jealous Fruits Ltd. | LMIA Watch"],
];

describe("page metadata", () => {
  it("every page has a title, a short description, a query-free canonical and language alternates", async () => {
    for (const [path, url, expected] of PAGES) {
      const head = await headOf(path);
      expect(title(head), path).toBe(expected);
      const description = meta(head, "description");
      expect(description.length, path).toBeGreaterThan(50);
      expect(description.length, path).toBeLessThanOrEqual(DESCRIPTION_MAX);
      expect(canonical(head), path).toBe(url);
      expect(alternates(head), path).toEqual({ en: url, fr: `${url}?lang=fr`, "x-default": url });
      expect(meta(head, "og:site_name")).toBe("LMIA Watch");
      expect(meta(head, "og:url")).toBe(url);
      expect(meta(head, "og:description")).toBe(description);
      expect(meta(head, "twitter:description")).toBe(description);
      expect(head).not.toContain('name="robots"');
      expect(head, path).not.toContain("\u2014");
    }
  });

  it("a French view names its own URL as canonical and speaks French", async () => {
    for (const headers of [{}, { cookie: "lang=fr" }] as Record<string, string>[]) {
      const path = Object.keys(headers).length ? "/employers/emp-a000000005" : "/employers/emp-a000000005?lang=fr";
      const head = await headOf(path, headers);
      expect(canonical(head)).toBe("https://lmiawatch.ca/employers/emp-a000000005?lang=fr");
      expect(meta(head, "og:locale")).toBe("fr_CA");
      expect(meta(head, "og:locale:alternate")).toBe("en_CA");
      expect(nbsp(meta(head, "description"))).toBe(
        "Jealous Fruits Ltd., Kelowna, BC : 19 EIMT approuvées (760 postes). Dossiers du Guichet-Emplois et d’EDSC, chacun lié à sa source.",
      );
      expect(meta(head, "og:image:alt")).toBe("LMIA Watch");
      expect(jsonLd(head)[0].itemListElement.map((i: any) => i.name)).toEqual(["Accueil", "Colombie-Britannique", "Employeur"]);
    }
    const home = await headOf("/?lang=fr");
    expect(nbsp(title(home))).toBe("LMIA Watch : qui demande des travailleurs étrangers temporaires");
    expect(nbsp(meta(home, "og:image:alt"))).toBe("LMIA Watch : Dossiers publics des études d’impact sur le marché du travail");
    const data = await headOf("/data?lang=fr");
    expect(nbsp(title(data))).toBe("Données EIMT : téléchargements, API et licence | LMIA Watch");
    const frFiles = Object.fromEntries(jsonLd(data)[0].distribution.map((d: any) => [d.name, d.license]));
    expect(frFiles["approved_quarterly.csv"]).toBe("https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada");
    expect(frFiles["findings.csv"]).toBe("https://www.canada.ca/fr/transparence/avis.html");
    expect(nbsp(meta(data, "description"))).toBe(
      "Les listes EIMT d’EDSC depuis 2014, les relevés du Guichet-Emplois et les employeurs fusionnés en CSV, une API JSON et la licence de chaque fichier.",
    );
    expect(jsonLd(data)[0].inLanguage).toBe("fr");
    expect(title(await headOf("/support?lang=fr"))).toBe("Soutenir le site | LMIA Watch");
    const cite = await headOf("/cite?lang=fr");
    expect(title(cite)).toBe("Comment citer | LMIA Watch");
    expect(canonical(cite)).toBe("https://lmiawatch.ca/cite?lang=fr");
    expect(canonical(home)).toBe("https://lmiawatch.ca/?lang=fr");
  });

  it("profile descriptions come from the employer's own counts", () => {
    const en = (id: string) => profileDescription(profiles[id], "en");
    expect(en("emp-a000000001")).toBe(
      "PinkCloud Cleaning & Home Services, Brackendale, BC: 1 pending Job Bank posting. LMIA records from Job Bank and ESDC, each linked to its source.",
    );
    expect(en("emp-a000000005")).toBe(
      "Jealous Fruits Ltd., Kelowna, BC: 19 approved LMIAs (760 positions). LMIA records from Job Bank and ESDC, each linked to its source.",
    );
    expect(en("emp-a000000008")).toBe(
      "Haveli Restaurant Inc, St. John's, NL: 1 refused LMIA (1 position). LMIA records from Job Bank and ESDC, each linked to its source.",
    );
    for (const id of Object.keys(profiles)) {
      for (const lang of ["en", "fr"] as const) expect(profileDescription(profiles[id], lang).length).toBeLessThanOrEqual(DESCRIPTION_MAX);
    }
  });

  it("long names and busy records still fit, dropping the closing sentence first", () => {
    const base = profiles["emp-a000000005"];
    const busy = (name: string): Profile => ({
      ...base,
      employer: {
        ...base.employer, display_name: name, city: "Abbotsford", province: "BC", pending_count: 12,
        approved_lmias: 1234, approved_positions: 5678, refused_lmias: 3, refused_positions: 9, finding_count: 1,
      },
    });
    // The closing sentence and the position counts go before the place does.
    expect(profileDescription(busy("Fraser Valley Greenhouse Growers Ltd."), "en")).toBe(
      "Fraser Valley Greenhouse Growers Ltd., Abbotsford, BC: 12 pending Job Bank postings, 1,234 approved LMIAs, 3 refused LMIAs and 1 IRCC non-compliance finding.",
    );
    // A name too long for the rest is clipped at a word, with an ellipsis.
    const long = profileDescription(
      busy("The Very Long Registered Name of an Agricultural Cooperative Operating Greenhouses and Packing Facilities Across the Lower Mainland"),
      "en",
    );
    expect(long.length).toBeLessThanOrEqual(DESCRIPTION_MAX);
    expect(long).toMatch(/^The Very Long Registered Name[^…]*…: 12 pending Job Bank postings, 1,234 approved LMIAs, 3 refused LMIAs and 1 IRCC non-compliance finding\.$/);
    for (const lang of ["en", "fr"] as const) {
      expect(profileDescription(busy("x".repeat(300)), lang).length).toBeLessThanOrEqual(DESCRIPTION_MAX);
    }
    const none: Profile = { ...base, employer: { ...base.employer, approved_lmias: 0, approved_positions: 0, city: null, province: "XX" } };
    expect(profileDescription(none, "en")).toBe(
      "Jealous Fruits Ltd., head office outside Canada: 1 public LMIA record. LMIA records from Job Bank and ESDC, each linked to its source.",
    );
  });

  it("the home page carries the WebSite search action and the project as publisher", async () => {
    const head = await headOf("/");
    expect(meta(head, "twitter:card")).toBe("summary_large_image");
    expect(meta(head, "og:image")).toBe("https://lmiawatch.ca/social-card.png");
    expect(meta(head, "og:image:width")).toBe("1200");
    expect(meta(head, "og:title")).toBe("LMIA Watch: Who Is Applying to Hire Temporary Foreign Workers");
    const [ld] = jsonLd(head);
    const site = ld["@graph"].find((n: any) => n["@type"] === "WebSite");
    const org = ld["@graph"].find((n: any) => n["@type"] === "Organization");
    expect(site.potentialAction).toEqual({
      "@type": "SearchAction",
      target: { "@type": "EntryPoint", urlTemplate: "https://lmiawatch.ca/search?q={search_term_string}" },
      "query-input": "required name=search_term_string",
    });
    expect(site.publisher).toEqual({ "@id": org["@id"] });
    expect(org.name).toBe("LMIA Watch");
    expect(org.sameAs).toEqual(["https://x.com/LMIAwatch", "https://bsky.app/profile/lmiawatch.ca"]);
    // A publisher is the project; nothing in the graph describes a person.
    expect(JSON.stringify(ld)).not.toMatch(/"Person"|founder|author|employee/);
  });

  it("the data page describes the downloads as a Dataset, each file under its own licence", async () => {
    const head = await headOf("/data");
    const [ld] = jsonLd(head);
    expect(ld["@type"]).toBe("Dataset");
    // The files do not share one licence: none is claimed for the whole dataset.
    expect(ld.license).toBeUndefined();
    expect(ld.usageInfo).toBe("https://lmiawatch.ca/data#licence");
    expect(ld.creditText).toContain("Open Government Licence, Canada");
    expect(ld.creditText).toContain("Job Bank and IRCC material reproduced under the Government of Canada terms of use");
    const files = Object.fromEntries(ld.distribution.map((d: any) => [d.name, d]));
    const ogl = "https://open.canada.ca/en/open-government-licence-canada";
    const terms = "https://www.canada.ca/en/transparency/terms.html";
    expect(Object.fromEntries(ld.distribution.map((d: any) => [d.name, d.license ?? null]))).toEqual({
      "pending_observations.csv": terms,
      "approved_quarterly.csv": ogl,
      "refused_quarterly.csv": ogl,
      "employers.csv": null,
      "indicators.csv": null,
      "findings.csv": terms,
      "esdc_resources.csv": ogl,
    });
    for (const name of ["employers.csv", "indicators.csv"]) {
      expect(files[name].description).toMatch(/\. The licence differs by column; see the licence table on the Data page\.$/);
    }
    expect(files["findings.csv"].description).toBe("IRCC non-compliant employers as published, joined to employer IDs");
    expect(meta(head, "description")).toBe(
      "Every ESDC LMIA employer list since 2014, nightly Job Bank observations and merged employers as CSV, a read-only JSON API, and each file's licence.",
    );
    expect(ld.isAccessibleForFree).toBe(true);
    expect(ld.dateModified).toBe("2026-10-12");
    expect(ld.temporalCoverage).toBe("2014/..");
    expect(ld.creator).toEqual({ "@type": "Organization", name: "LMIA Watch", url: "https://lmiawatch.ca/" });
    expect(ld.description.length).toBeGreaterThan(50);
    expect(ld.distribution.map((d: any) => d.contentUrl)).toEqual(DOWNLOADS.map((d) => `https://lmiawatch.ca/downloads/${d.file}`));
    expect(ld.distribution.every((d: any) => d["@type"] === "DataDownload" && d.encodingFormat === "text/csv")).toBe(true);
  });

  it("profiles get a summary card and a breadcrumb that names no one", async () => {
    const head = await headOf("/employers/emp-a000000001");
    expect(meta(head, "twitter:card")).toBe("summary");
    expect(meta(head, "og:image")).toBe("https://lmiawatch.ca/social-square.png");
    expect(meta(head, "og:title")).toBe("PinkCloud Cleaning & Home Services");
    expect(head).not.toContain('name="robots"');
    const [crumbs] = jsonLd(head);
    expect(crumbs["@type"]).toBe("BreadcrumbList");
    expect(crumbs.itemListElement.map((i: any) => [i.position, i.name, i.item])).toEqual([
      [1, "Home", "https://lmiawatch.ca/"],
      [2, "British Columbia", "https://lmiawatch.ca/search?province=BC"],
      [3, "Employer", undefined],
    ]);
    expect(JSON.stringify(crumbs)).not.toContain("PinkCloud");
  });

  it("outbound Job Bank and ESDC record links are nofollow", async () => {
    const pending = await (await get("/employers/emp-a000000001")).text();
    expect(pending).toContain('rel="nofollow noopener">Job Bank 50456228</a>');
    const refused = await (await get("/employers/emp-a000000008")).text();
    expect(refused).toMatch(/rel="nofollow noopener">ESDC negative 2026Q1<\/a>/);
    const search = await (await get("/search")).text();
    expect(search).toContain('rel="nofollow noopener" title="Job Bank 50456228">Job Bank</a>');
  });

  it("the response form stays out of the index and error pages carry only the site description", async () => {
    const form = await headOf("/employers/emp-a000000001/respond");
    expect(form).toContain('<meta name="robots" content="noindex"/>');
    expect(canonical(form)).toBeUndefined();
    expect(meta(form, "description")).toContain("PinkCloud Cleaning & Home Services");
    const missing = await headOf("/nowhere");
    expect(meta(missing, "description")).toContain("temporary foreign workers");
    expect(canonical(missing)).toBeUndefined();
    expect(missing).not.toContain("og:title");
  });

  it("the preview images the tags name exist in public/", async () => {
    const assets = (env as unknown as { ASSETS: Fetcher }).ASSETS;
    for (const image of [SOCIAL_CARD, SOCIAL_SQUARE]) {
      const res = await assets.fetch(new Request(`https://assets.invalid${image.path}`));
      expect(res.status, image.path).toBe(200);
      expect(res.headers.get("content-type")).toBe("image/png");
      const bytes = new Uint8Array(await res.arrayBuffer());
      // PNG header: width and height are the big-endian words at offsets 16 and 20.
      const view = new DataView(bytes.buffer);
      expect([view.getUint32(16), view.getUint32(20)], image.path).toEqual([image.width, image.height]);
      expect(bytes.length).toBeLessThan(200 * 1024);
    }
  });

  it("JSON-LD text cannot close its script element", () => {
    const text = scriptJson({ name: "A </script><b> & B\u2028" });
    expect(text).not.toMatch(/[<>&\u2028]/);
    expect(JSON.parse(text)).toEqual({ name: "A </script><b> & B\u2028" });
  });
});

// Whether a group's rules let a crawler fetch a path, as Google and Bing read
// them: the longest matching pattern wins, Allow on a tie; "*" matches any
// run of characters and a final "$" anchors the end. With no match, allowed.
function robotsAllow(rules: string[], path: string): boolean {
  let best = { length: -1, allow: true };
  for (const rule of rules) {
    const m = /^(Allow|Disallow):\s*(\S*)$/.exec(rule);
    if (!m || m[2] === "") continue;
    const pattern = m[2];
    const anchored = pattern.endsWith("$");
    const parts = (anchored ? pattern.slice(0, -1) : pattern).split("*").map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!new RegExp(`^${parts.join(".*")}${anchored ? "$" : ""}`).test(path)) continue;
    const allow = m[1] === "Allow";
    if (pattern.length > best.length || (pattern.length === best.length && allow)) best = { length: pattern.length, allow };
  }
  return best.allow;
}

describe("crawler files", () => {
  it("/sitemap.xml is the index and each part streams from data/sitemaps", async () => {
    const index = await get("/sitemap.xml");
    expect(index.status).toBe(200);
    expect(index.headers.get("content-type")).toBe("application/xml; charset=utf-8");
    expect(await index.text()).toBe(sitemapIndex);
    const part = await get("/sitemap-1.xml");
    expect(part.status).toBe(200);
    expect(await part.text()).toBe(sitemapPart);
    expect((await get("/sitemap-2.xml")).status).toBe(404);
    expect((await get("/sitemap-x.xml")).status).toBe(404);
    const none = await app.request("/sitemap.xml", {}, testEnv(emptyAssets));
    expect(none.status).toBe(404);
  });

  it("/robots.txt is the file in public/, open to all with the sitemap named", async () => {
    // The real assets binding, which serves site/public.
    const res = await app.request("/robots.txt", {}, env);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/plain; charset=utf-8");
    const text = await res.text();
    const rules = text.split("\n").filter((l) => l && !l.startsWith("#"));
    // Everyone may crawl the pages, at a polite pace; the hooks, API, downloads and the response form are not pages,
    // and the search's filter and cursor combinations all name /search as their canonical URL.
    expect(rules.slice(0, 9)).toEqual([
      "User-agent: *",
      "Allow: /",
      "Disallow: /hooks/",
      "Disallow: /api/",
      "Disallow: /downloads/",
      "Disallow: /employers/*/respond",
      "Disallow: /search?",
      "Allow: /search?lang=fr$",
      "Crawl-delay: 5",
    ]);
    const lines = text.split("\n");
    expect(lines).toContain("Disallow: /search?");
    expect(lines).toContain("Allow: /search?lang=fr$");
    // The search page itself is never shut out.
    expect(lines).not.toContain("Disallow: /search");
    const everyone = rules.slice(0, rules.indexOf("Crawl-delay: 5"));
    for (const path of ["/", "/search", "/search?lang=fr", "/employers/x", "/employers/x?lang=fr", "/places/bc"]) {
      expect(robotsAllow(everyone, path), path).toBe(true);
    }
    for (const path of ["/search?q=a", "/search?lang=fr&q=a", "/search?cursor=abc", "/search?status=pending&province=BC", "/employers/x/respond", "/api/stats"]) {
      expect(robotsAllow(everyone, path), path).toBe(false);
    }
    // Training and bulk-scraping crawlers are kept off the Worker entirely.
    const aiGroup = rules.slice(9, rules.indexOf("Disallow: /") + 1);
    for (const bot of ["ClaudeBot", "GPTBot", "Google-Extended", "CCBot", "Bytespider"]) expect(aiGroup).toContain(`User-agent: ${bot}`);
    expect(aiGroup[aiGroup.length - 1]).toBe("Disallow: /");
    expect(rules[rules.length - 1]).toBe("Sitemap: https://lmiawatch.ca/sitemap.xml");
    expect(text).not.toContain("\u2014");
  });
});
