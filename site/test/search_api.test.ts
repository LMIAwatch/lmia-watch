import { env } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { SearchCounts } from "../src/data";
import { app } from "../src/index";
import {
  LATEST_PERIOD_SQL, buildCount, buildProbes, buildSelect, choosePlan, countDriver, countsFor, decodeCursor, encodeCursor, ftsQuery,
  lastQuarterFrom, parseQuery, runSearch, type Plan, type SearchQuery, type SearchTrace,
} from "../src/search_db";
import { fakeAssets, testEnv } from "./assets";

// The search API against a real local D1 database: search_schema.sql applied
// by test/setup.ts (its indexes, its FTS5 index and the triggers that fill
// it), then the rows below inserted the way the nightly sync inserts them.

const DATA_DATE = "2026-10-22";
const NOW = new Date("2026-10-22T12:00:00Z");
// The newest list period in the seed below, which date=last_quarter keeps.
const LATEST_PERIOD = "2026Q1";

interface Seed {
  kind: "esdc" | "posting";
  ref: number;
  employer_id: string;
  employer: string;
  job: string | null;
  noc: string | null;
  street: string | null;
  city: string | null;
  prov: string | null;
  postal: string | null;
  wage_min: number | null;
  wage_max: number | null;
  unit: string | null;
  date: string | null;
  period: string | null;
  positions: number | null;
  status: string;
  stream: string | null;
  source: string;
  sort_date: string;
  year: number;
  ind: string;
}

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function periodEnd(period: string): string {
  const year = period.slice(0, 4);
  const m = /Q(\d)$/.exec(period);
  const q = m ? Number(m[1]) : 4;
  return `${year}-${["03-31", "06-30", "09-30", "12-31"][q - 1]}`;
}

function esdc(ref: number, employer: string, job: string, noc: string, city: string | null, prov: string | null, period: string,
  positions: number | null, status: string, stream: string | null, ind = ""): Seed {
  return {
    kind: "esdc", ref, employer_id: `emp-e${String(ref).padStart(9, "0")}`, employer, job, noc, street: null, city, prov,
    postal: null, wage_min: null, wage_max: null, unit: null, date: null, period, positions, status, stream,
    source: `https://open.canada.ca/data/en/dataset/x/resource/r${ref}`, sort_date: periodEnd(period),
    year: Number(period.slice(0, 4)), ind,
  };
}

function posting(ref: number, employer: string, job: string, noc: string, city: string, prov: string | null, wage: [number, number],
  date: string, positions: number | null, status: string, ind = ""): Seed {
  return {
    kind: "posting", ref, employer_id: `emp-p${String(ref).padStart(9, "0")}`, employer, job, noc, street: "1 Main St", city, prov,
    postal: null, wage_min: wage[0], wage_max: wage[1], unit: "HOUR", date, period: null, positions, status, stream: null,
    source: `https://www.jobbank.gc.ca/jobsearch/jobposting/${ref}`, sort_date: date, year: Number(date.slice(0, 4)), ind,
  };
}

const NAMED: Seed[] = [
  esdc(1, "Ferme Éloïse Québec Inc.", "Harvesting labourers", "85101", "Montréal", "QC", "2026Q1", 12, "approved", "Primary Agriculture", "repeat_applicant"),
  esdc(2, "O'Brien Farms Ltd", "Harvesting labourers", "8611", "Kelowna", "BC", "2015", 2, "refused", null, "high_volume,repeat_applicant"),
  esdc(3, "O'Brien Farms Ltd", "Cooks", "6322", "Kelowna", "BC", "2017Q1-Q2", 1, "approved", "High Wage", "high_volume,repeat_applicant"),
  esdc(4, "Global Talent Co", "Software engineers", "21231", "Toronto", "ON", "2024Q2", 3, "approved", "Global Talent"),
  esdc(5, "Société Talent Mondial", "Developers", "21232", "Québec", "QC", "2023Q1", 4, "approved", "Talent mondial"),
  esdc(6, "Nunavut Builders", "Carpenters", "72310", "Iqaluit", "NU", "2019Q3", 2, "approved", "Low Wage"),
  esdc(7, "Head Office Abroad", "Managers", "00012", null, "XX", "2020Q4", 1, "approved", "High Wage"),
  esdc(8, "No Province Ltd", "Cooks", "63200", null, null, "2026Q1", 1, "refused", "Low Wage"),
  esdc(9, "Permanent Resident Co", "Engineers", "21300", "Calgary", "AB", "2022Q2", 5, "approved", "Permanent Resident Only"),
  esdc(10, "Repost Farms", "Labourers", "85100", "Abbotsford", "BC", "2025Q3", null, "refused", "Primary Agriculture", "refused_then_reposted"),
  esdc(11, "Montreal Bakery", "Bakers", "63202", "Montréal", "QC", "2014", 1, "approved", null),
  posting(9001, "Tim Hortons #1234 (Horton Holdings Ltd)", "Food counter attendant", "65201", "Toronto", "ON", [16.55, 17], "2026-10-20", null, "pending"),
  posting(9002, "Timbers Lodge", "Cook", "63200", "Banff", "AB", [18, 20], "2026-09-01", 2, "approved"),
  posting(9003, "Junk Province Ltd", "Cleaner", "65310", "Halifax", ", ON", [15.5, 15.5], "2026-06-01", 1, "pending"),
  posting(9004, "Repost Farms", "Farm labourer", "85100", "Abbotsford", "BC", [17.4, 17.4], "2026-10-18", null, "pending", "refused_then_reposted"),
  posting(9005, "O'Brien Farms Ltd", "Farm supervisor", "82030", "Kelowna", "BC", [22, 25], "2026-10-12", 1, "approved", "high_volume,repeat_applicant"),
];

// Filler for paging: few distinct sort dates (ties of a quarter's size),
// positions mostly 1 or null (ties and the null boundary), names repeated
// four times (ties on the name sort).
const FILLER_NAMES = ["Acme", "Birch", "Cedar", "Delta", "Elm", "Fir", "Grove", "Harbour", "Iris", "Juniper", "Kestrel", "Larch",
  "Maple", "Nettle", "Oak", "Pine", "Quill", "Rowan", "Spruce", "Tamarack", "Umber", "Vale", "Willow", "Yarrow", "Zinnia",
  "Aspen", "Bramble", "Clover", "Dogwood", "Ember", "Fern", "Gorse", "Hazel", "Ivy", "Jasmine", "Kelp", "Lupin", "Moss"];
const FILLER_PERIODS = ["2024Q1", "2024Q1", "2024Q1", "2014", "2016", "2018Q2", "2021Q4", "2024Q1", "2025Q1", "2026Q1"];
const FILLER_PROVS = ["ON", "BC", "QC", "AB", "MB", "SK", "NS", "NB", "PE", "NL", "YT", "NT", "NU", "ON", "BC"];
const FILLER_STREAMS = ["Low Wage", "High Wage", "Primary Agriculture", null, "Global Talent Stream", "Low Wage"];
const FILLER: Seed[] = Array.from({ length: 150 }, (_, i) =>
  esdc(100 + i, `${FILLER_NAMES[i % FILLER_NAMES.length]} Holdings`, i % 7 === 0 ? "Line cooks" : "Labourers",
    i % 7 === 0 ? "63200" : "85100", "Town", FILLER_PROVS[i % FILLER_PROVS.length], FILLER_PERIODS[i % FILLER_PERIODS.length],
    i % 2 === 0 ? null : i % 5 === 0 ? 3 : 1, i % 4 === 3 ? "refused" : "approved", FILLER_STREAMS[i % FILLER_STREAMS.length],
    i % 11 === 0 ? "high_volume" : ""));

const SEEDS: Seed[] = [...NAMED, ...FILLER];

const COLUMNS = ["rid", "key", "kind", "ref", "employer_id", "employer", "job", "noc", "street", "city", "prov", "postal", "wage_min",
  "wage_max", "unit", "date", "period", "positions", "status", "stream", "source", "sort_date", "year", "ind", "name_fold", "hash"] as const;

const ridOf = (s: Seed) => (s.kind === "posting" ? s.ref * 2 + 1 : s.ref * 2);
const keyOf = (s: Seed) => `${s.kind === "posting" ? "p" : "e"}:${s.ref}`;

function values(s: Seed): (string | number | null)[] {
  const full: Record<string, string | number | null> = {
    ...s, rid: ridOf(s), key: keyOf(s), name_fold: fold(s.employer), hash: `h${ridOf(s)}`,
  };
  return COLUMNS.map((c) => full[c]);
}

async function insert(rows: Seed[]): Promise<void> {
  // Three rows a statement: 26 values each, and D1 binds at most 100.
  const stmts: D1PreparedStatement[] = [];
  for (let i = 0; i < rows.length; i += 3) {
    const chunk = rows.slice(i, i + 3);
    const sql = `INSERT INTO search_rows (${COLUMNS.join(", ")}) VALUES ` +
      chunk.map(() => `(${COLUMNS.map(() => "?").join(", ")})`).join(", ");
    stmts.push(env.SEARCH.prepare(sql).bind(...chunk.flatMap(values)));
  }
  for (let i = 0; i < stmts.length; i += 50) await env.SEARCH.batch(stmts.slice(i, i + 50));
}

// counts.json as export_static.write_search_counts writes it, from the seed.
function countsOf(rows: Seed[], dataAsOf: string | null = DATA_DATE, latestPeriod: string | null = LATEST_PERIOD): SearchCounts {
  const dims = ["status", "prov", "stream", "year", "ind"] as const;
  const lists: Record<string, (string | number | null)[]> = { status: [], prov: [], stream: [], year: [], ind: [] };
  const cells = new Map<string, number[]>();
  for (const r of rows) {
    const idx = dims.map((d) => {
      const v = r[d] as string | number | null;
      let i = lists[d].indexOf(v);
      if (i < 0) i = lists[d].push(v) - 1;
      return i;
    });
    const k = idx.join(",");
    const cell = cells.get(k) ?? [...idx, 0];
    cell[5] += 1;
    cells.set(k, cell);
  }
  return {
    data_as_of: dataAsOf, latest_period: latestPeriod, total: rows.length, dims: [...dims], cells: [...cells.values()],
    values: lists as unknown as SearchCounts["values"],
  };
}

function assetsWith(files: Record<string, unknown>): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path in files) return new Response(JSON.stringify(files[path]), { headers: { "content-type": "application/json" } });
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher;
}

const COUNTS = countsOf(SEEDS);
const withCounts = () => testEnv(assetsWith({ "search/counts.json": COUNTS }));
const withoutCounts = () => testEnv(fakeAssets);

let address = 1;
// As the search page's own fetch arrives: a browser marks it same-origin.
const FROM_PAGE = { "sec-fetch-site": "same-origin" };
async function api(query: string, environment = withCounts(), headers: Record<string, string> = FROM_PAGE) {
  // A fresh address each time, so the per-address API cap never trips.
  const res = await app.request(`/api/search${query ? `?${query}` : ""}`,
    { headers: { "cf-connecting-ip": `192.0.2.${address++ % 250}`, ...headers } }, environment);
  const text = await res.text();
  let body: any = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = { unparsed: text };
  }
  return { status: res.status, body, headers: res.headers };
}

function query(qs: string): SearchQuery {
  const parsed = parseQuery(new URL(`https://x.invalid/api/search?${qs}`), NOW);
  if (!parsed.ok) throw new Error(parsed.problems.join("; "));
  return parsed.query;
}

// -- the reference: the same filters and orders, in plain JavaScript -------

const SPELLINGS: Record<string, string[]> = {
  "High Wage": ["High Wage"], "Low Wage": ["Low Wage"], "Primary Agriculture": ["Primary Agriculture"],
  "Global Talent Stream": ["Global Talent Stream", "Global Talent", "Talent mondial"],
  "Permanent Resident Only": ["Permanent Resident Only"],
};

function shift(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function passes(r: Seed, q: SearchQuery, skip: "status" | "prov" | null = null): boolean {
  if (skip !== "status" && q.status.length && q.status.length < 3 && !q.status.includes(r.status as any)) return false;
  if (skip !== "prov" && q.province.length && !q.province.includes(r.prov ?? "UN")) return false;
  if (q.stream.length && !q.stream.some((s) => SPELLINGS[s].includes(r.stream ?? ""))) return false;
  if (q.nocCode && !(r.noc ?? "").startsWith(q.nocCode)) return false;
  if (q.wageMin !== null && !(r.wage_min !== null && r.wage_min >= q.wageMin)) return false;
  if (q.wageMax !== null && !(r.wage_max !== null && r.wage_max <= q.wageMax)) return false;
  if (q.date === "7d" && !(r.kind === "posting" && r.date !== null && r.date >= shift(DATA_DATE, -7))) return false;
  if (q.date === "last_quarter" &&
    !(r.kind === "posting" ? r.date !== null && r.date >= shift(DATA_DATE, -92) : r.period === LATEST_PERIOD)) return false;
  if (q.yearFrom !== null && r.year < q.yearFrom) return false;
  if (q.yearTo !== null && r.year > q.yearTo) return false;
  if (q.indicator && !r.ind.split(",").includes(q.indicator)) return false;
  return true;
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
function ordered(rows: Seed[], sort: string): Seed[] {
  const out = [...rows];
  if (sort === "name") out.sort((a, b) => cmp(fold(a.employer), fold(b.employer)) || cmp(keyOf(a), keyOf(b)));
  else if (sort === "positions") {
    out.sort((a, b) => {
      if (a.positions !== b.positions) {
        if (a.positions === null) return 1;
        if (b.positions === null) return -1;
        return b.positions - a.positions;
      }
      return cmp(b.sort_date, a.sort_date) || cmp(keyOf(b), keyOf(a));
    });
  } else out.sort((a, b) => cmp(b.sort_date, a.sort_date) || cmp(keyOf(b), keyOf(a)));
  return out;
}

const expected = (q: SearchQuery) => ordered(SEEDS.filter((r) => passes(r, q)), q.sort).map(keyOf);
const keyOfRow = (r: { kind: string; ref: number }) => `${r.kind === "posting" ? "p" : "e"}:${r.ref}`;

// Every page of a query through runSearch, with a plan forced or chosen.
async function walk(q: SearchQuery, plan?: Plan, counts: SearchCounts | null = null): Promise<{ keys: string[]; pages: number; reads: number[]; pageReads: number[] }> {
  const keys: string[] = [];
  const reads: number[] = [];
  const pageReads: number[] = [];
  let cursor: string | undefined;
  let pages = 0;
  do {
    const trace: SearchTrace = { statements: 0, rowsRead: 0, sql: [], reads: [] };
    const page = await runSearch(env, { ...q, cursor: cursor ? decodeCursor(cursor) : null }, DATA_DATE, counts, { plan, trace });
    expect(page, "the search answered").not.toBeNull();
    keys.push(...page!.rows.map(keyOfRow));
    reads.push(trace.rowsRead);
    // The page statement alone, without the probes and the count.
    pageReads.push(trace.reads!.filter((_, i) => trace.sql[i].startsWith("SELECT kind,")).reduce((a, b) => a + b, 0));
    cursor = page!.next;
    pages += 1;
    expect(pages).toBeLessThan(20);
  } while (cursor);
  return { keys, pages, reads, pageReads };
}

async function canary(): Promise<{ n: number; names: string; fts: number; schema: string }> {
  const n = await env.SEARCH.prepare("SELECT COUNT(*) AS n FROM search_rows").first<number>("n");
  const names = await env.SEARCH.prepare("SELECT group_concat(employer, '|') AS s FROM (SELECT employer FROM search_rows ORDER BY rid)").first<string>("s");
  const fts = await env.SEARCH.prepare("SELECT COUNT(*) AS n FROM search_fts WHERE search_fts MATCH '\"holdings\"'").first<number>("n");
  const schema = await env.SEARCH.prepare("SELECT group_concat(type || ':' || name, ',') AS s FROM (SELECT type, name FROM sqlite_master ORDER BY name)").first<string>("s");
  return { n: n ?? -1, names: names ?? "", fts: fts ?? -1, schema: schema ?? "" };
}

beforeAll(async () => {
  await env.SEARCH.prepare("DELETE FROM search_rows").run();
  await insert(SEEDS);
});

// -- parsing ---------------------------------------------------------------

describe("parsing", () => {
  it("keeps allowlisted values within their bounds and names what it dropped", () => {
    const p = parseQuery(new URL("https://x.invalid/api/search?q=%20tim%20&status=pending&status=bogus&province=bc&province=QC" +
      "&province=UN&stream=Global%20Talent&noc=632&wage_min=15.5&wage_max=20000&year_from=2013&year_to=2027&date=7d" +
      "&indicator=high_volume&sort=name&page=3"), NOW);
    expect(p.ok).toBe(true);
    if (!p.ok) return;
    expect(p.query).toMatchObject({
      q: "tim", status: ["pending"], province: ["QC", "UN"], stream: ["Global Talent Stream"], nocCode: "632", nocText: "",
      wageMin: 15.5, wageMax: null, yearFrom: null, yearTo: 2027, date: "7d", indicator: "high_volume", sort: "name", cursor: null,
    });
    expect(p.ignored.sort()).toEqual(["province", "status", "wage_max", "year_from"]);
  });

  it("cuts repeated and long parameters instead of refusing them", () => {
    const qs = new URLSearchParams();
    for (let i = 0; i < 200; i++) qs.append("status", "approved");
    for (let i = 0; i < 40; i++) qs.append("province", "ON");
    qs.set("q", ` ${"a".repeat(5000)} `);
    const p = parseQuery(new URL(`https://x.invalid/api/search?${qs}`), NOW);
    expect(p.ok).toBe(true);
    if (!p.ok) return;
    expect(p.query.status).toEqual(["approved"]);
    expect(p.query.province).toEqual(["ON"]);
    expect(p.query.q.length).toBe(200);
    expect(p.ignored.sort()).toEqual(["province", "status"]);
  });

  it("reads a NOC as a code prefix or as title words", () => {
    expect(query("noc=63").nocCode).toBe("63");
    expect(query("noc=632001").nocCode).toBeNull();
    expect(query("noc=632001").nocText).toBe("632001");
    expect(query("noc=line%20cook").nocText).toBe("line cook");
    expect(query("noc=%2A%2A").nocText).toBe("");
  });

  it("refuses only a cursor it did not issue", () => {
    const good = encodeCursor({ sort: "newest", key: "e:5", date: "2024-03-31" });
    expect(parseQuery(new URL(`https://x.invalid/api/search?cursor=${good}`), NOW).ok).toBe(true);
    expect(parseQuery(new URL(`https://x.invalid/api/search?sort=name&cursor=${good}`), NOW).ok).toBe(false);
    const forged = (o: unknown) => btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    for (const bad of [
      "not base64!", "%%%", "AAAA====", forged([1, 2]), forged("newest"), forged({ o: "newest", k: 5, d: "2024-03-31" }),
      forged({ o: "newest", k: "e:5", d: "2024-03-31", x: 1 }), forged({ o: "newest", k: "e:5' OR 1=1 --", d: "2024-03-31" }),
      forged({ o: "newest", k: "e:5", d: "2024-03-31'); DROP TABLE search_rows; --" }), forged({ o: "rid", k: "e:5", d: "2024-03-31" }),
      forged({ o: "positions", k: "e:5", d: "2024-03-31", p: "1" }), forged({ o: "positions", k: "e:5", d: "2024-03-31", p: -1 }),
      forged({ o: "positions", k: "e:5", d: "2024-03-31", p: 1.5 }), forged({ o: "name", k: "e:5", n: 7 }),
      forged({ o: "name", k: "e:5", n: "x".repeat(2001) }), "x".repeat(9000),
    ]) {
      expect(decodeCursor(bad), bad.slice(0, 60)).toBeNull();
    }
    expect(decodeCursor(encodeCursor({ sort: "name", key: "p:9", name: "société ø l'été" }))).toEqual({ sort: "name", key: "p:9", name: "société ø l'été" });
    expect(decodeCursor(encodeCursor({ sort: "positions", key: "e:1", date: "2026-03-31", positions: null })))
      .toEqual({ sort: "positions", key: "e:1", date: "2026-03-31", positions: null });
  });
});

describe("ftsQuery", () => {
  it("quotes every token as a phrase with a prefix star", () => {
    expect(ftsQuery("Tim Horton")).toBe('"tim"* "horton"*');
    expect(ftsQuery("  Québec   MONTRÉAL ")).toBe('"quebec"* "montreal"*');
    expect(ftsQuery("O’Brien")).toBe(`"o'brien"*`);
    expect(ftsQuery("cook", "job")).toBe('job : "cook"*');
  });

  it("leaves no FTS5 operator or quote alive", () => {
    expect(ftsQuery('employer:tim')).toBe('"employertim"*');
    expect(ftsQuery("NOT ltd")).toBe('"not"* "ltd"*');
    expect(ftsQuery("a OR b")).toBe('"a" "or"* "b"');
    expect(ftsQuery("(x")).toBe('"x"');
    expect(ftsQuery("*")).toBe("");
    expect(ftsQuery("^tim")).toBe('"tim"*');
    expect(ftsQuery("tim*")).toBe('"tim"*');
    expect(ftsQuery('"')).toBe("");
    expect(ftsQuery('x" OR "a"="a')).toBe('"x" "or"* "aa"*');
    expect(ftsQuery("NEAR(tim horton) -x {employer}:y")).toBe('"neartim"* "horton"* "x" "employery"*');
    expect(ftsQuery("one two three four five six seven eight nine ten")).toBe(
      '"one"* "two"* "three"* "four"* "five"* "six"* "seven"* "eight"*');
    for (const payload of ["' OR 1=1 --", '"; DROP TABLE search_rows; --', "x".repeat(5000), "\u0000\u0001", "😀 ⁂"]) {
      const out = ftsQuery(payload);
      // Only quoted phrases remain: no quote inside one, nothing between them.
      expect(out === "" || /^"[^"]+"\*?( "[^"]+"\*?)*$/.test(out), payload.slice(0, 40)).toBe(true);
    }
  });
});

// -- answers -----------------------------------------------------------------

describe("filters and sorts", () => {
  const cases = [
    "", "status=pending", "status=approved&status=refused", "province=BC", "province=UN", "province=NU&province=XX&province=UN",
    "stream=Global%20Talent%20Stream", "stream=Low%20Wage&stream=Permanent%20Resident%20Only", "noc=632", "noc=8",
    "wage_min=17", "wage_max=17", "wage_min=16&wage_max=21", "date=7d", "date=last_quarter", "year_from=2024", "year_to=2016",
    "year_from=2017&year_to=2019", "indicator=refused_then_reposted", "indicator=high_volume&province=BC",
    "status=approved&province=QC&year_from=2020", "status=refused&stream=Low%20Wage&indicator=high_volume",
  ];
  for (const sort of ["newest", "positions", "name"]) {
    it(`answers every filter, sorted by ${sort}`, async () => {
      for (const c of cases) {
        const qs = `${c}${c ? "&" : ""}sort=${sort}`;
        const q = query(qs);
        for (const environment of [withCounts(), withoutCounts()]) {
          const { status, body } = await api(qs, environment);
          expect(status, qs).toBe(200);
          const want = expected(q);
          expect(body.rows.map(keyOfRow), qs).toEqual(want.slice(0, 50));
          expect(body.total, qs).toBe(want.length);
          expect(body.capped).toBe(false);
          expect(body.next === undefined, qs).toBe(want.length <= 50);
        }
      }
    });
  }

  it("returns rows shaped exactly like SearchRow", async () => {
    const { body } = await api("q=tim%20hortons");
    expect(body.rows).toHaveLength(1);
    expect(body.rows[0]).toEqual({
      kind: "posting", ref: 9001, employer_id: "emp-p000009001", employer: "Tim Hortons #1234 (Horton Holdings Ltd)",
      job: "Food counter attendant", noc: "65201", street: "1 Main St", city: "Toronto", prov: "ON", postal: null, wage_min: 16.55,
      wage_max: 17, unit: "HOUR", date: "2026-10-20", period: null, positions: null, status: "pending", stream: null,
      source: "https://www.jobbank.gc.ca/jobsearch/jobposting/9001", sort_date: "2026-10-20", ind: [],
    });
    const two = await api("q=obrien&sort=newest");
    expect(two.body.rows).toEqual([]);
    const ob = await api("q=o'brien");
    expect(ob.body.rows[0].ind).toEqual(["high_volume", "repeat_applicant"]);
  });
});

describe("the last-quarter window", () => {
  const keysOf = (body: any) => body.rows.map(keyOfRow);

  it("keeps postings of the last 92 days and the list rows of the latest period only", async () => {
    const { body } = await api("date=last_quarter&sort=name");
    const rows = body.rows as { kind: string; date: string | null; period: string | null }[];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.filter((r) => r.kind === "esdc").every((r) => r.period === LATEST_PERIOD)).toBe(true);
    expect(rows.filter((r) => r.kind === "posting").every((r) => (r.date ?? "") >= "2026-07-22")).toBe(true);
    // A list row of an older period, and a posting from before the window, stay out.
    expect(keysOf(body)).not.toContain("e:2");
    expect(keysOf(body)).not.toContain("p:9003");
    expect(keysOf(body)).toContain("e:1");
    expect(keysOf(body)).toContain("p:9001");
    // Not answered from counts.json alone: the counts know no posting date.
    expect(body.facets).toBeUndefined();
    expect(body.total).toBe(expected(query("date=last_quarter")).length);
  });

  it("binds the period as a value", () => {
    const built = buildSelect(query("date=last_quarter"), { dataDate: DATA_DATE, latestPeriod: LATEST_PERIOD });
    expect(built.params).toContain(LATEST_PERIOD);
    expect(built.params).toContain("2026-07-22");
    expect(built.sql).not.toContain(LATEST_PERIOD);
    expect(built.sql).toContain("((+kind = 'posting' AND +date >= ?) OR (+kind <> 'posting' AND +period = ?))");
  });

  it("finds the period in the table when counts.json is missing or damaged", async () => {
    const q = query("date=last_quarter");
    const trace: SearchTrace = { statements: 0, rowsRead: 0, sql: [] };
    const res = await runSearch(env, q, DATA_DATE, null, { trace });
    expect(trace.sql[0]).toBe(LATEST_PERIOD_SQL);
    expect(res!.rows.map(keyOfRow)).toEqual(expected(q).slice(0, 50));
    for (const latest_period of ["2026Q5", "2026-Q1", 7, "'; DROP TABLE search_rows; --", ""]) {
      const damaged = testEnv(assetsWith({ "search/counts.json": { ...COUNTS, latest_period } }));
      const { status, body } = await api("date=last_quarter", damaged);
      expect(status, String(latest_period)).toBe(200);
      expect(keysOf(body), String(latest_period)).toEqual(expected(q).slice(0, 50));
      // The whole file reads as missing: a plain request gets no counts from it.
      expect((await api("", damaged)).body.facets, String(latest_period)).toBeUndefined();
    }
  });

  it("counts from the window's earliest sort date through an index, with the same total", async () => {
    // 92 days before 2026-10-22 is 2026-07-22; the 2026Q1 rows sort on 2026-03-31, the earlier of the two.
    expect(lastQuarterFrom(DATA_DATE, LATEST_PERIOD)).toBe("2026-03-31");
    expect(lastQuarterFrom(DATA_DATE, "2026Q3")).toBe("2026-07-22");
    expect(lastQuarterFrom(DATA_DATE, "2017Q1-Q2")).toBe("2017-06-30");
    expect(lastQuarterFrom(DATA_DATE, null)).toBe("2026-07-22");
    for (const qs of ["date=last_quarter", "date=last_quarter&status=approved", "date=last_quarter&province=BC"]) {
      const q = query(qs);
      const driver = qs.includes("status") ? "status" : qs.includes("province") ? "prov" : null;
      const built = buildCount(q, { driver, dataDate: DATA_DATE, latestPeriod: LATEST_PERIOD });
      const plan = await env.SEARCH.prepare(`EXPLAIN QUERY PLAN ${built.sql}`).bind(...built.params).all<{ detail: string }>();
      expect(plan.results.map((r) => r.detail).join(" / "), qs).toMatch(/USING (COVERING )?INDEX search_rows_(newest|status_newest|prov_newest) \(.*sort_date>\?\)/);
      const n = await env.SEARCH.prepare(built.sql).bind(...built.params).first<number>("n");
      expect(n, qs).toBe(expected(q).length);
    }
  });

  it("keeps postings only when no list period is known", async () => {
    const res = await runSearch(env, query("date=last_quarter"), DATA_DATE, countsOf(SEEDS, DATA_DATE, null));
    expect(res!.rows.length).toBeGreaterThan(0);
    expect(res!.rows.every((r) => r.kind === "posting")).toBe(true);
  });
});

describe("text", () => {
  const refs = async (qs: string) => (await api(qs)).body.rows.map((r: any) => r.ref).sort((a: number, b: number) => a - b);

  it("matches word prefixes over the name, the title and the city", async () => {
    expect(await refs("q=tim")).toEqual([9001, 9002]);
    expect(await refs("q=tim%20horton")).toEqual([9001]);
    expect(await refs("q=horton")).toEqual([9001]);
    expect(await refs("q=harvest")).toEqual([1, 2]);
    expect(await refs("q=kelowna%20farm")).toEqual([2, 3, 9005]);
    expect(await refs("q=O%E2%80%99Brien")).toEqual([2, 3, 9005]);
  });

  it("ignores accents both ways", async () => {
    expect(await refs("q=quebec")).toEqual([1, 5]);
    expect(await refs("q=Qu%C3%A9bec")).toEqual([1, 5]);
    expect(await refs("q=montreal")).toEqual([1, 11]);
    expect(await refs("q=MONTR%C3%89AL%20bakery")).toEqual([11]);
    expect(await refs("q=eloise")).toEqual([1]);
    expect(await refs("q=societe")).toEqual([5]);
  });

  it("matches a NOC given as words in the title only", async () => {
    const cooks = await api("noc=cook&sort=name");
    const want = SEEDS.filter((r) => /\bcook/i.test(r.job ?? "")).map(keyOf).sort();
    expect(cooks.body.rows.map(keyOfRow).sort()).toEqual(want);
    expect(cooks.body.total).toBe(want.length);
    // "Timbers" is a name, not a title.
    expect((await api("noc=timbers")).body.total).toBe(0);
  });

  it("counts a text query alone from its probe, and with filters in D1", async () => {
    const alone = await api("q=holdings");
    expect(alone.body.total).toBe(151);
    expect(alone.body.facets).toBeUndefined();
    const filtered = await api("q=holdings&province=BC&status=approved");
    const want = SEEDS.filter((r) => /holdings/i.test(r.employer) && r.prov === "BC" && r.status === "approved");
    expect(filtered.body.total).toBe(want.length);
  });
});

describe("totals", () => {
  it("are exact from counts.json, with facets, and match D1 when counted there", async () => {
    for (const qs of ["", "status=refused", "province=BC&province=UN", "stream=Global%20Talent%20Stream&year_from=2020",
      "indicator=high_volume", "status=approved&province=QC&stream=Low%20Wage&year_to=2024&indicator=repeat_applicant"]) {
      const q = query(qs);
      const fromCounts = await api(qs, withCounts());
      const fromD1 = await api(qs, withoutCounts());
      const want = SEEDS.filter((r) => passes(r, q));
      expect(fromCounts.body.total, qs).toBe(want.length);
      expect(fromD1.body.total, qs).toBe(want.length);
      expect(fromD1.body.facets, qs).toBeUndefined();
      const status: Record<string, number> = {};
      const prov: Record<string, number> = {};
      for (const r of SEEDS) {
        if (passes(r, q, "status")) status[r.status] = (status[r.status] ?? 0) + 1;
        const p = r.prov ?? "UN";
        if (passes(r, q, "prov") && /^[A-Z]{2}$/.test(p)) prov[p] = (prov[p] ?? 0) + 1;
      }
      expect(fromCounts.body.facets, qs).toEqual({ status, prov });
    }
  });

  it("leave a province the source wrote some other way out of the boxes, not out of the total", () => {
    const { total, facets } = countsFor(COUNTS, query(""));
    expect(total).toBe(SEEDS.length);
    expect(Object.values(facets.prov).reduce((a, b) => a + b, 0)).toBe(SEEDS.length - 1);
  });

  it("are left out on a later page that would need a count", async () => {
    const first = await api("wage_min=1&sort=name", withoutCounts());
    expect(first.body.total).toBe(5);
    const many = await api("noc=8", withoutCounts());
    expect(many.body.total).toBe(expected(query("noc=8")).length);
    expect(many.body.next).toBeDefined();
    const second = await api(`noc=8&cursor=${many.body.next}`, withoutCounts());
    expect(second.body.total).toBeNull();
    expect(second.body.rows).toHaveLength(50);
    // counts.json answers every page at no cost, so a later page keeps its total.
    const approved = await api("status=approved", withCounts());
    const next = await api(`status=approved&cursor=${approved.body.next}`, withCounts());
    expect(next.body.total).toBe(approved.body.total);
    expect(next.body.facets).toEqual(approved.body.facets);
  });

  it("refuse a counts file that does not add up, and count in D1 instead", async () => {
    const broken = { ...COUNTS, total: COUNTS.total + 1 };
    const res = await api("status=refused", testEnv(assetsWith({ "search/counts.json": broken })));
    expect(res.status).toBe(200);
    expect(res.body.facets).toBeUndefined();
    expect(res.body.total).toBe(SEEDS.filter((r) => r.status === "refused").length);
    for (const bad of [{ ...COUNTS, dims: ["status"] }, { ...COUNTS, cells: [[0, 0, 0, 0, 0, 0]] }, { ...COUNTS, cells: [[99, 0, 0, 0, 0, 1]] },
      { ...COUNTS, values: { ...COUNTS.values, year: ["2014"] } }, "not an object"]) {
      const r = await api("status=refused", testEnv(assetsWith({ "search/counts.json": bad })));
      expect(r.status).toBe(200);
      expect(r.body.facets).toBeUndefined();
    }
  });
});

describe("keyset paging", () => {
  const all = (sort: string) => ordered(SEEDS, sort).map(keyOf);

  for (const sort of ["newest", "positions", "name"] as const) {
    it(`walks every row exactly once, sorted by ${sort}, in every plan`, async () => {
      const plans: (Plan | undefined)[] = [undefined, { mode: "ordered", driver: null }, { mode: "small", driver: "status" }];
      for (const plan of plans) {
        const { keys, pages } = await walk(query(`sort=${sort}`), plan);
        expect(keys, JSON.stringify(plan)).toEqual(all(sort));
        expect(new Set(keys).size).toBe(SEEDS.length);
        expect(pages).toBe(Math.ceil(SEEDS.length / 50));
      }
      // Filtered walks: one status and one province (the prefix plans when
      // newest), several provinces, a year range, a text query.
      for (const qs of ["status=approved", "province=BC", "province=ON&province=UN&province=NU", "year_from=2018&year_to=2024",
        "q=holdings", "status=refused&province=BC"]) {
        const q = query(`${qs}&sort=${sort}`);
        const want = qs.startsWith("q=")
          ? ordered(SEEDS.filter((r) => /holdings/i.test(r.employer)), sort).map(keyOf)
          : expected(q);
        for (const counts of [null, COUNTS]) {
          const { keys } = await walk(q, undefined, counts);
          expect(keys, `${qs} ${counts ? "with" : "without"} counts`).toEqual(want);
        }
        for (const plan of [{ mode: "ordered", driver: null }, { mode: "small", driver: "prov" }] as Plan[]) {
          expect((await walk(q, plan)).keys, `${qs} ${plan.mode}`).toEqual(want);
        }
      }
    });
  }

  it("follows the API's own next links to the end", async () => {
    const seen: string[] = [];
    let next: string | undefined;
    do {
      const res = await api(`sort=positions${next ? `&cursor=${next}` : ""}`);
      expect(res.status).toBe(200);
      seen.push(...res.body.rows.map(keyOfRow));
      next = res.body.next;
    } while (next);
    expect(seen).toEqual(all("positions"));
  });

  it("crosses from counted to uncounted positions and pages inside them", async () => {
    const order = all("positions");
    const firstNull = order.findIndex((k) => SEEDS.find((s) => keyOf(s) === k)!.positions === null);
    expect(firstNull).toBeGreaterThan(50);
    expect(firstNull).toBeLessThan(100);
    expect(order.length - firstNull).toBeGreaterThan(50);
  });
});

describe("plans", () => {
  const plan = (qs: string, sizes = {}) => choosePlan(query(qs), sizes);

  it("reads newest within one status or province from that index", () => {
    expect(plan("status=approved")).toEqual({ mode: "prefix", driver: "status" });
    expect(plan("province=UN")).toEqual({ mode: "prefix", driver: "prov" });
    expect(plan("status=approved&province=BC", { status: 900_000, prov: 100_000 })).toEqual({ mode: "prefix", driver: "prov" });
    expect(plan("status=pending&province=ON", { status: 4_000, prov: 120_000 })).toEqual({ mode: "prefix", driver: "status" });
    expect(plan("status=approved&sort=name")).toEqual({ mode: "ordered", driver: null });
  });

  it("reads a small set and sorts it, and otherwise the sort's index", () => {
    expect(plan("province=NU&sort=name", { prov: 125 })).toEqual({ mode: "small", driver: "prov" });
    expect(plan("province=ON&sort=name", { prov: 129_000 })).toEqual({ mode: "ordered", driver: null });
    expect(plan("q=tim&province=ON", { fts: 40, prov: 129_000 })).toEqual({ mode: "small", driver: "fts" });
    expect(plan("q=inc&province=NU", { fts: 10_001, prov: 125 })).toEqual({ mode: "prefix", driver: "prov" });
    expect(plan("wage_min=20&sort=positions", { kind: 4_300 })).toEqual({ mode: "small", driver: "kind" });
    expect(plan("noc=99999&sort=name", { noc: 0 })).toEqual({ mode: "small", driver: "noc" });
    expect(plan("year_from=2014&year_to=2014&sort=positions", { year: 5_286 })).toEqual({ mode: "ordered", driver: null });
  });

  it("reads a larger set and sorts it when counts.json shows the filters share few rows", () => {
    const table = 478_772;
    const q = query("stream=Global%20Talent%20Stream&indicator=newly_incorporated&sort=name");
    expect(choosePlan(q, { stream: 16_000, ind: 9_000 }, "", { total: table, matching: 30 })).toEqual({ mode: "small", driver: "ind" });
    // Dense enough that reading the name index in order finds a page sooner.
    expect(choosePlan(q, { stream: 16_000, ind: 9_000 }, "", { total: table, matching: 8_000 })).toEqual({ mode: "ordered", driver: null });
    // Never more than SMALL_MAX rows to sort.
    expect(choosePlan(q, { stream: 60_000, ind: 25_000 }, "", { total: table, matching: 3 })).toEqual({ mode: "ordered", driver: null });
  });

  it("answers from counts.json alone when no row can match", async () => {
    const trace: SearchTrace = { statements: 0, rowsRead: 0, sql: [] };
    const res = await runSearch(env, query("province=XX&year_from=2014&year_to=2014"), DATA_DATE, COUNTS, { trace });
    expect(res).toMatchObject({ rows: [], total: 0, capped: false });
    expect(trace.statements).toBe(0);
    const text = await runSearch(env, query("q=holdings&province=XX&year_to=2015"), DATA_DATE, COUNTS, { trace });
    expect(text).toMatchObject({ rows: [], total: 0 });
    expect(trace.statements).toBe(0);
  });

  it("reads an indicator through the ind index, as the sets that hold it", async () => {
    const trace: SearchTrace = { statements: 0, rowsRead: 0, sql: [] };
    const q = query("indicator=refused_then_reposted&sort=name");
    const res = await runSearch(env, q, DATA_DATE, COUNTS, { trace });
    expect(trace.plan).toEqual({ mode: "small", driver: "ind" });
    expect(trace.sql.some((s) => /\bind IN \(\?, \?\)|\bind IN \(\?\)/.test(s))).toBe(true);
    expect(res!.rows.map(keyOfRow)).toEqual(expected(q));
  });

  it("binds every value once, within D1's limit, however many filters a request uses", async () => {
    const provinces = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX", "UN"];
    const streams = ["High Wage", "Low Wage", "Primary Agriculture", "Global Talent Stream", "Permanent Resident Only"];
    const qs = new URLSearchParams([["q", "tim horton"], ["status", "pending"], ["status", "approved"],
      ...provinces.map((p) => ["province", p]), ...streams.map((s) => ["stream", s]), ["noc", "632"], ["wage_min", "1"],
      ["wage_max", "9999"], ["date", "last_quarter"], ["year_from", "2014"], ["year_to", "2026"], ["indicator", "high_volume"],
      ["sort", "positions"]]);
    const q = { ...query(qs.toString()), cursor: decodeCursor(encodeCursor({ sort: "positions", key: "e:150", date: "2024-03-31", positions: 1 })) };
    const indValues = Array.from({ length: 32 }, (_, i) => `high_volume,set${i}`);
    for (const plan of [{ mode: "ordered", driver: null }, { mode: "small", driver: "ind" }] as Plan[]) {
      const built = buildSelect(q, { plan, dataDate: DATA_DATE, indValues });
      expect(built.params.length).toBeLessThanOrEqual(100);
      if (plan.mode === "ordered") {
        // Two arms, one set of numbered values.
        expect(built.sql).toContain("UNION ALL");
        expect(built.sql).not.toMatch(/\?(?!\d)/);
      }
      const res = await env.SEARCH.prepare(built.sql).bind(...built.params).all();
      expect(res.success).toBe(true);
      const count = buildCount(q, { driver: "fts", dataDate: DATA_DATE, indValues });
      expect((await env.SEARCH.prepare(count.sql).bind(...count.params).all()).success).toBe(true);
    }
  });

  it("counts through the index that lists the fewest rows", () => {
    const ordered: Plan = { mode: "ordered", driver: null };
    expect(countDriver(query("q=inc&province=ON&sort=name"), ordered, { fts: 10_001, prov: 129_000 })).toBe("fts");
    expect(countDriver(query("noc=632&province=ON&sort=name"), ordered, { noc: 5_001, prov: 129_000 })).toBe("noc");
    expect(countDriver(query("status=refused&sort=name"), ordered, { status: 41_000 })).toBe("status");
    expect(countDriver(query("indicator=high_volume&sort=name"), ordered, {})).toBeNull();
    expect(countDriver(query("province=NU&sort=name"), { mode: "small", driver: "prov" }, { prov: 125 })).toBe("prov");
    expect(countDriver(query("status=approved"), { mode: "prefix", driver: "status" }, {})).toBe("status");
  });

  it("never sorts what it reads in index order: no temp b-tree for any sort, with or without a status or province", async () => {
    for (const sort of ["newest", "positions", "name"]) {
      for (const f of ["", "status=approved", "status=pending&status=refused", "province=QC", "province=ON&province=UN"]) {
        const q = query(`${f}${f ? "&" : ""}sort=${sort}`);
        const chosen = choosePlan(q, {});
        expect(chosen.mode, `${sort} ${f}`).not.toBe("small");
        const pages = [q, { ...q, cursor: decodeCursor(encodeCursor(sort === "name"
          ? { sort: "name", key: "e:150", name: "maple holdings" }
          : { sort: sort as "newest", key: "e:150", date: "2024-03-31", positions: 1 })) }];
        for (const page of pages) {
          const built = buildSelect(page, { plan: chosen, dataDate: DATA_DATE });
          const rows = await env.SEARCH.prepare(`EXPLAIN QUERY PLAN ${built.sql}`).bind(...built.params).all<{ detail: string }>();
          const detail = rows.results.map((r) => r.detail).join(" | ");
          expect(detail, `${sort} ${f}: ${detail}`).not.toMatch(/TEMP B-TREE/);
          expect(detail, `${sort} ${f}: ${detail}`).toMatch(/USING (COVERING )?INDEX search_rows_(newest|status_newest|prov_newest|positions|name_key)/);
          if (page.cursor) expect(detail, `${sort} ${f}: ${detail}`).toMatch(/\(sort_date,key\)<|\(positions,sort_date,key\)<|\(name_fold,key\)>/);
        }
      }
    }
  });
});

describe("capped totals", () => {
  const BULK = 10_050;
  beforeAll(async () => {
    // Generated in the database: 10,050 rows the text "bulkfill" finds.
    await env.SEARCH.prepare(
      `WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < ${BULK}) ` +
      `INSERT INTO search_rows (${COLUMNS.join(", ")}) SELECT 2 * (100000 + i), 'e:' || (100000 + i), 'esdc', 100000 + i, ` +
      "'emp-bulk00001', 'Bulkfill Packers', 'Packers', '94141', NULL, 'Bulkton', 'PE', NULL, NULL, NULL, NULL, NULL, '2016', 1, " +
      "'approved', NULL, 'https://open.canada.ca/x', '2016-12-31', 2016, '', 'bulkfill packers', 'h' FROM n",
    ).run();
  });
  afterAll(async () => {
    await env.SEARCH.prepare("DELETE FROM search_rows WHERE employer_id = 'emp-bulk00001'").run();
  });

  it("stop counting at 10,001 rows and say so", async () => {
    const alone = await api("q=bulkfill");
    expect(alone.body).toMatchObject({ total: 10_000, capped: true });
    expect(alone.body.rows).toHaveLength(50);
    const filtered = await api("q=bulkfill&province=PE", withoutCounts());
    expect(filtered.body).toMatchObject({ total: 10_000, capped: true });
    const plain = await api("province=PE&sort=name", withoutCounts());
    expect(plain.body).toMatchObject({ total: 10_000, capped: true });
    const few = await api("q=bulkfill&noc=9999", withoutCounts());
    expect(few.body).toMatchObject({ total: 0, capped: false });
  });
});

describe("page only", () => {
  const REFUSAL = { error: "the search API is not open; the site's search page uses it" };
  const refusedProperly = (res: Awaited<ReturnType<typeof api>>) => {
    expect(res.status).toBe(403);
    expect(res.body).toEqual(REFUSAL);
    expect(res.headers.get("content-type")).toContain("application/json");
    // No shared cache may keep it, and it varies on what was checked.
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(res.headers.get("vary")).toBe("Sec-Fetch-Site, Origin, Referer");
  };

  it("answers the site's own page", async () => {
    expect((await api("q=tim", withCounts(), { "sec-fetch-site": "same-origin" })).status).toBe(200);
    expect((await api("q=tim", withCounts(), { "sec-fetch-site": "same-site" })).status).toBe(200);
    // An older browser without fetch metadata, on the site's own page.
    for (const referer of ["https://lmiawatch.ca/search?q=tim", "https://www.lmiawatch.ca/search", "http://localhost/search"]) {
      expect((await api("q=tim", withCounts(), { referer })).status, referer).toBe(200);
    }
    expect((await api("q=tim", withCounts(), { origin: "https://lmiawatch.ca" })).status).toBe(200);
  });

  it("refuses a cross-site request, whatever its referrer says", async () => {
    refusedProperly(await api("q=tim", withCounts(), { "sec-fetch-site": "cross-site" }));
    refusedProperly(await api("q=tim", withCounts(), { "sec-fetch-site": "cross-site", referer: "https://lmiawatch.ca/search" }));
    // Typed into the address bar: not the page either.
    refusedProperly(await api("q=tim", withCounts(), { "sec-fetch-site": "none" }));
  });

  it("refuses a request with no fetch metadata from anywhere else", async () => {
    for (const headers of [{}, { referer: "https://example.org/search" }, { referer: "https://lmiawatch.ca.example.org/" },
      { referer: "https://evil.example/?https://lmiawatch.ca/" }, { origin: "https://example.org" }, { referer: "not a url" },
      { referer: "ftp://lmiawatch.ca/" }] as Record<string, string>[]) {
      refusedProperly(await api("q=tim", withCounts(), headers));
    }
  });

  it("refuses before reading anything, so a bad cursor is a 403 too", async () => {
    refusedProperly(await api("cursor=not-a-cursor", withCounts(), { "sec-fetch-site": "cross-site" }));
    refusedProperly(await api("q=tim", { ...withCounts(), SEARCH: undefined } as any, {}));
  });
});

describe("unavailable", () => {
  it("answers 503 without a search database, and no cache keeps it", async () => {
    const res = await api("q=tim", { ...withCounts(), SEARCH: undefined } as any);
    expect(res.status).toBe(503);
    expect(res.body).toEqual({ error: "search unavailable" });
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("answers 503 when a query fails, and logs no request value", async () => {
    const failing = {
      prepare: () => ({ bind: () => ({}) }),
      batch: async () => {
        throw new Error('D1_ERROR: fts5: syntax error near "secretterm": SQLITE_ERROR');
      },
    } as unknown as D1Database;
    const logged: string[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      logged.push(args.map(String).join(" "));
    });
    try {
      const res = await api("q=secretterm", { ...withCounts(), SEARCH: failing } as any);
      expect(res.status).toBe(503);
      expect(res.body).toEqual({ error: "search unavailable" });
    } finally {
      spy.mockRestore();
    }
    expect(logged.join("\n")).toContain("SQLITE_ERROR");
    expect(logged.join("\n")).not.toContain("secretterm");
  });

  it("caches a good answer for five minutes", async () => {
    const res = await api("status=pending");
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("public, max-age=300");
    expect(res.headers.get("content-type")).toContain("application/json");
  });
});

// -- injection -----------------------------------------------------------------

const PAYLOADS = [
  "' OR 1=1 --", '"; DROP TABLE search_rows; --', 'x" OR "a"="a', "employer:tim", "NOT ltd", "a OR b", "(x", "*", "^tim", "tim*", '"',
  "x".repeat(5000), "NaN", "1e400", "99999", "-1", "0x10", "Infinity", "1; DELETE FROM search_rows", "') UNION SELECT sql FROM sqlite_master --",
  "NEAR(tim horton)", "{employer job}: tim", "tim AND horton", "%", "_", "\\", "\u0000", "../../etc/passwd", "<script>alert(1)</script>",
  "😀", "Montréal' --", "ON' OR '1'='1", "approved'--", "2014 OR 1=1", "15; DROP TABLE search_fts", "newest; --", "rid DESC",
  "search_fts MATCH '*'", "e:1') OR ('1'='1",
];
const PARAMS = ["q", "status", "province", "stream", "noc", "wage_min", "wage_max", "year_from", "year_to", "date", "indicator", "sort", "cursor"];

function wellFormed(body: any): boolean {
  return body && Array.isArray(body.rows) && body.rows.every((r: any) => typeof r.employer === "string" && Array.isArray(r.ind)) &&
    (body.total === null || Number.isInteger(body.total)) && typeof body.capped === "boolean" &&
    (body.next === undefined || /^[A-Za-z0-9_-]+$/.test(body.next));
}

describe("injection", () => {
  let before: Awaited<ReturnType<typeof canary>>;
  beforeAll(async () => {
    before = await canary();
    expect(before.n).toBe(SEEDS.length);
  });

  for (const param of PARAMS) {
    it(`answers every payload in ${param} without an error and without effect`, async () => {
      for (const payload of PAYLOADS) {
        const qs = new URLSearchParams({ [param]: payload }).toString();
        for (const environment of [withCounts(), withoutCounts()]) {
          const res = await api(qs, environment);
          if (param === "cursor") {
            expect(res.status, payload.slice(0, 40)).toBe(400);
            expect(res.body.error).toBe("bad request");
            expect(res.body.problems).toEqual(["cursor: not a cursor this API issued"]);
            expect(JSON.stringify(res.body)).not.toContain(payload.length > 3 ? payload.slice(0, 20) : "\u0001");
          } else {
            expect(res.status, `${param}=${payload.slice(0, 40)}`).toBe(200);
            expect(wellFormed(res.body), `${param}=${payload.slice(0, 40)}`).toBe(true);
            // A dropped value is named by its parameter, never echoed.
            for (const name of res.body.ignored ?? []) expect(PARAMS).toContain(name);
          }
        }
      }
    });
  }

  it("treats raw bytes, repeats and odd numbers as values", async () => {
    const raw = ["q=%FF%FE%00", "q=%zz", "q=%E2%80", "status=" + "approved&status=".repeat(199) + "approved",
      "wage_min=NaN", "wage_min=1e400", "wage_min=-0", "wage_max=10000.00001", "year_from=99999", "year_to=0x7E3",
      "province=" + "ON&province=".repeat(300) + "ON", "q=" + encodeURIComponent("\"".repeat(300)), "noc=" + "9".repeat(500),
      "sort=positions&sort=name", "date=7d&date=since_2023q4"];
    for (const qs of raw) {
      const res = await api(qs);
      expect(res.status, qs.slice(0, 60)).toBe(200);
      expect(wellFormed(res.body), qs.slice(0, 60)).toBe(true);
    }
  });

  it("refuses cursors that are not base64, hold the wrong types or hold SQL", async () => {
    const raw = (text: string) => btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const forged = (o: unknown) => raw(JSON.stringify(o));
    for (const c of ["not-base64!", "@@@@", forged({ o: "newest", k: ["e:1"], d: "2024-03-31" }), forged({ o: "newest", k: "e:1", d: 20240331 }),
      forged({ o: "newest", k: "e:1); DELETE FROM search_rows; --", d: "2024-03-31" }), forged({ o: "newest", k: "e:1", d: "' OR 1=1 --" }),
      forged({ o: "name", k: "e:1", n: { toString: 1 } }), raw('{"o":"positions","k":"e:1","d":"2024-03-31","p":1e400}'),
      raw('{"o":"newest","k":"e:1","d":"2024-03-31","d":"2024-03-31"} trailing'), forged(null), forged({ __proto__: { o: "newest" } })]) {
      const res = await api(`cursor=${encodeURIComponent(c)}`);
      expect(res.status, c).toBe(400);
      expect(res.body.problems).toHaveLength(1);
    }
    // SQL text in a name cursor is a value like any other: bound, compared, harmless.
    const sqlName = encodeCursor({ sort: "name", key: "e:1", name: "'); DROP TABLE search_rows; --" });
    const res = await api(`sort=name&cursor=${sqlName}`);
    expect(res.status).toBe(200);
    expect(res.body.rows.length).toBe(50);
  });

  it("never writes a request value into the SQL it builds", () => {
    const sqlFor = (q: SearchQuery): string[] => {
      const out: string[] = [];
      const plans: Plan[] = [{ mode: "ordered", driver: null }, { mode: "prefix", driver: "status" }, { mode: "prefix", driver: "prov" },
        { mode: "small", driver: "fts" }, { mode: "small", driver: "year" }, { mode: "small", driver: "noc" }, { mode: "small", driver: "kind" }];
      for (const plan of plans) {
        out.push(buildSelect(q, { plan, dataDate: DATA_DATE }).sql, buildCount(q, { driver: plan.driver, dataDate: DATA_DATE }).sql);
      }
      out.push(...buildProbes(q, undefined, true).map((p) => p.built.sql));
      return out;
    };
    const literal = (sql: string) => sql.replace(/'(posting)'/g, "").replace(/','/g, "");
    const name = encodeCursor({ sort: "name", key: "e:1", name: "'); DROP TABLE search_rows; --" });
    for (const param of PARAMS.filter((p) => p !== "cursor")) {
      for (const payload of PAYLOADS) {
        for (const sort of ["newest", "positions", "name"]) {
          const qs = `${new URLSearchParams({ [param]: payload })}&sort=${sort}`;
          const q = query(qs);
          for (const sql of sqlFor(q)) {
            // Fixed fragments only: no quote but the two literals the module
            // writes itself, and none of the payload's text.
            expect(literal(sql), `${param}=${payload.slice(0, 30)}`).not.toMatch(/['"]/);
            if (payload.length > 2 && /[A-Za-z]/.test(payload)) expect(sql).not.toContain(payload);
            expect(sql).not.toContain("*");
          }
        }
      }
    }
    // The cursor's values are bound too.
    const sql = buildSelect(query(`sort=name&cursor=${name}`)).sql;
    expect(sql).not.toContain("DROP");
    expect(literal(sql)).not.toMatch(/['"]/);
  });

  it("leaves the table exactly as it was", async () => {
    const after = await canary();
    expect(after).toEqual(before);
  });
});

// -- what requests read, for the step report -------------------------------------

describe("rows read", () => {
  it("reads about a page per page in the common plans", async () => {
    // D1 refuses sqlite_version(), so the report names the row count only.
    const report: string[] = [`${SEEDS.length} rows`];
    const firsts: number[] = [];
    for (const [qs, counts] of [
      ["sort=newest", COUNTS], ["sort=newest", null], ["sort=positions", null], ["sort=name", null], ["status=approved", null],
      ["status=pending&sort=positions", COUNTS], ["province=NU&sort=name", COUNTS], ["q=holdings", null], ["q=tim", null],
      ["q=holdings&province=BC", null], ["indicator=refused_then_reposted", COUNTS], ["indicator=refused_then_reposted", null],
      ["wage_min=17&sort=name", null], ["noc=632&sort=positions", null], ["year_from=2016&year_to=2016", null],
    ] as [string, SearchCounts | null][]) {
      const { reads, pages, pageReads } = await walk(query(qs), undefined, counts);
      const trace: SearchTrace = { statements: 0, rowsRead: 0, sql: [] };
      await runSearch(env, query(qs), DATA_DATE, counts, { trace });
      report.push(`${qs}${counts ? " (counts.json)" : ""}: plan ${JSON.stringify(trace.plan)}, ${trace.statements} statements, ` +
        `first page ${reads[0]} rows read, ${pages} pages, ${reads.reduce((a, b) => a + b, 0)} in all`);
      firsts.push(reads[0]);
      // A later page of a plan that reads an index in order seeks to the
      // cursor and reads its own rows, not the ones before it.
      if (trace.plan?.mode !== "small" && !qs.includes("indicator")) {
        for (const n of pageReads.slice(1)) expect(n, qs).toBeLessThanOrEqual(2 * 51 + 10);
      }
    }
    console.log(`search rows read:\n  ${report.join("\n  ")}`);
    for (const n of firsts) expect(n).toBeLessThanOrEqual(SEEDS.length * 8);
  });
});
