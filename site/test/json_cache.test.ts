// The per-isolate cache of parsed JSON (loadJson in src/data.ts). A file is
// parsed once and kept against its ETag; a later read with the same ETag
// returns the kept value without reading the body, a new ETag parses again,
// and every value is frozen because requests share it.
import { env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { clearParsedCache, loadJson, loadProfile, loadStats } from "../src/data";
import type { Env } from "../src/env";
import { app } from "../src/index";
import { contentEtag, fakeAssets, makeFakeAssets, testEnv } from "./assets";
import stats from "./fixtures/stats.json";

interface Served {
  body: string;
  etag?: string;
}

// A binding that counts, per path, the fetches and the bodies read, and the
// bodies cancelled. A body is a stream that yields its bytes only when read
// (highWaterMark 0), so a value served from the cache shows no read.
function counting(files: Record<string, Served>) {
  const fetches: Record<string, number> = {};
  const reads: Record<string, number> = {};
  const counts = { cancels: 0 };
  const assets = {
    fetch: async (input: Request) => {
      const path = new URL(input.url).pathname.replace(/^\/data\//, "");
      fetches[path] = (fetches[path] ?? 0) + 1;
      const file = files[path];
      if (!file) return new Response("not found", { status: 404 });
      const bytes = new TextEncoder().encode(file.body);
      const body = new ReadableStream<Uint8Array>(
        {
          pull(controller) {
            reads[path] = (reads[path] ?? 0) + 1;
            controller.enqueue(bytes);
            controller.close();
          },
          cancel() {
            counts.cancels++;
          },
        },
        { highWaterMark: 0 },
      );
      return new Response(body, { headers: file.etag ? { etag: file.etag } : {} });
    },
  } as unknown as Fetcher;
  return { env: { ASSETS: assets } as unknown as Env, fetches, reads, counts };
}

beforeEach(() => clearParsedCache());

describe("loadJson keeps parsed files by ETag", () => {
  it("returns the kept value for the same ETag without reading the body", async () => {
    const b = counting({ "a.json": { body: '{"rows":[1,2,3]}', etag: '"v1"' } });
    const first = await loadJson<{ rows: number[] }>(b.env, "a.json");
    const second = await loadJson<{ rows: number[] }>(b.env, "a.json");
    expect(first).toEqual({ rows: [1, 2, 3] });
    expect(second).toBe(first);
    expect(b.fetches["a.json"]).toBe(2);
    expect(b.reads["a.json"]).toBe(1);
    expect(b.counts.cancels).toBe(1);
  });

  it("parses again when the ETag changes", async () => {
    const files: Record<string, Served> = { "a.json": { body: '{"n":1}', etag: '"v1"' } };
    const b = counting(files);
    const before = await loadJson<{ n: number }>(b.env, "a.json");
    files["a.json"] = { body: '{"n":2}', etag: '"v2"' };
    const after = await loadJson<{ n: number }>(b.env, "a.json");
    expect(before).toEqual({ n: 1 });
    expect(after).toEqual({ n: 2 });
    expect(b.reads["a.json"]).toBe(2);
    // The new value is the one kept now.
    expect(await loadJson(b.env, "a.json")).toBe(after);
    expect(b.reads["a.json"]).toBe(2);
  });

  it("does not keep a response without an ETag", async () => {
    const b = counting({ "a.json": { body: '{"n":1}' } });
    const first = await loadJson(b.env, "a.json");
    const second = await loadJson(b.env, "a.json");
    expect(second).toEqual(first);
    expect(second).not.toBe(first);
    expect(b.reads["a.json"]).toBe(2);
  });

  it("does not keep a body that fails to parse, and reads it as missing", async () => {
    const files: Record<string, Served> = { "a.json": { body: '{"rows":', etag: '"v1"' } };
    const b = counting(files);
    expect(await loadJson(b.env, "a.json")).toBeNull();
    expect(await loadJson(b.env, "a.json")).toBeNull();
    expect(b.reads["a.json"]).toBe(2);
    // Nothing was kept under that ETag: a readable body with it is read.
    files["a.json"] = { body: '{"rows":[]}', etag: '"v1"' };
    expect(await loadJson(b.env, "a.json")).toEqual({ rows: [] });
    expect(b.reads["a.json"]).toBe(3);
  });

  it("drops the least recently used file at 64 entries", async () => {
    const files: Record<string, Served> = {};
    for (let i = 0; i <= 64; i++) files[`f${i}.json`] = { body: `{"i":${i}}`, etag: `"e${i}"` };
    const b = counting(files);
    for (let i = 0; i < 64; i++) await loadJson(b.env, `f${i}.json`);
    // f0 is read again, so f1 is now the oldest, and the 65th file pushes it out.
    await loadJson(b.env, "f0.json");
    await loadJson(b.env, "f64.json");
    await loadJson(b.env, "f0.json");
    await loadJson(b.env, "f2.json");
    expect(b.reads["f0.json"]).toBe(1);
    expect(b.reads["f2.json"]).toBe(1);
    await loadJson(b.env, "f1.json");
    expect(b.reads["f1.json"]).toBe(2);
  });

  it("does not keep a file over 2 MB of text, and holds at most 24 MB in all", async () => {
    const big = (n: number) => JSON.stringify("x".repeat(n));
    const files: Record<string, Served> = { "huge.json": { body: big(2 * 1024 * 1024 + 1), etag: '"h"' } };
    for (let i = 0; i < 13; i++) files[`big${i}.json`] = { body: big(1.9 * 1024 * 1024), etag: `"b${i}"` };
    const b = counting(files);
    await loadJson(b.env, "huge.json");
    await loadJson(b.env, "huge.json");
    expect(b.reads["huge.json"]).toBe(2);
    // Twelve files of 1.9 MB fit in 24 MB; the thirteenth pushes out the first.
    for (let i = 0; i < 13; i++) await loadJson(b.env, `big${i}.json`);
    for (let i = 12; i >= 1; i--) await loadJson(b.env, `big${i}.json`);
    for (let i = 1; i < 13; i++) expect(b.reads[`big${i}.json`], `big${i}`).toBe(1);
    await loadJson(b.env, "big0.json");
    expect(b.reads["big0.json"]).toBe(2);
  });

  it("freezes what it returns, kept or not, so a change in place throws", async () => {
    const body = '{"rows":[{"a":2},{"a":1}],"counts":{"n":1}}';
    for (const etag of ['"v1"', undefined]) {
      clearParsedCache();
      const b = counting({ "a.json": { body, etag } });
      const v = (await loadJson<any>(b.env, "a.json"))!;
      expect(() => { v.added = 1; }).toThrow(TypeError);
      expect(() => { delete v.counts.n; }).toThrow(TypeError);
      expect(() => v.rows.push({ a: 2 })).toThrow(TypeError);
      expect(() => v.rows.sort((x: any, y: any) => x.a - y.a)).toThrow(TypeError);
      expect(() => v.rows.reverse()).toThrow(TypeError);
      expect(() => { v.rows[0].a = 2; }).toThrow(TypeError);
      expect(await loadJson(b.env, "a.json")).toEqual(JSON.parse(body));
    }
  });
});

describe("the loaders built on it copy before they change a file", () => {
  it("loadStats drops a bad optional count from a copy and leaves the kept file whole", async () => {
    const body = JSON.stringify({ ...stats, counts: { ...stats.counts, grant_employers: "many" } });
    const b = counting({ "stats.json": { body, etag: '"s1"' } });
    const s = await loadStats(b.env);
    expect(s?.counts.grant_employers).toBeUndefined();
    expect(s?.counts.pending).toBe(stats.counts.pending);
    const raw = await loadJson<any>(b.env, "stats.json");
    expect(raw.counts.grant_employers).toBe("many");
    expect(b.reads["stats.json"]).toBe(1);
  });

  it("loadStats returns the kept file itself when every count reads", async () => {
    const b = counting({ "stats.json": { body: JSON.stringify(stats), etag: '"s1"' } });
    const first = await loadStats(b.env);
    expect(await loadStats(b.env)).toBe(first);
    expect(Object.isFrozen(first)).toBe(true);
  });

  it("loadProfile fills the lists an older shard lacks on a copy", async () => {
    const e = { ASSETS: fakeAssets } as unknown as Env;
    // A shard entry written before the public records: no grants, alberta or us_carrier.
    const older = await loadProfile(e, "emp-a000000002");
    expect(older?.grants).toEqual([]);
    expect(older?.alberta).toEqual([]);
    expect(older?.us_carrier).toEqual([]);
    expect(older?.grants_total).toBe(0);
    const shard = await loadJson<any>(e, "profiles/a00.json");
    expect(shard["emp-a000000002"].grants).toBeUndefined();
    const p = await loadProfile(e, "emp-a000000001");
    expect(p?.grants_total).toBe(3);
    expect(p?.employer).toBe(shard["emp-a000000001"].employer);
  });

  it("pages share the kept stats.json across requests", async () => {
    let reads = 0;
    const assets = {
      fetch: async (input: Request) => {
        const res = await fakeAssets.fetch(input);
        if (!new URL(input.url).pathname.endsWith("/stats.json")) return res;
        const bytes = new Uint8Array(await res.arrayBuffer());
        const body = new ReadableStream<Uint8Array>(
          { pull(controller) { reads++; controller.enqueue(bytes); controller.close(); } },
          { highWaterMark: 0 },
        );
        return new Response(body, { headers: res.headers });
      },
    } as unknown as Fetcher;
    for (const path of ["/methodology", "/data", "/methodology?lang=fr"]) {
      expect((await app.request(path, {}, testEnv(assets))).status, path).toBe(200);
    }
    expect(reads).toBe(1);
  });
});

describe("ETags in the test runtime", () => {
  it("the real assets binding sends one", async () => {
    const res = await (env as unknown as { ASSETS: Fetcher }).ASSETS.fetch(new Request("https://assets.invalid/robots.txt"));
    expect(res.status).toBe(200);
    expect(res.headers.get("etag")).toMatch(/^"[0-9a-f]+"$/);
    await res.body?.cancel();
  });

  it("the fake binding derives one from the content, and a test can set or remove it", async () => {
    const url = "https://assets.invalid/data/stats.json";
    const res = await fakeAssets.fetch(new Request(url));
    const body = await res.text();
    expect(res.headers.get("etag")).toBe(await contentEtag(body));
    expect(await contentEtag(`${body} `)).not.toBe(await contentEtag(body));
    const set = makeFakeAssets({ "stats.json": '"fixed"' });
    expect((await set.fetch(new Request(url))).headers.get("etag")).toBe('"fixed"');
    const none = makeFakeAssets({ "stats.json": null });
    expect((await none.fetch(new Request(url))).headers.has("etag")).toBe(false);
  });
});
