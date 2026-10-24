import { env } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { SearchCounts } from "../src/data";
import { app } from "../src/index";
import { readSearchUrl, searchParamsOf } from "../src/pages/search";
import { countsFor, parseQuery, runSearch } from "../src/search_db";
import { fakeAssets, testEnv } from "./assets";

// The search page's first view against a real local D1 (search_schema.sql
// applied by test/setup.ts), filled here the way the nightly sync fills it.
// Every other test file leaves its search database empty, so the pages they
// render are the fallback.

interface Seed {
  kind: "esdc" | "posting";
  ref: number;
  employer: string;
  job: string;
  noc: string;
  city: string | null;
  prov: string | null;
  wage_min: number | null;
  wage_max: number | null;
  date: string | null;
  period: string | null;
  positions: number | null;
  status: string;
  stream: string | null;
  sort_date: string;
  year: number;
  ind: string;
  street?: string;
  postal?: string;
}

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const periodEnd = (p: string) => `${p.slice(0, 4)}-${["03-31", "06-30", "09-30", "12-31"][Number(p.slice(5, 6) || "4") - 1]}`;

function esdc(ref: number, employer: string, prov: string | null, period: string, positions: number | null, status: string,
  stream: string | null, ind = ""): Seed {
  return {
    kind: "esdc", ref, employer, job: "Harvesting labourers", noc: "85100", city: "Town", prov, wage_min: null, wage_max: null,
    date: null, period, positions, status, stream, sort_date: periodEnd(period), year: Number(period.slice(0, 4)), ind,
  };
}

const NAMED: Seed[] = [
  {
    kind: "posting", ref: 9001, employer: "Tim Hortons #1234 (Horton Holdings Ltd)", job: "Food counter attendant/server", noc: "65201",
    city: "Toronto", prov: "ON", wage_min: 16.55, wage_max: 17, date: "2026-10-20", period: null, positions: null, status: "pending",
    stream: null, sort_date: "2026-10-20", year: 2026, ind: "low_wage_high_unemployment,repeat_applicant",
    street: "123 Queen Street West", postal: "M5H 2M9",
  },
  esdc(1, "Ferme Éloïse Québec Inc.", "QC", "2026Q1", 12, "approved", "Primary Agriculture", "repeat_applicant"),
  esdc(2, "O'Brien Farms Ltd", "BC", "2015Q4", 2, "refused", null, "high_volume,repeat_applicant"),
];
const NAMES = ["Acme", "Birch", "Cedar", "Delta", "Elm", "Fir", "Grove", "Harbour", "Iris", "Juniper", "Kestrel", "Larch", "Maple",
  "Nettle", "Oak", "Pine", "Quill", "Rowan", "Spruce", "Tamarack"];
const PROVS = ["ON", "BC", "QC", "AB", "ON", "MB"];
const STREAMS = ["Low Wage", "High Wage", "Primary Agriculture", null];
const FILLER: Seed[] = Array.from({ length: 123 }, (_, i) =>
  esdc(100 + i, `${NAMES[i % NAMES.length]} Holdings`, PROVS[i % PROVS.length], `${2014 + (i % 13)}Q${1 + (i % 4)}`,
    i % 3 === 0 ? null : 1 + (i % 5), i % 4 === 3 ? "refused" : "approved", STREAMS[i % STREAMS.length], i % 9 === 0 ? "high_volume" : ""));
const SEEDS = [...NAMED, ...FILLER];

const sourceOf = (s: Seed) =>
  s.kind === "posting" ? `https://www.jobbank.gc.ca/jobsearch/jobposting/${s.ref}` : `https://open.canada.ca/x/resource/r${s.ref}`;
const COLUMNS = ["rid", "key", "kind", "ref", "employer_id", "employer", "job", "noc", "street", "city", "prov", "postal", "wage_min",
  "wage_max", "unit", "date", "period", "positions", "status", "stream", "source", "sort_date", "year", "ind", "name_fold", "hash"] as const;

function values(s: Seed): (string | number | null)[] {
  const rid = s.kind === "posting" ? s.ref * 2 + 1 : s.ref * 2;
  const row: Record<string, string | number | null> = {
    ...s, rid, key: `${s.kind === "posting" ? "p" : "e"}:${s.ref}`, employer_id: `emp-${s.kind === "posting" ? "a" : "e"}${String(s.ref).padStart(9, "0")}`,
    street: s.street ?? null, postal: s.postal ?? null, unit: s.kind === "posting" ? "HOUR" : null, source: sourceOf(s),
    name_fold: fold(s.employer), hash: `h${rid}`,
  };
  return COLUMNS.map((c) => row[c]);
}

// counts.json as export_static.write_search_counts writes it, from the seed.
function countsOf(rows: Seed[]): SearchCounts {
  const dims = ["status", "prov", "stream", "year", "ind"] as const;
  const lists: Record<string, (string | number | null)[]> = { status: [], prov: [], stream: [], year: [], ind: [] };
  const cells = new Map<string, number[]>();
  for (const r of rows) {
    const idx = dims.map((d) => {
      const v = r[d] as string | number | null;
      const i = lists[d].indexOf(v);
      return i < 0 ? lists[d].push(v) - 1 : i;
    });
    const cell = cells.get(idx.join(",")) ?? [...idx, 0];
    cell[5] += 1;
    cells.set(idx.join(","), cell);
  }
  // 2026Q4 is the newest period the filler makes.
  return { data_as_of: "2026-10-22", latest_period: "2026Q4", total: rows.length, dims: [...dims], cells: [...cells.values()], values: lists as unknown as SearchCounts["values"] };
}

const COUNTS = countsOf(SEEDS);
function withCounts(): ReturnType<typeof testEnv> {
  return testEnv({
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url).pathname === "/data/search/counts.json") return new Response(JSON.stringify(COUNTS));
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher);
}

let address = 1;
const ip = () => `198.51.100.${address++ % 250}`;
async function html(path: string, environment: object = withCounts(), headers: Record<string, string> = {}) {
  const res = await app.request(path, { headers: { "cf-connecting-ip": ip(), ...headers } }, environment);
  return { status: res.status, headers: res.headers, text: await res.text() };
}
async function api(qs: string) {
  const res = await app.request(`/api/search?${qs}`, { headers: { "cf-connecting-ip": ip(), "sec-fetch-site": "same-origin" } }, withCounts());
  return { status: res.status, body: (await res.json()) as any };
}

const tbody = (page: string) => page.match(/<tbody id="results-body">([\s\S]*?)<\/tbody>/)?.[1] ?? "";
const sources = (page: string) => [...tbody(page).matchAll(/<a href="([^"]+)" class="mono" rel="nofollow noopener"[^>]*>/g)].map((m) => m[1]);
const unescape = (s: string) => s.replace(/&amp;/g, "&");
const nextHref = (page: string) => {
  const m = /<a href="([^"]*)" class="btn" id="page-next">/.exec(page);
  return m ? unescape(m[1]) : null;
};
const prevHref = (page: string) => {
  const m = /<a href="([^"]*)" class="btn" id="page-prev">/.exec(page);
  return m ? unescape(m[1]) : null;
};
const attr = (page: string, name: string) => new RegExp(`<div class="results" id="results"[^>]*\\s${name}="([^"]*)"`).exec(page)?.[1];
const nbsp = (s: string) => s.replace(/[  ]/g, " ");

// Every page of a query through the API, as search.js walks it.
async function apiWalk(qs: string): Promise<string[]> {
  const out: string[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < 20; i++) {
    const { body } = await api(cursor ? `${qs}${qs ? "&" : ""}cursor=${cursor}` : qs);
    out.push(...body.rows.map((r: { source: string }) => r.source));
    cursor = body.next;
    if (!cursor) return out;
  }
  throw new Error("more pages than the seed holds");
}

beforeAll(async () => {
  const stmts: D1PreparedStatement[] = [];
  for (let i = 0; i < SEEDS.length; i += 3) {
    const chunk = SEEDS.slice(i, i + 3);
    stmts.push(env.SEARCH.prepare(`INSERT INTO search_rows (${COLUMNS.join(", ")}) VALUES ` +
      chunk.map(() => `(${COLUMNS.map(() => "?").join(", ")})`).join(", ")).bind(...chunk.flatMap(values)));
  }
  for (let i = 0; i < stmts.length; i += 50) await env.SEARCH.batch(stmts.slice(i, i + 50));
});

describe("the first view from the search database", () => {
  it("renders the newest rows, the total, the filter counts and a link to the next page", async () => {
    const page = await html("/search");
    expect(page.status).toBe(200);
    expect(page.headers.get("cache-control")).toBe("public, max-age=300");
    const t = page.text;
    expect(attr(t, "data-mode")).toBe("db");
    expect(attr(t, "data-ssr")).toBe("1");
    expect(t).not.toContain('id="search-unavailable"');
    expect(t).toContain(`<strong>${SEEDS.length} records</strong> <span class="muted" id="results-note">Job Bank postings and ESDC lists since 2014</span>`);
    // The same rows, in the same order, as the search itself answers.
    const q = parseQuery(new URL("https://x.invalid/search")) as { ok: true; query: any };
    const direct = await runSearch(env, q.query, "2026-10-22", COUNTS);
    expect(sources(t)).toEqual(direct!.rows.map((r) => r.source));
    expect(sources(t)).toHaveLength(50);
    expect(t).toContain("Tim Hortons #1234 (Horton Holdings Ltd)</a>");
    // Filter counts from the counts file, beside each status and province.
    const { facets } = countsFor(COUNTS, q.query);
    for (const s of ["pending", "approved", "refused"]) {
      expect(t).toContain(`data-count="status:${s}"> ${(facets.status[s] ?? 0).toLocaleString("en-CA")}</span>`);
    }
    expect(t).toContain(`data-count="province:ON"> ${facets.prov.ON}</span>`);
    expect(t).toContain('data-count="province:NU"> 0</span>');
    expect(t).toContain("Showing 1 to 50 of 126");
    expect(t).toContain("Page 1 of 3");
    expect(t).toMatch(/<button type="button" class="btn" id="page-prev" disabled="">/);
    const next = nextHref(t);
    expect(next).toMatch(/^\/search\?cursor=[A-Za-z0-9_-]+&page=2$/);
    // The script starts from what the server drew.
    expect(attr(t, "data-next")).toBe(new URL(next!, "https://x.invalid").searchParams.get("cursor"));
    expect(attr(t, "data-cursor")).toBe("");
    expect(attr(t, "data-page")).toBe("1");
    expect(attr(t, "data-total")).toBe("126");
    expect(attr(t, "data-capped")).toBe("0");
    expect(t).toMatch(/name="date" value="any" checked=""\/><span class="lbl">Any date since 2014<\/span>/);
    expect(t).toMatch(/name="date" value="last_quarter"\/><span class="lbl">Postings of the last 92 days and the 2026 Q1 lists<\/span>/);
  });

  it("puts each filter's count in its own box after the label, where search.js finds it", async () => {
    const t = (await html("/search")).text;
    const q = parseQuery(new URL("https://x.invalid/search")) as { ok: true; query: any };
    const { facets } = countsFor(COUNTS, q.query);
    // Input, label, count: the CSS right-aligns the third in a column.
    expect(t).toContain('<label class="check"><input type="checkbox" name="province" value="ON"/><span class="lbl">Ontario</span>' +
      `<span class="mono muted" data-count="province:ON"> ${facets.prov.ON}</span></label>`);
    expect(t).toContain('<label class="check"><input type="checkbox" name="status" value="pending"/><span class="lbl">' +
      '<span class="badge badge-pending">Pending</span></span><span class="mono muted" data-count="status:pending">');
    // Streams and the radios take the same shape, without a count.
    expect(t).toContain('<label class="check"><input type="checkbox" name="stream" value="Low Wage"/><span class="lbl">Low Wage</span></label>');
    expect(t).toContain('<label class="check"><input type="radio" name="indicator" value="high_volume"/><span class="lbl">High volume</span></label>');
    // Every status and province box keeps its data-count span (search.js selects by it).
    expect(t.match(/ data-count="(status|province):[A-Za-z]+"/g)).toHaveLength(3 + 14);
  });

  it("draws short cells with the full text in each title, and a header that fits", async () => {
    const t = (await html("/search")).text;
    expect(t).toContain("<th>Status</th><th>Employer</th><th>Occupation</th><th>Location</th><th>Wage</th><th>Date</th>" +
      "<th class=\"num\">Positions</th><th>Indicators</th><th>Source</th>");
    expect(t).not.toContain("Job or occupation");
    const body = tbody(t);
    // A slash in a title is a place to break the line, not a new character.
    expect(body).toContain('<td data-label="Occupation">Food counter attendant/<wbr/>server</td>');
    expect(body).toContain('<td data-label="Occupation">85100 Harvesting labourers</td>');
    // The street moves to the title; city, province and postal code stay.
    expect(body).toContain('<td data-label="Location" title="123 Queen Street West, Toronto, ON M5H 2M9">Toronto, ON M5H 2M9</td>');
    expect(body).toContain('<td data-label="Location">Town, ON</td>');
    expect(body).not.toMatch(/data-label="Location" title="[^"]*">Town/);
    // A posting's date never wraps; a list's period may (the CSS reads the class).
    expect(body).toContain('<td data-label="Date" class="mono">2026-10-20</td>');
    expect(body).toMatch(/<td data-label="Date" class="mono period">\d{4} Q\d<\/td>/);
    // Positions keep their right alignment beside the date column.
    expect(body).toContain('<td data-label="Positions" class="mono num">see posting</td>');
    expect(t.match(/<table class="restack">[\s\S]*?<\/table>/)?.[0]).not.toMatch(/class="[^"]*\bnum\b/);
    // Long indicator labels shorten, the full label in the chip's title; short ones stay as they are.
    expect(body).toContain('<span class="chips"><span class="chip" title="Low-wage stream in a high-unemployment region">Low wage, high unemployment</span>' +
      '<span class="chip">Repeat applicant</span></span>');
    // The source link names the source; the record it points at is in the title.
    expect(body).toContain('<a href="https://www.jobbank.gc.ca/jobsearch/jobposting/9001" class="mono" rel="nofollow noopener" title="Job Bank 9001">Job Bank</a>');
    expect(body).toMatch(/<a href="https:\/\/open\.canada\.ca\/x\/resource\/r\d+" class="mono" rel="nofollow noopener" title="ESDC (positive|negative) \d{4}Q\d">ESDC<\/a>/);
    expect(body).not.toMatch(/>Job Bank \d+<\/a>|>ESDC (positive|negative)/);
  });

  it("renders the last-quarter window: recent postings and the latest period's list rows", async () => {
    const t = (await html("/search?date=last_quarter")).text;
    expect(t).toMatch(/name="date" value="last_quarter" checked=""/);
    const { body } = await api("date=last_quarter");
    expect(sources(t)).toEqual(body.rows.map((r: { source: string }) => r.source));
    // The posting dated 2026-10-20 and the 2026Q4 filler rows; never a list row of another period.
    expect(t).toContain("Tim Hortons #1234 (Horton Holdings Ltd)</a>");
    expect(body.rows.every((r: { kind: string; period: string | null }) => r.kind === "posting" || r.period === "2026Q4")).toBe(true);
    expect(t).toContain(`<strong>${body.total} records</strong>`);
  });

  it("follows its next links through every page, and links page 2 back to the first", async () => {
    const seen: string[] = [];
    let path: string | null = "/search";
    const labels: string[] = [];
    while (path) {
      const page = await html(path);
      seen.push(...sources(page.text));
      labels.push(/<span class="mono" id="page-label">([^<]*)<\/span>/.exec(page.text)?.[1] ?? "");
      if (labels.length === 2) expect(prevHref(page.text)).toBe("/search");
      if (labels.length === 3) {
        // Only page 2 knows its previous page; later pages leave it to the browser.
        expect(prevHref(page.text)).toBeNull();
        expect(page.text).toContain("Showing 101 to 126 of 126");
      }
      path = nextHref(page.text);
      expect(labels.length).toBeLessThan(5);
    }
    expect(labels).toEqual(["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"]);
    expect(new Set(seen).size).toBe(SEEDS.length);
    expect(seen).toEqual(await apiWalk(""));
  });

  it("renders a shared URL's filters and carries exactly those filters on its links", async () => {
    const qs = "status=approved&year_from=2015&sort=name";
    const page = await html(`/search?${qs}`);
    const t = page.text;
    expect(t).toMatch(/name="status" value="approved" checked=""/);
    expect(t).not.toMatch(/name="status" value="refused" checked/);
    expect(t).toContain('<option value="2015" selected="">2015</option>');
    expect(t).toContain('<option value="name" selected="">Employer A to Z</option>');
    const first = await api(qs);
    expect(sources(t)).toEqual(first.body.rows.map((r: { source: string }) => r.source));
    expect(t).toContain(`<strong>${first.body.total} records</strong>`);
    // Counts for the other statuses with this year range, as the API gives them.
    for (const [s, n] of Object.entries(first.body.facets.status)) expect(t).toContain(`data-count="status:${s}"> ${n}</span>`);
    const next = nextHref(t)!;
    const params = new URL(next, "https://x.invalid").searchParams;
    expect([...params.keys()]).toEqual(["status", "year_from", "sort", "cursor", "page"]);
    // Following the link gives the API's second page.
    const second = await html(next);
    expect(sources(second.text)).toEqual((await api(`${qs}&cursor=${params.get("cursor")}`)).body.rows.map((r: { source: string }) => r.source));
    expect(second.text).toContain("Page 2 of");
  });

  it("round-trips every filter through its controls and its links", async () => {
    const qs = "q=holdings&status=approved&status=refused&province=ON&province=BC&stream=Low+Wage&noc=851&wage_min=15.5&wage_max=40" +
      "&date=last_quarter&year_from=2016&year_to=2025&indicator=high_volume&sort=positions";
    const url = new URL(`https://x.invalid/search?${qs}`);
    const { query, ignored } = readSearchUrl(url);
    expect(ignored).toEqual([]);
    // The parameters the page writes read back as the same query.
    expect(readSearchUrl(new URL(`https://x.invalid/search?${searchParamsOf(query)}`)).query).toEqual(query);
    const t = (await html(`/search?${qs}`)).text;
    expect(t).toContain('id="q" name="q" type="search" value="holdings"');
    for (const s of ["approved", "refused"]) expect(t).toMatch(new RegExp(`name="status" value="${s}" checked=""`));
    expect(t).not.toMatch(/name="status" value="pending" checked/);
    for (const p of ["ON", "BC"]) expect(t).toMatch(new RegExp(`name="province" value="${p}" checked=""`));
    expect(t).toMatch(/name="stream" value="Low Wage" checked=""/);
    expect(t).toContain('name="noc" type="text" value="851"');
    expect(t).toContain('name="wage_min" type="number" step="0.01" min="0" value="15.5"');
    expect(t).toContain('name="wage_max" type="number" step="0.01" min="0" value="40"');
    expect(t).toMatch(/name="date" value="last_quarter" checked=""/);
    expect(t).toContain('<option value="2016" selected="">2016</option>');
    expect(t).toContain('<option value="2025" selected="">2025</option>');
    expect(t).toMatch(/name="indicator" value="high_volume" checked=""/);
    expect(t).toContain('<option value="positions" selected="">Positions</option>');
    // A wage filter means postings, and no posting matches the rest.
    expect(t).toContain("<strong>0 records</strong>");
    expect(t).toContain('<td colspan="9" class="muted">No records match these filters.</td>');
    expect(nextHref(t)).toBeNull();
    // A text filter has no counts file entry, so the counts stay blank.
    expect(t).toContain('data-count="status:approved"> </span>');
  });

  it("clears what the API drops instead of failing", async () => {
    const t = (await html("/search?status=lapsed&date=since_2023q4&wage_min=abc&year_from=1999&q=%2A%2A&sort=rid")).text;
    expect(attr(t, "data-mode")).toBe("db");
    expect(t).not.toContain('value="lapsed"');
    expect(t).not.toContain("since_2023q4");
    expect(t).toMatch(/name="date" value="any" checked=""/);
    expect(t).toContain('id="q" name="q" type="search" value=""');
    expect(t).toContain('name="wage_min" type="number" step="0.01" min="0" value=""');
    expect(t).not.toMatch(/<option value="\d{4}" selected/);
    expect(t).toContain('<option value="newest" selected="">');
    expect(t).toContain(`<strong>${SEEDS.length} records</strong>`);
  });

  it("starts a cursor it did not issue from the first page, and a cursor without a page number shows no range", async () => {
    const forged = (await html("/search?cursor=not-a-cursor&page=4")).text;
    expect(attr(forged, "data-mode")).toBe("db");
    expect(forged).toContain("Page 1 of 3");
    expect(attr(forged, "data-cursor")).toBe("");
    const cursor = attr((await html("/search")).text, "data-next")!;
    const bare = (await html(`/search?cursor=${cursor}`)).text;
    expect(sources(bare)).toHaveLength(50);
    expect(bare).toContain('<span class="mono" id="page-label"></span>');
    expect(bare).toContain('<span class="muted" id="page-range"></span>');
    expect(attr(bare, "data-page")).toBe("");
    expect(attr(bare, "data-cursor")).toBe(cursor);
    expect(nextHref(bare)).toMatch(/^\/search\?cursor=[A-Za-z0-9_-]+$/);
  });

  it("folds the filters for a phone, open and counted when the URL sets filters", async () => {
    const toggle = (page: string) => /<input type="checkbox" id="filters-open" class="filters-toggle"[^>]*>/.exec(page)?.[0] ?? "";
    const summary = (page: string) => /<label for="filters-open" class="filters-summary">([^<]*)<\/label>/.exec(page)?.[1];
    // The text search and the sort are not filters: the fold stays closed.
    const plain = (await html("/search?q=tim&sort=name")).text;
    expect(toggle(plain)).toBe('<input type="checkbox" id="filters-open" class="filters-toggle"/>');
    expect(summary(plain)).toBe("Filters");
    // The checkbox comes first, its label next and every filter after them,
    // the order the CSS sibling selectors need.
    expect(plain).toMatch(/class="filters-toggle"\/><label for="filters-open" class="filters-summary">Filters<\/label><div class="filters-body"><fieldset>/);
    expect(plain).toMatch(/<p class="filter-actions">[\s\S]*?<\/p><\/div><\/aside>/);
    const one = (await html("/search?province=AB")).text;
    expect(toggle(one)).toBe('<input type="checkbox" id="filters-open" class="filters-toggle" checked=""/>');
    expect(summary(one)).toBe("Filters (1 active)");
    // Groups, not values: two provinces count once, and a wage needs one bound.
    const three = (await html("/search?province=AB&province=ON&wage_min=15&year_to=2025&sort=positions&q=holdings")).text;
    expect(summary(three)).toBe("Filters (3 active)");
    // A value the API drops is no filter.
    expect(summary((await html("/search?status=lapsed&wage_min=abc")).text)).toBe("Filters");
    const fr = nbsp((await html("/search?province=AB&status=approved", withCounts(), { cookie: "lang=fr" })).text);
    expect(summary(fr)).toBe("Filtres (2 actifs)");
    expect(summary(nbsp((await html("/search?indicator=high_volume", withCounts(), { cookie: "lang=fr" })).text))).toBe("Filtres (1 actif)");
  });

  it("says no record matches when a filter matches nothing", async () => {
    const t = (await html("/search?q=zzqqxx")).text;
    expect(attr(t, "data-mode")).toBe("db");
    expect(t).toContain("<strong>0 records</strong>");
    expect(t).toContain("No records match these filters.");
  });

  it("renders in French", async () => {
    const t = nbsp((await html("/search", withCounts(), { cookie: "lang=fr" })).text);
    expect(t).toContain('<html lang="fr">');
    expect(t).toContain("<th>Statut</th><th>Employeur</th><th>Profession</th><th>Lieu</th><th>Salaire</th><th>Date</th>" +
      "<th>Postes</th><th>Indicateurs</th><th>Source</th>");
    expect(t).toContain('<td data-label="Profession">Food counter attendant/<wbr/>server</td>');
    expect(t).toContain('<span class="chip" title="Volet des postes à bas salaire dans une région à chômage élevé">Bas salaire, chômage élevé</span>');
    expect(t).toContain('rel="nofollow noopener" title="Guichet-Emplois 9001">Guichet-Emplois</a>');
    expect(t).toMatch(/rel="nofollow noopener" title="EDSC (positive|négative) \d{4}Q\d">EDSC<\/a>/);
    expect(t).toContain("<strong>126 dossiers</strong>");
    expect(t).toContain("offres du Guichet-Emplois et listes d’EDSC depuis 2014");
    expect(t).toContain("Affichage de 1 à 50 sur 126");
    expect(t).toContain("Page 1 sur 3");
    expect(t).toContain('id="page-next">Suivante</a>');
    expect(t).toContain("Toutes les dates depuis 2014");
    expect(t).toContain("Offres des 92 derniers jours et listes du T1 2026");
    expect(t).toContain("Année de la liste ou de l’offre");
    expect(t).toContain('<option value="">Toutes</option>');
    expect(t).not.toContain('id="search-unavailable"');
  });

  it("falls back when the table is empty, as when the database is missing", async () => {
    // A database that answers but holds no row: every page statement comes
    // back empty and the one-row check finds nothing.
    const empty = {
      prepare: () => ({ bind: () => ({}), first: async () => null }),
      batch: async (stmts: unknown[]) => stmts.map(() => ({ results: [], meta: { rows_read: 0 } })),
    } as unknown as D1Database;
    for (const SEARCH of [empty, undefined]) {
      const page = await html("/search", { ...withCounts(), SEARCH });
      expect(attr(page.text, "data-mode")).toBe("static");
      expect(page.headers.get("cache-control")).toBe("no-store");
      expect(page.text).toContain('id="search-unavailable" role="status">Search is unavailable for the moment, so the newest records are shown.</p>');
      // The fallback is the page as it was: search/first.json's rows, counted from search/facets.json.
      expect(page.text).toContain("<strong>5 records</strong>");
      expect(page.text).toContain("PinkCloud Cleaning &amp; Home Services");
      expect(page.text).toContain('data-count="status:pending"> 2');
      expect(page.text).toContain("Page 1 of 1");
    }
  });
});

describe("the page-only rule", () => {
  it("still answers the page's own fetch and nothing else", async () => {
    expect((await api("q=holdings")).status).toBe(200);
    for (const headers of [{ "sec-fetch-site": "cross-site" }, { "sec-fetch-site": "none" }, {}] as Record<string, string>[]) {
      const res = await app.request("/api/search?q=holdings", { headers: { "cf-connecting-ip": ip(), ...headers } }, withCounts());
      expect(res.status).toBe(403);
    }
  });
});

describe("a capped total", () => {
  const BULK = 10_050;
  beforeAll(async () => {
    await env.SEARCH.prepare(
      `WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < ${BULK}) ` +
      `INSERT INTO search_rows (${COLUMNS.join(", ")}) SELECT 2 * (100000 + i), 'e:' || (100000 + i), 'esdc', 100000 + i, ` +
      "'emp-b000000001', 'Bulkfill Packers', 'Packers', '94141', NULL, 'Bulkton', 'PE', NULL, NULL, NULL, NULL, NULL, '2016Q4', 1, " +
      "'approved', NULL, 'https://open.canada.ca/x/bulk', '2016-12-31', 2016, '', 'bulkfill packers', 'h' FROM n",
    ).run();
  });
  afterAll(async () => {
    await env.SEARCH.prepare("DELETE FROM search_rows WHERE employer_id = 'emp-b000000001'").run();
  });

  it("is shown as 10,000 or more, with no last page", async () => {
    const t = (await html("/search?q=bulkfill")).text;
    expect(t).toContain("<strong>10,000 or more records</strong>");
    expect(t).toContain("Showing 1 to 50 of 10,000 or more");
    expect(t).toContain('<span class="mono" id="page-label">Page 1</span>');
    expect(attr(t, "data-capped")).toBe("1");
    expect(nextHref(t)).toMatch(/^\/search\?q=bulkfill&cursor=[A-Za-z0-9_-]+&page=2$/);
    const fr = nbsp((await html("/search?q=bulkfill", withCounts(), { cookie: "lang=fr" })).text);
    expect(fr).toContain("<strong>10 000 dossiers ou plus</strong>");
    expect(fr).toContain("Affichage de 1 à 50 sur 10 000 ou plus");
  });
});
