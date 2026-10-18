import { Hono, type Context } from "hono";
import { assetResponse, loadProfile, type SearchRow } from "./data";
import type { AppEnv } from "./env";

// Every endpoint is a view over the static JSON files, so the API costs no
// database reads. Pass-through responses keep the asset's body as is.
export const api = new Hono<AppEnv>();

api.use("*", async (c, next) => {
  await next();
  c.res.headers.set("Cache-Control", "public, max-age=300");
});

async function passThrough(c: Context<AppEnv>, path: string): Promise<Response> {
  const res = await assetResponse(c.env, path);
  if (!res) return c.json({ error: "not published yet" }, 503);
  return new Response(res.body, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

api.get("/stats", (c) => passThrough(c, "stats.json"));

api.get("/employers/:id", async (c) => {
  const profile = await loadProfile(c.env, c.req.param("id") ?? "");
  if (!profile) return c.json({ error: "not found" }, 404);
  return c.json(profile);
});

// The pending list is about 2 MB, and parsing it, or even decoding it to
// text, would use most of a request's CPU allowance on the free plan. The
// pipeline writes it newest first by sort_date, which for a posting is the
// date this filter compares (the posting date, or the day it was first
// seen), with sorted keys and no spaces, so every row opens with {"city":
// and the rows asked for are a prefix of the file. The reply is that prefix
// of the file's bytes; a file in any other shape is parsed instead.
const bytesOf = (s: string) => new TextEncoder().encode(s);
const FILE_START = bytesOf('[{"city":');
const ROW_GAP = bytesOf('},{"city":');
const SORT_KEY = bytesOf('"sort_date":"');
const SORT_KEY_UNDERSCORE = 5; // where the key's one "_" sits, a byte rarer than a quote to search for
const CLOSE_BRACE = 0x7d;
type Part = Uint8Array | string;
const UNDERSCORE = 0x5f;

function at(bytes: Uint8Array, i: number, pattern: Uint8Array): boolean {
  if (i < 0 || i + pattern.length > bytes.length) return false;
  for (let j = 0; j < pattern.length; j++) if (bytes[i + j] !== pattern[j]) return false;
  return true;
}

function filterParsed(bytes: Uint8Array, since: string | null): Part[] | null {
  try {
    const rows = JSON.parse(new TextDecoder().decode(bytes)) as SearchRow[];
    if (!Array.isArray(rows)) return null;
    return [JSON.stringify(since ? rows.filter((r) => (r.date ?? r.sort_date) >= since) : rows)];
  } catch {
    return null;
  }
}

// The results array, as parts of a Blob: every row when since is null, else
// the rows dated on or after it. Null when the file is not a JSON array.
export function pendingResults(bytes: Uint8Array, since: string | null): Part[] | null {
  const n = bytes.length;
  if (n === 2 && bytes[0] === 0x5b && bytes[1] === 0x5d) return ["[]"];
  if (!at(bytes, 0, FILE_START) || bytes[n - 1] !== 0x5d || bytes[n - 2] !== CLOSE_BRACE) return filterParsed(bytes, since);
  if (since === null) return [bytes];
  // Row bounds: a row ends at the "}" of the separator. A "}" inside a value
  // cannot be followed by ,{"city": since a quote inside a string is escaped.
  const starts = [1];
  const ends: number[] = [];
  for (let i = bytes.indexOf(CLOSE_BRACE, 1); i !== -1; i = bytes.indexOf(CLOSE_BRACE, i + 1)) {
    if (at(bytes, i, ROW_GAP)) {
      ends.push(i + 1);
      starts.push(i + 2);
    }
  }
  ends.push(n - 1);
  const dateOf = (row: number): string | null => {
    let key = bytes.indexOf(UNDERSCORE, starts[row]);
    while (key !== -1 && key < ends[row] && !at(bytes, key - SORT_KEY_UNDERSCORE, SORT_KEY)) key = bytes.indexOf(UNDERSCORE, key + 1);
    if (key < 0 || key >= ends[row]) return null;
    const from = key - SORT_KEY_UNDERSCORE + SORT_KEY.length;
    return String.fromCharCode(...bytes.subarray(from, from + 10));
  };
  // Dates fall row by row, so the first row older than since is found by halving.
  let lo = 0;
  let hi = starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const date = dateOf(mid);
    if (date === null) return filterParsed(bytes, since);
    if (date < since) hi = mid;
    else lo = mid + 1;
  }
  return lo === 0 ? ["[]"] : [bytes.subarray(0, ends[lo - 1]), "]"];
}

api.get("/pending", async (c) => {
  const asked = c.req.query("since") ?? "";
  const since = /^\d{4}-\d{2}-\d{2}$/.test(asked) ? asked : null;
  const res = await assetResponse(c.env, "search/latest/status/pending.json");
  const results = res ? pendingResults(new Uint8Array(await res.arrayBuffer()), since) : null;
  if (results === null) return c.json({ error: "not published yet" }, 503);
  return new Response(new Blob([`{"since":${JSON.stringify(since ?? "1970-01-01")},"results":`, ...results, "}"]), {
    status: 200,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
});

api.get("/search/facets", (c) => passThrough(c, "search/facets.json"));

api.get("/clusters", (c) => {
  const scope = c.req.query("scope") === "since_2023q4" ? "since_2023q4" : "latest";
  return passThrough(c, `clusters/${scope}.json`);
});

api.get("/area/:fsa", async (c) => {
  const fsa = (c.req.param("fsa") ?? "").toUpperCase().slice(0, 3);
  if (!/^[A-Z]\d[A-Z]$/.test(fsa)) return c.json({ error: "bad fsa" }, 400);
  const res = await assetResponse(c.env, `areas/${fsa}.json`);
  if (!res) return c.json({ error: "no records in this area" }, 404);
  return new Response(res.body, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8" } });
});
