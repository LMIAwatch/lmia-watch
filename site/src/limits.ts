import type { Context, Next } from "hono";
import type { AppEnv, Env } from "./env";
import { t } from "./i18n";

// Which cap a request falls under. The API and the downloads get their own
// because a script can hammer them without ever looking like a visitor; form
// posts get the tightest because each one writes to the database; everything
// else (pages) gets a cap no reader reaches. Static files are served before
// the Worker runs and never arrive here.
export type Bucket = "page" | "api" | "download" | "form";

export function bucketFor(method: string, path: string): Bucket {
  if (path.startsWith("/api/")) return "api";
  if (path.startsWith("/downloads/")) return "download";
  if (method === "POST" && (path === "/corrections" || /^\/employers\/[^/]+\/respond$/.test(path))) return "form";
  return "page";
}

const BINDING: Record<Bucket, keyof Env> = {
  page: "PAGE_LIMIT", api: "API_LIMIT", download: "DOWNLOAD_LIMIT", form: "FORM_LIMIT",
};

// The address Cloudflare saw. The edge sets this header itself and drops any
// copy a client sends, so it cannot be spoofed from outside.
export function clientKey(c: Context<AppEnv>): string {
  return c.req.header("cf-connecting-ip") ?? "unknown";
}

export async function throttle(c: Context<AppEnv>, next: Next): Promise<Response | void> {
  const bucket = bucketFor(c.req.method, c.req.path);
  const limiter = c.env[BINDING[bucket]] as RateLimit | undefined;
  if (!limiter) return next();
  let allowed = true;
  try {
    allowed = (await limiter.limit({ key: `${bucket}:${clientKey(c)}` })).success;
  } catch {
    allowed = true; // a limiter fault must never take the site down
  }
  if (allowed) return next();
  c.header("Retry-After", "60");
  c.header("Cache-Control", "no-store");
  const lang = c.get("lang") ?? "en";
  if (bucket === "api") {
    return c.json({ error: t(lang, "limits.too_many_api") }, 429);
  }
  return c.text(t(lang, "limits.too_many"), 429);
}
