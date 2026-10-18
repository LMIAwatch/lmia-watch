import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { emptyAssets, testEnv } from "./assets";

const json = async (path: string) => {
  const res = await app.request(path, {}, testEnv());
  return { status: res.status, body: (await res.json()) as any, headers: res.headers };
};

describe("api", () => {
  it("stats passes the file through", async () => {
    const { status, body, headers } = await json("/api/stats");
    expect(status).toBe(200);
    expect(body.counts.pending).toBe(5883);
    expect(body.esdc_latest_period).toBe("2026Q1");
    expect(headers.get("content-type")).toContain("application/json");
    expect(headers.get("cache-control")).toContain("max-age=300");
  });

  it("employer detail from the profile shard", async () => {
    const { status, body } = await json("/api/employers/emp-a000000001");
    expect(status).toBe(200);
    expect(body.employer.display_name).toContain("PinkCloud");
    expect(body.postings.length).toBe(1);
    expect(body.registry[0].registry_id).toBe("BC1596446");
    expect(body.indicators.some((i: any) => i.indicator === "newly_incorporated" && i.state === "triggered")).toBe(true);
    const missing = await json("/api/employers/emp-ffffffffff");
    expect(missing.status).toBe(404);
    const malformed = await json("/api/employers/not-an-id");
    expect(malformed.status).toBe(404);
  });

  it("pending since a date", async () => {
    const { body } = await json("/api/pending?since=2026-10-07");
    expect(body.results.map((r: any) => r.ref)).toEqual([50456228]);
    const all = await json("/api/pending");
    expect(all.body.results.length).toBe(2);
    expect(all.body.results.every((r: any) => r.status === "pending")).toBe(true);
  });

  it("facets pass through", async () => {
    const { status, body } = await json("/api/search/facets");
    expect(status).toBe(200);
    expect(body.default.total).toBe(5);
    expect(body.files["search/first.json"].rows).toBe(5);
  });

  it("clusters and areas", async () => {
    const { body } = await json("/api/clusters");
    const byFsa = Object.fromEntries(body.map((c: any) => [c.fsa, c]));
    expect(byFsa.V0N.pending).toBe(1);
    expect(byFsa.A1C.refused).toBe(1);
    const area = await json("/api/area/v0n");
    expect(area.status).toBe(200);
    expect(area.body.rows[0].employer).toContain("PinkCloud");
    expect(area.body.prov).toBe("BC");
    const none = await json("/api/area/X0X");
    expect(none.status).toBe(404);
    const bad = await json("/api/area/zzzz");
    expect(bad.status).toBe(400);
  });

  it("unknown api routes and missing data answer in json", async () => {
    const unknown = await json("/api/employers");
    expect(unknown.status).toBe(404);
    expect(unknown.body.error).toBe("not found");
    const res = await app.request("/api/stats", {}, testEnv(emptyAssets));
    expect(res.status).toBe(503);
  });
});
