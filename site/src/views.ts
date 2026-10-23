import type { Context, Next } from "hono";
import type { AppEnv } from "./env";
import { DOWNLOADS } from "./pages/data";

// Aggregate counts of what the Worker serves, written to Workers Analytics
// Engine (the VIEWS binding in wrangler.jsonc): one data point per response,
// holding the route template, the kind of request, the page language, the
// country code Cloudflare's edge attaches, the referring site's host name and
// the status code. Nothing that identifies a visitor is written: no address,
// no user agent, no cookie, no full referrer, and no raw path (a mistyped or
// pasted URL could carry anything, so a path that matches no route is stored
// as "other"). No script runs in the browser for this.
//
// The Atom feeds are the one static file counted: wrangler.jsonc runs the
// Worker first for /data/feeds/*, so a feed reader's poll passes through
// here. Its point also holds the feed's file name (only when the file was
// served, so a typed path is never stored) and the subscriber count the
// reader states in its user agent; that number is the only thing taken from
// the user agent, which is never written.
//
// Other static files under /data/ and /fonts/ never reach the Worker, and a
// request the per-address limits answer with 429 stops before this
// middleware, so neither is counted. The plan's included data points match
// its included requests (100,000 a day on the free plan, 10 million a month
// on the paid one), so one point per response cannot exceed them. Data
// points are kept for three months; the nightly run keeps a daily roll-up in
// R2 (pipeline/lmia_pipeline/views_rollup.py).

export type Kind = "page" | "api" | "download" | "form" | "hook" | "file" | "feed" | "other";

const PAGES = new Set([
  "/", "/search", "/map", "/methodology", "/data", "/support", "/corrections",
  "/feeds", "/watchlist", "/releases", "/rankings", "/trends", "/occupations", "/places",
]);
const API_FIXED = new Set(["/api/stats", "/api/pending", "/api/clusters", "/api/search", "/api/search/facets"]);
const DOWNLOAD_FILES = new Set(DOWNLOADS.map((d) => d.file));
// The feed files feeds.py writes: feeds/<scope folders>/<event>.xml.
const FEED_PATH = /^\/data\/(feeds\/[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*\.xml)$/;

export function routeTemplate(method: string, path: string): { route: string; kind: Kind } {
  if (PAGES.has(path)) return { route: path, kind: method === "POST" ? "form" : "page" };
  if (/^\/employers\/[^/]+$/.test(path)) return { route: "/employers/:id", kind: "page" };
  if (/^\/employers\/[^/]+\/respond$/.test(path)) return { route: "/employers/:id/respond", kind: method === "POST" ? "form" : "page" };
  if (/^\/releases\/[^/]+$/.test(path)) return { route: "/releases/:slug", kind: "page" };
  if (/^\/rankings\/[^/]+$/.test(path)) return { route: "/rankings/:year", kind: "page" };
  if (/^\/trends\/[^/]+$/.test(path)) return { route: "/trends/:view", kind: "page" };
  if (/^\/occupations\/[^/]+$/.test(path)) return { route: "/occupations/:noc", kind: "page" };
  if (/^\/places\/[^/]+$/.test(path)) return { route: "/places/:prov", kind: "page" };
  if (/^\/places\/[^/]+\/[^/]+$/.test(path)) return { route: "/places/:prov/:slug", kind: "page" };
  if (path.startsWith("/api/")) {
    if (API_FIXED.has(path)) return { route: path, kind: "api" };
    if (/^\/api\/employers\/[^/]+$/.test(path)) return { route: "/api/employers/:id", kind: "api" };
    if (/^\/api\/area\/[^/]+$/.test(path)) return { route: "/api/area/:fsa", kind: "api" };
    return { route: "/api/other", kind: "api" };
  }
  if (path.startsWith("/downloads/")) {
    const file = path.slice("/downloads/".length);
    if (DOWNLOAD_FILES.has(file)) return { route: path, kind: "download" };
    if (/^mirror\/[A-Za-z0-9._-]+$/.test(file)) return { route: "/downloads/mirror/:file", kind: "download" };
    return { route: "/downloads/other", kind: "download" };
  }
  if (FEED_PATH.test(path)) return { route: "/data/feeds/:file", kind: "feed" };
  if (path === "/data/feeds/index.json") return { route: path, kind: "file" };
  if (path === "/hooks/kofi") return { route: path, kind: "hook" };
  if (path === "/robots.txt") return { route: path, kind: "file" };
  if (/^\/sitemap(?:-[0-9]+)?\.xml$/.test(path)) return { route: "/sitemap.xml", kind: "file" };
  return { route: "other", kind: "other" };
}

// The host name of an http(s) referrer, lower case, and nothing else: no
// path, no query, no port. Anything else is "".
export function referrerHost(header: string | undefined | null): string {
  if (!header) return "";
  try {
    const url = new URL(header);
    if (url.protocol !== "https:" && url.protocol !== "http:") return "";
    const host = url.hostname.toLowerCase();
    return /^[a-z0-9.-]{1,100}$/.test(host) ? host : "";
  } catch {
    return "";
  }
}

export function countryCode(value: unknown): string {
  return typeof value === "string" && /^[A-Z0-9]{2}$/.test(value) ? value : "";
}

// Readers that poll a feed for many people say how many in their user agent:
// "Feedly/1.0 (+https://feedly.com/poller.html; 12 subscribers; like
// FeedFetcher-Google)", "inoreader.com; 9 subscribers". Only the number before
// the word is read; 0 when there is none. The cap keeps a forged header from
// writing an absurd figure.
export function subscriberCount(userAgent: string | undefined | null): number {
  if (!userAgent) return 0;
  const m = /(?:^|[^0-9])([0-9]{1,9})\s+subscribers?\b/i.exec(userAgent.slice(0, 512));
  return m ? Number(m[1]) : 0;
}

// The feed's path under /data/, kept only when the file was served (200, or
// 304 to a reader that already has it): the file names are the pipeline's,
// while a path that found no file could hold whatever was typed.
export function feedFile(path: string, status: number): string {
  if (status !== 200 && status !== 304) return "";
  const m = FEED_PATH.exec(path);
  return m && m[1].length <= 120 ? m[1] : "";
}

export function viewPoint(c: Context<AppEnv>): AnalyticsEngineDataPoint {
  const { route, kind } = routeTemplate(c.req.method, c.req.path);
  const cf = (c.req.raw as Request & { cf?: { country?: unknown } }).cf;
  const lang = c.get("lang") === "fr" ? "fr" : "en";
  const blobs = [route, kind, lang, countryCode(cf?.country), referrerHost(c.req.header("referer")), c.req.method.slice(0, 8)];
  const doubles = [c.res.status];
  if (kind === "feed") {
    // blob7 and double2; every other point leaves them empty (read back as "" and 0).
    blobs.push(feedFile(c.req.path, c.res.status));
    doubles.push(subscriberCount(c.req.header("user-agent")));
  }
  return { indexes: [route], blobs, doubles };
}

export function recordView(c: Context<AppEnv>): void {
  const dataset = c.env.VIEWS;
  if (!dataset) return; // tests and local development have no binding
  try {
    dataset.writeDataPoint(viewPoint(c));
  } catch (e) {
    // A counting fault must never cost a reader the page.
    console.error(`views: ${String(e).slice(0, 200)}`);
  }
}

export async function measure(c: Context<AppEnv>, next: Next): Promise<void> {
  try {
    await next();
  } finally {
    recordView(c);
  }
}
