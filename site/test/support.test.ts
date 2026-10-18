import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { DEFAULT_DONATE_LABEL, donateLink } from "../src/pages/support";
import {
  COSTS_TODAY_CENTS,
  RESERVE_GOAL_MONTHS,
  TARGET_CENTS_PER_MONTH,
  TIERS,
  type Tier,
  barWidth,
  budgetMet,
  feeSplit,
  fmtCents,
  tierCoverage,
  toCents,
} from "../src/support";
import { emptyAssets, testEnv } from "./assets";

const get = (path: string, headers: Record<string, string> = {}, env: object = testEnv()) =>
  app.request(path, { headers }, env);

// Located by class: the nav's aria-label is translated on French pages.
const mainNav = (html: string) => html.match(/<nav aria-label="[^"]*" class="main-nav"[\s\S]*?<\/nav>/)?.[0] ?? "";
const count = (html: string, s: string) => html.split(s).length - 1;

describe("support page", () => {
  it("renders every section and the tax receipt statement", async () => {
    const res = await get("/support");
    expect(res.status).toBe(200);
    const html = await res.text();
    for (const s of [
      "<h1>Support the Site</h1>",
      "What the Site Holds Today",
      "Limits of the Free Tier",
      "What It Costs Today",
      "Upgrade Paths",
      "Beyond the Costs",
      "Where a Donation Goes",
      "How to Give",
      "Transparency",
      "The Records and the Law",
      "The site is not a registered charity and cannot issue tax receipts.",
      "personal support for the person who runs the site",
      "The figures above are the whole hosting budget.",
      "The table updates itself from the payment page",
      "Open Government Licence",
    ]) {
      expect(html).toContain(s);
    }
    expect(html).not.toContain("What support would pay for");
    expect(html).toContain(fmtCents(COSTS_TODAY_CENTS));
    expect(html).not.toContain(String.fromCharCode(0x2014));
  });

  it("reads what the site holds from the stats file", async () => {
    const html = await (await get("/support")).text();
    expect(html).toContain("Every ESDC quarterly list since 2014 is loaded, through 2026 Q1.");
    expect(html).toContain("(166,497 employers)");
    expect(html).toContain("everything since 2023 Q4 in the browser");
    expect(html).toContain("Records before 2023 Q4 are in the");
    expect(html).toContain("One refresh a day, at midnight UTC.</li>");
    expect(html).toContain("100,000 page views a day.");
  });

  it("renders without the data files", async () => {
    const res = await get("/support", {}, testEnv(emptyAssets));
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toContain("Data as of n/a");
    expect(html).toContain("a longer history in the browser");
    expect(html).toContain("Older records are in the");
  });

  it("states monthly cost against monthly support, and every tier is unfunded by default", async () => {
    const html = await (await get("/support")).text();
    expect(html).toContain(
      `Monthly cost of every tier: ${fmtCents(TARGET_CENTS_PER_MONTH)}. Monthly support received: $0.00.`,
    );
    expect(html).toContain(`Reserve held: 0 of ${RESERVE_GOAL_MONTHS} months.`);
    expect(count(html, '<td class="tier-status">Not yet funded</td>')).toBe(TIERS.length);
    expect(html).not.toContain('<td class="tier-status">Funded</td>');
    expect(html).not.toContain('<td class="tier-status">Partly funded</td>');
    for (const t of TIERS) expect(html).toContain(`data-tier="${t.id}"`);
    expect(html).not.toContain("so the site needs nothing further.</strong>");
  });

  it("shows an empty transparency table with a monthly cost column", async () => {
    const html = await (await get("/support")).text();
    const table = html.slice(html.indexOf('id="transparency"'));
    expect(table).toContain('<th class="num">Monthly cost</th><th class="num">Received</th>');
    expect(table).toContain('<td colspan="5" class="muted">No donations yet</td>');
  });

  it("says donations are closed when DONATE_URL is unset", async () => {
    // The deployed config carries a real address; the test pins the closed state explicitly.
    const html = await (await get("/support", {}, { ...testEnv(), DONATE_URL: "", DONATE_LABEL: "" })).text();
    expect(html).toContain("Donations are not open yet.");
    expect(html).not.toContain('class="btn btn-primary" href=');
  });

  it("shows one outbound button when DONATE_URL is set", async () => {
    const env = { ...testEnv(), DONATE_URL: "https://donate.example/lmia", DONATE_LABEL: "Give monthly" };
    const html = await (await get("/support", {}, env)).text();
    expect(html).toContain('<a class="btn btn-primary" href="https://donate.example/lmia" rel="noopener">Give monthly</a>');
    expect(html).not.toContain("Donations are not open yet.");

    const defaultLabel = await (await get("/support", {}, { ...testEnv(), DONATE_URL: "https://donate.example/lmia", DONATE_LABEL: "" })).text();
    expect(defaultLabel).toContain(`rel="noopener">${DEFAULT_DONATE_LABEL}</a>`);
  });

  it("splits the example gift into the card fee and the rest", async () => {
    const html = await (await get("/support")).text();
    expect(html).toContain("Card processing fee: $0.59 (2.9 percent plus 30 cents)");
    expect(html).toContain("Toward the monthly cost: $9.41");
    expect(html).toContain('style="width:5.9%"');
    expect(html).toContain('style="width:94.1%"');
  });

  it("is in the main navigation after Data & About, in both languages, and in the footer", async () => {
    const html = await (await get("/")).text();
    const nav = mainNav(html);
    expect(nav).toContain(">Support</a>");
    expect(nav.indexOf(">Data &amp; About</a>")).toBeLessThan(nav.indexOf(">Support</a>"));
    expect(html).toContain('<a href="/support">Support the Site</a>');

    const fr = mainNav(await (await get("/", { cookie: "lang=fr" })).text());
    expect(fr).toContain(">Soutenir</a>");

    const own = mainNav(await (await get("/support")).text());
    expect(own).toContain('href="/support" class="active"');
  });
});

describe("fee split", () => {
  it("takes 2.9 percent plus 30 cents from a $10 gift", () => {
    expect(feeSplit(1000)).toEqual({ giftCents: 1000, feeCents: 59, netCents: 941, feeTenths: 59, netTenths: 941 });
  });

  it("rounds the percentage part to the nearest cent", () => {
    // 2.9 percent of $25 is 72.5 cents.
    expect(feeSplit(2500).feeCents).toBe(103);
    expect(feeSplit(2500).netCents).toBe(2397);
  });

  it("always adds back up to the gift", () => {
    for (const gift of [1, 31, 99, 500, 1000, 1234, 5000, 100000]) {
      const s = feeSplit(gift);
      expect(s.feeCents + s.netCents).toBe(gift);
      expect(s.feeTenths + s.netTenths).toBe(1000);
      expect(s.netCents).toBeGreaterThanOrEqual(0);
    }
  });

  it("never takes more than the gift and handles nonsense input", () => {
    expect(feeSplit(20)).toMatchObject({ feeCents: 20, netCents: 0 });
    for (const bad of [0, -500, Number.NaN]) {
      expect(feeSplit(bad)).toEqual({ giftCents: 0, feeCents: 0, netCents: 0, feeTenths: 0, netTenths: 0 });
    }
  });
});

describe("tier coverage", () => {
  const tier = (id: Tier["id"], monthlyCost: number): Tier => ({ id, name: id, monthlyCost, unlocks: "" });
  const sample = [tier("baseline", 1), tier("workers_paid", 2), tier("hosted_search", 3), tier("storage", 4)];

  it("funds the first two tiers exactly and part of the third", () => {
    // Cumulative monthly cost: 1.00, 3.00, 6.00, 10.00. Support of 4.50 covers
    // the first two and half of the third tier's own cost.
    const rows = tierCoverage(450, sample);
    expect(rows.map((r) => r.cumulativeCents)).toEqual([100, 300, 600, 1000]);
    expect(rows.map((r) => r.status)).toEqual(["Funded", "Funded", "Partly funded", "Partly funded"]);
    expect(rows.map((r) => r.width)).toEqual([100, 100, 75, 45]);
  });

  it("does the same with the real tiers", () => {
    const real = tierCoverage(0, TIERS);
    const support = real[1].cumulativeCents + Math.floor(real[2].costCents / 2);
    const rows = tierCoverage(support, TIERS);
    expect(rows.map((r) => r.status)).toEqual(["Funded", "Funded", "Partly funded", "Partly funded", "Partly funded"]);
    expect(rows[2].width).toBeLessThan(100);
  });

  it("reads Not yet funded everywhere with no support, and Funded everywhere at the target", () => {
    expect(tierCoverage(0, sample).map((r) => [r.status, r.width])).toEqual(
      Array(4).fill(["Not yet funded", 0]),
    );
    expect(tierCoverage(1000, sample).every((r) => r.status === "Funded" && r.width === 100)).toBe(true);
  });

  it("keeps the tiers in order and the target equal to their cumulative cost", () => {
    expect(TIERS.map((t) => t.id)).toEqual(["baseline", "workers_paid", "hosted_search", "storage", "x_verification"]);
    const rows = tierCoverage(0);
    expect(rows[rows.length - 1].cumulativeCents).toBe(TARGET_CENTS_PER_MONTH);
    expect(rows[0].costCents).toBe(COSTS_TODAY_CENTS);
    expect(TARGET_CENTS_PER_MONTH).toBe(TIERS.reduce((s, t) => s + toCents(t.monthlyCost), 0));
  });

  it("counts the budget as met only with full monthly support and a full reserve", () => {
    expect(budgetMet(0, 0)).toBe(false);
    expect(budgetMet(TARGET_CENTS_PER_MONTH, RESERVE_GOAL_MONTHS)).toBe(true);
    expect(budgetMet(TARGET_CENTS_PER_MONTH - 1, RESERVE_GOAL_MONTHS)).toBe(false);
    expect(budgetMet(TARGET_CENTS_PER_MONTH, RESERVE_GOAL_MONTHS - 1)).toBe(false);
  });
});

describe("support helpers", () => {
  it("bar widths are relative to the largest bar and zero stays empty", () => {
    expect(barWidth(117, 117)).toBe(100);
    expect(barWidth(0, 117)).toBe(0);
    expect(barWidth(1, 100000)).toBe(1);
    expect(barWidth(5, 0)).toBe(0);
  });

  it("only an https DONATE_URL opens donations", () => {
    expect(donateLink({})).toBeNull();
    expect(donateLink({ DONATE_URL: "  " })).toBeNull();
    expect(donateLink({ DONATE_URL: "http://donate.example/" })).toBeNull();
    expect(donateLink({ DONATE_URL: "javascript:alert(1)" })).toBeNull();
    expect(donateLink({ DONATE_URL: "not a url" })).toBeNull();
    expect(donateLink({ DONATE_URL: "https://donate.example/x", DONATE_LABEL: " " })).toEqual({
      href: "https://donate.example/x",
      label: DEFAULT_DONATE_LABEL,
    });
  });
});
