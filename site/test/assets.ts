// A stand-in for the static assets binding: serves the JSON fixtures under
// /data/ the way the deployed Worker reads the pipeline's export.
import { env } from "cloudflare:test";
import aliases from "./fixtures/aliases-a00.json";
import area from "./fixtures/area-V0N.json";
import clusters from "./fixtures/clusters-latest.json";
import facets from "./fixtures/facets.json";
import profiles from "./fixtures/profiles-a00.json";
import program from "./fixtures/program-index.json";
import latest from "./fixtures/search-latest.json";
import sitemapPart from "./fixtures/sitemap-1.xml?raw";
import sitemapIndex from "./fixtures/sitemap-index.xml?raw";
import stats from "./fixtures/stats.json";

// The sitemaps are XML, served as written rather than as JSON.
const TEXT_FILES: Record<string, string> = {
  "sitemaps/index.xml": sitemapIndex,
  "sitemaps/sitemap-1.xml": sitemapPart,
};

const FILES: Record<string, unknown> = {
  "stats.json": stats,
  "search/first.json": latest,
  "search/facets.json": facets,
  // The export's other search files: the pending list /api/pending serves.
  // The search page reads the search database (test/search_page.test.ts).
  "search/latest/status/pending.json": latest.filter((r) => r.status === "pending"),
  "clusters/latest.json": clusters,
  "clusters/since_2023q4.json": clusters,
  "areas/V0N.json": area,
  "profiles/a00.json": profiles,
  // Retired ids whose shard key (characters 5 to 7 of the old id) is a00, each
  // pointing at a live id in the profile shard above.
  "aliases/a00.json": aliases,
  // The program conditions (/program), written by the pipeline's export.
  "program/index.json": program,
};

export const fakeAssets = {
  fetch: async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = new URL(url).pathname.replace(/^\/data\//, "");
    const text = TEXT_FILES[path];
    if (text !== undefined) return new Response(text, { headers: { "content-type": "application/xml" } });
    const file = FILES[path];
    if (file === undefined) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(file), { headers: { "content-type": "application/json" } });
  },
} as unknown as Fetcher;

export const emptyAssets = {
  fetch: async () => new Response("not found", { status: 404 }),
} as unknown as Fetcher;

export function testEnv(assets: Fetcher = fakeAssets) {
  return { ...(env as object), ASSETS: assets } as typeof env & { ASSETS: Fetcher };
}
