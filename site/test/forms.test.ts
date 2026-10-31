import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { testEnv } from "./assets";

// Each post comes from its own address, so the per-address form cap (5 a minute) never trips here.
let nextAddress = 1;
const post = (path: string, fields: Record<string, string>) =>
  app.request(
    path,
    {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", "cf-connecting-ip": `198.51.100.${nextAddress++}` },
      body: new URLSearchParams(fields).toString(),
    },
    testEnv(),
  );

// What a current browser sends when it follows a link on the site's own pages.
const NAVIGATE = { "sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-site": "same-origin" };
const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";

describe("forms", () => {
  it("renders the response form for a known employer only", async () => {
    const res = await app.request("/employers/emp-a000000001/respond", { headers: NAVIGATE }, testEnv());
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Submit an Employer Response");
    const unknown = await app.request("/employers/emp-ffffffffff/respond", { headers: NAVIGATE }, testEnv());
    expect(unknown.status).toBe(404);
  });

  it("stores a valid response unpublished", async () => {
    const res = await post("/employers/emp-a000000005/respond", {
      name: "Owner, Jealous Fruits",
      email: "owner@example.com",
      statement: "Our harvest crews are seasonal and return every year under the agricultural stream.",
    });
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Thank You");
    const row = await env.DB.prepare("SELECT * FROM employer_responses WHERE employer_id = ?").bind("emp-a000000005").first<any>();
    expect(row.published).toBe(0);
    expect(row.verified).toBe(0);
    expect(row.statement).toContain("seasonal");
  });

  it("rejects the honeypot and bad input", async () => {
    const bot = await post("/employers/emp-a000000001/respond", {
      name: "x", email: "a@b.co", statement: "a long enough statement for the form", website: "http://spam",
    });
    expect(bot.status).toBe(400);
    const bad = await post("/employers/emp-a000000001/respond", { name: "Owner", email: "not-an-email", statement: "short" });
    expect(bad.status).toBe(400);
    const html = await bad.text();
    expect(html).toContain("valid work email");
    expect(html).toContain("at least 20 characters");
    const unknown = await post("/employers/emp-ffffffffff/respond", {
      name: "Owner", email: "a@b.co", statement: "a long enough statement for the form",
    });
    expect(unknown.status).toBe(404);
  });

  it("stores a response posted with no Fetch Metadata and no Referer: the POST is not checked", async () => {
    const res = await post("/employers/emp-a000000008/respond", {
      name: "Owner, Example Farms",
      email: "owner@example.com",
      statement: "A statement long enough for the form to take it, sent by a plain client.",
    });
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Thank You");
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM employer_responses WHERE employer_id = ?").bind("emp-a000000008").first<{ n: number }>();
    expect(row?.n).toBe(1);
    const bad = await post("/employers/emp-a000000001/respond", { name: "Owner", email: "not-an-email", statement: "short" });
    expect(bad.status).toBe(400);
    expect(await bad.text()).toContain("Submit an Employer Response");
  });

  it("stores corrections and links them to an employer when possible", async () => {
    const res = await post("/corrections", {
      record_ref: "emp-a000000002",
      request: "The street address on this profile is out of date.",
      email: "",
    });
    expect(res.status).toBe(200);
    const row = await env.DB.prepare("SELECT * FROM corrections ORDER BY id DESC LIMIT 1").first<any>();
    expect(row.employer_id).toBe("emp-a000000002");
    expect(row.published).toBe(0);
    expect(row.contact_email).toBeNull();
    const loose = await post("/corrections", { record_ref: "Job Bank 50436247", request: "Wage is shown with the wrong unit." });
    expect(loose.status).toBe(200);
    const row2 = await env.DB.prepare("SELECT * FROM corrections ORDER BY id DESC LIMIT 1").first<any>();
    expect(row2.employer_id).toBeNull();
    const invalid = await post("/corrections", { record_ref: "x", request: "short" });
    expect(invalid.status).toBe(400);
  });
});

// A stand-in for the Analytics Engine binding that keeps what it is given.
function recorder() {
  const points: AnalyticsEngineDataPoint[] = [];
  const dataset = { writeDataPoint: (p?: AnalyticsEngineDataPoint) => void (p && points.push(p)) } as AnalyticsEngineDataset;
  return { points, dataset };
}

describe("the response form opens in a browser only", () => {
  const FORM = "/employers/emp-a000000001/respond";
  const open = (path: string, headers: Record<string, string>, dataset?: AnalyticsEngineDataset) =>
    app.request(path, { headers: { "user-agent": CHROME, ...headers } }, { ...testEnv(), VIEWS: dataset });

  it("refuses a request with no Fetch Metadata and no Referer, naming the profile, and counts it as a bot", async () => {
    const { points, dataset } = recorder();
    const res = await open(FORM, {}, dataset);
    expect(res.status).toBe(403);
    expect(res.headers.get("content-type")).toMatch(/^text\/plain/);
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(res.headers.get("vary")).toContain("Sec-Fetch-Mode");
    expect(await res.text()).toBe("This form opens in a web browser from the employer's profile: https://lmiawatch.ca/employers/emp-a000000001");
    expect(points).toHaveLength(1);
    expect(points[0].blobs?.slice(0, 2)).toEqual(["/employers/:id/respond", "page"]);
    expect(points[0].blobs?.slice(7)).toEqual(["bot", "", ""]);
    expect(points[0].doubles).toEqual([403]);
  });

  it("refuses in the request's language", async () => {
    const res = await open(`${FORM}?lang=fr`, {});
    expect(res.status).toBe(403);
    expect(await res.text()).toBe(
      "Ce formulaire s’ouvre dans un navigateur Web à partir du profil de l’employeur\u00a0: https://lmiawatch.ca/employers/emp-a000000001?lang=fr",
    );
    const cookie = await open(FORM, { cookie: "lang=fr" });
    expect(await cookie.text()).toContain("Ce formulaire");
  });

  it("refuses a Referer from another site when no Fetch Metadata comes with it", async () => {
    for (const referer of ["https://news.example.org/story", "https://lmiawatch.ca.example.org/", "not a url"]) {
      expect((await open(FORM, { referer })).status, referer).toBe(403);
    }
  });

  it("serves a navigation from the site's own pages", async () => {
    const { points, dataset } = recorder();
    const res = await open(FORM, NAVIGATE, dataset);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Submit an Employer Response");
    expect(points[0].blobs?.[7]).toBe("human");
  });

  it("serves any Sec-Fetch-Mode, whatever its value", async () => {
    expect((await open(FORM, { "sec-fetch-mode": "no-cors" })).status).toBe(200);
  });

  it("serves a link followed from another site, such as an emailed message", async () => {
    const res = await open(FORM, { "sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-site": "cross-site" });
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Submit an Employer Response");
  });

  it("serves a Referer from the site's own host alone", async () => {
    for (const referer of ["https://lmiawatch.ca/employers/emp-a000000001", "https://www.lmiawatch.ca/search?q=pink", "http://localhost/employers/emp-a000000001"]) {
      expect((await open(FORM, { referer })).status, referer).toBe(200);
    }
  });

  it("keeps the redirect for a retired id and the 404 for an unknown one, for a browser", async () => {
    const moved = await open("/employers/emp-a00dead001/respond", NAVIGATE);
    expect(moved.status).toBe(301);
    expect((await open("/employers/emp-ffffffffff/respond", NAVIGATE)).status).toBe(404);
    // A path that is no employer id is never written into the refusal.
    expect((await open("/employers/not-an-id/respond", {})).status).toBe(404);
  });

  it("leaves the corrections page open to any client", async () => {
    const res = await app.request("/corrections", { headers: { "user-agent": "curl/8.5.0" } }, testEnv());
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("<form");
  });
});
