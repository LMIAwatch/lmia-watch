// The public records on a profile (federal funding, the Alberta employer
// record, the US carrier record): rendered in both languages with how each was
// matched, checked field by field like the rest of the profile, and credited
// on the Data and Methodology pages. Values in the fixture are invented.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { fmtMoney, grantUrl, matchText, saferUrl } from "../src/pages/employer";
import { fakeAssets, testEnv } from "./assets";
import profiles from "./fixtures/profiles-a00.json";

const ID = "emp-a000000001";
const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");

let address = 1;
const get = (path: string, assets: Fetcher = fakeAssets) =>
  app.request(path, { headers: { "cf-connecting-ip": `198.51.100.${address++ % 250}` } }, testEnv(assets));

function shardWith(edit: (p: any) => void): Fetcher {
  const shard = JSON.parse(JSON.stringify(profiles));
  edit(shard[ID]);
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url).pathname === "/data/profiles/a00.json") return new Response(JSON.stringify(shard));
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher;
}

describe("public records on the employer page", () => {
  it("shows federal funding newest first, each with its match and record link, and counts the rest", async () => {
    const res = await get(`/employers/${ID}`);
    expect(res.status).toBe(200);
    const html = await res.text();
    const grants = html.slice(html.indexOf('<section id="grants">'), html.indexOf("</section>", html.indexOf('<section id="grants">')));
    expect(grants).toContain("<h2>Federal Funding Received</h2>");
    expect(grants).toContain("matched to this employer by the business number of its federal corporation or by name and postal area");
    expect(grants).toContain("A match is not an identity");
    expect(grants.indexOf("2025-05-01")).toBeLessThan(grants.indexOf("2023-09-14"));
    expect(grants).toContain("Canada Summer Jobs");
    expect(grants).toContain("Employment and Social Development Canada");
    expect(grants).toContain("$48,500");
    expect(grants).toContain("Exact match (name and postal area)");
    expect(grants).toContain("Probable match (name and province)");
    expect(grants).toContain('href="https://search.open.canada.ca/grants/record/pacifican%2CPAC%202023%20117%2Ccurrent"');
    expect(grants).toContain("1 older matched agreement is not listed here.");
    expect(grants).toContain('href="https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013"');
    expect(html).not.toContain(EM_DASH);
  });

  it("shows the Alberta record and the US carrier record near the registry card", async () => {
    const html = await (await get(`/employers/${ID}`)).text();
    const cards = html.slice(html.indexOf('id="public-records"'), html.indexOf("<h2>Indicators</h2>"));
    expect(html.indexOf('id="public-records"')).toBeGreaterThan(html.indexOf("<h2>Registry</h2>"));
    expect(cards).toContain("<h2>Alberta Employer Record</h2>");
    expect(cards).toContain("This is Alberta&#39;s record of the employer as a workers&#39; compensation account, matched by name and city.");
    expect(cards).toContain("PINKCLOUD CLEANING &amp; HOME SERVICES LTD.");
    expect(cards).toContain("2024 (on file since 2020)");
    expect(cards).toContain("48.53 (full-time equivalents)");
    expect(cards).toContain("1 (2.06 per 100 person-years)");
    expect(cards).toContain("2 (4.12 per 100 person-years)");
    expect(cards).toContain("Not given in this release");
    expect(cards).toContain("Exact match (name and city)");
    expect(cards).toContain('href="https://open.alberta.ca/opendata/employer-records"');
    expect(cards).toContain("<h2>US Carrier Record</h2>");
    expect(cards).toContain("PINKCLOUD CLEANING &amp; HOME SERVICES LTD, doing business as PINKCLOUD HAULING");
    expect(cards).toContain("Satisfactory, rated 2019-06-11");
    expect(cards).toContain("2026-04-21 (latest census update)");
    expect(cards).toContain("Exact match (name and postal code)");
    expect(cards).toContain(`href="${saferUrl(3000001).replace(/&/g, "&amp;")}"`);
  });

  it("says the same in French", async () => {
    const html = nbsp(await (await get(`/employers/${ID}?lang=fr`)).text());
    expect(html).toContain("<h2>Financement fédéral reçu</h2>");
    expect(html).toContain("Une correspondance n’est pas une identité");
    expect(html).toContain("Emplois d&#39;été Canada");
    // A program with no French name shows the English one.
    expect(html).toContain("Business Scale-up and Productivity");
    expect(html).toContain("Développement économique Canada pour le Pacifique");
    expect(html).toContain("48 500 $");
    expect(html).toContain("Correspondance exacte (nom et secteur postal)");
    expect(html).toContain("1 accord jumelé plus ancien n’est pas affiché ici.");
    expect(html).toContain("<h2>Dossier d’employeur de l’Alberta</h2>");
    expect(html).toContain("Il s’agit du dossier que tient l’Alberta sur l’employeur en tant que compte d’indemnisation des accidents du travail, jumelé par le nom et la ville.");
    expect(html).toContain("48,53 (équivalents temps plein)");
    expect(html).toContain("1 (2,06 par 100 années-personnes)");
    expect(html).toContain("<h2>Dossier de transporteur aux États-Unis</h2>");
    expect(html).toContain("Satisfaisante, cote du 2019-06-11");
    expect(html).not.toContain("Federal Funding Received");
    expect(html).not.toContain(EM_DASH);
  });

  it("leaves the sections out of a profile without records, and of a shard written before the sources", async () => {
    for (const id of ["emp-a000000005", "emp-a000000002"]) {
      const res = await get(`/employers/${id}`);
      expect(res.status, id).toBe(200);
      const html = await res.text();
      expect(html).not.toContain("Federal Funding Received");
      expect(html).not.toContain('id="public-records"');
    }
    const api = (await (await get("/api/employers/emp-a000000002")).json()) as Record<string, unknown>;
    expect([api.grants, api.grants_total, api.alberta, api.us_carrier]).toEqual([[], 0, [], []]);
  });

  it("treats a profile with an unreadable record as missing; null where the export writes it is fine", async () => {
    const bad: [string, (p: any) => void][] = [
      ["grant value text", (p) => { p.grants[0].agreement_value = "48500"; }],
      ["grant ref null", (p) => { p.grants[0].ref_number = null; }],
      ["grant grade removed", (p) => { delete p.grants[0].grade; }],
      ["grants not a list", (p) => { p.grants = {}; }],
      ["grants_total text", (p) => { p.grants_total = "3"; }],
      ["alberta year null", (p) => { p.alberta[0].year = null; }],
      ["alberta claims text", (p) => { p.alberta[0].lost_time_claims = "1"; }],
      ["carrier dot text", (p) => { p.us_carrier[0].dot_number = "3000001"; }],
      ["carrier element null", (p) => { p.us_carrier = [null]; }],
    ];
    for (const [label, edit] of bad) {
      for (const path of [`/employers/${ID}`, `/api/employers/${ID}`]) {
        expect((await get(path, shardWith(edit))).status, `${path} ${label}`).toBe(404);
      }
    }
    const nulls = shardWith((p) => {
      Object.assign(p.grants[0], { department_en: null, department_fr: null, program_en: null, program_fr: null, agreement_value: null, start_date: null, end_date: null, agreement_type: null });
      Object.assign(p.alberta[0], { first_year: null, city: null, industry: null, person_years: null, lost_time_claims: null, lost_time_rate: null, disabling_injuries: null, disabling_rate: null, fatalities: null, cor_year: 2023, trade_name: null });
      Object.assign(p.us_carrier[0], { dba_name: null, city: null, province: null, postal_code: null, status: null, power_units: null, drivers: null, safety_rating: null, safety_rating_date: null, record_date: null });
      p.grants_total = 1;
    });
    const res = await get(`/employers/${ID}`, nulls);
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("Held in 2023");
    expect(html).toContain("Not rated");
    expect(html).toContain("esdc-edsc");
    // A count below the agreements listed is read as the agreements listed.
    expect(html).not.toContain("older matched agreement");
  });

  it("formats and links as the source does", () => {
    expect(grantUrl({ owner_org: "aafc-aac", ref_number: "235-2018-2019-Q3-00005" }))
      .toBe("https://search.open.canada.ca/grants/record/aafc-aac%2C235-2018-2019-Q3-00005%2Ccurrent");
    expect(fmtMoney(1461108, "en")).toBe("$1,461,108");
    expect(nbsp(fmtMoney(1461108, "fr"))).toBe("1 461 108 $");
    expect(fmtMoney(null, "en")).toBe("n/a");
    expect(matchText("en", "probable", "business_number")).toBe("Probable match (business number of its federal corporation)");
    expect(matchText("en", "exact", "unknown_basis")).toBe("Exact match");
  });
});

describe("the sources are credited", () => {
  const licence = (html: string) => html.slice(html.indexOf('<h2 id="licence">'), html.indexOf('<h2 id="changelog">'));

  it("on the Data page, with a licence row and a link each", async () => {
    const lic = licence(await (await get("/data")).text());
    expect(lic).toContain("Federal grants and contributions on profiles and in the API");
    expect(lic).toContain("Alberta workers&#39; compensation figures on profiles and in the API");
    expect(lic).toContain('<a href="https://open.alberta.ca/licence">Open Government Licence, Alberta</a>: reuse, commercial or not, with attribution. Contains information licensed under the Open Government Licence, Alberta.');
    expect(lic).toContain("US carrier records on profiles and in the API");
    expect(lic).toContain("A work of the United States government, in the public domain.");
    expect(lic).toContain('<a href="https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013">disclosure of federal grants and contributions</a>');
    expect(lic).toContain('<a href="https://open.alberta.ca/opendata/employer-records">Alberta Employer Records</a>');
    expect(lic).toContain('<a href="https://data.transportation.gov/d/az4n-8mr2">US FMCSA Company Census</a>');
    expect(lic).toContain("None of them feeds the indicators.");
    const fr = nbsp(licence(await (await get("/data?lang=fr")).text()));
    expect(fr).toContain("Subventions et contributions fédérales dans les profils et l’API");
    expect(fr).toContain("Œuvre du gouvernement des États-Unis, dans le domaine public.");
    expect(fr).toContain("Aucun n’entre dans les indicateurs.");
  });

  it("on the Methodology page, with a source row each and the matching rule", async () => {
    const html = await (await get("/methodology")).text();
    expect(html).toContain("Proactive Disclosure of Grants and Contributions (federal departments, open.canada.ca)");
    expect(html).toContain("Alberta Employer Records (Alberta Jobs, Economy, Trade and Immigration, open.alberta.ca)");
    expect(html).toContain("US FMCSA Company Census (data.transportation.gov)");
    expect(html.split("Shown on profiles only; not used by the indicators").length - 1).toBe(3);
    expect(html).toContain("A name alone never matches");
    const fr = nbsp(await (await get("/methodology?lang=fr")).text());
    expect(fr).toContain("Un nom seul ne suffit jamais");
  });
});
