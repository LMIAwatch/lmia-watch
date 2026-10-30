// The international-candidates page, the profile sections, the methodology's
// #express-entry block, the Data page's lists, the nav and the watchdog's notices.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { t } from "../src/i18n";
import { isIntlFile, reasonSentences } from "../src/pages/international";
import { routeTemplate } from "../src/views";
import { collectAlerts, collectNotices, readStatus } from "../src/watchdog";
import { emptyAssets, makeFakeAssets, testEnv } from "./assets";
import international from "./fixtures/international-index.json";
import profiles from "./fixtures/profiles-a00.json";

const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const get = (path: string, assets?: Fetcher) => app.request(path, {}, testEnv(assets));

// The fixtures with some files replaced or added (removed with null).
function withFiles(files: Record<string, unknown>): Fetcher {
  const base = makeFakeAssets();
  return {
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(input, init);
      const path = new URL(req.url).pathname.replace(/^\/data\//, "");
      if (path in files) {
        const body = files[path];
        return body === null ? new Response("not found", { status: 404 }) : new Response(JSON.stringify(body));
      }
      return base.fetch(req);
    },
  } as unknown as Fetcher;
}

// The fixtures with the international file replaced (or removed with null).
const withIntl = (body: unknown): Fetcher => withFiles({ "international/index.json": body });

// The occupation index with a page for 21231 and none for 60030.
const occIndex = {
  threshold: 3,
  rows: [
    { noc: "21231", indexed: true, records: 9, title: { en: "Software engineers and designers", fr: "Ingénieurs et concepteurs en logiciel" } },
    { noc: "60030", indexed: false, records: 1, title: { en: "Restaurant and food service managers", fr: "Gestionnaires de la restauration" } },
  ],
};

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
    // The chart carries the baseline and the change date as numbered lines, in
    // date order, each with its legend line; the note says the days before the
    // baseline undercount.
    expect(html.match(/class="mark"/g)?.length).toBe(2 * 3);    // two lines in each of three panels
    expect(html).toContain('<span class="legend-line">1 October 9, 2026: tracking began (the first full sweep of the filter).</span>');
    expect(html).toContain('<span class="legend-line">2 November 3, 2026: a job offer for Express Entry no longer needs an LMIA.</span>');
    expect(html).toContain("Tracking began on 2026-10-09 (line 1). The lighter bars before that date undercount, because postings that had already closed before the first sweep were never seen. Grades fill in as posting pages are read");
    // Breakdowns.
    expect(html).toContain("Live Postings Without an LMIA Request, by Grade");
    expect(html).toContain("Software engineers and designers");
    expect(html).toContain(">70 points<");
    expect(html).toContain(">not listed<");
    expect(html).toContain("Not recorded");   // the UN province bucket
    expect(html).not.toContain(EM_DASH);
  });

  it("draws the days before the baseline a lighter step, and only those", async () => {
    const html = await (await get("/international")).text();
    const bar = (title: string) => new RegExp(`<rect class="([^"]+)"[^>]*><title>${title}</title>`).exec(html)?.[1];
    // The no-LMIA panel: A + B + C + not graded.
    expect(bar("2026-10-06: 10")).toBe("bar bar-light");
    expect(bar("2026-10-08: 20")).toBe("bar bar-light");
    expect(bar("2026-10-09: 44")).toBe("bar");
    expect(bar("2026-10-12: 37")).toBe("bar");
    // Three early days in each of the two posting-date panels, and the facet panel's own light bars.
    expect(html.match(/class="bar bar-light"/g)?.length).toBe(3 * 2 + international.facet.length);
  });

  it("keeps one line and the earlier note for a series that starts at the baseline", async () => {
    const fromBaseline = { ...international, daily: international.daily.filter((r) => r.day >= international.baseline) };
    const html = await (await get("/international", withIntl(fromBaseline))).text();
    expect(html.match(/class="mark"/g)?.length).toBe(3);
    expect(html).toContain('<span class="legend-line">1 November 3, 2026: a job offer for Express Entry no longer needs an LMIA.</span>');
    expect(html).toContain("from 2026-10-09, the day this tracking began");
    // Only the facet panel's bars are light, as before.
    expect(html.match(/class="bar bar-light"/g)?.length).toBe(international.facet.length);
    expect(html).not.toContain("tracking began (the first full sweep");
  });

  it("lists occupations by NOC code, linked where the occupation has a page, the title in the tooltip and read out", async () => {
    const plain = await (await get("/international")).text();
    // No occupation index: plain codes, the title still there for the tooltip and screen readers.
    expect(plain).toContain('<span title="Software engineers and designers"><span class="mono">21231</span><span class="noc-name"> Software engineers and designers</span></span>');
    expect(plain).not.toContain('href="/occupations/21231"');
    const html = await (await get("/international", withFiles({ "occupations/index.json": occIndex }))).text();
    expect(html).toContain('<a href="/occupations/21231" title="Software engineers and designers"><span class="mono">21231</span><span class="noc-name"> Software engineers and designers</span></a>');
    expect(html).not.toContain('href="/occupations/60030"');
    expect(html).toContain('<span title="Restaurant and food service managers"><span class="mono">60030</span>');
    // The two breakdowns restack on a phone, each figure with its label.
    expect(html.match(/<table class="restack restack-compact intl-split">/g)?.length).toBe(2);
    expect(html).toContain('<td class="mono num" data-label="Not graded yet">');
    const fr = nbsp(await (await get("/international?lang=fr", withFiles({ "occupations/index.json": occIndex }))).text());
    expect(fr).toContain('<a href="/occupations/21231" title="Ingénieurs/ingénieures et concepteurs/conceptrices en logiciel">');
  });

  it("scrolls the recent postings inside their own box, header pinned", async () => {
    const html = await (await get("/international")).text();
    expect(html).toContain('<div class="table-wrap bordered scroll-y scroll-tall"><table class="restack intl-recent">');
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
    expect(section).toContain("PDF, not readable");
    expect(section).toContain("Last read 2026-10-10");
    expect(section).toContain("2,160 employers listed on the lists read; 55 of them matched");
  });

  // One row of the lists table by the place it names.
  const regRow = (html: string, place: string) => {
    const at = html.indexOf(place, html.indexOf("<tbody>", html.indexOf('id="registers"')));
    return html.slice(html.lastIndexOf("<tr>", at), html.indexOf("</tr>", at));
  };
  const countCell = (row: string) => /<td class="mono num" data-label="[^"]+">(.*?)<\/td>/.exec(row)?.[1];

  it("shows a list loaded by hand, a blocked site and a list never read for what they are", async () => {
    const html = await (await get("/international")).text();
    const ns = regRow(html, "Nova Scotia");
    expect(ns).toContain("By hand, list of 2026-07-01");
    expect(countCell(ns)).toBe("1,522");
    const pe = regRow(html, "Prince Edward Island");
    expect(pe).toContain("Blocked by the site");
    expect(pe).not.toContain("not readable");
    expect(html).toContain("answers every automated reader with a bot challenge");
    expect(countCell(pe)).toBe("");                 // blank, never 0
    const nb = regRow(html, "New Brunswick");
    expect(nb).toContain("PDF, not readable");
    expect(countCell(nb)).toBe('<span aria-hidden="true">–</span><span class="visually-hidden">Never read</span>');
    expect(countCell(regRow(html, "Kelowna, BC"))).toBe("52");   // failing, its last good rows kept
    const section = html.slice(html.indexOf('id="registers"'));
    expect(section).toContain(
      "Atlantic Immigration Program (Nova Scotia): the employers listed come from the province&#39;s list dated 2026-07-01, " +
      "loaded by hand on 2026-10-30 because the province&#39;s server does not answer the nightly run. " +
      "The run checks every night for a newer edition.");
    expect(section).not.toContain(EM_DASH);
  });

  it("says so in French", async () => {
    const html = nbsp(await (await get("/international?lang=fr")).text());
    expect(regRow(html, "Nouvelle-Écosse")).toContain("À la main, liste du 2026-07-01");
    expect(regRow(html, "Île-du-Prince-Édouard")).toContain("Bloquée par le site");
    expect(regRow(html, "Nouveau-Brunswick")).toContain("Jamais lue");
    expect(html).toContain(
      "Programme d’immigration au Canada atlantique (Nouvelle-Écosse) : les employeurs inscrits proviennent de la liste " +
      "de la province datée du 2026-07-01, chargée à la main le 2026-10-30 parce que le serveur de la province ne répond " +
      "pas au relevé de nuit. Le relevé vérifie chaque nuit si une édition plus récente est publiée.");
  });

  it("refuses a malformed record of a copy loaded by hand", () => {
    for (const snapshot of [{ list_date: "2026-07-01", loaded_on: "yesterday" }, { loaded_on: "2026-10-30" }, "2026-10-30"]) {
      const bad = JSON.parse(JSON.stringify(international));
      bad.registers.find((r: { key: string }) => r.key === "aip_ns").snapshot = snapshot;
      expect(isIntlFile(bad)).toBe(false);
    }
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
    expect(html).toContain("1 9 octobre 2026 : début du suivi (premier relevé complet du filtre).");
    expect(html).toContain("2 3 novembre 2026 : une offre d’emploi pour Entrée express n’exige plus d’EIMT.");
    expect(html).toContain("Les barres plus pâles qui précèdent cette date sont incomplètes");
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

  it("names the list's date and the hand load for a listing read from a copy loaded by hand", async () => {
    const shard = JSON.parse(JSON.stringify(profiles)) as Record<string, { designated: Record<string, unknown>[] }>;
    shard["emp-a000000008"].designated = [{
      list: "aip_ns", program: "AIP", jurisdiction: "NS", community: null, name: "Haveli Restaurant Inc.", location: null,
      designated_on: null, first_seen: "2026-10-30", last_seen: "2026-10-30", current: true,
      url: "https://liveinnovascotia.com/atlantic-immigration-program", grade: "probable", basis: "name_province",
      snapshot: { list_date: "2026-07-01", loaded_on: "2026-10-30" },
    }];
    const assets = withFiles({ "profiles/a00.json": shard });
    const html = await (await get("/employers/emp-a000000008", assets)).text();
    const records = html.slice(html.indexOf('id="public-records"'));
    expect(records).toContain("Designated employer, Atlantic Immigration Program (Nova Scotia), listed since 2026-10-30");
    expect(records).toContain("Listed on the list dated 2026-07-01, loaded by hand on 2026-10-30");
    expect(records).not.toContain("Still listed as read");
    const fr = nbsp(await (await get("/employers/emp-a000000008?lang=fr", assets)).text());
    expect(fr).toContain("Inscrit sur la liste datée du 2026-07-01, chargée à la main le 2026-10-30");
    // A malformed record makes the shard unreadable, like any other malformed row.
    shard["emp-a000000008"].designated[0].snapshot = { list_date: "July 1", loaded_on: "2026-10-30" };
    expect((await get("/employers/emp-a000000008", withFiles({ "profiles/a00.json": shard }))).status).toBe(404);
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
    expect(section).toContain("Programme d’immigration au Canada atlantique (Nouvelle-Écosse) : les employeurs inscrits proviennent");
    expect(section).toContain(
      "Programme d’immigration au Canada atlantique (Île-du-Prince-Édouard) : le site de la province bloque les lecteurs " +
      "automatisés, donc sa liste n’est pas lue.");
  });

  it("names the list loaded by hand in the lists paragraph and the blocked site in the limits", async () => {
    const html = await (await get("/methodology")).text();
    const block = html.indexOf('id="express-entry"');
    const section = html.slice(block, html.indexOf("</section>", block));
    const lists = section.slice(section.indexOf("Designated-Employer Lists"), section.indexOf("<h3>", section.indexOf("Designated-Employer Lists")));
    expect(lists).toContain(
      "Atlantic Immigration Program (Nova Scotia): the employers listed come from the province&#39;s list dated 2026-07-01, " +
      "loaded by hand on 2026-10-30 because the province&#39;s server does not answer the nightly run. " +
      "The run checks every night for a newer edition.");
    const limits = section.slice(section.lastIndexOf("<ul>"));
    expect(limits).toContain(
      "<li>Atlantic Immigration Program (Prince Edward Island): the province&#39;s site blocks automated readers, so its list " +
      "is not read. The run tries once a night and reads the list again when the block is lifted.</li>");
    expect(section).not.toContain(EM_DASH);
  });

  it("leaves both out when stats.json carries no lists", async () => {
    const base = makeFakeAssets();
    const stats = await (await base.fetch(new Request("https://assets.invalid/data/stats.json"))).json() as Record<string, unknown>;
    delete stats.registers;
    const html = await (await get("/methodology", withFiles({ "stats.json": stats }))).text();
    expect(html).toContain('id="express-entry"');
    expect(html).not.toContain("loaded by hand");
    expect(html).not.toContain("blocks automated readers");
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
    // The lists' row says which list comes from a copy loaded by hand, in one sentence.
    const row = lic.slice(lic.indexOf("Designated-employer lists (provincial"), lic.indexOf("</tr>", lic.indexOf("Designated-employer lists (provincial")));
    expect(row).toContain(
      '<div class="small">Atlantic Immigration Program (Nova Scotia): the employers listed come from the province&#39;s list ' +
      "dated 2026-07-01, loaded by hand on 2026-10-30 because the province&#39;s server does not answer the nightly run.</div>");
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
  it("carries each notice the run recorded as information, never an alert, and drops an unreadable one", () => {
    const { status } = readStatus({
      run_at: "2026-10-20T00:48:00Z", ok: true, stages: [],
      notices: [{ source: "high_wage", detail: "IRCC high-wage list changed: 2 codes added, 0 removed" }, { bad: true }, "x"],
    });
    expect(status?.notices).toEqual([{ source: "high_wage", detail: "IRCC high-wage list changed: 2 codes added, 0 removed" }]);
    const inputs = {
      now: new Date("2026-10-20T06:00:00Z"), dataAsOf: "2026-10-20", backupUploaded: new Date("2026-10-20T00:50:00Z"), status,
    };
    expect(collectAlerts(inputs)).toEqual([]);
    expect(collectNotices(inputs)).toEqual(["high_wage: IRCC high-wage list changed: 2 codes added, 0 removed"]);
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
