import type { Context } from "hono";
import type { AppEnv } from "./env";

// The donation page (Ko-fi) sends one notice per payment as a form post whose
// `data` field holds a JSON document. The document carries the donor's name,
// email and message as well as the amount; only the amount, time, kind and
// transaction id are kept, so the site never holds a supporter's identity.
// The notice is accepted only when its verification token matches the one
// in the Worker secret, and a repeated notice for the same transaction is
// ignored, which makes Ko-fi's retries harmless.

export type DonationNotice = {
  transactionId: string;
  receivedAt: string; // ISO 8601
  kind: string; // Donation, Subscription, Shop Order, Commission
  amountCents: number;
  currency: string; // ISO 4217
  recurring: boolean;
  firstPayment: boolean;
};

const KIND_MAX = 40;

// Constant-time comparison so a wrong token takes as long as a right one.
export function tokensMatch(given: string, expected: string): boolean {
  const a = new TextEncoder().encode(given);
  const b = new TextEncoder().encode(expected);
  if (a.length !== b.length || a.length === 0) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

// Reads the fields the ledger needs out of a notice; null when the notice is
// not a payment the ledger can count. Everything else in the document is
// left behind here and never reaches storage.
export function parseNotice(doc: unknown): DonationNotice | null {
  if (!doc || typeof doc !== "object") return null;
  const d = doc as Record<string, unknown>;
  const transactionId = typeof d.kofi_transaction_id === "string" ? d.kofi_transaction_id.trim() : "";
  if (!transactionId || transactionId.length > 100) return null;
  const amount = typeof d.amount === "string" || typeof d.amount === "number" ? Number(d.amount) : NaN;
  if (!Number.isFinite(amount) || amount < 0 || amount > 1_000_000) return null;
  const currency = typeof d.currency === "string" ? d.currency.trim().toUpperCase() : "";
  if (!/^[A-Z]{3}$/.test(currency)) return null;
  const when = typeof d.timestamp === "string" ? new Date(d.timestamp) : new Date(NaN);
  const receivedAt = Number.isNaN(when.getTime()) ? new Date().toISOString() : when.toISOString();
  const kind = (typeof d.type === "string" ? d.type.trim() : "Donation").slice(0, KIND_MAX) || "Donation";
  return {
    transactionId,
    receivedAt,
    kind,
    amountCents: Math.round(amount * 100),
    currency,
    recurring: d.is_subscription_payment === true,
    firstPayment: d.is_first_subscription_payment === true,
  };
}

export async function storeNotice(db: D1Database, n: DonationNotice): Promise<boolean> {
  const result = await db
    .prepare(
      "INSERT OR IGNORE INTO donations (transaction_id, received_at, kind, amount_cents, currency, recurring, first_payment, created_at) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(n.transactionId, n.receivedAt, n.kind, n.amountCents, n.currency, n.recurring ? 1 : 0, n.firstPayment ? 1 : 0, new Date().toISOString())
    .run();
  return (result.meta?.changes ?? 0) > 0;
}

export async function kofiWebhook(c: Context<AppEnv>): Promise<Response> {
  const expected = (c.env.KOFI_VERIFICATION_TOKEN ?? "").trim();
  if (!expected) return c.text("Webhook not configured", 503);

  let doc: unknown;
  try {
    const body = (await c.req.parseBody()) as Record<string, unknown>;
    const raw = body.data;
    if (typeof raw !== "string" || raw.length > 20_000) return c.text("Bad request", 400);
    doc = JSON.parse(raw);
  } catch {
    return c.text("Bad request", 400);
  }

  const token = doc && typeof doc === "object" ? (doc as Record<string, unknown>).verification_token : undefined;
  if (typeof token !== "string" || !tokensMatch(token, expected)) return c.text("Forbidden", 403);

  const notice = parseNotice(doc);
  if (!notice) return c.text("Ignored", 200);
  await storeNotice(c.env.DB, notice);
  return c.text("ok", 200);
}
