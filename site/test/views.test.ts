import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { countryCode, referrerHost, routeTemplate } from "../src/views";
import { testEnv } from "./assets";

// A stand-in for the Analytics Engine binding that keeps what it is given.
function recorder(fail = false) {
  const points: AnalyticsEngineDataPoint[] = [];
  const dataset = {
    writeDataPoint(p?: AnalyticsEngineDataPoint) {
      if (fail) throw new Error("dataset unavailable");
      if (p) points.push(p);
    },
  } as AnalyticsEngineDataset;
  return { points, dataset };
}

const IP = "203.0.113.42";
const UA = "Mozilla/5.0 (X11; Linux x86_64) ExampleBrowser/1.0";

function visit(path: string, dataset?: AnalyticsEngineDataset, init: RequestInit = {}) {
  const headers = {
    "cf-connecting-ip": IP,
    "user-agent": UA,
    cookie: "lang=fr; theme=dark",
    referer: "https://news.example.org/2026/10/story?utm_source=x#frag",
    ...(init.headers as Record<string, string>),
  };
  return app.request(path, { ...init, headers }, { ...testEnv(), VIEWS: dataset });
}

describe("route templates", () => {
  it("names every route by its template, never by its parameters", () => {
    expect(routeTemplate("GET", "/")).toEqual({ route: "/", kind: "page" });
    expect(routeTemplate("GET", "/search")).toEqual({ route: "/search", kind: "page" });
    expect(routeTemplate("GET", "/employers/emp-a000000001")).toEqual({ route: "/employers/:id", kind: "page" });
    expect(routeTemplate("GET", "/employers/emp-a000000001/respond")).toEqual({ route: "/employers/:id/respond", kind: "page" });
    expect(routeTemplate("POST", "/employers/emp-a000000001/respond")).toEqual({ route: "/employers/:id/respond", kind: "form" });
    expect(routeTemplate("POST", "/corrections")).toEqual({ route: "/corrections", kind: "form" });
    expect(routeTemplate("GET", "/api/employers/emp-a000000001")).toEqual({ route: "/api/employers/:id", kind: "api" });
    expect(routeTemplate("GET", "/api/area/V0N")).toEqual({ route: "/api/area/:fsa", kind: "api" });
    expect(routeTemplate("GET", "/api/stats")).toEqual({ route: "/api/stats", kind: "api" });
    expect(routeTemplate("GET", "/api/search")).toEqual({ route: "/api/search", kind: "api" });
    expect(routeTemplate("GET", "/api/search/facets")).toEqual({ route: "/api/search/facets", kind: "api" });
    expect(routeTemplate("GET", "/api/anything/else")).toEqual({ route: "/api/other", kind: "api" });
    expect(routeTemplate("GET", "/downloads/employers.csv")).toEqual({ route: "/downloads/employers.csv", kind: "download" });
    expect(routeTemplate("GET", "/downloads/mirror/SHA256SUMS")).toEqual({ route: "/downloads/mirror/:file", kind: "download" });
    expect(routeTemplate("GET", "/downloads/secret.txt")).toEqual({ route: "/downloads/other", kind: "download" });
    expect(routeTemplate("POST", "/hooks/kofi")).toEqual({ route: "/hooks/kofi", kind: "hook" });
    expect(routeTemplate("GET", "/sitemap-12.xml")).toEqual({ route: "/sitemap.xml", kind: "file" });
    expect(routeTemplate("GET", "/robots.txt")).toEqual({ route: "/robots.txt", kind: "file" });
    for (const page of ["/feeds", "/watchlist", "/releases", "/rankings", "/trends", "/occupations", "/places"]) {
      expect(routeTemplate("GET", page), page).toEqual({ route: page, kind: "page" });
    }
    expect(routeTemplate("GET", "/releases/2026-q1")).toEqual({ route: "/releases/:slug", kind: "page" });
    expect(routeTemplate("GET", "/rankings/2025")).toEqual({ route: "/rankings/:year", kind: "page" });
    expect(routeTemplate("GET", "/trends/streams")).toEqual({ route: "/trends/:view", kind: "page" });
    expect(routeTemplate("GET", "/occupations/63200")).toEqual({ route: "/occupations/:noc", kind: "page" });
    expect(routeTemplate("GET", "/places/mb")).toEqual({ route: "/places/:prov", kind: "page" });
    expect(routeTemplate("GET", "/places/mb/winnipeg")).toEqual({ route: "/places/:prov/:slug", kind: "page" });
  });

  it("stores a path that matches no route as 'other', whatever it holds", () => {
    for (const path of ["/someone@example.com", "/search/", "/wp-login.php", "/employers/a/b/c", "/%E2%80%94", "/places/a/b/c", "/trends/a/b"]) {
      expect(routeTemplate("GET", path), path).toEqual({ route: "other", kind: "other" });
    }
  });
});

describe("referrer and country", () => {
  it("keeps the referring host only", () => {
    expect(referrerHost("https://News.Example.org:8443/a/b?q=1#x")).toBe("news.example.org");
    expect(referrerHost("http://www.google.com/")).toBe("www.google.com");
    expect(referrerHost("android-app://com.google.android.gm/")).toBe("");
    expect(referrerHost("not a url")).toBe("");
    expect(referrerHost(undefined)).toBe("");
    expect(referrerHost("")).toBe("");
  });

  it("keeps a two-character code from the edge and nothing else", () => {
    expect(countryCode("CA")).toBe("CA");
    expect(countryCode("T1")).toBe("T1");
    expect(countryCode("Canada")).toBe("");
    expect(countryCode(undefined)).toBe("");
    expect(countryCode(42)).toBe("");
  });
});

describe("measurement middleware", () => {
  it("writes one aggregate point per response, with no address, agent, cookie or full referrer", async () => {
    const { points, dataset } = recorder();
    const res = await visit("/employers/emp-a000000001", dataset);
    expect(res.status).toBe(200);
    expect(points).toHaveLength(1);
    const [p] = points;
    expect(p).toEqual({
      indexes: ["/employers/:id"],
      blobs: ["/employers/:id", "page", "fr", "", "news.example.org", "GET"],
      doubles: [200],
    });
    const raw = JSON.stringify(p);
    for (const secret of [IP, UA, "theme", "lang=fr", "utm_source", "/2026/10/story", "emp-a000000001"]) {
      expect(raw, secret).not.toContain(secret);
    }
  });

  it("counts pages, the API, downloads, not-found pages and form posts with their status", async () => {
    const { points, dataset } = recorder();
    await visit("/?lang=en", dataset);
    await visit("/api/stats", dataset);
    await visit("/downloads/not-a-file.csv", dataset);
    await visit("/nothing-here/someone@example.com", dataset);
    await visit("/corrections", dataset, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ record_ref: "emp-a000000002", request: "The street address on this profile is out of date." }).toString(),
    });
    expect(points.map((p) => [p.blobs?.[0], p.blobs?.[1], p.blobs?.[2], p.doubles?.[0]])).toEqual([
      ["/", "page", "en", 200],
      ["/api/stats", "api", "fr", 200],
      ["/downloads/other", "download", "fr", 404],
      ["other", "other", "fr", 404],
      ["/corrections", "form", "fr", 200],
    ]);
    expect(JSON.stringify(points)).not.toContain("someone@example.com");
  });

  it("records the edge's country code when the request carries one", async () => {
    const { points, dataset } = recorder();
    const req = new Request("http://localhost/search", { headers: { referer: "https://lmiawatch.ca/" } });
    Object.defineProperty(req, "cf", { value: { country: "CA", city: "Somewhere", latitude: "1" } });
    await app.fetch(req, { ...testEnv(), VIEWS: dataset });
    expect(points[0].blobs).toEqual(["/search", "page", "en", "CA", "lmiawatch.ca", "GET"]);
    expect(JSON.stringify(points)).not.toContain("Somewhere");
  });

  it("serves the page when the dataset throws or is absent", async () => {
    const broken = recorder(true);
    const res = await visit("/methodology", broken.dataset);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("<h1>");
    expect((await visit("/methodology")).status).toBe(200);
    expect((await visit("/methodology", undefined)).status).toBe(200);
  });
});
