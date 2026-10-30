// The employer directory (/places/<pp>/employers) and the related employers on
// a profile. The directory fixtures are the pipeline's export of the seed in
// pipeline/tests/test_places.py, written two employers to a page so that
// Manitoba's five run to three pages: Malo Cafe and Malo Farms, Old Times and
// Prairie Diner, Remote Ranch. British Columbia has one employer, Yukon none,
// and the directory of head offices outside Canada one.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { routeTemplate } from "../src/views";
import { emptyAssets, fakeAssets, testEnv } from "./assets";
import dirIndex from "./fixtures/directory-index.json";
import bc1 from "./fixtures/directory-bc-1.json";
import bcIndex from "./fixtures/directory-bc-index.json";
import mb1 from "./fixtures/directory-mb-1.json";
import mb2 from "./fixtures/directory-mb-2.json";
import mb3 from "./fixtures/directory-mb-3.json";
import mbIndex from "./fixtures/directory-mb-index.json";
import other1 from "./fixtures/directory-other-1.json";
import otherIndex from "./fixtures/directory-other-index.json";
import ytIndex from "./fixtures/directory-yt-index.json";
import bc from "./fixtures/place-bc.json";
import mb from "./fixtures/place-mb.json";
import placesIndex from "./fixtures/places-index.json";
import profiles from "./fixtures/profiles-a00.json";

const FILES: Record<string, unknown> = {
  "directory/index.json": dirIndex,
  "directory/mb/index.json": mbIndex,
  "directory/mb/1.json": mb1,
  "directory/mb/2.json": mb2,
  "directory/mb/3.json": mb3,
  "directory/bc/index.json": bcIndex,
  "directory/bc/1.json": bc1,
  "directory/other/index.json": otherIndex,
  "directory/other/1.json": other1,
  "directory/yt/index.json": ytIndex,
  "places/index.json": placesIndex,
  "places/mb.json": mb,
  "places/bc.json": bc,
};

// The fixtures of the other tests, plus these files, each override replacing
// or (with undefined) removing one.
function assets(overrides: Record<string, unknown> = {}): Fetcher {
  const files = { ...FILES, ...overrides };
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path in files) {
        const file = files[path];
        if (file === undefined) return new Response("not found", { status: 404 });
        const body = typeof file === "string" ? file : JSON.stringify(file);
        return new Response(body, { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input);
    },
  } as unknown as Fetcher;
}

const get = (path: string, env = testEnv(assets()), headers: Record<string, string> = {}) => app.request(path, { headers }, env);
const EM_DASH = String.fromCharCode(0x2014);

// The page's HTML with entities decoded and no-break spaces made plain.
async function text(path: string, env = testEnv(assets())): Promise<string> {
  const html = await (await get(path, env)).text();
  return html
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/[  ]/g, " ");
}

function jsonLd(html: string): any[] {
  return [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]));
}

const head = (html: string) => html.slice(0, html.indexOf("</head>"));

describe("the employer directory", () => {
  it("lists a province's employers A to Z with their city and record count", async () => {
    const res = await get("/places/mb/employers");
    expect(res.status).toBe(200);
    const html = await text("/places/mb/employers");
    expect(html).toContain("<title>Employers in Manitoba, A to Z, page 1 of 3 | LMIA Watch</title>");
    expect(html).toContain("<h1>Employers in Manitoba, A to Z, page 1 of 3</h1>");
    expect(html).toContain("Every employer with a profile on this site whose records place it in Manitoba, sorted by name: 5 in all, 2 to a page.");
    expect(html).toContain("Records counts what the profile lists");
    expect(html).toContain("This page: Malo Cafe Inc to Malo Farms Inc.");
    expect(html).toContain('<td data-label="Employer"><a href="/employers/emp-3350057c50">Malo Cafe Inc</a></td>');
    expect(html).toContain('<td data-label="City">Saint-Malo</td>');
    expect(html).toContain('<a href="/employers/emp-745ad19163">Malo Farms Inc</a>');
    expect(html.match(/href="\/employers\//g)?.length).toBe(2);
    expect(html).toContain('<td data-label="Records" class="mono num">1</td>');
    expect(html).toContain("Page 1 of 3");
    expect(html).not.toContain(EM_DASH);
  });

  it("links the neighbouring pages, every page and each initial", async () => {
    const one = await text("/places/mb/employers");
    expect(head(one)).toContain('<link rel="next" href="https://lmiawatch.ca/places/mb/employers/2"/>');
    expect(head(one)).not.toContain('rel="prev"');
    expect(one).toContain('<a href="/places/mb/employers/2" class="btn" rel="next">Next</a>');
    expect(one).not.toContain(">Previous<");
    // Initials: M on page 1 (this one), O and P on 2, R on 3.
    expect(one).toContain('<a href="/places/mb/employers" aria-current="page">M</a>');
    expect(one).toContain('<a href="/places/mb/employers/2">O</a>');
    expect(one).toContain('<a href="/places/mb/employers/2">P</a>');
    expect(one).toContain('<a href="/places/mb/employers/3">R</a>');
    // Every page, the current one unlinked, each other with its first and last name.
    expect(one).toContain('<span class="mono" aria-current="page">1</span>');
    expect(one).toContain('<a href="/places/mb/employers/2" class="mono" title="Old Times Co … Prairie Diner Ltd">2</a>');
    expect(one).toContain('<a href="/places/mb/employers/3" class="mono" title="Remote Ranch Ltd … Remote Ranch Ltd">3</a>');

    const two = await text("/places/mb/employers/2");
    expect(two).toContain("<h1>Employers in Manitoba, A to Z, page 2 of 3</h1>");
    expect(head(two)).toContain('<link rel="prev" href="https://lmiawatch.ca/places/mb/employers"/>');
    expect(head(two)).toContain('<link rel="next" href="https://lmiawatch.ca/places/mb/employers/3"/>');
    expect(two).toContain('<a href="/places/mb/employers" class="btn" rel="prev">Previous</a>');
    expect(two).toContain('<a href="/employers/emp-ad951ffc1e">Prairie Diner Ltd</a>');
    expect(two).toContain('<td data-label="Records" class="mono num">5</td>');

    const three = await text("/places/mb/employers/3");
    expect(head(three)).not.toContain('rel="next"');
    expect(three).not.toContain(">Next<");
  });

  it("carries a canonical URL, language links, a description and a breadcrumb back to the province", async () => {
    const html = await text("/places/mb/employers/2");
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/places/mb/employers/2"/>');
    expect(html).toContain('<link rel="alternate" hreflang="fr" href="https://lmiawatch.ca/places/mb/employers/2?lang=fr"/>');
    expect(html).toContain('<link rel="alternate" hreflang="x-default" href="https://lmiawatch.ca/places/mb/employers/2"/>');
    expect(html).not.toContain('name="robots"');
    const description = /<meta name="description" content="([^"]*)"/.exec(html)?.[1] ?? "";
    expect(description).toBe(
      "Employers with LMIA records in Manitoba, A to Z, page 2 of 3: Old Times Co to Prairie Diner Ltd. Each name links to the employer's records and their sources.",
    );
    expect(html).toContain(
      '<a href="/">Home</a> / <a href="/places">LMIA Records by Place</a> / <a href="/places/mb">Manitoba</a> / <a href="/places/mb/employers">Employers, A to Z</a> / Page 2',
    );
    const crumbs = jsonLd(html).find((d) => d["@type"] === "BreadcrumbList");
    expect(crumbs.itemListElement.map((i: any) => [i.name, i.item])).toEqual([
      ["Home", "https://lmiawatch.ca/"],
      ["LMIA Records by Place", "https://lmiawatch.ca/places"],
      ["Manitoba", "https://lmiawatch.ca/places/mb"],
      ["Employers, A to Z", "https://lmiawatch.ca/places/mb/employers"],
      ["Page 2", undefined],
    ]);
    const first = await text("/places/mb/employers");
    expect(first).toContain('<a href="/places/mb">Manitoba</a> / Employers, A to Z</nav>');
  });

  it("reads in French with its own canonical URL", async () => {
    const env = testEnv(assets());
    const res = await app.request("/places/mb/employers/2?lang=fr", {}, env);
    expect(res.status).toBe(200);
    const html = (await res.text()).replace(/&#39;/g, "'").replace(/[  ]/g, " ");
    expect(html).toContain("<title>Employeurs de A à Z : Manitoba, page 2 sur 3 | LMIA Watch</title>");
    expect(html).toContain("Tous les employeurs ayant un profil sur ce site dont les dossiers indiquent la province ou le territoire suivant : Manitoba.");
    expect(html).toContain("Cette page : de Old Times Co à Prairie Diner Ltd.");
    expect(html).toContain('<link rel="canonical" href="https://lmiawatch.ca/places/mb/employers/2?lang=fr"/>');
    expect(html).toContain('<link rel="prev" href="https://lmiawatch.ca/places/mb/employers?lang=fr"/>');
    expect(html).toContain('<a href="/places/mb/employers" class="btn" rel="prev">Précédente</a>');
    expect(html).toContain('<a href="/">Accueil</a> / <a href="/places">Dossiers EIMT par lieu</a> / <a href="/places/mb">Manitoba</a>');
    expect(html).toContain("<th>Ville</th>");
    expect(html).toContain('<th class="num">Dossiers</th>');
    for (const english of ["Every employer", "This page", "Records counts", "All pages", "Jump to"]) expect(html).not.toContain(english);
    expect(html).not.toContain(EM_DASH);
  });

  it("sends a differently written address to the canonical one", async () => {
    for (const [from, to] of [
      ["/places/MB/employers", "/places/mb/employers"],
      ["/places/mb/employers/1", "/places/mb/employers"],
      ["/places/mb/employers/02", "/places/mb/employers/2"],
      ["/places/Other/employers?lang=fr", "/places/other/employers?lang=fr"],
    ]) {
      const res = await get(from);
      expect(res.status, from).toBe(301);
      expect(res.headers.get("location"), from).toBe(to);
    }
  });

  it("answers 404 for a page past the end, a code with no directory and a malformed page number", async () => {
    const past = await get("/places/mb/employers/4");
    expect(past.status).toBe(404);
    expect(await past.text()).toContain("Directory Page Not Found");
    for (const path of ["/places/xx/employers", "/places/zz/employers", "/places/mb/employers/0", "/places/mb/employers/two", "/places/mb/employers/2/3"]) {
      expect((await get(path)).status, path).toBe(404);
    }
  });

  it("gives head offices outside Canada and employers without a province one list", async () => {
    const res = await get("/places/other/employers");
    expect(res.status).toBe(200);
    const html = await text("/places/other/employers");
    expect(html).toContain("<h1>Employers With a Head Office Outside Canada or No Province, A to Z, page 1 of 1</h1>");
    expect(html).toContain("whose head office is outside Canada, or whose records give no province");
    expect(html).toContain('<a href="/employers/emp-aee7d50e64">Foreign Head Office Ltd</a>');
    expect(html).toContain('<td data-label="Location">Head office outside Canada</td>');
    // No province page to go back to: the trail runs from the place index.
    expect(html).toContain('<a href="/places">LMIA Records by Place</a> / Employers, A to Z');
    expect(html).not.toContain('name="robots"');
    expect(html).not.toContain(">All pages<");
  });

  it("says when a province has no employer yet, and keeps that page out of the index", async () => {
    const res = await get("/places/yt/employers");
    expect(res.status).toBe(200);
    const html = await text("/places/yt/employers");
    expect(html).toContain("<h1>Employers in Yukon, A to Z</h1>");
    expect(html).toContain("No employer with a profile on this site has its records in Yukon yet.");
    expect(html).toContain('<meta name="robots" content="noindex"/>');
    expect((await get("/places/yt/employers/2")).status).toBe(404);
  });

  it("answers 'not published' when the data or the directory's files are missing or unreadable", async () => {
    const none = await get("/places/mb/employers", testEnv(emptyAssets));
    expect(none.status).toBe(503);
    expect(await none.text()).toContain("Data Not Published Yet");
    // A province with no directory file, a damaged index, a missing page file, a page of another directory.
    for (const [path, overrides] of [
      ["/places/nb/employers", {}],
      ["/places/mb/employers", { "directory/mb/index.json": '{"code":"mb","pages":' }],
      ["/places/mb/employers", { "directory/mb/index.json": { ...mbIndex, ranges: [] } }],
      ["/places/mb/employers/2", { "directory/mb/2.json": undefined }],
      ["/places/mb/employers/2", { "directory/mb/2.json": { ...mb2, page: 3 } }],
      ["/places/mb/employers/2", { "directory/mb/2.json": { ...mb2, rows: [{ ...mb2.rows[0], id: "javascript:alert(1)" }] } }],
    ] as [string, Record<string, unknown>][]) {
      const res = await get(path, testEnv(assets(overrides)));
      expect(res.status, `${path} ${JSON.stringify(overrides).slice(0, 60)}`).toBe(503);
    }
  });
});

describe("links to the directory", () => {
  it("from the province page, with the number of employers", async () => {
    const html = await text("/places/mb");
    expect(html).toContain('<a href="/places/mb/employers">All employers in Manitoba, A to Z</a> <span class="muted mono">5</span>');
    const fr = await text("/places/mb?lang=fr");
    expect(fr).toContain('<a href="/places/mb/employers">Tous les employeurs de A à Z : Manitoba</a>');
    // No summary file, no link.
    const bare = await text("/places/mb", testEnv(assets({ "directory/index.json": undefined })));
    expect(bare).not.toContain("/places/mb/employers");
  });

  it("from the place index, one per directory that lists anyone", async () => {
    const html = await text("/places");
    expect(html).toContain("<h2>Employers, A to Z</h2>");
    expect(html).toContain('<a href="/places/bc/employers">British Columbia</a> <span class="muted mono">1</span>');
    expect(html).toContain('<a href="/places/mb/employers">Manitoba</a> <span class="muted mono">5</span>');
    expect(html).toContain('<a href="/places/other/employers">Head office outside Canada or no province</a>');
    expect(html).not.toContain("/places/yt/employers");
  });

  it("from every profile, to the list of its province", async () => {
    const html = await text("/employers/emp-a000000001");
    expect(html).toContain('<a href="/places/bc/employers">All employers in British Columbia, A to Z</a>');
  });

  it("are named by template in the audience counts", () => {
    expect(routeTemplate("GET", "/places/mb/employers")).toEqual({ route: "/places/:prov/employers", kind: "page" });
    expect(routeTemplate("GET", "/places/other/employers/12")).toEqual({ route: "/places/:prov/employers/:page", kind: "page" });
    expect(routeTemplate("GET", "/places/mb/winnipeg")).toEqual({ route: "/places/:prov/:slug", kind: "page" });
  });
});

describe("related employers on a profile", () => {
  it("are listed near the bottom with their city when it differs", async () => {
    const html = await text("/employers/emp-a000000005");
    expect(html).toContain('<section id="related"><h2>Related Employers</h2>');
    expect(html).toContain("The list implies no connection between these employers.");
    expect(html).toContain('<li><a href="/employers/emp-a000000003">Kelowna Packers Ltd</a></li>');
    expect(html).toContain('<li><a href="/employers/emp-a000000009">Valley Orchard Growers Ltd.</a><span class="muted"> Oliver</span></li>');
    expect(html).toContain('<li><a href="/employers/emp-a000000002">Edsa Mini Mart</a><span class="muted"> Penticton</span></li>');
    // After the records, before the response and corrections cards.
    expect(html.indexOf('id="related"')).toBeGreaterThan(html.indexOf("Records</h2>"));
    expect(html.indexOf('id="related"')).toBeLessThan(html.lastIndexOf('<section class="cards two">'));
    expect(html).toContain('<a href="/places/bc/employers">All employers in British Columbia, A to Z</a>');
  });

  it("read in French", async () => {
    const html = await text("/employers/emp-a000000005?lang=fr");
    expect(html).toContain("<h2>Employeurs comparables</h2>");
    expect(html).toContain("La liste n’implique aucun lien entre ces employeurs.");
    expect(html).toContain('<a href="/places/bc/employers">Tous les employeurs de A à Z : Colombie-Britannique</a>');
  });

  it("are left off when the profile has none or the list does not read, and the profile still answers", async () => {
    expect(await text("/employers/emp-a000000001")).not.toContain('id="related"');
    const shard = structuredClone(profiles) as Record<string, any>;
    shard["emp-a000000005"].related = [{ id: "not-an-id", name: "X" }];
    const res = await get("/employers/emp-a000000005", testEnv(assets({ "profiles/a00.json": shard })));
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain('id="related"');
  });
});
