// Retired employer ids. The export writes aliases/<abc>.json, where abc is the
// old id's characters 5 to 7 (the profile shards' key), mapping each old id to
// the id that took its records. A profile lookup that misses redirects through
// it; anything unreadable there leaves the 404 as it was.
import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { loadAlias } from "../src/data";
import type { Env } from "../src/env";
import { app } from "../src/index";
import { fakeAssets, testEnv } from "./assets";

const OLD = "emp-a00dead001";
const LIVE = "emp-a000000001";
// Same shard as OLD, no entry in it; and a shard the fixtures do not have.
const UNKNOWN = ["emp-a00dead0ff", "emp-ffffffffff"];

// Each request from its own documentation address, so the per-address caps never answer first.
let address = 1;
const visitor = () => ({ "cf-connecting-ip": `2001:db8:a::${(address++).toString(16)}` });

const get = (path: string, assets: Fetcher = fakeAssets) => app.request(path, { headers: visitor() }, testEnv(assets));

const post = (path: string, fields: Record<string, string>, assets: Fetcher = fakeAssets) =>
  app.request(
    path,
    {
      method: "POST",
      headers: { ...visitor(), "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(fields).toString(),
    },
    testEnv(assets),
  );

const STATEMENT = { name: "Owner", email: "owner@example.com", statement: "A statement long enough for the form to take it." };

// The fixtures, with the alias shard's body replaced.
function aliasBody(body: string): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url).pathname === "/data/aliases/a00.json") return new Response(body, { headers: { "content-type": "application/json" } });
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher;
}

// A stand-in for the Analytics Engine binding that keeps what it is given.
function recorder() {
  const points: AnalyticsEngineDataPoint[] = [];
  const dataset = { writeDataPoint: (p?: AnalyticsEngineDataPoint) => void (p && points.push(p)) } as AnalyticsEngineDataset;
  return { points, dataset };
}

describe("retired employer ids", () => {
  it("loadAlias reads the live id from the old id's shard", async () => {
    const e = testEnv() as unknown as Env;
    expect(await loadAlias(e, OLD)).toBe(LIVE);
    expect(await loadAlias(e, "emp-a00dead002")).toBe("emp-a000000005");
    for (const id of [...UNKNOWN, LIVE, "not-an-id", "emp-A00DEAD001", "../aliases/a00"]) expect(await loadAlias(e, id), id).toBeNull();
  });

  it("the profile page answers 301 to the live id, keeping the language and nothing else", async () => {
    const res = await get(`/employers/${OLD}`);
    expect(res.status).toBe(301);
    expect(res.headers.get("location")).toBe(`/employers/${LIVE}`);
    expect(res.headers.get("cache-control")).toBe("public, max-age=300");
    const fr = await get(`/employers/${OLD}?lang=fr`);
    expect(fr.status).toBe(301);
    expect(fr.headers.get("location")).toBe(`/employers/${LIVE}?lang=fr`);
    expect((await get(`/employers/${OLD}?lang=en&utm_source=x`)).headers.get("location")).toBe(`/employers/${LIVE}?lang=en`);
    expect((await get(`/employers/${OLD}?lang=de`)).headers.get("location")).toBe(`/employers/${LIVE}`);
    const landed = await get(fr.headers.get("location")!);
    expect(landed.status).toBe(200);
    expect(await landed.text()).toContain("PinkCloud");
  });

  it("the response form redirects a GET with 301 and a POST with 308, storing nothing under the old id", async () => {
    const form = await get(`/employers/${OLD}/respond?lang=fr`);
    expect(form.status).toBe(301);
    expect(form.headers.get("location")).toBe(`/employers/${LIVE}/respond?lang=fr`);
    expect((await get(form.headers.get("location")!)).status).toBe(200);
    const sent = await post(`/employers/${OLD}/respond`, STATEMENT);
    expect(sent.status).toBe(308);
    expect(sent.headers.get("location")).toBe(`/employers/${LIVE}/respond`);
    const stored = await env.DB.prepare("SELECT COUNT(*) AS n FROM employer_responses WHERE employer_id = ?").bind(OLD).first<{ n: number }>();
    expect(stored?.n).toBe(0);
  });

  it("the API answers 301 to the live id's API path", async () => {
    const res = await get(`/api/employers/${OLD}`);
    expect(res.status).toBe(301);
    expect(res.headers.get("location")).toBe(`/api/employers/${LIVE}`);
    const landed = await get(res.headers.get("location")!);
    expect(landed.status).toBe(200);
    expect(((await landed.json()) as any).employer.id).toBe(LIVE);
  });

  it("an id with no alias is still a 404 on the page, the form and the API", async () => {
    for (const id of UNKNOWN) {
      const page = await get(`/employers/${id}`);
      expect(page.status, id).toBe(404);
      expect(await page.text()).toContain("Employer Not Found");
      expect((await get(`/employers/${id}/respond`)).status, id).toBe(404);
      expect((await post(`/employers/${id}/respond`, STATEMENT)).status, id).toBe(404);
      const api = await get(`/api/employers/${id}`);
      expect(api.status, id).toBe(404);
      expect(await api.json()).toEqual({ error: "not found" });
    }
  });

  it("a malformed shard or entry reads as no alias: a 404, never a 500", async () => {
    const BODIES = [
      `{"${OLD}":`, "[]", `["${LIVE}"]`, '"x"', "null", "7",
      ...[7, null, true, {}, [LIVE], "", "not-an-id", `/employers/${LIVE}`, `https://example.com/${LIVE}`, `${LIVE}\r\nSet-Cookie: x=1`, LIVE.toUpperCase(), OLD]
        .map((v) => JSON.stringify({ [OLD]: v })),
    ];
    for (const body of BODIES) {
      const assets = aliasBody(body);
      for (const path of [`/employers/${OLD}`, `/employers/${OLD}/respond`, `/api/employers/${OLD}`]) {
        const res = await get(path, assets);
        expect(res.status, `${path} ${body}`).toBe(404);
        await res.arrayBuffer();
      }
      expect((await post(`/employers/${OLD}/respond`, STATEMENT, assets)).status, body).toBe(404);
    }
  });

  it("counts a redirect under the route's template, with its status", async () => {
    const { points, dataset } = recorder();
    for (const path of [`/employers/${OLD}`, `/employers/${OLD}/respond`, `/api/employers/${OLD}`]) {
      await app.request(path, { headers: visitor() }, { ...testEnv(), VIEWS: dataset });
    }
    expect(points.map((p) => [p.blobs?.[0], p.blobs?.[1], p.doubles?.[0]])).toEqual([
      ["/employers/:id", "page", 301],
      ["/employers/:id/respond", "page", 301],
      ["/api/employers/:id", "api", 301],
    ]);
    expect(JSON.stringify(points)).not.toContain("dead001");
  });
});
