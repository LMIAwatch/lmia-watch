// Hosted search: the query builder and runner behind GET /api/search, over
// the D1 database the nightly sync fills (binding SEARCH, schema in
// pipeline/search_schema.sql, docs/hosted-search.md).
//
// No SQL injection, and no query a visitor can make expensive:
//
// - Every statement is prepared with ? placeholders and bound values. The
//   SQL text is assembled only from fixed fragments in this file; which
//   fragments appear depends on which filters a request uses and how many
//   values each has, never on what the values are. Filter keys, sort keys
//   and the date windows come from allowlists here; a value outside them is
//   dropped.
// - Text never reaches MATCH as typed. ftsQuery keeps at most eight tokens,
//   strips every character but letters, digits and apostrophes from each,
//   and writes each as a double-quoted FTS5 phrase, so AND, OR, NOT, NEAR, a
//   column filter, parentheses, ^, * and - stay literal words, and no token
//   can hold a double quote to end its phrase. The expression is bound as a
//   value like any other.
// - Pages are keyset pages of 50 rows (51 are read to know whether a next
//   page exists), so page 1,000 costs what page 1 does. The cursor is
//   base64url JSON this module wrote; it is decoded field by field and
//   anything else is refused with a 400.
// - Each sort has an index in its order, and the keyset condition is a row
//   value, (sort_date, key) < (?, ?), which SQLite turns into a seek on that
//   index (an OR of comparisons it does not: a page deep inside one quarter
//   then read every row of the quarter before it). Filters the index cannot
//   answer are checked row by row while it is read, and their columns are
//   written with a unary plus (+status) so the planner cannot switch to an
//   index that would make it read and sort every matching row instead.
// - Every filter but the wage and date ones has an index that lists its
//   rows (the text index, status, province, stream, year, the indicator sets,
//   a NOC prefix; a wage or posting-date filter implies the postings, which
//   have one too). When one lists at most SMALL_SET rows, the plan reads
//   those and sorts them. When counts.json shows that the filters together
//   match so few rows that reading an index in order would cost more, the
//   plan reads the smallest filter's rows instead, up to SMALL_MAX. Sizes
//   come from counts.json, or from probes capped at SMALL_SET + 1.
//
// Totals are the expensive part, since a count reads every matching row.
// search/counts.json (export_static.py) holds the rows counted by status,
// province, stream, year and indicators, so a request filtering on nothing
// else gets an exact total and exact facet counts (by status and by
// province) with no database read, and one no row can match is answered
// without the database at all. A text query with no other filter gets its
// total from the text probe the planner runs anyway. A first page holding
// fewer than 51 rows is its own total. Any other first page counts in D1, as
// SELECT COUNT(1) FROM (SELECT rid ... LIMIT 10001) through the index that
// lists the fewest rows: at most 10,001 matching rows, with capped: true
// when it reached that. A later page (one with a cursor) is not counted
// again; the client keeps page 1's total.
//
// What is left unbounded by the plans is bounded by the data: a text query
// lists its matches once per statement (a common word, "inc" on the full
// data, lists 220,000), and without counts.json an indicator filter is
// checked row by row. Measured figures are in docs/hosted-search.md.

import type { SearchCounts, SearchRow } from "./data";
import type { Env } from "./env";

export const PAGE_SIZE = 50;
const FETCH_ROWS = PAGE_SIZE + 1;
export const COUNT_CAP = 10_000;
export const SMALL_SET = 5_000;
// The most rows a plan reads and sorts when counts.json shows that reading
// an index in order would cost more (see choosePlan).
export const SMALL_MAX = 20_000;
export const MAX_Q = 200;
export const MAX_NOC_TEXT = 60;
export const MAX_TOKENS = 8;
// A name cursor carries the folded name, the longest of which was 744
// characters on 2026-10-23 data; these leave room for names well past that.
const MAX_CURSOR = 8_200;
const MAX_CURSOR_NAME = 2_000;
export const YEAR_MIN = 2014;
export const WAGE_MAX = 10_000;
// D1 refuses a statement with more than 100 bound values; the largest query
// this module writes binds about 70.
const MAX_BINDINGS = 100;

export const STATUSES = ["pending", "approved", "refused"] as const;
export type Status = (typeof STATUSES)[number];
// The thirteen provinces and territories, XX (head office outside Canada)
// and UN, the search page's name for a row with no province.
export const PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX", "UN"] as const;
export const UNKNOWN_PROVINCE = "UN";
// ESDC's five streams under the names the search page and releases.py use,
// each with the spellings ESDC has published it under (releases.py
// STREAM_ALIASES). A filter on a stream matches every spelling, and counts
// sums cells the same way, so the two totals agree.
export const STREAMS: Record<string, readonly string[]> = {
  "High Wage": ["High Wage"],
  "Low Wage": ["Low Wage"],
  "Primary Agriculture": ["Primary Agriculture"],
  "Global Talent Stream": ["Global Talent Stream", "Global Talent", "Talent mondial"],
  "Permanent Resident Only": ["Permanent Resident Only"],
};
// Every accepted spelling, as the name it stands for.
const STREAM_NAME: Record<string, string> = Object.fromEntries(
  Object.entries(STREAMS).flatMap(([name, spellings]) => spellings.map((s) => [s, name])),
);
// The indicator keys (pipeline/lmia_pipeline/indicators.py INDICATORS).
export const INDICATORS = [
  "newly_incorporated", "repeat_applicant", "wage_at_floor", "low_wage_high_unemployment", "high_volume",
  "refused_then_reposted",
] as const;
export const SORTS = ["newest", "positions", "name"] as const;
export type Sort = (typeof SORTS)[number];
// Counted from the data's date: postings of the last 7 days; and postings of
// the last 92 days with the list rows of the latest ESDC period (counts.json
// latest_period), which is what the search page's control says.
export const DATES = ["any", "7d", "last_quarter"] as const;
export type DateFilter = (typeof DATES)[number];

// How many values of a repeatable parameter are read; the rest are cut.
const MAX_REPEAT = { status: 3, province: 15, stream: 7 } as const;

export interface Cursor {
  sort: Sort;
  key: string;
  date?: string;             // newest, positions
  positions?: number | null; // positions
  name?: string;             // name
}

export interface SearchQuery {
  q: string;
  status: Status[];
  province: string[];
  stream: string[];          // the stream names, not their spellings
  nocCode: string | null;    // 1 to 5 digits, matched as a prefix of the code
  nocText: string;           // otherwise words matched in the job or occupation title
  wageMin: number | null;
  wageMax: number | null;
  yearFrom: number | null;
  yearTo: number | null;
  date: DateFilter;
  indicator: string | null;
  sort: Sort;
  cursor: Cursor | null;
}

export type Parsed =
  | { ok: true; query: SearchQuery; ignored: string[] }
  | { ok: false; problems: string[] };

const isOneOf = <T extends string>(list: readonly T[], v: string): v is T => (list as readonly string[]).includes(v);

// -- parsing -----------------------------------------------------------------

// A value this cannot use is dropped and its parameter named in `ignored`
// (never the value itself); only a cursor that is not one this module wrote
// is a problem, since paging from a position it cannot trust would be wrong.
export function parseQuery(url: URL, now: Date = new Date()): Parsed {
  const p = url.searchParams;
  const ignored = new Set<string>();
  const first = (name: string): string => (p.get(name) ?? "").trim();

  const repeated = <T extends string>(name: keyof typeof MAX_REPEAT, accept: (v: string) => T | null): T[] => {
    const all = p.getAll(name).map((v) => v.trim()).filter((v) => v !== "");
    if (all.length > MAX_REPEAT[name]) ignored.add(name);
    const out: T[] = [];
    for (const v of all.slice(0, MAX_REPEAT[name])) {
      const ok = accept(v);
      if (ok === null) ignored.add(name);
      else if (!out.includes(ok)) out.push(ok);
    }
    return out;
  };

  const q = first("q").slice(0, MAX_Q).trim();
  if (q && !ftsQuery(q)) ignored.add("q");
  const status = repeated("status", (v) => (isOneOf(STATUSES, v) ? v : null));
  const province = repeated("province", (v) => (isOneOf(PROVINCES, v) ? v : null));
  const stream = repeated("stream", (v) => STREAM_NAME[v] ?? null);

  let nocCode: string | null = null;
  let nocText = "";
  const noc = first("noc");
  if (/^\d{1,5}$/.test(noc)) nocCode = noc;
  else if (noc) {
    nocText = noc.slice(0, MAX_NOC_TEXT);
    if (!ftsQuery(nocText)) {
      nocText = "";
      ignored.add("noc");
    }
  }

  const number = (name: string, max: number, min: number, pattern: RegExp): number | null => {
    const v = first(name);
    if (!v) return null;
    const n = pattern.test(v) ? Number(v) : NaN;
    if (Number.isFinite(n) && n >= min && n <= max) return n;
    ignored.add(name);
    return null;
  };
  const decimal = /^\d{1,5}(\.\d{1,4})?$/;
  const wageMin = number("wage_min", WAGE_MAX, 0, decimal);
  const wageMax = number("wage_max", WAGE_MAX, 0, decimal);
  const yearMax = now.getUTCFullYear() + 1;
  const yearFrom = number("year_from", yearMax, YEAR_MIN, /^\d{4}$/);
  const yearTo = number("year_to", yearMax, YEAR_MIN, /^\d{4}$/);

  const pick = <T extends string>(name: string, list: readonly T[], fallback: T | null): T | null => {
    const v = first(name);
    if (!v) return fallback;
    if (isOneOf(list, v)) return v;
    ignored.add(name);
    return fallback;
  };
  const date = pick("date", DATES, "any") as DateFilter;
  const indicator = pick("indicator", INDICATORS, null);
  const sort = pick("sort", SORTS, "newest") as Sort;

  let cursor: Cursor | null = null;
  const rawCursor = first("cursor");
  if (rawCursor) {
    cursor = decodeCursor(rawCursor);
    if (!cursor) return { ok: false, problems: ["cursor: not a cursor this API issued"] };
    if (cursor.sort !== sort) return { ok: false, problems: ["cursor: issued for another sort"] };
  }

  return {
    ok: true,
    query: { q, status, province, stream, nocCode, nocText, wageMin, wageMax, yearFrom, yearTo, date, indicator, sort, cursor },
    ignored: [...ignored],
  };
}

// -- text --------------------------------------------------------------------

// Folded as search_db.py's fold and search.js's fold do (NFD, combining marks
// U+0300 to U+036F removed, lower case); the index's tokenizer removes
// diacritics too, so "quebec" and "Québec" are the same token either way.
const fold = (s: string): string => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

// Text as an FTS5 expression of quoted phrases, joined by spaces (an implicit
// AND), or "" when nothing usable is left (no text filter). Typographic
// apostrophes count as apostrophes, so "O’Brien" finds "O'Brien" (the
// tokenizer splits both into o and brien). A phrase gets a prefix star
// ("tim"* finds Tim and Timbers) unless it is a single character: a
// one-letter prefix makes FTS5 merge the lists of every word starting with
// that letter (about 28 ms each on the full data, against under 1 ms for the
// letter as a word), and eight of them would cost a request a quarter of a
// second for nothing a reader wants.
export function ftsQuery(text: string, column: "job" | null = null): string {
  const phrases: string[] = [];
  for (const raw of text.split(/\s+/).filter(Boolean).slice(0, MAX_TOKENS)) {
    const token = fold(raw).replace(/[\u2018\u2019\u02bc]/g, "'").replace(/[^\p{L}\p{N}']/gu, "");
    if (!/[\p{L}\p{N}]/u.test(token)) continue;
    const phrase = [...token].length > 1 ? `"${token}"*` : `"${token}"`;
    // The column name is this module's, never the request's.
    phrases.push(column ? `${column} : ${phrase}` : phrase);
  }
  return phrases.join(" ");
}

// The request's whole text filter: q over the name, title and city, and a
// NOC given as words over the title alone.
export function matchExpression(q: SearchQuery): string {
  return [ftsQuery(q.q), ftsQuery(q.nocText, "job")].filter(Boolean).join(" ");
}

// -- cursors -----------------------------------------------------------------

const KEY_RE = /^[ep]:\d{1,19}$/;
const SORT_DATE_RE = /^(\d{4}-\d{2}-\d{2})?$/;

function toBase64Url(text: string): string {
  let bin = "";
  for (const b of new TextEncoder().encode(text)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromBase64Url(text: string): string | null {
  if (text.length > MAX_CURSOR || !/^[A-Za-z0-9_-]+$/.test(text) || text.length % 4 === 1) return null;
  try {
    const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(bin, (ch) => ch.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes);
  } catch {
    return null;
  }
}

export function encodeCursor(c: Cursor): string {
  const body: Record<string, unknown> = { o: c.sort, k: c.key };
  if (c.sort === "name") body.n = c.name;
  else body.d = c.date;
  if (c.sort === "positions") body.p = c.positions ?? null;
  return toBase64Url(JSON.stringify(body));
}

// Each sort's cursor holds exactly its fields: o (the sort), k (the row's
// key), and d (sort date), p (positions or null) or n (folded name). Any
// other shape, type or bound fails.
export function decodeCursor(text: string): Cursor | null {
  const json = fromBase64Url(text);
  if (json === null) return null;
  let v: unknown;
  try {
    v = JSON.parse(json);
  } catch {
    return null;
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  const sort = o.o;
  if (typeof sort !== "string" || !isOneOf(SORTS, sort)) return null;
  if (typeof o.k !== "string" || !KEY_RE.test(o.k)) return null;
  const fields = Object.keys(o).sort().join(",");
  const date = (x: unknown): x is string => typeof x === "string" && SORT_DATE_RE.test(x);
  if (sort === "newest") {
    return fields === "d,k,o" && date(o.d) ? { sort, key: o.k, date: o.d } : null;
  }
  if (sort === "positions") {
    const p = o.p;
    const okP = p === null || (typeof p === "number" && Number.isSafeInteger(p) && p >= 0 && p <= 2_147_483_647);
    return fields === "d,k,o,p" && date(o.d) && okP ? { sort, key: o.k, date: o.d, positions: p as number | null } : null;
  }
  const n = o.n;
  return fields === "k,n,o" && typeof n === "string" && n.length <= MAX_CURSOR_NAME
    ? { sort, key: o.k, name: n }
    : null;
}

// -- planning ----------------------------------------------------------------

export type Driver = "fts" | "status" | "prov" | "stream" | "year" | "ind" | "noc" | "kind";
export interface Plan {
  // ordered: read the sort's index in order and check every filter per row.
  // prefix: newest within one status or one province, from that index.
  // small: read the driver's rows and sort them.
  mode: "ordered" | "prefix" | "small";
  driver: Driver | null;
}
export const ORDERED: Plan = { mode: "ordered", driver: null };

// What counts.json says about a request: the rows in the table, and how many
// pass its status, province, stream, year and indicator filters (at most
// that many when it has other filters too).
export interface Shape {
  total: number;
  matching: number;
}

const statusFilter = (q: SearchQuery): Status[] => (q.status.length < STATUSES.length ? q.status : []);
const impliesPosting = (q: SearchQuery): boolean => q.wageMin !== null || q.wageMax !== null || q.date === "7d";

// The filters with an index that can list their rows. The indicator filter
// has one only with counts.json, whose list of indicator sets turns it into
// ind IN (...) (indValues below); hasInd says whether that list is at hand.
function drivers(q: SearchQuery, match: string, hasInd = false): Driver[] {
  const out: Driver[] = [];
  if (match) out.push("fts");
  if (statusFilter(q).length) out.push("status");
  if (q.province.length) out.push("prov");
  if (q.stream.length) out.push("stream");
  if (q.yearFrom !== null || q.yearTo !== null) out.push("year");
  if (q.indicator && hasInd) out.push("ind");
  if (q.nocCode) out.push("noc");
  if (impliesPosting(q)) out.push("kind");
  return out;
}

export function choosePlan(q: SearchQuery, sizes: Partial<Record<Driver, number>>, match = matchExpression(q), shape?: Shape): Plan {
  let small: Driver | null = null;
  for (const d of drivers(q, match, sizes.ind !== undefined)) {
    const n = sizes[d];
    if (n !== undefined && (small === null || n < (sizes[small] as number))) small = d;
  }
  const smallSize = small ? (sizes[small] as number) : Infinity;
  // Newest within one status or one province: that index is already in the
  // order, so the page stops after its rows, unless another filter lists
  // fewer rows than the status or province holds.
  let prefix: Driver | null = null;
  if (q.sort === "newest") {
    const oneStatus = statusFilter(q).length === 1;
    const oneProv = q.province.length === 1;
    if (oneStatus && oneProv) prefix = (sizes.status ?? Infinity) < (sizes.prov ?? Infinity) ? "status" : "prov";
    else if (oneStatus) prefix = "status";
    else if (oneProv) prefix = "prov";
  }
  const prefixSize = prefix ? (sizes[prefix] ?? Infinity) : Infinity;
  const prefixPlan: Plan | null = prefix ? { mode: "prefix", driver: prefix } : null;
  if (small && smallSize <= SMALL_SET) {
    return prefixPlan && (small === prefix || prefixSize <= smallSize) ? prefixPlan : { mode: "small", driver: small };
  }
  // No filter lists a small set. With counts.json the planner knows how many
  // rows can match: reading an index in order meets one about every
  // total / matching rows, so a page reads 51 times that, while reading the
  // smallest filter's rows and sorting them reads each once. The cheaper
  // wins, up to SMALL_MAX rows (two filters that each hold many rows can
  // still have few in common: Global Talent Stream and a newly incorporated
  // employer, say).
  if (shape && small && smallSize <= SMALL_MAX) {
    const scan = (51 * (prefixPlan ? prefixSize : shape.total)) / Math.max(shape.matching, 1);
    if (smallSize < scan) return { mode: "small", driver: small };
  }
  return prefixPlan ?? ORDERED;
}

// -- SQL ---------------------------------------------------------------------

const COLUMNS =
  "kind, ref, employer_id, employer, job, noc, street, city, prov, postal, wage_min, wage_max, unit, date, period, " +
  "positions, status, stream, source, sort_date, ind, name_fold, key";
const FTS_ROWIDS = "SELECT rowid FROM search_fts WHERE search_fts MATCH ?";
const marks = (n: number): string => Array(n).fill("?").join(", ");

export interface BuiltSql {
  sql: string;
  params: (string | number)[];
}

interface BuildOptions {
  plan?: Plan;
  dataDate?: string;
  // The indicator sets (counts.json values.ind) that hold the requested
  // indicator; without them the filter is checked with instr row by row.
  indValues?: string[] | null;
  // The latest ESDC period, for date=last_quarter (null: no list row).
  latestPeriod?: string | null;
}

interface CountOptions {
  // The index the count reads through (see countDriver); null scans.
  driver?: Driver | null;
  dataDate?: string;
  indValues?: string[] | null;
  latestPeriod?: string | null;
}

// The indicator sets in counts.json that contain the key: "high_volume"
// gives "high_volume" and "high_volume,repeat_applicant", and so on. Pipeline
// data, bound as values like any other.
export function indicatorSets(counts: SearchCounts | null, q: SearchQuery): string[] | null {
  if (!counts || !q.indicator) return null;
  const sets = counts.values.ind.filter((s) => s.split(",").includes(q.indicator as string));
  // Six indicators make at most 32 sets holding any one of them (eleven sets
  // exist on 2026-10-23 data); more would mean a damaged file, so the filter
  // falls back to instr rather than binding past D1's limit.
  return sets.length <= 32 ? sets : null;
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "";
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

// A list period's last day, which is a list row's sort date
// (normalize.period_end_date): "2026Q1" gives "2026-03-31", "2017Q1-Q2"
// "2017-06-30", "2015" "2015-12-31"; null for anything else.
function periodEnd(period: string): string | null {
  const m = /^(\d{4})(?:Q([1-4])(?:-Q([1-4]))?)?$/.exec(period);
  if (!m) return null;
  return `${m[1]}-${["03-31", "06-30", "09-30", "12-31"][Number(m[3] ?? m[2] ?? 4) - 1]}`;
}

// The earliest sort date a row in the last-quarter window can have: a
// posting sorts on its date, which the window holds to the last 92 days, and
// a list row of the latest period on that period's last day. As a bound on
// sort_date it changes no result, and it lets a count seek the newest,
// status or province index instead of reading the table from its start,
// where the latest period's rows (the highest ids) come last.
export function lastQuarterFrom(dataDate: string, latestPeriod: string | null | undefined): string {
  const cutoff = shiftDate(dataDate, -92);
  const end = latestPeriod ? periodEnd(latestPeriod) : null;
  return end && end < cutoff ? end : cutoff;
}

// The string just after every string that starts with prefix: "632" gives
// "633", so noc >= '632' AND noc < '633' is the prefix match as a range an
// index can seek ("9" gives ":", the next character).
function prefixEnd(prefix: string): string {
  return prefix.slice(0, -1) + String.fromCharCode(prefix.charCodeAt(prefix.length - 1) + 1);
}

class Where {
  parts: string[] = [];
  params: (string | number)[] = [];
  add(sql: string, ...params: (string | number)[]): void {
    this.parts.push(sql);
    this.params.push(...params);
  }
  get sql(): string {
    return this.parts.length ? ` WHERE ${this.parts.join(" AND ")}` : "";
  }
}

// The predicates of the filters that have an index, with the column as given
// (bare to read through its index, "+col" to check it row by row).
function statusPredicate(w: Where, q: SearchQuery, col: string): void {
  const status = statusFilter(q);
  if (status.length) w.add(`${col} IN (${marks(status.length)})`, ...status);
}

function provPredicate(w: Where, q: SearchQuery, col: string): void {
  if (!q.province.length) return;
  const named = q.province.filter((p) => p !== UNKNOWN_PROVINCE);
  const unknown = named.length < q.province.length;
  if (named.length && unknown) w.add(`(${col} IN (${marks(named.length)}) OR ${col} IS NULL)`, ...named);
  else if (named.length) w.add(`${col} IN (${marks(named.length)})`, ...named);
  else w.add(`${col} IS NULL`);
}

function yearPredicate(w: Where, q: SearchQuery, col: string): void {
  if (q.yearFrom !== null) w.add(`${col} >= ?`, q.yearFrom);
  if (q.yearTo !== null) w.add(`${col} <= ?`, q.yearTo);
}

function nocPredicate(w: Where, q: SearchQuery, col: string): void {
  if (q.nocCode) w.add(`${col} >= ? AND ${col} < ?`, q.nocCode, prefixEnd(q.nocCode));
}

// The filters, without the keyset. A column is written bare when the plan
// reads through its index and with a unary plus otherwise. text: "in" lists
// the matching rows from the FTS index and reads them; "residual" checks
// each row read against that list; "none" leaves the text to the caller (the
// count's join).
//
// A row is never checked against the text index one at a time (a correlated
// MATCH): FTS5 rebuilds a prefix term's whole list on every call, which on
// the full data took 4 ms a row (half a second for Nunavut's 125 rows and
// "ltd"). The list is built once per statement instead; it costs a row read
// per matching row, and no more CPU than a scan.
function filters(q: SearchQuery, bare: Driver | null, dataDate: string, text: "in" | "residual" | "none",
  indValues: string[] | null | undefined, latestPeriod: string | null | undefined): Where {
  const w = new Where();
  const col = (name: string, d: Driver): string => (bare === d ? name : `+${name}`);
  const match = matchExpression(q);
  if (match && text !== "none") w.add(`${text === "in" ? "rid" : "+rid"} IN (${FTS_ROWIDS})`, match);
  statusPredicate(w, q, col("status", "status"));
  provPredicate(w, q, col("prov", "prov"));
  if (q.stream.length) {
    const spellings = q.stream.flatMap((s) => STREAMS[s] ?? []);
    w.add(`${col("stream", "stream")} IN (${marks(spellings.length)})`, ...spellings);
  }
  nocPredicate(w, q, col("noc", "noc"));
  if (impliesPosting(q)) w.add(`${col("kind", "kind")} = 'posting'`);
  if (q.wageMin !== null) w.add("+wage_min >= ?", q.wageMin);
  if (q.wageMax !== null) w.add("+wage_max <= ?", q.wageMax);
  if (q.date === "7d") w.add("+date >= ?", shiftDate(dataDate, -7));
  else if (q.date === "last_quarter") {
    // Postings of the last 92 days, and the list rows of the latest period.
    // kind is posting or esdc, so "<> 'posting'" is the list rows and the
    // module needs no second literal. Every column carries a plus, so the OR
    // never turns into an index lookup per arm that would then need a sort.
    // Without a latest period the second arm binds "", which no list row
    // holds.
    w.add("((+kind = 'posting' AND +date >= ?) OR (+kind <> 'posting' AND +period = ?))", shiftDate(dataDate, -92), latestPeriod ?? "");
  }
  yearPredicate(w, q, col("year", "year"));
  if (q.indicator) {
    // As the sets that contain it, the filter is an equality the ind index
    // can answer; without the list (no counts.json, or no row has it) it is
    // checked in each row's comma-separated keys.
    if (indValues && indValues.length) w.add(`${col("ind", "ind")} IN (${marks(indValues.length)})`, ...indValues);
    else w.add("instr(',' || ind || ',', ?) > 0", `,${q.indicator},`);
  }
  return w;
}

// Bounds on sort_date that let the newest index seek a year range. A row's
// year is its sort date's year (export_static and search_db write both from
// the same date; the pipeline's tests hold it), so they change no result,
// and the year predicates stay as the definition.
function yearBounds(q: SearchQuery): { from: string | null; to: string | null } {
  return {
    from: q.yearFrom !== null ? `${q.yearFrom}-01-01` : null,
    to: q.yearTo !== null ? `${q.yearTo + 1}-01-01` : null,
  };
}

const ORDER: Record<Sort, string[]> = {
  newest: ["sort_date DESC", "key DESC"],
  positions: ["positions DESC", "sort_date DESC", "key DESC"],
  name: ["name_fold", "key"],
};

function finish(built: BuiltSql): BuiltSql {
  if (built.params.length > MAX_BINDINGS) throw new Error("search: too many bound values");
  return built;
}

// The page query: one statement, 51 rows at most.
export function buildSelect(q: SearchQuery, opts: BuildOptions = {}): BuiltSql {
  const plan = opts.plan ?? ORDERED;
  const dataDate = opts.dataDate ?? new Date().toISOString().slice(0, 10);
  const small = plan.mode === "small";
  const p = small ? "+" : "";
  const where = () => filters(q, plan.mode === "ordered" ? null : plan.driver, dataDate, small && plan.driver === "fts" ? "in" : "residual",
    opts.indValues, opts.latestPeriod);
  const w = where();
  const c = q.cursor;
  const order = (small ? ORDER[q.sort].map((t) => `+${t}`) : ORDER[q.sort]).join(", ");
  const tail = ` ORDER BY ${order} LIMIT ${FETCH_ROWS}`;

  if (q.sort === "newest") {
    const { from, to } = small ? { from: null, to: null } : yearBounds(q);
    if (from) w.add("sort_date >= ?", from);
    if (c && c.date !== undefined && !(to !== null && c.date >= to)) {
      // Rows before the cursor all lie before the year's end, so the keyset
      // is the upper bound and the year's own bound is left out.
      w.add(`(${p}sort_date, ${p}key) < (?, ?)`, c.date, c.key);
    } else if (to) {
      // No cursor, or one past the year range: every row of the range comes
      // before it, so the year's bound is the only one needed.
      w.add("sort_date < ?", to);
    }
    return finish({ sql: `SELECT ${COLUMNS} FROM search_rows${w.sql}${tail}`, params: w.params });
  }

  if (q.sort === "name") {
    if (c && c.name !== undefined) w.add(`(${p}name_fold, ${p}key) > (?, ?)`, c.name, c.key);
    return finish({ sql: `SELECT ${COLUMNS} FROM search_rows${w.sql}${tail}`, params: w.params });
  }

  // Positions, largest first, then rows without a count (most postings). A
  // row value is never true for a null, so a cursor among the counted rows
  // reaches the uncounted ones through a second arm; SQLite merges the two
  // arms in order (MERGE (UNION ALL)) without sorting either.
  if (!c || c.date === undefined) {
    return finish({ sql: `SELECT ${COLUMNS} FROM search_rows${w.sql}${tail}`, params: w.params });
  }
  if (c.positions === null || c.positions === undefined) {
    w.add(`${p}positions IS NULL AND (${p}sort_date, ${p}key) < (?, ?)`, c.date, c.key);
    return finish({ sql: `SELECT ${COLUMNS} FROM search_rows${w.sql}${tail}`, params: w.params });
  }
  if (small) {
    w.add("((+positions, +sort_date, +key) < (?, ?, ?) OR +positions IS NULL)", c.positions, c.date, c.key);
    return finish({ sql: `SELECT ${COLUMNS} FROM search_rows${w.sql}${tail}`, params: w.params });
  }
  // The second arm repeats the first's filters, so both refer to the same
  // numbered values (?1, ?2, ...) and the statement binds them once.
  w.add("(positions, sort_date, key) < (?, ?, ?)", c.positions, c.date, c.key);
  const uncounted = where();
  uncounted.add("positions IS NULL");
  return finish({
    sql: `SELECT ${COLUMNS} FROM search_rows${numbered(w.sql)} UNION ALL SELECT ${COLUMNS} FROM search_rows${numbered(uncounted.sql)}` +
      ` ORDER BY ${ORDER.positions.join(", ")} LIMIT ${FETCH_ROWS}`,
    params: w.params,
  });
}

// Each ? as ?1, ?2, ... in order. The fragments here hold no ? but the
// placeholders, and the filters come first in both arms, so their numbers
// agree.
function numbered(sql: string): string {
  let n = 0;
  return sql.replace(/\?/g, () => `?${++n}`);
}

// The index a count reads through: the plan's own when it has one, else the
// text index when there is text (its rows stream in and the count stops at
// COUNT_CAP + 1 that pass), else the index-backed filter that lists the
// fewest rows. Every row read through it passes that filter, so the count
// reaches its cap or the end sooner than a scan would.
export function countDriver(q: SearchQuery, plan: Plan, sizes: Partial<Record<Driver, number>>, match = matchExpression(q)): Driver | null {
  if (plan.mode !== "ordered") return plan.driver;
  if (match) return "fts";
  let best: Driver | null = null;
  for (const d of drivers(q, match, sizes.ind !== undefined)) {
    if (best === null || (sizes[d] ?? Infinity) < (sizes[best] ?? Infinity)) best = d;
  }
  return best;
}

// The total for a first page that neither counts.json nor the text probe
// answers, and whose page came back full: at most COUNT_CAP + 1 matching
// rows are counted.
export function buildCount(q: SearchQuery, opts: CountOptions = {}): BuiltSql {
  const driver = opts.driver ?? null;
  const dataDate = opts.dataDate ?? new Date().toISOString().slice(0, 10);
  const cap = ` LIMIT ${COUNT_CAP + 1})`;
  if (driver === "fts") {
    // From the text index, row by row: CROSS JOIN keeps search_fts the outer
    // loop, and every search_rows column is checked with a plus, so the
    // planner cannot turn this into a text lookup per row.
    const w = filters(q, null, dataDate, "none", opts.indValues, opts.latestPeriod);
    const others = w.parts.length ? ` AND ${w.parts.join(" AND ")}` : "";
    return finish({
      sql: `SELECT COUNT(1) AS n FROM (SELECT search_rows.rid FROM search_fts CROSS JOIN search_rows ON search_rows.rid = search_fts.rowid ` +
        `WHERE search_fts MATCH ?${others}${cap}`,
      params: [matchExpression(q), ...w.params],
    });
  }
  const w = filters(q, driver === "ind" && !opts.indValues?.length ? null : driver, dataDate, "residual", opts.indValues,
    opts.latestPeriod);
  // The year's sort-date bounds, bare: the newest, status and province
  // indexes all hold sort_date next, so a year range narrows any of them.
  const { from, to } = yearBounds(q);
  if (from) w.add("sort_date >= ?", from);
  if (to) w.add("sort_date < ?", to);
  if (q.date === "last_quarter") w.add("sort_date >= ?", lastQuarterFrom(dataDate, opts.latestPeriod));
  return finish({ sql: `SELECT COUNT(1) AS n FROM (SELECT rid FROM search_rows${w.sql}${cap}`, params: w.params });
}

// How many rows each index-backed filter would list, capped: the text probe
// at COUNT_CAP + 1 (it is a text-only query's total), the others at
// SMALL_SET + 1 (all the planner needs to know). Each reads an index and
// nothing else. withDims: also the status, province and year filters, which
// counts.json sizes when it is there.
export function buildProbes(q: SearchQuery, match = matchExpression(q), withDims = false): { driver: Driver; built: BuiltSql }[] {
  const out: { driver: Driver; built: BuiltSql }[] = [];
  const probe = (driver: Driver, fill: (w: Where) => void) => {
    const w = new Where();
    fill(w);
    out.push({ driver, built: { sql: `SELECT COUNT(1) AS n FROM (SELECT 1 FROM search_rows${w.sql} LIMIT ${SMALL_SET + 1})`, params: w.params } });
  };
  if (match) {
    out.push({ driver: "fts", built: { sql: `SELECT COUNT(1) AS n FROM (${FTS_ROWIDS} LIMIT ${COUNT_CAP + 1})`, params: [match] } });
  }
  if (q.nocCode) probe("noc", (w) => nocPredicate(w, q, "noc"));
  if (impliesPosting(q)) probe("kind", (w) => w.add("kind = 'posting'"));
  if (withDims) {
    if (statusFilter(q).length) probe("status", (w) => statusPredicate(w, q, "status"));
    if (q.province.length) probe("prov", (w) => provPredicate(w, q, "prov"));
    if (q.yearFrom !== null || q.yearTo !== null) probe("year", (w) => yearPredicate(w, q, "year"));
    if (q.stream.length) {
      const spellings = q.stream.flatMap((s) => STREAMS[s] ?? []);
      probe("stream", (w) => w.add(`stream IN (${marks(spellings.length)})`, ...spellings));
    }
  }
  return out;
}

// -- counts.json -------------------------------------------------------------

export interface Facets {
  status: Record<string, number>;
  prov: Record<string, number>;
}

type Dim = "status" | "prov" | "stream" | "year" | "ind";

// Per dimension, which of counts.json's values a query's filter accepts
// (null: no filter on it).
function acceptors(counts: SearchCounts, q: SearchQuery): Record<Dim, boolean[] | null> {
  const v = counts.values;
  const status = statusFilter(q);
  const spellings = new Set(q.stream.flatMap((s) => STREAMS[s] ?? []));
  return {
    status: status.length ? v.status.map((s) => (status as string[]).includes(s)) : null,
    prov: q.province.length ? v.prov.map((s) => q.province.includes(s ?? UNKNOWN_PROVINCE)) : null,
    stream: q.stream.length ? v.stream.map((s) => s !== null && spellings.has(s)) : null,
    year: q.yearFrom !== null || q.yearTo !== null
      ? v.year.map((y) => y !== null && (q.yearFrom === null || y >= q.yearFrom) && (q.yearTo === null || y <= q.yearTo))
      : null,
    ind: q.indicator ? v.ind.map((s) => s.split(",").includes(q.indicator as string)) : null,
  };
}

const DIMS: Dim[] = ["status", "prov", "stream", "year", "ind"];

// True when counts.json answers the request's total: no filter outside its
// dimensions.
export function countsAnswer(q: SearchQuery, match = matchExpression(q)): boolean {
  return !match && !q.nocCode && q.wageMin === null && q.wageMax === null && q.date === "any";
}

// The exact total, and the facet counts the search page shows beside its
// status and province boxes (each counted with every other filter applied).
export function countsFor(counts: SearchCounts, q: SearchQuery): { total: number; facets: Facets } {
  const acc = acceptors(counts, q);
  const passes = (cell: number[], skip: Dim | null): boolean =>
    DIMS.every((d, i) => d === skip || acc[d] === null || (acc[d] as boolean[])[cell[i]]);
  let total = 0;
  const status: Record<string, number> = {};
  const prov: Record<string, number> = {};
  const provinces = new Set<string>(PROVINCES);
  for (const cell of counts.cells) {
    const n = cell[5];
    if (passes(cell, null)) total += n;
    if (passes(cell, "status")) {
      const s = counts.values.status[cell[0]];
      status[s] = (status[s] ?? 0) + n;
    }
    if (passes(cell, "prov")) {
      // Only the codes the filter offers: a province the source wrote some
      // other way still counts in the total, under no box.
      const key = counts.values.prov[cell[1]] ?? UNKNOWN_PROVINCE;
      if (provinces.has(key)) prov[key] = (prov[key] ?? 0) + n;
    }
  }
  return { total, facets: { status, prov } };
}

// Rows each index-backed dimension filter would list on its own: what the
// planner compares with SMALL_SET.
export function dimensionSizes(counts: SearchCounts, q: SearchQuery): Partial<Record<Driver, number>> {
  const acc = acceptors(counts, q);
  const out: Partial<Record<Driver, number>> = {};
  const pairs: [Driver, number][] = [["status", 0], ["prov", 1], ["stream", 2], ["year", 3], ["ind", 4]];
  for (const [driver, i] of pairs) {
    const ok = acc[DIMS[i]];
    if (ok === null) continue;
    out[driver] = counts.cells.reduce((sum, cell) => sum + (ok[cell[i]] ? cell[5] : 0), 0);
  }
  return out;
}

// -- running -----------------------------------------------------------------

export interface SearchResult {
  rows: SearchRow[];
  // null on a later page that counts.json and the FTS probe cannot answer:
  // the first page carried the total, and counting again would read the
  // same rows again.
  total: number | null;
  capped: boolean;
  facets?: Facets;
  next?: string;
}

// For tests and the step report: what a request read.
export interface SearchTrace {
  plan?: Plan;
  statements: number;
  rowsRead: number;
  // Rows read by each statement, in the order of sql.
  reads?: number[];
  sql: string[];
}

const str = (v: unknown): string => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));
const strOrNull = (v: unknown): string | null => (v === null || v === undefined ? null : String(v));
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function toRow(r: Record<string, unknown>): SearchRow {
  return {
    kind: r.kind === "posting" ? "posting" : "esdc",
    ref: Number(r.ref),
    employer_id: str(r.employer_id),
    employer: str(r.employer),
    job: strOrNull(r.job),
    noc: strOrNull(r.noc),
    street: strOrNull(r.street),
    city: strOrNull(r.city),
    prov: strOrNull(r.prov),
    postal: strOrNull(r.postal),
    wage_min: numOrNull(r.wage_min),
    wage_max: numOrNull(r.wage_max),
    unit: strOrNull(r.unit),
    date: strOrNull(r.date),
    period: strOrNull(r.period),
    positions: numOrNull(r.positions),
    status: str(r.status),
    stream: strOrNull(r.stream),
    source: str(r.source),
    sort_date: str(r.sort_date),
    ind: typeof r.ind === "string" && r.ind ? r.ind.split(",") : [],
  };
}

function cursorAfter(sort: Sort, r: Record<string, unknown>): Cursor {
  const key = str(r.key);
  if (sort === "name") return { sort, key, name: str(r.name_fold) };
  if (sort === "positions") return { sort, key, date: str(r.sort_date), positions: numOrNull(r.positions) };
  return { sort, key, date: str(r.sort_date) };
}

// What a failure is, in words that cannot carry a request value: a D1 or
// SQLite code and a few fixed phrases. An FTS5 error quotes the expression,
// which is built from the visitor's text, so its message is never logged.
const KNOWN_FAULTS = ["no such table", "no such index", "no such column", "syntax error", "too many", "interrupted", "timeout",
  "locked", "overloaded", "reset"];

export function faultSummary(e: unknown): string {
  const s = String(e);
  const code = /SQLITE_[A-Z_]+/.exec(s)?.[0] ?? /D1_[A-Z_]+/.exec(s)?.[0] ?? "no code";
  const phrase = KNOWN_FAULTS.find((k) => s.toLowerCase().includes(k)) ?? "other";
  return `${code}, ${phrase}`;
}

type Stmt = { driver?: Driver; built: BuiltSql };

async function batch(db: D1Database, stmts: Stmt[], trace?: SearchTrace): Promise<D1Result<Record<string, unknown>>[]> {
  const results = await db.batch<Record<string, unknown>>(stmts.map((s) => db.prepare(s.built.sql).bind(...s.built.params)));
  if (trace) {
    trace.statements += stmts.length;
    trace.sql.push(...stmts.map((s) => s.built.sql));
    for (const r of results) {
      const n = Number(r.meta?.rows_read ?? 0);
      trace.rowsRead += n;
      trace.reads?.push(n);
    }
  }
  return results;
}

const firstCount = (r: D1Result<Record<string, unknown>> | undefined): number => Number(r?.results?.[0]?.n ?? 0);

export interface RunOptions {
  trace?: SearchTrace;
  // Tests only: run this plan instead of the one choosePlan picks, so every
  // shape of query can be walked.
  plan?: Plan;
}

// The latest list period, for date=last_quarter when counts.json (which
// carries it as latest_period) is missing: the period of the newest list row,
// read backwards through the newest index past the postings (about 4,500 on
// the full data). Null when the table holds no list row.
export const LATEST_PERIOD_SQL = "SELECT period FROM search_rows WHERE +kind <> 'posting' ORDER BY sort_date DESC, key DESC LIMIT 1";

async function latestListPeriod(db: D1Database, trace?: SearchTrace): Promise<string | null> {
  const res = (await batch(db, [{ built: { sql: LATEST_PERIOD_SQL, params: [] } }], trace))[0];
  const period = res?.results?.[0]?.period;
  return typeof period === "string" && period ? period : null;
}

// The search, or null when the database is missing or a query failed (the
// route answers 503; the page falls back to its static files).
export async function runSearch(env: Env, q: SearchQuery, dataDate: string, counts: SearchCounts | null = null,
  opts: RunOptions = {}): Promise<SearchResult | null> {
  const db = env.SEARCH;
  if (!db) return null;
  const trace = opts.trace;
  try {
    const match = matchExpression(q);
    const dims = counts ? countsFor(counts, q) : null;
    const fromCounts = dims && countsAnswer(q, match) ? dims : null;
    // No row passes the status, province, stream, year and indicator filters,
    // so no other filter can add one: the answer needs no database read.
    if (dims && dims.total === 0 && !opts.plan) {
      const empty: SearchResult = { rows: [], total: 0, capped: false };
      if (fromCounts) empty.facets = fromCounts.facets;
      return empty;
    }
    const indValues = indicatorSets(counts, q);
    const latestPeriod = q.date === "last_quarter" ? (counts ? counts.latest_period : await latestListPeriod(db, trace)) : null;
    const sizes: Partial<Record<Driver, number>> = counts ? dimensionSizes(counts, q) : {};
    // Without counts.json the status, province, stream and year filters are
    // sized by probes too, each reading at most SMALL_SET + 1 index entries.
    const probes = buildProbes(q, match, !counts);
    if (probes.length) {
      const res = await batch(db, probes, trace);
      probes.forEach((p, i) => {
        sizes[p.driver as Driver] = firstCount(res[i]);
      });
    }
    const shape: Shape | undefined = counts && dims ? { total: counts.total, matching: dims.total } : undefined;
    const plan = opts.plan ?? choosePlan(q, sizes, match, shape);
    if (trace) trace.plan = plan;

    // A text query with nothing else: the probe counted it.
    const textOnly = !!match && drivers(q, match).length === 1 && !q.stream.length && !q.indicator && q.date === "any";
    let total: number | null = fromCounts ? fromCounts.total : null;
    let capped = false;
    if (!fromCounts && textOnly) {
      const n = sizes.fts ?? 0;
      total = Math.min(n, COUNT_CAP);
      capped = n > COUNT_CAP;
    }
    const raw = (await batch(db, [{ built: buildSelect(q, { plan, dataDate, indValues, latestPeriod }) }], trace))[0]?.results ?? [];
    if (total === null && !q.cursor) {
      if (raw.length <= PAGE_SIZE) {
        // The first page holds every match: that is the total, and the count,
        // which for a rare match is the most expensive statement, is skipped.
        total = raw.length;
      } else {
        const built = buildCount(q, { driver: countDriver(q, plan, sizes, match), dataDate, indValues, latestPeriod });
        const n = firstCount((await batch(db, [{ built }], trace))[0]);
        total = Math.min(n, COUNT_CAP);
        capped = n > COUNT_CAP;
      }
    }
    const result: SearchResult = { rows: raw.slice(0, PAGE_SIZE).map(toRow), total, capped };
    if (fromCounts) result.facets = fromCounts.facets;
    if (raw.length > PAGE_SIZE) result.next = encodeCursor(cursorAfter(q.sort, raw[PAGE_SIZE - 1]));
    return result;
  } catch (e) {
    console.error(`search: query failed (${faultSummary(e)})`);
    return null;
  }
}
