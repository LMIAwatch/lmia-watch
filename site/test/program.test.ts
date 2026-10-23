// The program conditions page against fixture JSON written by the pipeline's
// export (pipeline/lmia_pipeline/conditions.py) from its trimmed copies of the
// three canada.ca pages as read on 2026-10-22.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { DESCRIPTION_MAX } from "../src/seo";
import { emptyAssets, fakeAssets, testEnv } from "./assets";
import program from "./fixtures/program-index.json";

function assetsWith(files: Record<string, unknown>): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path in files) {
        const file = files[path];
        if (file === undefined) return new Response("not found", { status: 404 });
        return new Response(JSON.stringify(file), { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input as RequestInfo);
    },
  } as unknown as Fetcher;
}

const env = (data: unknown = program) => testEnv(assetsWith({ "program/index.json": data }));
const get = (path: string, e: object = env()) => app.request(path, {}, e);
const html = async (path: string, e?: object) => (await get(path, e)).text();
const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const decode = (s: string) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
// Tags become spaces, so a comma or full stop right after a link is drawn back to it.
const text = (page: string) =>
  nbsp(decode(page.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ")).replace(/ ([,.])(?= |$)/g, "$1");
const head = (page: string) => page.slice(0, page.indexOf("</head>"));
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v));

const TIMES_EN = "https://www.canada.ca/en/employment-social-development/services/foreign-workers/labour-market-impact-assessment-processing-times.html";
const TIMES_FR = "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/delais-traitement-demandes-evaluation-impact-marche-travail.html";
const CMA_EN = "https://www.canada.ca/en/employment-social-development/services/foreign-workers/refusal.html";
const CMA_FR = "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/refus.html";
const WAGE_EN = "https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage.html";
const WAGE_FR = "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/salaire-moyen.html";

describe("the program conditions page", () => {
  it("states what is in force on the export date", async () => {
    const page = await html("/program");
    const body = text(page);
    expect(page).toContain("<h1>Program Conditions</h1>");
    expect(body).toContain("In Force on 2026-10-22");
    expect(body).toContain("Average processing time in September 2026: 7 business days (Seasonal Agricultural Worker Program) to 98 (High-wage stream).");
    expect(body).toContain(
      "Low-wage LMIA applications are not processed in 30 of 41 census metropolitan areas (unemployment rate of 6.0 percent or more), for applications submitted from 2026-10-09 to 2027-01-07.",
    );
    expect(body).toContain("Wage thresholds for LMIAs received from 2026-07-17: $31.20 an hour (Prince Edward Island) to $48.00 (Northwest Territories).");
  });

  it("gives every processing time with its month, the advertising caveat, the source and the date read", async () => {
    const page = await html("/program");
    const body = text(page);
    expect(body).toContain("Average business days, September 2026");
    expect(body).toContain("Global Talent Stream 9");
    expect(body).toContain("Low-wage stream 82");
    expect(body).toContain("Permanent resident stream 79");
    expect(body).toContain("The times do not include the minimum advertising period an employer must complete before applying (14 days to 8 weeks, depending on the stream).");
    expect(body).toContain(
      "Source: ESDC, Labour Market Impact Assessment application processing times, page updated 2026-10-07; first read 2026-10-22, last checked 2026-10-22.",
    );
    expect(page).toContain(`href="${TIMES_EN}"`);
    expect(body).toContain("September 2026 9 22 7 98 82 79 2026-10-07 2026-10-22");
  });

  it("lists the census metropolitan areas where low-wage LMIAs are not processed, and every list read", async () => {
    const page = await html("/program");
    const body = text(page);
    expect(body).toContain("List in force for applications submitted from 2026-10-09 to 2027-01-07: 30 of 41 areas at 6.0 percent or more.");
    // Highest rate first; Winnipeg (5.9) is not on it.
    const list = body.slice(body.indexOf("List in force"), body.indexOf("Source: ESDC, Refusal"));
    expect(list).toContain("Oshawa, Ontario 9.8");
    expect(list).toContain("Ottawa-Gatineau, Ontario/Quebec 7.9");
    expect(list).toContain("St. John's, Newfoundland and Labrador 6.4");
    expect(list).not.toContain("Winnipeg");
    expect(list.indexOf("Oshawa")).toBeLessThan(list.indexOf("Kingston"));
    expect(body).toContain("Source: ESDC, Refusal to process a Labour Market Impact Assessment application, page updated 2026-10-09; first read 2026-10-22, last checked 2026-10-22.");
    expect(page).toContain(`href="${CMA_EN}"`);
    // The history: each list with its dates, its cut-off, how many areas reach it, and when it was read.
    expect(body).toContain("from 2026-10-09 to 2027-01-07 6.0 30 / 41 In force 2026-10-09 2026-10-22");
    expect(body).toContain("from 2026-07-10 to 2026-10-08 6.0 26 / 41 2026-10-09 2026-10-22");
    expect(body).toContain("from 2026-04-10 to 2026-07-09 6.0 30 / 41 2026-10-09 2026-10-22");
    // Every area's rate in each list, the ones at the cut-off in bold as on ESDC's page.
    expect(body).toContain("Winnipeg, Manitoba 5.9 5.6 6.0");
    expect(page).toContain("<strong>9.8</strong>");
    // The low-wage indicator's two bases, by quarter.
    expect(body).toContain("reads these lists for each quarter whose two applicable lists have been read here (2026 Q3 on)");
    expect(page).toContain('href="/methodology#indicators"');
  });

  it("gives the thirteen wage thresholds of each edition with the change", async () => {
    const page = await html("/program");
    const body = text(page);
    expect(body).toContain("Thresholds in force for LMIAs received from 2026-07-17.");
    expect(body).toContain("Province or territory From 2026-07-17 From 2025-06-27 Change");
    expect(body).toContain("Ontario $36.92 $36.00 +$0.92");
    expect(body).toContain("Northwest Territories $48.00 $48.00 $0.00");
    expect(body).toContain("British Columbia $38.40 $36.60 +$1.80");
    for (const name of ["Alberta", "Manitoba", "New Brunswick", "Newfoundland and Labrador", "Nova Scotia", "Nunavut", "Prince Edward Island", "Quebec", "Saskatchewan", "Yukon"]) {
      expect(body, name).toMatch(new RegExp(`${name} \\$\\d+\\.\\d\\d \\$\\d+\\.\\d\\d`));
    }
    expect(body).toContain("from 2026-07-17 In force 2026-10-07 2026-10-22");
    expect(body).toContain("from 2025-06-27 to 2026-07-16 2026-10-07 2026-10-22");
    expect(body).toContain("the province's or territory's median hourly wage plus 20 percent");
    expect(page).toContain(`href="${WAGE_EN}"`);
    expect(page).toContain('href="https://www.canada.ca/en/transparency/terms.html"');
  });

  it("reads in French, with the French pages linked", async () => {
    const page = await html("/program?lang=fr");
    const body = text(page);
    expect(page).toContain('<html lang="fr">');
    expect(page).toContain("<h1>Conditions du programme</h1>");
    expect(body).toContain("En vigueur le 2026-10-22");
    expect(body).toContain("Délai de traitement moyen en septembre 2026 : de 7 jours ouvrables (Programme des travailleurs agricoles saisonniers) à 98 (Volet des postes à haut salaire).");
    expect(body).toContain("Les demandes d’EIMT à bas salaire ne sont pas traitées dans 30 des 41 régions métropolitaines de recensement (taux de chômage de 6,0 % ou plus), pour les demandes soumises du 2026-10-09 au 2027-01-07.");
    expect(body).toContain("Seuils salariaux pour les EIMT reçues à compter du 2026-07-17 : de 31,20 $ l’heure (Île-du-Prince-Édouard) à 48,00 $ (Territoires du Nord-Ouest).");
    expect(body).toContain("Ontario 36,92 $ 36,00 $ +0,92 $");
    expect(body).toContain("Ottawa-Gatineau, Ontario/Québec 7,9");
    expect(body).toContain("Grand Sudbury, Ontario 6,2");
    expect(body).toContain("Volet des talents mondiaux 9");
    expect(body).toContain("à partir du T3 2026");
    for (const href of [TIMES_FR, CMA_FR, WAGE_FR, "https://www.canada.ca/fr/transparence/avis.html"]) expect(page).toContain(`href="${href}"`);
    for (const english of ["In Force on", "Business days", "Census metropolitan area", "Province or territory", "Source: ESDC", "first read", "Global Talent Stream"]) {
      expect(page, english).not.toContain(english);
    }
  });

  it("has a title, a short description, canonical and language links, and breadcrumbs", async () => {
    for (const lang of ["en", "fr"] as const) {
      const page = await html(lang === "fr" ? "/program?lang=fr" : "/program");
      const h = head(page);
      const url = "https://lmiawatch.ca/program";
      if (lang === "en") {
        expect(decode(h.match(/<title>([^<]*)<\/title>/)?.[1] ?? "")).toBe(
          "LMIA Program Conditions: Processing Times, Low-Wage Refusal List, Wage Thresholds | LMIA Watch",
        );
      }
      const description = decode(h.match(/<meta name="description" content="([^"]*)"/)?.[1] ?? "");
      expect(description.length, lang).toBeGreaterThan(50);
      expect(description.length, lang).toBeLessThanOrEqual(DESCRIPTION_MAX);
      expect(h).toContain(`<link rel="canonical" href="${lang === "fr" ? `${url}?lang=fr` : url}"`);
      expect(h).toContain(`<link rel="alternate" hreflang="fr" href="${url}?lang=fr"`);
      const crumbs = [...h.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
        .map((m) => JSON.parse(m[1])).find((d) => d["@type"] === "BreadcrumbList");
      expect(crumbs.itemListElement.map((i: any) => i.name)).toEqual(lang === "en" ? ["Home", "Program conditions"] : ["Accueil", "Conditions du programme"]);
      expect(page).toContain('<nav aria-label="');
    }
  });

  it("fills every placeholder, has no em-dash and runs no inline script", async () => {
    for (const path of ["/program", "/program?lang=fr"]) {
      const page = await html(path);
      const visible = page.replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "");
      expect(visible, path).not.toMatch(/\{\w+\}/);
      expect(page, path).not.toContain(EM_DASH);
      for (const tag of page.match(/<script\b[^>]*>/g) ?? []) {
        expect(/\bsrc="|type="application\/(?:ld\+)?json"/.test(tag), `${path}: ${tag}`).toBe(true);
      }
      expect(text(page), path).not.toMatch(/\b(abuse|abusers?|fraud\w*|violat\w*|offenders?|worst|cheat\w*|wrongdoers?)\b/i);
    }
  });

  it("is not in the main navigation", async () => {
    const nav = (await html("/program")).match(/<nav aria-label="[^"]*" class="main-nav"[\s\S]*?<\/nav>/)?.[0] ?? "";
    expect(nav).not.toContain('href="/program"');
  });

  it("says when nothing is in force on the export date", async () => {
    const later = clone(program);
    later.as_of = "2027-01-08";
    for (const e of later.series.cma_refusal.editions) e.status = "past";
    const body = text(await html("/program", env(later)));
    expect(body).toContain("No list read is in force on 2027-01-08.");
    expect(body).toContain("from 2026-10-09 to 2027-01-07 6.0 30 / 41 2026-10-09 2026-10-22");
  });

  it("answers 503 with no file, a broken file or a link off canada.ca", async () => {
    expect((await get("/program", testEnv(emptyAssets))).status).toBe(503);
    expect((await get("/program", testEnv(assetsWith({ "program/index.json": undefined })))).status).toBe(503);
    const res = await get("/program", env({ as_of: "2026-10-22", series: {} }));
    expect(res.status).toBe(503);
    expect(text(await res.text())).toContain("The program conditions have not been read yet.");
    const offsite = clone(program);
    offsite.series.wage_thresholds.source.en = "https://example.com/median-wage.html";
    expect((await get("/program", env(offsite))).status).toBe(503);
  });
});

describe("links to the program conditions page", () => {
  it("are in the Trends notes and on the Data page", async () => {
    const trends = await html("/trends", testEnv(assetsWith({ "trends/national.json": (await import("./fixtures/trends-national.json")).default })));
    expect(trends).toContain('<a href="/program">Program conditions</a>');
    expect(text(trends)).toContain("The quarterly lists of census metropolitan areas where low-wage LMIAs are not processed are a series rather than single rule changes");
    const data = await html("/data");
    expect(data).toContain('<a href="/program">Program conditions</a>');
    expect(data).toContain('href="https://www.canada.ca/en/transparency/terms.html"');
    expect(text(data)).toContain("2026-10-22 New Program conditions page");
    expect(text(data)).toContain("Indicator rules v0.3");
  });
});
