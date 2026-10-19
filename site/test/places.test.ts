// Occupation and place pages against fixture JSON written by the pipeline's
// exporter from its own test seed (pipeline/tests/test_places.py), with the
// record threshold set to 3 there, so Manitoba is above it and BC below.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { emptyAssets, fakeAssets, testEnv } from "./assets";
import occIndex from "./fixtures/occupations-index.json";
import occ63200 from "./fixtures/occupation-63200.json";
import occ85101 from "./fixtures/occupation-85101.json";
import bc from "./fixtures/place-bc.json";
import mb from "./fixtures/place-mb.json";
import winnipeg from "./fixtures/place-mb-winnipeg.json";
import winnipegCma from "./fixtures/place-mb-winnipeg-cma.json";
import placesIndex from "./fixtures/places-index.json";

const FILES: Record<string, unknown> = {
  "occupations/index.json": occIndex,
  "occupations/63200.json": occ63200,
  "occupations/85101.json": occ85101,
  "places/index.json": placesIndex,
  "places/mb.json": mb,
  "places/bc.json": bc,
  "places/mb/winnipeg.json": winnipeg,
  "places/mb/winnipeg-cma.json": winnipegCma,
};

// The fixtures of the other tests, plus these files and one that does not parse.
const assets = {
  fetch: async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url).pathname.replace(/^\/data\//, "");
    if (path === "places/mb/broken.json") return new Response("{\"kind\":", { headers: { "content-type": "application/json" } });
    const file = FILES[path];
    if (file !== undefined) return new Response(JSON.stringify(file), { headers: { "content-type": "application/json" } });
    return fakeAssets.fetch(input);
  },
} as unknown as Fetcher;

const get = (path: string, env = testEnv(assets)) => app.request(path, {}, env);
const EM_DASH = String.fromCharCode(0x2014);

// Visible text with entities decoded and no-break spaces made plain.
async function text(path: string): Promise<string> {
  const html = await (await get(path)).text();
  return html
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/[  ]/g, " ");
}

function jsonLd(html: string): any[] {
  return [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]));
}

describe("occupation pages", () => {
  it("carry their own reading of the figures", async () => {
    const res = await get("/occupations/63200");
    expect(res.status).toBe(200);
    const html = await text("/occupations/63200");
    expect(html).toContain("<h1>Cooks (NOC 63200)</h1>");
    expect(html).toContain("Cooks prepare food.");
    expect(html).toContain("Broad category: Sales and service occupations. TEER 3.");
    // 9 positions in 2026 Q1 against 2 in 2025 Q4; 9 of the 19 approved nationally.
    expect(html).toContain("Approved positions in 2026 Q1: 9, up 350.0 percent from 2025 Q4 (2).");
    expect(html).toContain("Refusal records in 2026 Q1: 1, against 0 in 2025 Q4.");
    expect(html).toContain("Share of all positions approved in Canada in 2026 Q1: 47.4 percent.");
    // Posted minimums 15, 17 and 20 an hour: median 17, against 18 (Job Bank) and 19.55 (Statistics Canada).
    expect(html).toContain("Median posted minimum on 3 LMIA-flagged Job Bank postings: $17.00/h.");
    expect(html).toContain("Job Bank median: $18.00/h (Canada); the posted minimum is 5.6 percent below it.");
    expect(html).toContain("Statistics Canada average offered wage, 2026 Q2: $19.55/h (Canada); the hourly posted minimum is 13.0 percent below it.");
    expect(html).toContain("Job vacancies counted by Statistics Canada, 2026 Q2: 13,310 (Canada).");
    expect(html).toContain("Economic region with the most records: Winnipeg, Manitoba (5, 63 percent of the total).");
    // The regional row: posted 16.00 on two postings, the regional median, the survey's E flag.
    expect(html).toContain("$16.00/h <span class=\"muted\">(2)</span>");
    expect(html).toMatch(/300<abbr title="Use with caution \(Statistics Canada quality rating E\)"> E<\/abbr>/);
    expect(html).toContain("$16.50/h<span class=\"muted\"> (provincial figure)</span>");
    expect(html).toContain('<a href="/employers/emp-ad951ffc1e">Prairie Diner Ltd</a>');
    expect(html.match(/href="\/employers\//g)?.length).toBe(4);
    expect(html).toContain('href="/search?noc=63200&date=since_2023q4"');
    expect(html).toContain("A past LMIA is not a job offer.");
    expect(html).toContain('href="https://www.jobbank.gc.ca/jobsearch/jobsearch?fn21=63200"');
    expect(html).toContain("earlier quarters are not counted here");
    expect(html).not.toContain(EM_DASH);
  });

  it("carry a title, a description, canonical and language links and a breadcrumb trail", async () => {
    const html = await (await get("/occupations/63200")).text();
    expect(html).toContain("<title>LMIA Records for Cooks (NOC 63200) | LMIA Watch</title>");
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/occupations/63200"/>');
    expect(html).toContain('<link rel="alternate" hreflang="fr" href="https://lmiawatch.ca/occupations/63200?lang=fr"/>');
    const description = /<meta name="description" content="([^"]*)"/.exec(html)?.[1] ?? "";
    expect(description.length).toBeGreaterThan(40);
    expect(description.length).toBeLessThanOrEqual(159 + 40); // entities count here, not on the page
    expect(html).not.toContain('name="robots"');
    const crumbs = jsonLd(html).find((d) => d["@type"] === "BreadcrumbList");
    expect(crumbs.itemListElement.map((i: any) => i.name)).toEqual(["Home", "LMIA Records by Occupation", "Cooks (NOC 63200)"]);
    expect(crumbs.itemListElement[1].item).toBe("https://lmiawatch.ca/occupations");
  });

  it("mark a page under the record threshold noindex", async () => {
    const html = await (await get("/occupations/85101")).text();
    expect(html).toContain('<meta name="robots" content="noindex"/>');
    expect(html).not.toContain('rel="canonical"');
    expect(html).toContain("Only 1 records, below the 3 a page needs");
  });

  it("answer 404 for an unknown or malformed code", async () => {
    expect((await get("/occupations/12345")).status).toBe(404);
    expect(await (await get("/occupations/12345")).text()).toContain("Occupation Not Found");
    expect((await get("/occupations/6320")).status).toBe(404);
    expect((await get("/occupations/abcde")).status).toBe(404);
  });

  it("list every occupation by broad category", async () => {
    const html = await text("/occupations");
    expect(html).toContain("<h1>LMIA Records by Occupation</h1>");
    expect(html).toContain("<h2>Sales and service occupations</h2>");
    expect(html).toContain('<a href="/occupations/63200">Cooks</a>');
    expect(html).toContain('<a href="/occupations/85101">');
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/occupations"/>');
    expect(html).toContain('href="/places"');
  });

  it("read in French", async () => {
    const html = await text("/occupations/63200?lang=fr");
    expect(html).toContain('<html lang="fr">');
    expect(html).toContain("<h1>Cuisiniers/cuisinières (CNP 63200)</h1>");
    expect(html).toContain("Postes approuvés, T1 2026 : 9, en hausse de 350,0 % par rapport au T4 2025 (2).");
    expect(html).toContain("Médiane du Guichet-Emplois : 18,00 $/h (Canada); le minimum affiché lui est inférieur de 5,6 %.");
    expect(html).toContain("Grande catégorie : Vente et services. FEER 3.");
    expect(html).toContain("Une EIMT passée n’est pas une offre d’emploi.");
    expect(html).toContain('href="https://www.guichetemplois.gc.ca/jobsearch/rechercheemplois?fn21=63200"');
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/occupations/63200?lang=fr"/>');
  });
});

describe("place pages", () => {
  it("read a province's figures", async () => {
    const html = await text("/places/mb");
    expect(html).toContain("<h1>Manitoba</h1>");
    expect(html).toContain("Approved positions in 2026 Q1: 14, up 600.0 percent from 2025 Q4 (2).");
    expect(html).toContain("Share of all positions approved in Canada in 2026 Q1: 73.7 percent.");
    expect(html).toContain("Occupation with the most records here since 2025 Q4: Cooks (NOC 63200), 6.");
    expect(html).toContain('<a href="/places/mb/winnipeg-cma">Winnipeg</a>');
    expect(html).toContain('<a href="/places/mb/winnipeg">Winnipeg</a>');
    expect(html).toContain('<a href="/occupations/63200">Cooks</a>');
    expect(html).toContain('href="/search?province=MB&date=since_2023q4"');
    expect(html).toContain('href="https://www.jobbank.gc.ca/jobsearch/jobsearch?locationstring=Manitoba"');
    // Stream mix for the newest quarters, as a share of positions: 10 of 20 in primary agriculture.
    expect(html).toContain("Primary Agriculture");
    expect(html).toContain(">50.0%<");
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/places/mb"/>');
    const crumbs = jsonLd(await (await get("/places/mb")).text()).find((d) => d["@type"] === "BreadcrumbList");
    expect(crumbs.itemListElement.map((i: any) => i.name)).toEqual(["Home", "LMIA Records by Place", "Manitoba"]);
  });

  it("read a metropolitan area with its vacancies and unemployment rate", async () => {
    const html = await text("/places/mb/winnipeg-cma");
    expect(html).toContain("<h1>Winnipeg (census metropolitan area)</h1>");
    expect(html).toContain("Job vacancies counted by Statistics Canada in all occupations, 2026 Q2: 11,315 (Winnipeg economic region), at an average offered wage of $26.00/h.");
    expect(html).toContain("A year earlier: 12,200 vacancies.");
    expect(html).toContain("three months ending 2026-09: 5.9 percent");
    // Under 6 percent, so the refusal-to-process sentence is not shown.
    expect(html).not.toContain("refuses to process");
    const crumbs = jsonLd(await (await get("/places/mb/winnipeg-cma")).text()).find((d) => d["@type"] === "BreadcrumbList");
    expect(crumbs.itemListElement.map((i: any) => i.name)).toEqual(["Home", "LMIA Records by Place", "Manitoba", "Winnipeg (census metropolitan area)"]);
    expect(crumbs.itemListElement[2].item).toBe("https://lmiawatch.ca/places/mb");
  });

  it("read a city and link its metropolitan area", async () => {
    const html = await text("/places/mb/winnipeg");
    expect(html).toContain("<h1>Winnipeg, MB</h1>");
    expect(html).toContain('<a href="/places/mb/winnipeg-cma">Winnipeg</a>');
    expect(html).toContain('href="/search?province=MB&q=Winnipeg&date=since_2023q4"');
    expect(html).toContain('href="https://www.jobbank.gc.ca/jobsearch/jobsearch?locationstring=Winnipeg%2C+MB"');
  });

  it("mark a province under the threshold noindex", async () => {
    const html = await (await get("/places/bc")).text();
    expect(html).toContain('<meta name="robots" content="noindex"/>');
  });

  it("send other spellings to the lower-case address", async () => {
    const res = await get("/places/MB?lang=fr");
    expect(res.status).toBe(301);
    expect(res.headers.get("location")).toBe("/places/mb?lang=fr");
    const city = await get("/places/Mb/Winnipeg");
    expect(city.status).toBe(301);
    expect(city.headers.get("location")).toBe("/places/mb/winnipeg");
  });

  it("answer 404 for a missing, malformed or unparseable file", async () => {
    for (const path of ["/places/mb/nowhere", "/places/zz", "/places/mb/broken", "/places/mb/a--b", "/places/manitoba"]) {
      expect((await get(path)).status, path).toBe(404);
    }
    expect(await (await get("/places/mb/nowhere")).text()).toContain("Place Not Found");
  });

  it("list provinces, metropolitan areas and cities", async () => {
    const html = await text("/places");
    expect(html).toContain("<h1>LMIA Records by Place</h1>");
    expect(html).toContain('<a href="/places/mb">Manitoba</a>');
    expect(html).toContain('<a href="/places/mb/winnipeg-cma">Winnipeg</a>');
    expect(html).toContain('<a href="/places/mb/winnipeg">Winnipeg</a>');
    expect(html).toContain('href="/occupations"');
  });

  it("read in French", async () => {
    const html = await text("/places/mb/winnipeg-cma?lang=fr");
    expect(html).toContain("<h1>Winnipeg (région métropolitaine de recensement)</h1>");
    // Only employer A's records lie in the area's postal codes: 3 positions against 2.
    expect(html).toContain("Postes approuvés, T1 2026 : 3, en hausse de 50,0 % par rapport au T4 2025 (2).");
    expect(html).toContain("Postes vacants recensés par Statistique Canada, toutes professions, T2 2026 : 11 315 (région économique Winnipeg), à un salaire horaire moyen offert de 26,00 $/h.");
    expect(html).toContain('href="https://www.guichetemplois.gc.ca/jobsearch/rechercheemplois?locationstring=Winnipeg%2C+MB"');
  });
});

describe("every new page", () => {
  const PAGES = ["/occupations", "/occupations/63200", "/occupations/85101", "/places", "/places/mb", "/places/bc", "/places/mb/winnipeg", "/places/mb/winnipeg-cma"];
  const SENTINELS = ["Approved positions", "What the Figures Show", "Looking for Work", "Stream Mix", "Census Metropolitan Areas", "Job Bank median", "not a job offer", "Records by"];

  it("fills every placeholder, has no em-dash and runs no inline script", async () => {
    for (const base of PAGES) {
      for (const path of [base, `${base}?lang=fr`]) {
        const html = await (await get(path)).text();
        const visible = html.replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "");
        expect(visible, path).not.toMatch(/\{\w+\}/);
        expect(html, path).not.toContain(EM_DASH);
        for (const tag of html.match(/<script\b[^>]*>/g) ?? []) {
          expect(/\bsrc="|type="application\/(?:ld\+)?json"/.test(tag), `${path}: ${tag}`).toBe(true);
        }
        expect(html, path).not.toContain("undefined");
        expect(html, path).not.toContain("NaN");
      }
    }
  });

  it("keeps English off the French pages", async () => {
    for (const base of PAGES) {
      const fr = await (await get(`${base}?lang=fr`)).text();
      for (const s of SENTINELS) expect(fr, `${base} still says "${s}"`).not.toContain(s);
    }
    // The sentinels are real: each is on some English page.
    const en = (await Promise.all(PAGES.map(async (p) => (await get(p)).text()))).join("\n");
    for (const s of SENTINELS) expect(en, s).toContain(s);
  });

  it("answers 503 before any data is published", async () => {
    for (const path of ["/occupations", "/occupations/63200", "/places", "/places/mb", "/places/mb/winnipeg"]) {
      expect((await get(path, testEnv(emptyAssets))).status, path).toBe(503);
    }
  });

  it("is linked once from the search page and the Data page", async () => {
    for (const path of ["/search", "/data"]) {
      const html = await (await get(path)).text();
      expect(html.match(/href="\/occupations"/g)?.length, path).toBe(1);
      expect(html.match(/href="\/places"/g)?.length, path).toBe(1);
    }
  });

  it("cites the vacancy table and its licence on the Data page", async () => {
    const html = await text("/data");
    expect(html).toContain("https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410044401");
    expect(html).toContain("job vacancy and offered wage table 14-10-0444-01");
    expect(html).toContain("NOC 2021 classification, used on the occupation and place pages, are under the Statistics Canada Open Licence.");
    const fr = await text("/data?lang=fr");
    expect(fr).toContain("https://www150.statcan.gc.ca/t1/tbl1/fr/tv.action?pid=1410044401");
  });
});
