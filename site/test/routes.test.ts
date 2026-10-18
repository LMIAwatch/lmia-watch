import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { emptyAssets, testEnv } from "./assets";

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
    expect(html).toContain('<link rel="icon" href="/favicon.svg" type="image/svg+xml"');
    expect(html).toContain('class="brand-mark"');
    expect(html).toContain('<script src="/theme.js"></script>');
    expect(html).toContain('<a href="https://x.com/LMIAwatch" class="footer-x" rel="noopener" aria-label="LMIA Watch on X"');
    expect(html).toContain('<button type="button" class="theme-toggle"><span class="when-light">Dark</span><span class="when-dark">Light</span></button>');
  });

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
    expect(html).toContain("5 records, larger download");
    const page2 = await (await get("/search?page=2")).text();
    expect(page2).toContain('data-ssr="1"');
    expect(page2).toContain("No records.");
  });

  it("a filtered search renders the rail and leaves the rows to the script", async () => {
    const html = await (await get("/search?status=refused&province=NL&q=haveli&date=since_2023q4")).text();
    expect(html).toContain('data-ssr="0"');
    expect(html).toContain("Loading records");
    expect(html).toContain('data-latest="2026Q1"');
    expect(html).toContain('data-from="2023Q4"');
    expect(html).toContain('data-years="2023,2024,2025,2026"');
    expect(html).toContain('src="/search.js"');
    expect(html).toContain('value="haveli"');
    expect(html).toMatch(/name="status" value="refused" checked/);
    expect(html).toMatch(/name="province" value="NL" checked/);
    expect(html).toMatch(/name="date" value="since_2023q4" checked/);
    expect(html).not.toContain("Haveli Restaurant Inc</a>");
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
    expect(html).not.toContain("Map at postal-area centroid");
    expect(html).not.toContain("still under review");
    const edsa = await (await get("/employers/emp-a000000002")).text();
    expect(edsa).toContain("405 Martin Street");
    expect(edsa).toContain("Street updated from the current posting.");
    const refused = await (await get("/employers/emp-a000000008")).text();
    expect(refused).toContain("ESDC negative 2026Q1");
    expect(refused).toContain("Refused");
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

    const data = await (await get("/data")).text();
    expect(data).toContain("pending_observations.csv");
    expect(data).toContain("Open Government Licence");
    expect(data).toContain("2026Q1");
    expect(data).toContain("GeoNames");
    expect(data.split('class="table-wrap bordered scroll-y"').length - 1).toBe(2);
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
