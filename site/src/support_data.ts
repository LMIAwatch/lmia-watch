// The support page's live figures, computed from the stored payment notices.
// Received is what the notices add up to; spent is the known monthly cost
// times the months that have started; the reserve is the difference, never
// shown below zero (a shortfall is paid by the person who runs the site).

import { COSTS_TODAY_CENTS, SITE_START, TARGET_CENTS_PER_MONTH, USD_TO_CAD } from "./support";

export type LedgerRow = {
  quarter: string; // "2026 Q4"
  monthlyCostCents: number;
  receivedCents: number;
  spentCents: number;
  reserveCents: number; // cumulative, after this quarter
};

export type SupportFigures = {
  monthlySupportCents: number; // received in the last 30 days
  totalReceivedCents: number;
  totalSpentCents: number;
  reserveCents: number;
  reserveMonths: number; // whole months of the full monthly cost held
  donations: number;
  ledger: LedgerRow[];
};

type Row = { received_at: string; amount_cents: number; currency: string };

const DAY_MS = 24 * 60 * 60 * 1000;

// Notices arrive in the payment page's currency. Canadian dollars count as
// given, US dollars at the page's planning rate, anything else at face value.
export function toCadCents(cents: number, currency: string): number {
  if (currency === "USD") return Math.round(cents * USD_TO_CAD);
  return cents;
}

export function quarterOf(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCFullYear()} Q${Math.floor(d.getUTCMonth() / 3) + 1}`;
}

// Every quarter from the site's first month through `now`, in order.
export function quartersSince(start: string, now: Date): string[] {
  const out: string[] = [];
  const s = new Date(start);
  let y = s.getUTCFullYear();
  let q = Math.floor(s.getUTCMonth() / 3);
  const endY = now.getUTCFullYear();
  const endQ = Math.floor(now.getUTCMonth() / 3);
  while (y < endY || (y === endY && q <= endQ)) {
    out.push(`${y} Q${q + 1}`);
    q += 1;
    if (q === 4) {
      q = 0;
      y += 1;
    }
  }
  return out;
}

// Months of a quarter that have started by `now`, counting from the site's
// first month; 0 to 3.
export function monthsStarted(quarter: string, start: string, now: Date): number {
  const [yText, qText] = quarter.split(" Q");
  const y = Number(yText);
  const q0 = (Number(qText) - 1) * 3;
  const s = new Date(start);
  let n = 0;
  for (let m = 0; m < 3; m++) {
    const monthStart = Date.UTC(y, q0 + m, 1);
    if (monthStart <= now.getTime() && monthStart >= Date.UTC(s.getUTCFullYear(), s.getUTCMonth(), 1)) n += 1;
  }
  return n;
}

export function computeFigures(rows: Row[], now: Date, start: string = SITE_START): SupportFigures {
  const since = now.getTime() - 30 * DAY_MS;
  let monthly = 0;
  const byQuarter = new Map<string, number>();
  for (const r of rows) {
    const cad = toCadCents(r.amount_cents, r.currency);
    const t = new Date(r.received_at).getTime();
    if (t >= since && t <= now.getTime() + DAY_MS) monthly += cad;
    const q = quarterOf(r.received_at);
    byQuarter.set(q, (byQuarter.get(q) ?? 0) + cad);
  }
  let received = 0;
  let spent = 0;
  const ledger: LedgerRow[] = quartersSince(start, now).map((quarter) => {
    const receivedCents = byQuarter.get(quarter) ?? 0;
    // The Workers Paid plan inside COSTS_TODAY_CENTS began part way through
    // the site's first month and bills a full month from its start day, so
    // that month carries it in full, as the invoice does.
    const spentCents = COSTS_TODAY_CENTS * monthsStarted(quarter, start, now);
    received += receivedCents;
    spent += spentCents;
    return { quarter, monthlyCostCents: COSTS_TODAY_CENTS, receivedCents, spentCents, reserveCents: Math.max(0, received - spent) };
  });
  const reserveCents = Math.max(0, received - spent);
  return {
    monthlySupportCents: monthly,
    totalReceivedCents: received,
    totalSpentCents: spent,
    reserveCents,
    reserveMonths: TARGET_CENTS_PER_MONTH > 0 ? Math.floor(reserveCents / TARGET_CENTS_PER_MONTH) : 0,
    donations: rows.length,
    ledger,
  };
}

// The page must render even before the table exists, so a storage failure
// reads as no donations rather than an error page.
export async function loadSupport(db: D1Database | undefined, now: Date = new Date()): Promise<SupportFigures> {
  let rows: Row[] = [];
  if (db) {
    try {
      const res = await db
        .prepare("SELECT received_at, amount_cents, currency FROM donations WHERE received_at >= ? ORDER BY received_at")
        .bind(SITE_START)
        .all<Row>();
      rows = res.results ?? [];
    } catch {
      rows = [];
    }
  }
  return computeFigures(rows, now);
}
