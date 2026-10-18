import type { Context } from "hono";
import type { AppEnv } from "./env";

// Form posts are read here rather than with parseBody so a body can never be
// larger than the forms could produce. The platform accepts request bodies of
// up to 100 MB; parsing one that size would spend the request's CPU allowance
// and could exhaust the isolate's memory, failing other visitors' requests on
// the same isolate. A browser-sent form here is a few kilobytes.
export const FORM_MAX_BYTES = 64 * 1024;

export type FormResult = { ok: true; fields: Record<string, string> } | { ok: false; status: 400 | 413 };

async function readCapped(body: ReadableStream<Uint8Array> | null, max: number): Promise<Uint8Array | null> {
  if (!body) return new Uint8Array(0);
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

// The first value of each text field. A body that is too large answers 413;
// one that is not a form (wrong content type, a multipart body without its
// boundary, broken encoding) answers 400.
export async function readForm(c: Context<AppEnv>, max: number = FORM_MAX_BYTES): Promise<FormResult> {
  const declared = Number(c.req.header("content-length") ?? "");
  if (Number.isFinite(declared) && declared > max) return { ok: false, status: 413 };
  let bytes: Uint8Array | null;
  try {
    bytes = await readCapped(c.req.raw.body, max);
  } catch {
    return { ok: false, status: 400 };
  }
  if (bytes === null) return { ok: false, status: 413 };
  const type = c.req.header("content-type") ?? "";
  if (!/^(application\/x-www-form-urlencoded|multipart\/form-data)\b/i.test(type)) return { ok: false, status: 400 };
  try {
    const form = await new Request("https://form.invalid/", { method: "POST", headers: { "content-type": type }, body: bytes }).formData();
    const fields: Record<string, string> = {};
    form.forEach((value, key) => {
      if (typeof value === "string" && !(key in fields)) fields[key] = value;
    });
    return { ok: true, fields };
  } catch {
    return { ok: false, status: 400 };
  }
}
