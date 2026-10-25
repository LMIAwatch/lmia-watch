// The international-candidates page, the profile sections, the methodology's
// #express-entry block, the Data page's lists, the nav and the watchdog's notices.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { t } from "../src/i18n";
import { isIntlFile, reasonSentences } from "../src/pages/international";
import { routeTemplate } from "../src/views";
import { collectAlerts, readStatus } from "../src/watchdog";
import { emptyAssets, makeFakeAssets, testEnv } from "./assets";
import international from "./fixtures/international-index.json";

const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const get = (path: string, assets?: Fetcher) => app.request(path, {}, testEnv(assets));

// The fixtures with the international file replaced (or removed with null).
function withIntl(body: unknown): Fetcher {
  const base = makeFakeAssets();
  return {
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(input, init);
      if (new URL(req.url).pathname === "/data/international/index.json") {
        return body === null ? new Response("not found", { status: 404 }) : new Response(JSON.stringify(body));
      }
      return base.fetch(req);
    },
  } as unknown as Fetcher;
}

describe("the international-candidates page", () => {
  it("renders the lede, the change, the counts, the grades and the lists in English", async () => {
    const res = await get("/international");
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("<h1>Open to International Candidates</h1>");
    expect(html).toContain("These are signals, not records of job offers.");
    expect(html).toContain('<a href="/methodology#express-entry">');
    expect(html).toContain(">8,032<");          // live postings
    expect(html).toContain(">6,946<");          // without an LMIA request
    expect(html).toContain("The November 3, 2026 Change");
    expect(html).toContain("https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/check-score/high-wage.html");
    expect(html).toContain("as read on 2026-10-25 (page dated 2026-10-16): 186 occupations");
    // The chart carries the change date as a numbered marker, with its legend.
    expect(html).toContain('class="mark"');
    expect(html).toContain("1 November 3, 2026: a job offer for Express Entry no longer needs an LMIA.");
    // Breakdowns.
    expect(html).toContain("Live Postings Without an LMIA Request, by Grade");
    expect(html).toContain("Software engineers and designers");
    expect(html).toContain(">70 points<");
    expect(html).toContain(">not listed<");
    expect(html).toContain("Not recorded");   // the UN province bucket
    expect(html).not.toContain(EM_DASH);
  });

  it("separates what the employer selected from what the site inferred on every row", async () => {
    const html = await (await get("/international")).text();
    const start = html.indexOf('class="restack intl-recent"');
    const rows = html.slice(start, html.indexOf("</table>", start)).split("<tr>").slice(2);
    expect(rows).toHaveLength(international.recent.length);
    for (const row of rows) {
      expect(row).toContain("Employer selected:");
      expect(row).toContain("The employer marked this posting open to international candidates and requested no LMIA.");
      expect(row).toContain("Site inferred:");
      expect(row).toContain("A posting does not show that a job offer was made.");
    }
    expect(rows[0]).toContain("Its occupation is on IRCC&#39;s high-wage list (70 points).");
    expect(rows[0]).toContain('<span class="badge grade-A">Grade A</span>');
    expect(rows[1]).toContain("Its text names Express Entry: “Express Entry”.");
    expect(rows[1]).toContain("Its text offers help with permanent residence: “PR sponsorship”.");
    // LMIA history is context, linked to the profile, never a reason.
    expect(rows[1]).toContain('href="/employers/emp-a000000008"');
    expect(rows[1]).toContain("(never used in a grade)");
    expect(rows[2]).toContain("Its occupation is TEER 0 and not on IRCC&#39;s high-wage list.");
    expect(rows[3]).toContain("outside the TEER 0 to 3 levels Express Entry asks for");
    expect(rows[3]).toContain("no longer listed");
    // Job Bank links only.
    expect(rows[0]).toContain('href="https://www.jobbank.gc.ca/jobsearch/jobposting/50571474"');
  });

  it("shows the designated-employer lists with their state", async () => {
    const html = await (await get("/international")).text();
    const section = html.slice(html.indexOf('id="registers"'));
    expect(section).toContain("Atlantic Immigration Program");
    expect(section).toContain("Francophone Community Immigration Pilot");
    expect(section).toContain("Kelowna, BC");
    expect(section).toContain("Read 2026-10-12");
    expect(section).toContain("PDF, not yet readable");
    expect(section).toContain("Not read lately; last good read 2026-10-10");
    expect(section).toContain("638 employers listed on the lists read; 43 of them matched");
  });

  it("says the same in French, with French typography and no English left", async () => {
    const html = nbsp(await (await get("/international?lang=fr")).text());
    expect(html).toContain("<h1>Ouvert aux candidats internationaux</h1>");
    expect(html).toContain("Ce sont des signaux, pas des dossiers d’offres d’emploi.");
    expect(html).toContain("L’employeur a ouvert cette annonce aux candidats internationaux et n’a demandé aucune EIMT.");
    expect(html).toContain("Une annonce ne montre pas qu’une offre d’emploi a été faite.");
    expect(html).toContain("Son texte nomme Entrée express : « Express Entry ».");
    expect(html).toContain("8 032");
    expect(html).toContain("verifier-note/salaire-eleve.html");
    for (const english of ["Employer selected", "Site inferred", "These are signals", "Grade A<"]) expect(html).not.toContain(english);
  });

  it("carries a canonical URL, both language versions and a description, and is indexable", async () => {
    for (const [path, canonical] of [["/international", "https://lmiawatch.ca/international"], ["/international?lang=fr", "https://lmiawatch.ca/international?lang=fr"]]) {
      const html = await (await get(path)).text();
      expect(html).toContain(`<link rel="canonical" href="${canonical}"/>`);
      expect(html).toContain('hreflang="fr" href="https://lmiawatch.ca/international?lang=fr"');
      expect(html).toContain('hreflang="en" href="https://lmiawatch.ca/international"');
      expect(html).not.toContain('name="robots"');
      const desc = /<meta name="description" content="([^"]+)"/.exec(html)?.[1] ?? "";
      expect(desc.length).toBeGreaterThan(60);
      expect(desc.length).toBeLessThanOrEqual(159);
    }
  });

  it("answers 503 with the lede when the file is missing or malformed, never an error", async () => {
    for (const body of [null, { ...international, recent: [{ id: "x" }] }, { ...international, daily: "no" }, []]) {
      const res = await get("/international", withIntl(body));
      expect(res.status).toBe(503);
      const html = await res.text();
      expect(html).toContain("has not run yet");
      expect(html).toContain('<a href="/methodology#express-entry">');
    }
    expect((await get("/international", emptyAssets)).status).toBe(503);
  });

  it("refuses links to other hosts in the file", () => {
    const bad = JSON.parse(JSON.stringify(international));
    bad.recent[0].url = "https://example.com/jobsearch/jobposting/1";
    expect(isIntlFile(bad)).toBe(false);
    const badReg = JSON.parse(JSON.stringify(international));
    badReg.registers[0].page_url = "javascript:alert(1)";
    expect(isIntlFile(badReg)).toBe(false);
    expect(isIntlFile(international)).toBe(true);
  });

  it("builds the reason sentences from the reason keys", () => {
    const r = reasonSentences("en", ["intl", "no_lmia", "full_time", "not_permanent", "no_noc"], null);
    expect(r.selected).toEqual([
      "The employer marked this posting open to international candidates and requested no LMIA.",
      "The work is full-time, not permanent.",
    ]);
    expect(r.inferred).toEqual(["The posting gives no NOC 2021 code."]);
    expect(reasonSentences("en", ["intl", "no_lmia", "not_full_time", "not_permanent"], "65201").selected[1]).toBe(
      "The work is neither full-time nor permanent.");
  });

  it("is in the nav, marked active on its own page", async () => {
    const html = await (await get("/")).text();
    expect(html).toContain('<a href="/international">International</a>');
    const own = await (await get("/international")).text();
    expect(own).toContain('<a href="/international" class="active" aria-current="page">International</a>');
    expect(routeTemplate("GET", "/international")).toEqual({ route: "/international", kind: "page" });
  });
});

describe("the employer profile", () => {
  it("lists the employer's postings open to international candidates and its designated-employer listing", async () => {
    const html = await (await get("/employers/emp-a000000008")).text();
    const intl = html.slice(html.indexOf('<section id="international">'), html.indexOf("</section>", html.indexOf('<section id="international">')));
    expect(intl).toContain("Postings Open to International Candidates");
    expect(intl).toContain('<span class="badge grade-B">Grade B</span>');
    expect(intl).toContain("The employer marked this posting open to international candidates and requested no LMIA.");
    expect(intl).toContain("LMIA requested (no grade)");
    expect(intl).toContain("A posting does not show that a job offer was made.");
    expect(intl).toContain('href="/international"');
    const records = html.slice(html.indexOf('id="public-records"'));
    expect(records).toContain("Designated employer, Atlantic Immigration Program (Newfoundland and Labrador), listed since 2026-10-12");
    expect(records).toContain("Exact match (name and city)");
    expect(records).toContain("Still listed as read 2026-10-12");
    expect(records).toContain("2023-03-14");
    expect(html).not.toContain(EM_DASH);
  });

  it("says the same in French", async () => {
    const html = nbsp(await (await get("/employers/emp-a000000008?lang=fr")).text());
    expect(html).toContain("Annonces ouvertes aux candidats internationaux");
    expect(html).toContain("Employeur désigné, Programme d’immigration au Canada atlantique (Terre-Neuve-et-Labrador), inscrit depuis le 2026-10-12");
    expect(html).toContain("EIMT demandée (sans catégorie)");
  });

  it("shows neither section for an employer without them", async () => {
    const html = await (await get("/employers/emp-a000000001")).text();
    expect(html).not.toContain('<section id="international">');
    expect(html).not.toContain("Designated employer,");
  });
});

describe("the methodology's November 3 section", () => {
  it("opens the page, before the sources, as a highlighted block with IRCC's links", async () => {
    const html = await (await get("/methodology")).text();
    const block = html.indexOf('<section class="ee-block" id="express-entry"');
    expect(block).toBeGreaterThan(0);
    expect(block).toBeLessThan(html.indexOf('<h2 id="sources">'));
    expect(html.indexOf('<a href="#express-entry">')).toBeLessThan(html.indexOf('<a href="#sources">'));
    const section = html.slice(block, html.indexOf("</section>", block));
    expect(section).toContain("The November 3, 2026 Change to Express Entry");
    expect(section).toContain("news/2026/10/canada-refocusing-express-entry");
    expect(section).toContain("express-entry/documents/job-offer.html");
    expect(section).toContain("express-entry/check-score/high-wage.html");
    expect(section).toContain("A: open to international candidates, no LMIA requested, an occupation on IRCC&#39;s high-wage list, full-time and permanent");
    expect(section).toContain("B: open to international candidates, no LMIA requested, an occupation of TEER 0 to 3");
    expect(section).toContain("C: any other posting");
    expect(section).toContain("never part of a grade");
    expect(section).toContain("Atlantic Immigration Program (New Brunswick, Nova Scotia, Prince Edward Island, Newfoundland and Labrador)");
    expect(section).toContain("No rule requires an employer to advertise");
    expect(section).toContain("Offers made to people already working for the employer");
    expect(section).toContain("Every count is a floor");
    expect(section).toContain("existed before November 3");
    expect(section).toContain("Indeed, LinkedIn, Glassdoor");
    expect(section).toContain('href="/international"');
    expect(section).toContain('href="/data#registers"');
    expect(section).not.toContain(EM_DASH);
    // The three new sources have rows in the sources table.
    expect(html).toContain("search filter fglo=1): the 48-hour Atom feed");
    expect(html).toContain("IRCC, High-wage occupations and how we assess them (canada.ca)");
    expect(html).toContain("Designated-employer lists: Atlantic Immigration Program (NB, NS, PE, NL)");
  });

  it("in French too", async () => {
    const html = nbsp(await (await get("/methodology?lang=fr")).text());
    const block = html.indexOf('id="express-entry"');
    expect(block).toBeGreaterThan(0);
    const section = html.slice(block, html.indexOf("</section>", block));
    expect(section).toContain("Le changement du 3 novembre 2026 dans Entrée express");
    expect(section).toContain("nouvelles/2026/10/le-canada-reoriente");
    expect(section).toContain("entree-express/documents/offre-emploi.html");
    expect(section).toContain("verifier-note/salaire-eleve.html");
    expect(section).toContain("FEER 0 à 3");
  });
});

describe("the Data page", () => {
  it("cites the facet, IRCC's list and each designated-employer list with its terms", async () => {
    const html = await (await get("/data")).text();
    expect(html).toContain('href="https://www.jobbank.gc.ca/jobsearch/jobsearch?fglo=1"');
    expect(html).toContain("check-score/high-wage.html");
    const table = html.slice(html.indexOf('<h3 id="registers">'));
    expect(table).toContain("Atlantic Immigration Program, <a href=\"https://www.gov.nl.ca/immigration/");
    expect(table).toContain('<a href="https://www.gov.nl.ca/disclaimer/" rel="nofollow noopener">gov.nl.ca disclaimer</a>');
    expect(table).toContain("The community website&#39;s copyright (all rights reserved)");
    expect(table).toContain(">PDF<");
    const lic = html.slice(html.indexOf('<h2 id="licence">'), html.indexOf('<h2 id="changelog">'));
    expect(lic).toContain("Postings open to international candidates (Job Bank)");
    expect(lic).toContain("none is under an open licence");
  });

  it("leaves the lists table out when stats.json has none", async () => {
    const base = makeFakeAssets();
    const stats = await (await base.fetch(new Request("https://assets.invalid/data/stats.json"))).json() as Record<string, unknown>;
    delete stats.registers;
    const assets = {
      fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
        const req = input instanceof Request ? input : new Request(input, init);
        return new URL(req.url).pathname === "/data/stats.json" ? new Response(JSON.stringify(stats)) : base.fetch(req);
      },
    } as unknown as Fetcher;
    const res = await get("/data", assets);
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain('<h3 id="registers">');
  });
});

describe("the watchdog", () => {
  it("emails each notice the run recorded, and drops an unreadable one", () => {
    const { status } = readStatus({
      run_at: "2026-10-20T00:48:00Z", ok: true, stages: [],
      notices: [{ source: "high_wage", detail: "IRCC high-wage list changed: 2 codes added, 0 removed" }, { bad: true }, "x"],
    });
    expect(status?.notices).toEqual([{ source: "high_wage", detail: "IRCC high-wage list changed: 2 codes added, 0 removed" }]);
    const alerts = collectAlerts({
      now: new Date("2026-10-20T06:00:00Z"), dataAsOf: "2026-10-20", backupUploaded: new Date("2026-10-20T00:50:00Z"), status,
    });
    expect(alerts).toEqual(["The last run noted (high_wage): IRCC high-wage list changed: 2 codes added, 0 removed"]);
  });
});

describe("the notice bar", () => {
  it("points at the methodology section and keeps the IRCC link", async () => {
    for (const lang of ["en", "fr"] as const) {
      const html = await (await get(lang === "fr" ? "/?lang=fr" : "/")).text();
      const bar = /<div class="notice-ee">([\s\S]*?)<\/div>/.exec(html)?.[1] ?? "";
      expect(bar).toContain(`<a href="/methodology#express-entry">${t(lang, "notice_ee.track")}</a>`);
      expect(bar.indexOf("/methodology#express-entry")).toBeLessThan(bar.indexOf("canada.ca"));
    }
  });
});

describe("the high-wage list version", () => {
  it("is dated on the methodology page, in both languages", async () => {
    const en = await (await get("/methodology")).text();
    expect(en).toContain("adopts a new version the night it appears");
    expect(en).toContain("The version in use was read on 2026-10-25 (page dated 2026-10-16): 186 occupations.");
    const fr = nbsp(await (await get("/methodology?lang=fr")).text());
    expect(fr).toContain("La version utilisée a été relevée le 2026-10-25 (page datée du 2026-10-16) : 186 professions.");
  });

  it("says when IRCC's page could not be read at the last check", async () => {
    const stale = { ...international, high_wage: { ...international.high_wage, stale: true } };
    const html = await (await get("/international", withIntl(stale))).text();
    expect(html).toContain("could not be read at the last check; the grades keep this version until it can.");
    expect(await (await get("/international")).text()).not.toContain("could not be read at the last check");
  });
});
