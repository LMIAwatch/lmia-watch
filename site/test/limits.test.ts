import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { bucketFor } from "../src/limits";
import { testEnv } from "./assets";

const from = (ip: string, path: string, init: RequestInit = {}) =>
  app.request(path, { ...init, headers: { ...(init.headers as Record<string, string>), "cf-connecting-ip": ip } }, testEnv());

describe("request buckets", () => {
  it("sorts paths into the right cap", () => {
    expect(bucketFor("GET", "/api/stats")).toBe("api");
    expect(bucketFor("GET", "/downloads/employers.csv")).toBe("download");
    expect(bucketFor("POST", "/corrections")).toBe("form");
    expect(bucketFor("POST", "/employers/emp-a000000001/respond")).toBe("form");
    expect(bucketFor("GET", "/corrections")).toBe("page");
    expect(bucketFor("GET", "/employers/emp-a000000001")).toBe("page");
    expect(bucketFor("POST", "/hooks/kofi")).toBe("page");
  });
});

describe("per-address limits", () => {
  const limiters = env as unknown as { API_LIMIT?: unknown; FORM_LIMIT?: unknown };

  it("answers 429 on the API past 60 requests a minute from one address", async () => {
    if (!limiters.API_LIMIT) return; // no binding in this environment: nothing is limited
    let first429 = 0;
    for (let i = 1; i <= 70; i++) {
      const res = await from("203.0.113.7", "/api/stats");
      if (res.status === 429) {
        first429 = i;
        expect(res.headers.get("retry-after")).toBe("60");
        expect(((await res.json()) as { error: string }).error).toContain("60 requests a minute");
        break;
      }
      expect(res.status).toBe(200);
    }
    expect(first429).toBeGreaterThan(50);
    expect(first429).toBeLessThanOrEqual(70);
    // Another address is unaffected.
    expect((await from("203.0.113.8", "/api/stats")).status).toBe(200);
  });

  it("caps form posts tightly and leaves the form page alone", async () => {
    if (!limiters.FORM_LIMIT) return;
    const body = new URLSearchParams({ record_ref: "emp-a000000002", request: "The street address on this profile is out of date." }).toString();
    const headers = { "content-type": "application/x-www-form-urlencoded" };
    let statuses: number[] = [];
    for (let i = 0; i < 7; i++) {
      statuses.push((await from("203.0.113.9", "/corrections", { method: "POST", headers, body })).status);
    }
    expect(statuses.slice(0, 5).every((s) => s === 200)).toBe(true);
    expect(statuses.slice(5)).toEqual([429, 429]);
    expect((await from("203.0.113.9", "/corrections")).status).toBe(200);
  });
});
