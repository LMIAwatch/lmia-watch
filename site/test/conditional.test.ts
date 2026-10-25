import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { bodyEtag, noneMatch } from "../src/conditional";
import { app } from "../src/index";
import { testEnv } from "./assets";

const request = (path: string, init: RequestInit = {}, bindings: object = testEnv()) => app.request(path, init, bindings);
const get = (path: string, headers: Record<string, string> = {}) => request(path, { headers });

// A stand-in for the Analytics Engine binding that keeps what it is given (as in views.test.ts).
function recorder() {
  const points: AnalyticsEngineDataPoint[] = [];
  const dataset = { writeDataPoint: (p?: AnalyticsEngineDataPoint) => void (p && points.push(p)) } as AnalyticsEngineDataset;
  return { points, dataset };
}

describe("If-None-Match", () => {
  it("compares weakly, reads lists and takes * for any tag", () => {
    const tag = 'W/"abc123"';
    expect(noneMatch('W/"abc123"', tag)).toBe(true);
    expect(noneMatch('"abc123"', tag)).toBe(true);
    expect(noneMatch('"zzz", W/"abc123"', tag)).toBe(true);
    expect(noneMatch(' W/"zzz" ,W/"abc123" ', tag)).toBe(true);
    expect(noneMatch("*", tag)).toBe(true);
    expect(noneMatch('W/"abc12"', tag)).toBe(false);
    expect(noneMatch('"zzz", W/"yyy"', tag)).toBe(false);
    expect(noneMatch("", tag)).toBe(false);
    expect(noneMatch(",", tag)).toBe(false);
    expect(noneMatch(undefined, tag)).toBe(false);
  });

  it("tags a body by the SHA-1 of its bytes", async () => {
    const bytes = new TextEncoder().encode("abc").buffer as ArrayBuffer;
    expect(await bodyEtag(bytes)).toBe('W/"a9993e364706816aba3e25717850c26c9cd0d89d"');
  });
});

describe("conditional pages", () => {
  it("answers a page's own ETag with an empty 304", async () => {
    const first = await get("/employers/emp-a000000005");
    expect(first.status).toBe(200);
    const etag = first.headers.get("etag") ?? "";
    expect(etag).toMatch(/^W\/"[0-9a-f]{40}"$/);
    const body = await first.text();
    expect(etag).toBe(await bodyEtag(new TextEncoder().encode(body).buffer as ArrayBuffer));
    expect(first.headers.get("content-type")).toContain("text/html");

    for (const header of [etag, etag.slice(2), `"other", ${etag}`, "*"]) {
      const again = await get("/employers/emp-a000000005", { "if-none-match": header });
      expect(again.status, header).toBe(304);
      expect(await again.text(), header).toBe("");
      expect(again.headers.get("etag")).toBe(etag);
      expect(again.headers.get("cache-control")).toBe("public, max-age=300");
      expect(again.headers.get("content-type")).toBeNull();
      expect(again.headers.get("content-length")).toBeNull();
    }
  });

  it("sends the page again when the tag differs", async () => {
    const etag = (await get("/methodology")).headers.get("etag");
    const res = await get("/methodology", { "if-none-match": 'W/"0000000000000000000000000000000000000000"' });
    expect(res.status).toBe(200);
    expect(res.headers.get("etag")).toBe(etag);
    expect(await res.text()).toContain("<h1>");
  });

  it("gives the English and French renderings of one URL different tags", async () => {
    const en = await get("/employers/emp-a000000005");
    const fr = await get("/employers/emp-a000000005", { cookie: "lang=fr" });
    const enTag = en.headers.get("etag");
    const frTag = fr.headers.get("etag");
    expect(enTag).toBeTruthy();
    expect(frTag).toBeTruthy();
    expect(frTag).not.toBe(enTag);
    // A browser holding the English page that switched to French gets the French page, not a 304.
    const switched = await get("/employers/emp-a000000005", { cookie: "lang=fr", "if-none-match": enTag! });
    expect(switched.status).toBe(200);
    expect(await switched.text()).toContain("Employeur");
    // The language cookie a ?lang= visit sets rides on the 304 as well.
    const queryTag = (await get("/employers/emp-a000000005?lang=fr")).headers.get("etag")!;
    const query = await get("/employers/emp-a000000005?lang=fr", { "if-none-match": queryTag });
    expect(query.status).toBe(304);
    expect(query.headers.get("set-cookie")).toContain("lang=fr");
  });

  it("treats HEAD like GET", async () => {
    const getTag = (await get("/methodology")).headers.get("etag");
    const head = await request("/methodology", { method: "HEAD" });
    expect(head.status).toBe(200);
    expect(head.headers.get("etag")).toBe(getTag);
    expect(await head.text()).toBe("");
    const cond = await request("/methodology", { method: "HEAD", headers: { "if-none-match": getTag! } });
    expect(cond.status).toBe(304);
    expect(cond.headers.get("etag")).toBe(getTag);
  });

  it("leaves other statuses, methods and content types alone", async () => {
    const missing = await get("/nowhere");
    expect(missing.status).toBe(404);
    expect(missing.headers.get("etag")).toBeNull();
    const unknown = await get("/employers/emp-ffffffffff", { "if-none-match": "*" });
    expect(unknown.status).toBe(404);
    expect(unknown.headers.get("etag")).toBeNull();

    const post = await request("/corrections", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", "if-none-match": "*" },
      body: new URLSearchParams({ record_ref: "emp-a000000002", request: "The street address on this profile is out of date." }).toString(),
    });
    expect(post.status).toBe(200);
    expect(post.headers.get("content-type")).toContain("text/html");
    expect(post.headers.get("etag")).toBeNull();

    const json = await get("/api/stats", { "if-none-match": "*" });
    expect(json.status).toBe(200);
    expect(json.headers.get("content-type")).toContain("application/json");
    expect(json.headers.get("etag")).toBeNull();

    const sitemap = await get("/sitemap.xml", { "if-none-match": "*" });
    expect(sitemap.status).toBe(200);
    expect(sitemap.headers.get("etag")).toBeNull();
    // robots.txt from the real assets binding, which serves site/public.
    const robots = await app.request("/robots.txt", { headers: { "if-none-match": "*" } }, env);
    expect(robots.status).toBe(200);
    expect(robots.headers.get("etag")).toBeNull();
  });

  it("is counted with its final status", async () => {
    const { points, dataset } = recorder();
    const bindings = { ...testEnv(), VIEWS: dataset };
    const etag = (await request("/methodology", {}, bindings)).headers.get("etag")!;
    await request("/methodology", { headers: { "if-none-match": etag } }, bindings);
    expect(points.map((p) => [p.blobs?.[0], p.blobs?.[1], p.doubles?.[0]])).toEqual([
      ["/methodology", "page", 200],
      ["/methodology", "page", 304],
    ]);
  });
});
