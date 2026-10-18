import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { parseNotice, tokensMatch } from "../src/hooks";
import { app } from "../src/index";
import { COSTS_TODAY_CENTS } from "../src/support";
import { computeFigures, monthsStarted, quarterOf, quartersSince, toCadCents } from "../src/support_data";
import { testEnv } from "./assets";

const TOKEN = "test-token-1234";
const DAY = 24 * 60 * 60 * 1000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

// The shape Ko-fi documents, name and email included, so the tests prove they are dropped.
const notice = (over: Record<string, unknown> = {}) => ({
  verification_token: TOKEN,
  message_id: "7a8b9c",
  timestamp: ago(2),
  type: "Donation",
  is_public: true,
  from_name: "A Person",
  message: "Keep going",
  amount: "5.00",
  url: "https://ko-fi.com/x/1",
  email: "person@example.com",
  currency: "CAD",
  is_subscription_payment: false,
  is_first_subscription_payment: false,
  kofi_transaction_id: "00000000-1111-2222-3333-444444444444",
  shop_items: null,
  tier_name: null,
  shipping: null,
  ...over,
});

const post = (doc: unknown, extra: Record<string, unknown> = {}, raw?: string) =>
  app.request(
    "/hooks/kofi",
    {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: raw ?? new URLSearchParams({ data: JSON.stringify(doc) }).toString(),
    },
    { ...testEnv(), KOFI_VERIFICATION_TOKEN: TOKEN, ...extra },
  );

const rows = async () => (await env.DB.prepare("SELECT * FROM donations ORDER BY id").all<Record<string, unknown>>()).results;

describe("donation webhook", () => {
  it("is closed until the secret exists", async () => {
    const res = await post(notice(), { KOFI_VERIFICATION_TOKEN: "" });
    expect(res.status).toBe(503);
    expect(await rows()).toHaveLength(0);
  });

  it("refuses a wrong token and malformed bodies", async () => {
    expect((await post(notice({ verification_token: "nope" }))).status).toBe(403);
    expect((await post(notice({ verification_token: 42 }))).status).toBe(403);
    expect((await post(null, {}, "data=not-json")).status).toBe(400);
    expect((await post(null, {}, "other=1")).status).toBe(400);
    expect(await rows()).toHaveLength(0);
  });

  it("stores amount, time, kind and id only, ignores repeats, and feeds the support page", async () => {
    expect((await post(notice())).status).toBe(200);
    expect((await post(notice())).status).toBe(200);
    const usd = notice({
      kofi_transaction_id: "55555555-6666-7777-8888-999999999999",
      type: "Subscription",
      amount: "5",
      currency: "usd",
      is_subscription_payment: true,
      is_first_subscription_payment: true,
      timestamp: ago(1),
    });
    expect((await post(usd)).status).toBe(200);

    const stored = await rows();
    expect(stored).toHaveLength(2);
    expect(stored[0]).toMatchObject({ kind: "Donation", amount_cents: 500, currency: "CAD", recurring: 0, first_payment: 0 });
    expect(stored[1]).toMatchObject({ kind: "Subscription", amount_cents: 500, currency: "USD", recurring: 1, first_payment: 1 });
    const columns = Object.keys(stored[0]);
    for (const c of ["from_name", "email", "message", "name", "url"]) expect(columns).not.toContain(c);
    expect(JSON.stringify(stored)).not.toContain("A Person");
    expect(JSON.stringify(stored)).not.toContain("example.com");

    const html = await (await app.request("/support", {}, testEnv())).text();
    // 5.00 CAD plus 5 USD at the planning rate of 1.4.
    expect(html).toContain("Monthly support received: $12.00.");
    expect(html).not.toContain("No donations yet");
    const table = html.slice(html.indexOf('id="transparency"'));
    expect(table).toContain(quarterOf(new Date().toISOString()));
    expect(table).toContain(fmtCentsLike(1200));
  });
});

const fmtCentsLike = (cents: number) => `$${(cents / 100).toFixed(2)}`;

describe("notice parsing", () => {
  it("rejects what the ledger cannot count", () => {
    expect(parseNotice(null)).toBeNull();
    expect(parseNotice(notice({ kofi_transaction_id: "" }))).toBeNull();
    expect(parseNotice(notice({ amount: "abc" }))).toBeNull();
    expect(parseNotice(notice({ amount: "-1" }))).toBeNull();
    expect(parseNotice(notice({ currency: "C$" }))).toBeNull();
    const ok = parseNotice(notice({ amount: 3.5, timestamp: "not a date", type: "" }));
    expect(ok).toMatchObject({ amountCents: 350, kind: "Donation", currency: "CAD" });
    expect(new Date(ok!.receivedAt).getTime()).toBeGreaterThan(Date.now() - DAY);
  });

  it("compares tokens in full", () => {
    expect(tokensMatch("abc", "abc")).toBe(true);
    expect(tokensMatch("abc", "abd")).toBe(false);
    expect(tokensMatch("ab", "abc")).toBe(false);
    expect(tokensMatch("", "")).toBe(false);
  });
});

describe("support figures", () => {
  it("counts quarters and months from the site's first month", () => {
    expect(quartersSince("2026-10-01", new Date("2026-10-17T00:00:00Z"))).toEqual(["2026 Q4"]);
    expect(quartersSince("2026-10-01", new Date("2027-02-15T00:00:00Z"))).toEqual(["2026 Q4", "2027 Q1"]);
    expect(monthsStarted("2026 Q4", "2026-10-01", new Date("2026-10-17T00:00:00Z"))).toBe(1);
    expect(monthsStarted("2026 Q4", "2026-10-01", new Date("2026-12-01T00:00:00Z"))).toBe(3);
    expect(monthsStarted("2027 Q1", "2026-10-01", new Date("2026-12-01T00:00:00Z"))).toBe(0);
    expect(quarterOf("2026-10-20T15:04:05Z")).toBe("2026 Q4");
    expect(toCadCents(500, "USD")).toBe(700);
    expect(toCadCents(500, "EUR")).toBe(500);
  });

  it("turns rows into the ledger: received, spent per month started, reserve floored at zero", () => {
    const now = new Date("2026-11-20T12:00:00Z");
    const rows = [
      { received_at: "2026-10-20T15:04:05Z", amount_cents: 500, currency: "CAD" },
      { received_at: "2026-11-15T09:00:00Z", amount_cents: 1000, currency: "USD" },
    ];
    const f = computeFigures(rows, now, "2026-10-01");
    expect(f.donations).toBe(2);
    expect(f.monthlySupportCents).toBe(1400); // the October gift is 31 days old
    expect(f.totalReceivedCents).toBe(1900);
    expect(f.totalSpentCents).toBe(COSTS_TODAY_CENTS * 2);
    // The sample gifts may not cover two months of cost; the reserve never goes below zero.
    expect(f.reserveCents).toBe(Math.max(0, 1900 - COSTS_TODAY_CENTS * 2));
    expect(f.ledger).toEqual([
      { quarter: "2026 Q4", monthlyCostCents: COSTS_TODAY_CENTS, receivedCents: 1900, spentCents: COSTS_TODAY_CENTS * 2, reserveCents: Math.max(0, 1900 - COSTS_TODAY_CENTS * 2) },
    ]);
    const empty = computeFigures([], new Date("2027-01-10T00:00:00Z"), "2026-10-01");
    expect(empty.ledger.map((r) => [r.quarter, r.spentCents, r.reserveCents])).toEqual([
      ["2026 Q4", COSTS_TODAY_CENTS * 3, 0],
      ["2027 Q1", COSTS_TODAY_CENTS, 0],
    ]);
    expect(empty.reserveMonths).toBe(0);
  });
});
