import type { Env } from "./env";
import { loadStats } from "./data";

// A daily check, run by the cron trigger, that emails the operator when the
// site needs a hand: data that stopped refreshing, a backup that stopped
// arriving, a refresh whose stages failed, or a daily post that X refused.
// It reads only what the nightly run leaves behind (the stats file, the
// backup's timestamp, status.json in R2), so a run that never happened is
// caught as well as one that failed. Sending goes through Cloudflare's email
// binding to a destination verified in the zone's Email Routing; with no
// binding or no address the check still runs and only logs.

export const DATA_STALE_HOURS = 36;
export const BACKUP_STALE_HOURS = 36;
const HOUR = 60 * 60 * 1000;

export type RunStatus = {
  run_at?: string;
  ok?: boolean;
  x_post?: string;
  stages?: { source: string; ok: boolean; detail?: string }[];
};

export type Inputs = {
  now: Date;
  dataAsOf: string | null; // YYYY-MM-DD from stats.json, or null when missing
  backupUploaded: Date | null; // lmia.sqlite.gz uploaded time in R2
  status: RunStatus | null; // status.json from R2
};

export function collectAlerts(i: Inputs): string[] {
  const out: string[] = [];
  if (!i.dataAsOf) {
    out.push("The site has no data file (stats.json is missing): the pages show Data Not Published Yet.");
  } else {
    const age = (i.now.getTime() - Date.parse(`${i.dataAsOf}T00:00:00Z`)) / HOUR;
    if (age > DATA_STALE_HOURS + 24) {
      out.push(`The data is dated ${i.dataAsOf}, ${Math.floor(age / 24)} days old: the nightly refresh has not published since.`);
    }
  }
  if (!i.backupUploaded) {
    out.push("No database backup (lmia.sqlite.gz) is in R2.");
  } else if ((i.now.getTime() - i.backupUploaded.getTime()) / HOUR > BACKUP_STALE_HOURS) {
    out.push(`The database backup in R2 was last saved ${i.backupUploaded.toISOString().slice(0, 16)} UTC, more than ${BACKUP_STALE_HOURS} hours ago.`);
  }
  if (!i.status) {
    out.push("No run status (status.json) is in R2: the nightly workflow has not completed a run with the current version.");
  } else {
    if (i.status.run_at && (i.now.getTime() - Date.parse(i.status.run_at)) / HOUR > DATA_STALE_HOURS) {
      out.push(`The last completed run was ${i.status.run_at.slice(0, 16)} UTC.`);
    }
    for (const s of i.status.stages ?? []) {
      if (!s.ok) out.push(`Stage "${s.source}" failed in the last run${s.detail ? `: ${s.detail.slice(0, 160)}` : ""}.`);
    }
    if (i.status.x_post === "failed" || i.status.x_post === "no credentials") {
      out.push(`The daily X post did not go out (${i.status.x_post}). Check the credits in the X developer console and the run log.`);
    }
  }
  return out;
}

export function buildEmail(from: string, to: string, alerts: string[], now: Date): string {
  const subject = `LMIA Watch: ${alerts.length} item${alerts.length === 1 ? "" : "s"} need attention`;
  const lines = [
    `Daily check at ${now.toISOString().slice(0, 16)} UTC found:`,
    "",
    ...alerts.map((a, n) => `${n + 1}. ${a}`),
    "",
    "Run log: https://github.com/LMIAwatch/lmia-watch/actions",
    "Site: https://lmiawatch.ca/data",
    "",
    "This message is sent by the site's own daily check; it repeats each day while an item remains.",
  ];
  return [
    `From: LMIA Watch <${from}>`,
    `To: ${to}`,
    `Subject: ${subject}`,
    `Date: ${now.toUTCString()}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "",
    ...lines,
  ].join("\r\n");
}

export async function gatherInputs(env: Env, now: Date): Promise<Inputs> {
  const stats = await loadStats(env).catch(() => null);
  let backupUploaded: Date | null = null;
  let status: RunStatus | null = null;
  if (env.DATA) {
    try {
      const head = await env.DATA.head("lmia.sqlite.gz");
      backupUploaded = head ? head.uploaded : null;
    } catch {
      backupUploaded = null;
    }
    try {
      const obj = await env.DATA.get("status.json");
      status = obj ? ((await obj.json()) as RunStatus) : null;
    } catch {
      status = null;
    }
  }
  return { now, dataAsOf: stats?.data_as_of ?? null, backupUploaded, status };
}

export async function runWatchdog(env: Env, now: Date = new Date()): Promise<{ alerts: string[]; sent: boolean; error?: string }> {
  const alerts = collectAlerts(await gatherInputs(env, now));
  if (alerts.length === 0) return { alerts, sent: false };
  const to = (env.ALERT_EMAIL ?? "").trim();
  const from = (env.ALERT_FROM ?? "").trim();
  if (!env.ALERTS || !to || !from) {
    console.log(`watchdog: ${alerts.length} alert(s), no email binding or address configured`);
    return { alerts, sent: false };
  }
  try {
    const { EmailMessage } = await import("cloudflare:email");
    await env.ALERTS.send(new EmailMessage(from, to, buildEmail(from, to, alerts, now)));
    console.log(`watchdog: ${alerts.length} alert(s), email sent`);
    return { alerts, sent: true };
  } catch (e) {
    console.log(`watchdog: ${alerts.length} alert(s), email failed: ${String(e).slice(0, 200)}`);
    return { alerts, sent: false, error: String(e).slice(0, 300) };
  }
}
