import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { emptyAssets, fakeAssets, testEnv } from "./assets";
import stats from "./fixtures/stats.json";

const get = (path: string, headers: Record<string, string> = {}) => app.request(path, { headers }, testEnv());

describe("pages", () => {
  it("home renders tiles and lists from stats.json", async () => {
    const res = await get("/");
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("Who Is Applying to Hire Temporary Foreign Workers");
    expect(html).toContain("5,883");
    expect(html).toContain("PinkCloud Cleaning &amp; Home Services");
    expect(html).toContain("Jealous Fruits Ltd.");
    expect(html).toContain("Data as of 2026-10-12");
    expect(html).toContain("Primary Agriculture");
    expect(html).toContain("2026 Q1");
    expect(html).toContain("Job Bank postings carrying the &quot;LMIA requested&quot; flag, newest first.");
    expect(html).toContain("Pending by province, all 5,883 postings.");
    expect(html).toContain('<a href="/search?status=pending&amp;province=BC">British Columbia</a>');
    // Search covers every year, so the last-quarter links carry the window.
    expect(html).toContain('<a href="/search?status=approved&amp;date=last_quarter">Approved Last Quarter</a>');
    expect(html).toContain('<a href="/search?status=refused&amp;date=last_quarter">Refused Last Quarter</a>');
    expect(html).toContain('<link rel="icon" href="/favicon.svg" type="image/svg+xml"');
    expect(html).toContain('class="brand-mark"');
    expect(html).toContain('<script src="/theme.js"></script>');
    // Off-site links open in a new tab; the script marks the rest at load.
    expect(html).toContain('<a href="https://x.com/LMIAwatch" class="footer-x" target="_blank" rel="noopener" aria-label="LMIA Watch on X"');
    expect(html).toContain('<a href="https://bsky.app/profile/lmiawatch.ca" class="footer-x" target="_blank" rel="noopener" aria-label="LMIA Watch on Bluesky"');
    expect(html).toContain('<script src="/links.js" defer=""></script>');
    expect(html).toContain('<button type="button" class="theme-toggle"><span class="when-light">Dark</span><span class="when-dark">Light</span></button>');
  });

  it("home names the public records on profiles and counts the employers matched to a federal agreement", async () => {
    const html = await (await get("/")).text();
    expect(html).toContain("Each employer&#39;s page also carries its corporate registry record and, where the public records match,");
    expect(html).toContain('<span class="badge badge-neutral">Public money</span><span class="tile-value">2,140</span>');
    expect(html).toContain(
      '<a href="/data#public-records">employers on this site matched to a disclosed federal grant or contribution (9,812 agreements)</a>',
    );
    expect(html).toContain('<a href="/methodology#matching">corporate registry record</a>');
    expect(html).toContain('<a href="/data#public-records">US carrier records</a>');
    expect(html).not.toContain(String.fromCharCode(0x2014));
    const fr = await (await get("/?lang=fr")).text();
    expect(fr).toContain("Fonds publics");
    expect(fr).toContain("accords)</a>");
    expect(fr).toContain('<a href="/data#public-records">dossiers de transporteurs américains</a>');
    // The anchor the tile and the list link to.
    expect(await (await get("/data")).text()).toContain('<p id="public-records">');
  });

  it("home shows four tiles when stats.json has no public-record counts, or none matched yet", async () => {
    const { grant_employers, grant_agreements, ...older } = stats.counts;
    for (const counts of [older, { ...stats.counts, grant_employers: 0, grant_agreements: 0 }, { ...stats.counts, grant_employers: "2140" }]) {
      const assets = {
        fetch: async (input: Request) =>
          new URL(input.url).pathname === "/data/stats.json"
            ? new Response(JSON.stringify({ ...stats, counts }))
            : fakeAssets.fetch(input),
      } as unknown as Fetcher;
      const res = await app.request("/", {}, testEnv(assets));
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).not.toContain("badge-neutral");
      expect(html.match(/class="tile"/g)?.length).toBe(4);
    }
  });

  it("home charts pending postings by occupation under the province bars", async () => {
    const html = await (await get("/")).text();
    expect(html).toContain("Pending by occupation, of 1,204 postings with a NOC 2021 code.");
    // The code in muted mono before the title, which links to the filtered search.
    expect(html).toContain('<span class="mono muted">85101</span> <a href="/search?status=pending&amp;noc=85101">Harvesting labourers</a>');
    expect(html).toContain('<a href="/search?status=pending&amp;noc=62020">Food service supervisors</a>');
    // Six rows of the eight the export writes, after the province bars.
    expect(html).not.toContain("noc=65201");
    expect(html.indexOf("Pending by occupation")).toBeGreaterThan(html.indexOf("Pending by province"));
    const fr = await (await get("/?lang=fr")).text();
    expect(fr).toContain("En attente par profession, sur");
    expect(fr).toContain('<a href="/search?status=pending&amp;noc=85101">Manœuvres à la récolte</a>');
    // A slash in a title is a place the line may break.
    expect(fr).toContain(">Cuisiniers/<wbr/>cuisinières</a>");
  });

  it("home leaves out the occupation bars when stats.json lacks them or they fail the check", async () => {
    const { pending_by_noc: rows, ...older } = stats;
    const { pending_with_noc, ...olderCounts } = stats.counts;
    const variants: unknown[] = [
      older,
      { ...stats, counts: olderCounts },
      { ...stats, counts: { ...stats.counts, pending_with_noc: "1204" } },
      { ...stats, pending_by_noc: [] },
      { ...stats, pending_by_noc: "x" },
      { ...stats, pending_by_noc: [{ ...rows[0], k: "8510" }] },
      { ...stats, pending_by_noc: [{ ...rows[0], title: "Harvesting labourers" }] },
      { ...stats, pending_by_noc: [{ ...rows[0], title: { en: "Harvesting labourers" } }] },
      { ...stats, pending_by_noc: [rows[0], { ...rows[1], n: "187" }] },
    ];
    for (const body of variants) {
      const assets = {
        fetch: async (input: Request) =>
          new URL(input.url).pathname === "/data/stats.json" ? new Response(JSON.stringify(body)) : fakeAssets.fetch(input),
      } as unknown as Fetcher;
      const res = await app.request("/", {}, testEnv(assets));
      expect(res.status).toBe(200);
      const html = await res.text();
      expect(html).not.toContain("Pending by occupation");
      expect(html).not.toContain("noc=");
      // The rest of the page stands.
      expect(html).toContain("Pending by province, all 5,883 postings.");
      expect(html).toContain("Jealous Fruits Ltd.");
    }
  });

  // This file's search database is empty (test/search_page.test.ts fills its
  // own), so these are the fallback: the page as before hosted search.
  it("a plain search visit is rendered on the server with counts", async () => {
    const html = await (await get("/search")).text();
    expect(html).toContain('data-ssr="1"');
    expect(html).toContain("5 records");
    expect(html).toContain("PinkCloud Cleaning &amp; Home Services");
    expect(html).toContain("Haveli Restaurant Inc");
    expect(html).toContain("Job Bank 50456228");
    expect(html).toContain("Newly incorporated applicant");
    expect(html).toContain('data-count="status:pending"> 2');
    expect(html).toContain('data-count="province:BC"> 4');
    expect(html).toContain("Page 1 of 1");
    expect(html).toContain('<p class="panel bordered" id="search-unavailable" role="status">Search is unavailable for the moment, so the newest records are shown.</p>');
    const page2 = await (await get("/search?page=2")).text();
    expect(page2).toContain('data-ssr="1"');
    expect(page2).toContain("No records.");
  });

  it("a filtered search without the search database keeps the filters and shows the newest records", async () => {
    const html = await (await get("/search?status=refused&province=NL&q=haveli&date=since_2023q4")).text();
    expect(html).toContain('data-mode="static"');
    expect(html).toContain('data-ssr="1"');
    expect(html).toContain('<p class="panel bordered" id="search-unavailable" role="status">Search is unavailable for the moment, so the newest records are shown.</p>');
    expect(html).toContain('src="/search.js"');
    expect(html).toContain('value="haveli"');
    expect(html).toMatch(/name="status" value="refused" checked/);
    expect(html).toMatch(/name="province" value="NL" checked/);
    // The longer search period is gone: its old value is dropped, and every year is the default.
    expect(html).not.toContain("since_2023q4");
    expect(html).toMatch(/name="date" value="any" checked/);
    expect(html).not.toContain("data-years");
    expect(html).toContain("Haveli Restaurant Inc</a>");
    expect(html).toContain("downloads");
  });

  it("employer profile shows every section, including published site rows", async () => {
    const res = await get("/employers/emp-a000000001");
    expect(res.status).toBe(200);
    const html = await res.text();
    for (const s of [
      "PinkCloud Cleaning &amp; Home Services",
      "BC1596446",
      "Probable",
      "Newly incorporated applicant",
      "Triggered",
      "Timeline",
      "Job Bank 50456228",
      "1-866-602-9448",
      "sole proprietorship since 2018",
      "1 published",
      "Submit an Employer Response",
      'class="minimap" role="img" aria-label="Map of postal area V0N, centred on its centroid"',
      "https://tile.openstreetmap.org/11/",
      "Map: OpenStreetMap contributors",
    ]) {
      expect(html).toContain(s);
    }
    // The indicator table restacks on a phone, each cell labelled with its column.
    expect(html).toMatch(/<table class="restack"><thead><tr><th>Indicator<\/th><th>State<\/th><th>Basis<\/th>/);
    expect(html).toContain('<td data-label="Indicator">Newly incorporated applicant</td>');
    expect(html).toContain('<td data-label="State"><span class="badge state-triggered">Triggered</span></td>');
    expect(html).toMatch(/<td data-label="Basis">[^<]+<\/td>/);
    expect(html).not.toContain("Map at postal-area centroid");
    expect(html).not.toContain("still under review");
    const edsa = await (await get("/employers/emp-a000000002")).text();
    expect(edsa).toContain("405 Martin Street");
    expect(edsa).toContain("Street updated from the current posting.");
    const refused = await (await get("/employers/emp-a000000008")).text();
    expect(refused).toContain("ESDC negative 2026Q1");
    expect(refused).toContain("Refused");
    // The timeline reads newest first; the awaiting-decision line, when present, sits above the dated events.
    const timeline = html.slice(html.indexOf('<ol class="timeline">'), html.indexOf("</ol>", html.indexOf('<ol class="timeline">')));
    const dates = [...timeline.matchAll(/<li class="tl-(?!future)[a-z]+"><span class="mono">(\d{4}-\d{2}-\d{2})<\/span>/g)].map((m) => m[1]);
    expect(dates.length).toBeGreaterThan(1);
    expect([...dates].sort().reverse()).toEqual(dates);
    if (timeline.includes('class="tl-future"')) expect(timeline.indexOf('class="tl-future"')).toBeLessThan(timeline.search(/<li class="tl-(?!future)/));
  });

  it("unknown or malformed employer ids are 404s in the layout", async () => {
    const res = await get("/employers/emp-ffffffffff");
    expect(res.status).toBe(404);
    expect(await res.text()).toContain("Employer Not Found");
    const bad = await get("/employers/../../etc");
    expect(bad.status).toBe(404);
  });

  it("map, methodology and data pages render", async () => {
    const map = await get("/map?fsa=v0n");
    expect(map.status).toBe(200);
    const mapHtml = await map.text();
    expect(mapHtml).toContain('id="map"');
    expect(mapHtml).toContain("leaflet");
    expect(mapHtml).toContain('data-fsa="V0N"');
    expect(mapHtml).toContain("never");

    const meth = await (await get("/methodology")).text();
    expect(meth).toContain("<h2 id=\"status\">Status Lifecycle</h2>");
    expect(meth).toContain("Known false positives");
    expect(meth).toContain("Private households and individuals are not published");
    expect(meth).toContain("(NOC 4411, 4412, 44100 or 44101) and the employer is named as a person");
    // The wage and unemployment rules as published, with their sources.
    expect(meth).toContain("Job Bank wages by occupation and economic region (ESDC, open.canada.ca)");
    expect(meth).toContain("Statistics Canada Labour Force Survey, table 14-10-0459-01");
    expect(meth).toContain("Statistics Canada 2021 Census boundary files");
    expect(meth).toContain("Posted minimum wage is within 1 percent of the Job Bank median for the posting&#39;s occupation and economic region");
    expect(meth).toContain("the provincial and then the national median");
    expect(meth).toContain("6 percent or higher in both three-month periods that could have applied");
    expect(meth).toContain("Since 2024-09-26 ESDC refuses to process low-wage applications");
    expect(meth).toContain("food manufacturing including fish processing, hospitals, nursing and residential care");
    expect(meth).not.toContain("(planned)");

    const data = await (await get("/data")).text();
    expect(data).toContain("pending_observations.csv");
    expect(data).toContain("Open Government Licence");
    expect(data).toContain("2026Q1");
    expect(data).toContain("GeoNames");
    expect(data).toContain('href="https://open.canada.ca/data/en/dataset/adad580f-76b0-4502-bd05-20c125de9116"');
    expect(data).toContain("Labour Force Survey table 14-10-0459-01");
    expect(data).toContain("Statistics Canada Open Licence");
    expect(data).toContain('<td class="mono nw">2026-10-17</td>');
    // Newest change first.
    expect(data.indexOf('<td class="mono nw">2026-10-18</td>')).toBeLessThan(data.indexOf('<td class="mono nw">2026-10-12</td>'));
    expect(data).toContain("Indicator rules v0.2.");
    expect(data).toContain("Private households left out of the ESDC lists");
    expect(data).not.toContain("planned");
    // The ESDC files, the changelog and the recent runs each scroll inside their own box.
    expect(data.split('class="table-wrap bordered scroll-y"').length - 1).toBe(3);
  });

  it("downloads fall back to a plain 404 page when nothing is published", async () => {
    const res = await get("/downloads/employers.csv");
    expect(res.status).toBe(404);
    expect(await res.text()).toContain("not available yet");
  });

  it("unknown routes get the 404 page", async () => {
    const res = await get("/nothing-here");
    expect(res.status).toBe(404);
    expect(await res.text()).toContain("Page Not Found");
  });

  it("explains itself when the data files are missing", async () => {
    const res = await app.request("/", {}, testEnv(emptyAssets));
    expect(res.status).toBe(503);
    expect(await res.text()).toContain("Data Not Published Yet");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("sets security headers on every response", async () => {
    const res = await get("/");
    expect(res.headers.get("content-security-policy")).toContain("default-src 'self'");
    expect(res.headers.get("content-security-policy")).toContain("cdnjs.cloudflare.com");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(res.headers.get("x-frame-options")).toBe("DENY");
    expect(res.headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
    expect(res.headers.get("cache-control")).toContain("max-age=300");
  });

  it("switches language by query and cookie", async () => {
    const res = await get("/?lang=fr");
    expect(res.headers.get("set-cookie")).toContain("lang=fr");
    expect(await res.text()).toContain("Recherche");
    const cookie = await (await get("/methodology", { cookie: "lang=fr" })).text();
    expect(cookie).toContain("Carte");
    const en = await (await get("/methodology")).text();
    expect(en).toContain(">Map<");
  });
});
