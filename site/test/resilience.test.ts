import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { pendingResults } from "../src/api";
import { FORM_MAX_BYTES } from "../src/body";
import { app } from "../src/index";
import { fakeAssets, testEnv } from "./assets";
import facets from "./fixtures/facets.json";
import profiles from "./fixtures/profiles-a00.json";
import latest from "./fixtures/search-latest.json";

// Assets that answer like the real ones except where a test says otherwise:
// a string replaces a file's body, null removes the file, "throw" makes the
// binding itself fail.
function assetsWith(overrides: Record<string, string | null | "throw">): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path in overrides) {
        const v = overrides[path];
        if (v === "throw") throw new Error("assets unavailable");
        if (v === null) return new Response("not found", { status: 404 });
        return new Response(v, { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher;
}

const brokenDb = {
  prepare: () => {
    throw new Error("D1 unavailable");
  },
  batch: async () => {
    throw new Error("D1 unavailable");
  },
} as unknown as D1Database;

const brokenBucket = {
  get: async () => {
    throw new Error("R2 unavailable");
  },
  head: async () => {
    throw new Error("R2 unavailable");
  },
} as unknown as R2Bucket;

let address = 1;
const req = (path: string, envOver: Record<string, unknown> = {}, init: RequestInit = {}) =>
  app.request(
    path,
    { ...init, headers: { "cf-connecting-ip": `203.0.113.${address++ % 250}`, ...(init.headers as Record<string, string>) } },
    { ...testEnv(), ...envOver },
  );

const PAGES = ["/", "/search", "/search?page=3", "/search?status=pending", "/map", "/data", "/employers/emp-a000000001"];

describe("missing and corrupt data files", () => {
  it("a truncated stats.json reads as not published on every page, never a 500", async () => {
    const assets = assetsWith({ "stats.json": '{"data_as_of":"2026-10-12","counts":{"pend' });
    for (const path of PAGES) {
      const res = await req(path, { ASSETS: assets });
      expect(res.status, path).toBe(503);
      expect(await res.text(), path).toContain("Data Not Published Yet");
    }
    // Pages that do not need the data keep working.
    expect((await req("/methodology", { ASSETS: assets })).status).toBe(200);
    expect((await req("/support", { ASSETS: assets })).status).toBe(200);
    expect((await req("/corrections", { ASSETS: assets })).status).toBe(200);
    expect((await req("/nothing", { ASSETS: assets })).status).toBe(404);
  });

  it("a stats.json of the wrong shape is treated like a missing one", async () => {
    for (const body of ["[]", "null", '"text"', '{"data_as_of":"2026-10-12"}']) {
      const res = await req("/", { ASSETS: assetsWith({ "stats.json": body }) });
      expect(res.status, body).toBe(503);
    }
  });

  it("home reads its lists strictly", async () => {
    const stats = JSON.parse(await (await fakeAssets.fetch("https://assets.invalid/data/stats.json")).text());
    const row = stats.recent_pending[0];
    const broken: Record<string, unknown>[] = [
      { recent_pending: null },
      { recent_approved: [{ ...row, employer: null }] },
      { recent_pending: [{ ...row, date: 20261010 }] },
      { top_approvals: [{ ...stats.top_approvals[0], positions: null }] },
      { top_approvals: [{ ...stats.top_approvals[0], stream: 7 }] },
      { by_stream: [{ k: null, n: 1 }] },
      { by_province: [{ k: "QC", n: "3054" }] },
    ];
    for (const change of broken) {
      const res = await req("/", { ASSETS: assetsWith({ "stats.json": JSON.stringify({ ...stats, ...change }) }) });
      expect(res.status, JSON.stringify(change)).toBe(503);
      expect(await res.text()).toContain("Data Not Published Yet");
    }
    // The fields the export writes as null are allowed to be null.
    const nulls = {
      recent_pending: [{ ...row, date: null, job: null, city: null, prov: null }],
      top_approvals: [{ ...stats.top_approvals[0], city: null, prov: null, stream: null }],
    };
    expect((await req("/", { ASSETS: assetsWith({ "stats.json": JSON.stringify({ ...stats, ...nulls }) }) })).status).toBe(200);
  });

  it("the search page's year range survives an unreadable data date", async () => {
    const stats = JSON.parse(await (await fakeAssets.fetch("https://assets.invalid/data/stats.json")).text());
    for (const asOf of [null, 7, 20261, "", "x2026", { y: 1 }, "9999-12-31"]) {
      const res = await req("/search", { ASSETS: assetsWith({ "stats.json": JSON.stringify({ ...stats, data_as_of: asOf }) }) });
      expect(res.status, JSON.stringify(asOf)).toBe(200);
      // The range runs from 2014 to the current year instead, and a date far
      // ahead stops at the last year the API accepts.
      const html = await res.text();
      const year = new Date().getUTCFullYear();
      expect(html).toContain('<option value="2014">2014</option>');
      expect(html).toContain(`<option value="${year}">`);
      expect(html).not.toContain(`<option value="${year + 2}">`);
    }
  });

  it("a corrupt search/first.json leaves the rows to the script; a corrupt facets file still renders", async () => {
    const first = await req("/search", { ASSETS: assetsWith({ "search/first.json": "[{" }) });
    expect(first.status).toBe(200);
    expect(await first.text()).toContain('data-ssr="0"');
    const facets = await req("/search", { ASSETS: assetsWith({ "search/facets.json": "{" }) });
    expect(facets.status).toBe(200);
    expect(await facets.text()).toContain('data-ssr="1"');
    const home = await req("/", { ASSETS: assetsWith({ "search/facets.json": "{" }) });
    expect(home.status).toBe(200);
  });

  it("a first.json with an unreadable row leaves the rows to the script; null where the export writes it is fine", async () => {
    const [posting] = latest;
    const bad: Record<string, unknown>[] = [
      { kind: "other" }, { ref: "50456228" }, { employer: null }, { employer_id: 7 }, { ind: null }, { ind: [1] },
      { wage_min: "38" }, { unit: 7 }, { positions: "1" }, { source: null }, { status: null }, { period: 7 }, { date: {} },
    ];
    for (const change of bad) {
      const res = await req("/search", { ASSETS: assetsWith({ "search/first.json": JSON.stringify([{ ...posting, ...change }, ...latest.slice(1)]) }) });
      expect(res.status, JSON.stringify(change)).toBe(200);
      expect(await res.text(), JSON.stringify(change)).toContain('data-ssr="0"');
    }
    const { kind, ...noKind } = posting;
    expect(kind).toBe("posting");
    expect(await (await req("/search", { ASSETS: assetsWith({ "search/first.json": JSON.stringify([noKind]) }) })).text()).toContain('data-ssr="0"');
    const nulls = { job: null, noc: null, street: null, city: null, prov: null, postal: null, wage_min: null, wage_max: null, unit: null, date: null, period: null, positions: null };
    const ok = await req("/search", { ASSETS: assetsWith({ "search/first.json": JSON.stringify([{ ...posting, ...nulls }]) }) });
    expect(await ok.text()).toContain('data-ssr="1"');
  });

  it("a facets.json of the wrong shape reads as missing on the search and home pages", async () => {
    const bad: unknown[] = [
      { ...facets, default: { ...facets.default, total: "5" } },
      { ...facets, default: { ...facets.default, status: null } },
      { ...facets, default: { ...facets.default, prov: { BC: "4" } } },
      { ...facets, default: { ...facets.default, status_prov: { "pending|BC": null } } },
      { ...facets, long: { ...facets.long, total: null } },
      { default: facets.default },
    ];
    for (const body of bad) {
      const assets = assetsWith({ "search/facets.json": JSON.stringify(body) });
      const search = await req("/search", { ASSETS: assets });
      expect(search.status, JSON.stringify(body).slice(0, 80)).toBe(200);
      // Without the facets the total comes from the first rows.
      expect(await search.text()).toContain('data-ssr="1"');
      const home = await req("/", { ASSETS: assets });
      expect(home.status).toBe(200);
      expect(await home.text()).not.toContain("Pending by province");
    }
  });

  it("a profile with an unreadable field is a 404 on the page, the form and the API; null where the export writes it is fine", async () => {
    const ID = "emp-a000000001";
    const shardWith = (edit: (p: any) => void) => {
      const shard = JSON.parse(JSON.stringify(profiles));
      edit(shard[ID]);
      return JSON.stringify(shard);
    };
    const finding = { operating_name: "Op", legal_name: null, address: null, reasons: "Reason", decision_date: "2025-01-01", penalty: null, status: null };
    const bad: [string, (p: any) => void][] = [
      ["id of another employer", (p) => { p.employer.id = "emp-a000000002"; }],
      ["display_name null", (p) => { p.employer.display_name = null; }],
      ["pending_count text", (p) => { p.employer.pending_count = "1"; }],
      ["postal_code number", (p) => { p.employer.postal_code = 7; }],
      ["street_source number", (p) => { p.employer.street_source = 7; }],
      ["names element null", (p) => { p.names = [null]; }],
      ["posting first_seen null", (p) => { p.postings[0].first_seen = null; }],
      ["posting wage text", (p) => { p.postings[0].wage_min = "38"; }],
      ["posting vacancies removed", (p) => { delete p.postings[0].vacancies; }],
      ["registry grade null", (p) => { p.registry[0].grade = null; }],
      ["indicator basis null", (p) => { p.indicators[0].basis = null; }],
      ["finding reasons number", (p) => { p.findings = [{ ...finding, reasons: 7 }]; }],
      ["list row period null", (p) => { p.esdc = [{ ...profiles["emp-a000000005"].esdc[0], period: null }]; }],
      ["list row published removed", (p) => { const { published, ...row } = profiles["emp-a000000005"].esdc[0]; p.esdc = [row]; }],
    ];
    for (const [label, edit] of bad) {
      const assets = assetsWith({ "profiles/a00.json": shardWith(edit) });
      for (const path of [`/employers/${ID}`, `/employers/${ID}/respond`, `/api/employers/${ID}`]) {
        expect((await req(path, { ASSETS: assets })).status, `${path} ${label}`).toBe(404);
      }
    }
    const nulls = assetsWith({
      "profiles/a00.json": shardWith((p) => {
        Object.assign(p.employer, { province: null, city: null, postal_code: null, street: null, street_source: null, status_changed_at: null });
        Object.assign(p.postings[0], { title: null, noc_code: null, wage_min: null, wage_max: null, wage_unit: null, vacancies: null, date_posted: null, valid_through: null, approved_seen_at: null });
        Object.assign(p.registry[0], { legal_name: null, entity_type: null, status: null, registered_on: null });
        p.findings = [finding, { ...finding, operating_name: null, reasons: null, decision_date: null }];
        p.esdc = [{ ...profiles["emp-a000000005"].esdc[0], stream: null, lmias: null, city: null, postal_code: null, noc_code: null, noc_title: null, positions: null, published: null }];
      }),
    });
    for (const path of [`/employers/${ID}`, `/employers/${ID}/respond`, `/api/employers/${ID}`]) {
      expect((await req(path, { ASSETS: nulls })).status, path).toBe(200);
    }
  });

  it("a corrupt or missing profile shard is a 404, in the page and in the API", async () => {
    for (const body of ['{"emp-a000000001":{"employer":', null, '{"emp-a000000001":{"employer":{}}}', '{"emp-a000000001":[]}']) {
      const assets = assetsWith({ "profiles/a00.json": body });
      expect((await req("/employers/emp-a000000001", { ASSETS: assets })).status).toBe(404);
      expect((await req("/api/employers/emp-a000000001", { ASSETS: assets })).status).toBe(404);
      expect((await req("/employers/emp-a000000001/respond", { ASSETS: assets })).status).toBe(404);
    }
  });

  it("a corrupt area file costs the profile its map, not the page", async () => {
    const res = await req("/employers/emp-a000000001", { ASSETS: assetsWith({ "areas/V0N.json": "{" }) });
    expect(res.status).toBe(200);
    expect(await res.text()).not.toContain('class="minimap"');
  });

  it("missing cluster, pending and sitemap files answer 503 or 404", async () => {
    const assets = assetsWith({
      "clusters/latest.json": null,
      "search/latest/status/pending.json": null,
      "sitemaps/index.xml": null,
    });
    expect((await req("/api/clusters", { ASSETS: assets })).status).toBe(503);
    expect((await req("/api/pending", { ASSETS: assets })).status).toBe(503);
    expect((await req("/sitemap.xml", { ASSETS: assets })).status).toBe(404);
    expect((await req("/sitemap-9.xml")).status).toBe(404);
    const corrupt = await req("/api/pending", { ASSETS: assetsWith({ "search/latest/status/pending.json": '[{"city":' }) });
    expect(corrupt.status).toBe(503);
  });

  it("an assets binding that throws gives the not-published page", async () => {
    const assets = assetsWith({ "stats.json": "throw", "search/facets.json": "throw" });
    const res = await req("/", { ASSETS: assets });
    expect(res.status).toBe(503);
    expect((await req("/api/stats", { ASSETS: assets })).status).toBe(503);
  });
});

describe("pending API without parsing the file", () => {
  const pending = latest.filter((r) => r.status === "pending");
  const parsed = (since: string) => pending.filter((r) => (r.date ?? r.sort_date) >= since);

  const bytes = (s: string) => new TextEncoder().encode(s);
  const refs = async (text: string, since: string | null) => {
    const parts = pendingResults(bytes(text), since);
    if (parts === null) return null;
    return (JSON.parse(await new Blob(parts).text()) as { ref: number }[]).map((r) => r.ref);
  };

  it("answers the same rows as parsing and filtering, for every date", async () => {
    // The fixture as the pipeline writes it: sorted keys, no spaces, newest first,
    // with a name that holds the row separator's characters and an accent.
    const sorted = (o: Record<string, unknown>) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
    const rows = pending.map((r, i) => sorted({ ...(r as unknown as Record<string, unknown>), employer: i ? r.employer : 'Café "},{city": Ltd' }));
    const text = JSON.stringify(rows);
    const dates = new Set(["0000-00-00", "2026-01-01", "2026-10-07", "2026-10-08", "2026-10-09", "9999-12-31"]);
    for (const r of pending) dates.add(r.date ?? r.sort_date);
    for (const since of dates) {
      expect(await refs(text, since), since).toEqual(parsed(since).map((r) => r.ref));
    }
    expect(await refs(text, null)).toHaveLength(pending.length);
  });

  it("falls back to parsing a file in another shape, and refuses one that is not an array", async () => {
    const pretty = JSON.stringify(pending, null, 2);
    expect(await refs(pretty, "2026-10-07")).toEqual(parsed("2026-10-07").map((r) => r.ref));
    expect(await refs("[]", "2026-10-07")).toEqual([]);
    expect(pendingResults(bytes('{"a":1}'), "2026-10-07")).toBeNull();
    expect(pendingResults(bytes("[{"), null)).toBeNull();
    expect(pendingResults(bytes('[{"city":"x"'), null)).toBeNull();
  });

  it("ignores a malformed since and says so in the reply", async () => {
    for (const since of ["2026-13-45x", "<b>", "", "2026-10-07&since=2026-10-08"]) {
      const res = await req(`/api/pending?since=${encodeURIComponent(since)}`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as { since: string; results: unknown[] };
      expect(body.since).toBe("1970-01-01");
      expect(body.results).toHaveLength(pending.length);
    }
  });
});

describe("storage outages", () => {
  it("pages render with D1 down; the support page shows its empty state", async () => {
    const profile = await req("/employers/emp-a000000001", { DB: brokenDb });
    expect(profile.status).toBe(200);
    expect(await profile.text()).toContain("PinkCloud Cleaning &amp; Home Services");
    const support = await req("/support", { DB: brokenDb });
    expect(support.status).toBe(200);
    expect(await support.text()).toContain("Monthly support received: $0.00.");
    const noBinding = await req("/support", { DB: undefined });
    expect(noBinding.status).toBe(200);
  });

  it("the search page falls back to its static rows when the search database fails or is missing, and no cache keeps it", async () => {
    for (const SEARCH of [brokenDb, undefined]) {
      for (const path of ["/search", "/search?q=haveli&status=refused&sort=name", "/search?cursor=abc&page=3"]) {
        const res = await req(path, { SEARCH });
        expect(res.status, path).toBe(200);
        expect(res.headers.get("cache-control"), path).toBe("no-store");
        const html = await res.text();
        expect(html, path).toContain('data-mode="static"');
        expect(html, path).toContain('<p class="panel bordered" id="search-unavailable" role="status">Search is unavailable for the moment, so the newest records are shown.</p>');
        expect(html, path).toContain("PinkCloud Cleaning &amp; Home Services");
      }
    }
    // With the fallback file broken too, the page still answers and leaves the rows to the script.
    const both = await req("/search", { SEARCH: brokenDb, ASSETS: assetsWith({ "search/first.json": "[{" }) });
    expect(both.status).toBe(200);
    const html = await both.text();
    expect(html).toContain('data-ssr="0"');
    // No sentence about newest records when none are shown (the script's
    // strings block still carries it).
    expect(html).not.toContain('id="search-unavailable"');
  });

  it("forms fail politely with D1 down: the form comes back with what was typed", async () => {
    const form = (path: string, fields: Record<string, string>) =>
      req(path, { DB: brokenDb }, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(fields).toString(),
      });
    const response = await form("/employers/emp-a000000001/respond", {
      name: "Owner", email: "owner@example.com", statement: "A statement long enough to pass the form's check.",
    });
    expect(response.status).toBe(503);
    const html = await response.text();
    expect(html).toContain("Try again in a moment.");
    expect(html).toContain("A statement long enough to pass the form&#39;s check.");
    expect(response.headers.get("cache-control")).toBe("no-store");
    const correction = await form("/corrections", { record_ref: "emp-a000000002", request: "The street is out of date." });
    expect(correction.status).toBe(503);
    expect(await correction.text()).toContain("The street is out of date.");
  });

  it("the donation webhook answers 503 when it cannot store, so the notice is sent again", async () => {
    const doc = {
      verification_token: "tok-123456", kofi_transaction_id: "tx-outage-1", amount: "5.00", currency: "CAD",
      timestamp: new Date().toISOString(), type: "Donation",
    };
    const res = await req("/hooks/kofi", { DB: brokenDb, KOFI_VERIFICATION_TOKEN: "tok-123456" }, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ data: JSON.stringify(doc) }).toString(),
    });
    expect(res.status).toBe(503);
  });

  it("downloads answer 503 when R2 fails and 404 when it is not bound", async () => {
    const down = await req("/downloads/employers.csv", { DATA: brokenBucket });
    expect(down.status).toBe(503);
    expect(await down.text()).toContain("not available yet");
    expect((await req("/downloads/employers.csv", { DATA: undefined })).status).toBe(404);
    expect((await req("/downloads/..%2Fstatus.json")).status).toBe(404);
    expect((await req("/downloads/mirror/..%2F..%2Fstatus.json")).status).toBe(404);
  });
});

describe("hostile form bodies", () => {
  const post = (path: string, body: BodyInit, headers: Record<string, string>) =>
    req(path, {}, { method: "POST", headers, body });

  it("a multipart body without its boundary, or a non-form body, is a 400, never a 500", async () => {
    for (const path of ["/corrections", "/employers/emp-a000000001/respond"]) {
      expect((await post(path, "garbage", { "content-type": "multipart/form-data" })).status, path).toBe(400);
      expect((await post(path, "--zz\r\nbroken", { "content-type": "multipart/form-data; boundary=zz" })).status, path).toBe(400);
      expect((await post(path, '{"request":"x"}', { "content-type": "application/json" })).status, path).toBe(400);
      expect((await post(path, "a=1", {})).status, path).toBe(400);
    }
  });

  it("an oversized body is refused before it is parsed, declared or not", async () => {
    const big = "request=" + "x".repeat(FORM_MAX_BYTES + 10);
    const declared = await post("/corrections", big, { "content-type": "application/x-www-form-urlencoded" });
    expect(declared.status).toBe(413);
    const stream = new ReadableStream({
      start(controller) {
        const chunk = new TextEncoder().encode("x".repeat(16 * 1024));
        controller.enqueue(new TextEncoder().encode("request="));
        for (let i = 0; i < 8; i++) controller.enqueue(chunk);
        controller.close();
      },
    });
    const undeclared = await req("/corrections", {}, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: stream,
      // @ts-expect-error duplex is required for a streamed body and missing from the type
      duplex: "half",
    });
    expect(undeclared.status).toBe(413);
    const hook = await req("/hooks/kofi", { KOFI_VERIFICATION_TOKEN: "tok" }, {
      method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: big,
    });
    expect(hook.status).toBe(413);
  });

  it("null bytes and other control characters never reach the database", async () => {
    const res = await post(
      "/corrections",
      new URLSearchParams({ record_ref: "Job Bank \u000050436247", request: "Wage\u0000 shown\u0007 with the wrong unit.\nSecond line." }).toString(),
      { "content-type": "application/x-www-form-urlencoded" },
    );
    expect(res.status).toBe(200);
    const row = await env.DB.prepare("SELECT record_ref, request FROM corrections ORDER BY id DESC LIMIT 1").first<{ record_ref: string; request: string }>();
    expect(row?.record_ref).toBe("Job Bank 50436247");
    expect(row?.request).toBe("Wage shown with the wrong unit.\nSecond line.");
  });

  it("markup in a form comes back escaped", async () => {
    const res = await post(
      "/corrections",
      new URLSearchParams({ record_ref: "<script>x</script>", request: "<img src=x onerror=alert(1)>", email: "<b>not-an-address" }).toString(),
      { "content-type": "application/x-www-form-urlencoded" },
    );
    expect(res.status).toBe(400);
    const html = await res.text();
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });
});

describe("odd query input", () => {
  it("search, map and language inputs never fail and never echo raw markup", async () => {
    const mark = "<x9z>";
    for (const path of [
      `/search?q=${"a".repeat(5000)}`,
      `/search?q=${encodeURIComponent(mark)}&noc=${encodeURIComponent(mark)}&wage_min=${encodeURIComponent(mark)}`,
      "/search?page=-1", "/search?page=99999999", "/search?page=NaN", "/search?page=1e400",
      "/search?province=ZZ&province=ZZ&status=bogus", "/search?q=%ff%fe", "/search?q=%",
      `/search?q=${encodeURIComponent("‮abc שלום 😀")}`,
      `/search?date=${encodeURIComponent(mark)}&sort=${encodeURIComponent(mark)}&indicator=${encodeURIComponent(mark)}`,
      "/?lang=zz", `/map?fsa=${encodeURIComponent(mark)}`, "/map?fsa=%00%00", `/corrections?employer=${encodeURIComponent(mark)}`,
      `/employers/${encodeURIComponent(mark)}`, "/employers/EMP-A000000001", "/api/area/..%2F..%2Fstats",
    ]) {
      const res = await req(path);
      expect(res.status, path).toBeLessThan(500);
      expect(await res.text(), path).not.toContain(mark);
    }
    const garbage = await req("/", {}, { headers: { cookie: "lang=%%%;;" } });
    expect(garbage.status).toBe(200);
  });
});
