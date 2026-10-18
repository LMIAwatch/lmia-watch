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

describe("forms", () => {
  it("renders the response form for a known employer only", async () => {
    const res = await app.request("/employers/emp-a000000001/respond", {}, testEnv());
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Submit an Employer Response");
    const unknown = await app.request("/employers/emp-ffffffffff/respond", {}, testEnv());
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
