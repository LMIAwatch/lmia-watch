import { Hono, type Context } from "hono";
import { assetResponse, loadJson, loadProfile, type SearchRow } from "./data";
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

api.get("/pending", async (c) => {
  const since = /^\d{4}-\d{2}-\d{2}$/.test(c.req.query("since") ?? "") ? (c.req.query("since") as string) : "1970-01-01";
  const rows = await loadJson<SearchRow[]>(c.env, "search/latest/status/pending.json");
  if (!rows) return c.json({ error: "not published yet" }, 503);
  return c.json({ since, results: rows.filter((r) => (r.date ?? r.sort_date) >= since) });
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
