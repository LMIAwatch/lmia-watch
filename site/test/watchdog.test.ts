import { describe, expect, it } from "vitest";
import { buildEmail, collectAlerts, gatherInputs, readStatus, runWatchdog } from "../src/watchdog";
import { testEnv } from "./assets";

const now = new Date("2026-10-20T06:00:00Z");
const healthy = {
  now,
  dataAsOf: "2026-10-20",
  backupUploaded: new Date("2026-10-20T00:50:00Z"),
  status: { run_at: "2026-10-20T00:48:00Z", ok: true, x_post: "posted", stages: [{ source: "jobbank", ok: true }, { source: "esdc", ok: true }] },
};

describe("daily check", () => {
  it("finds nothing wrong on a healthy morning", () => {
    expect(collectAlerts(healthy)).toEqual([]);
  });

  it("flags stale data, a stale or missing backup, a missing status, failed stages and a refused post", () => {
    expect(collectAlerts({ ...healthy, dataAsOf: "2026-10-16" })[0]).toContain("4 days old");
    expect(collectAlerts({ ...healthy, dataAsOf: null })[0]).toContain("no data file");
    expect(collectAlerts({ ...healthy, backupUploaded: new Date("2026-10-18T00:50:00Z") })[0]).toContain("more than 36 hours");
    expect(collectAlerts({ ...healthy, backupUploaded: null })[0]).toContain("No database backup");
    expect(collectAlerts({ ...healthy, status: null })[0]).toContain("No run status");
    const failed = collectAlerts({ ...healthy, status: { ...healthy.status, stages: [{ source: "jobbank", ok: false, detail: "HTTP 503" }] } });
    expect(failed).toEqual(['Stage "jobbank" failed in the last run: HTTP 503.']);
    expect(collectAlerts({ ...healthy, status: { ...healthy.status, x_post: "failed" } })[0]).toContain("daily X post did not go out (failed)");
    expect(collectAlerts({ ...healthy, status: { ...healthy.status, x_post: "no new postings" } })).toEqual([]);
    expect(collectAlerts({ ...healthy, status: { ...healthy.status, run_at: "2026-10-17T00:48:00Z" } })[0]).toContain("last completed run was 2026-10-17");
  });

  it("flags a refused Bluesky post and a failed Zenodo deposit, and nothing else they report", () => {
    const with_ = (extra: object) => collectAlerts({ ...healthy, status: { ...healthy.status, ...extra } });
    expect(with_({ bluesky_post: "failed" })).toEqual([
      "The daily Bluesky post did not go out (failed). Check the app password in the BSKY_APP_PASSWORD secret and the run log.",
    ]);
    expect(with_({ bluesky_post: "no credentials" })[0]).toContain("Bluesky post did not go out (no credentials)");
    expect(with_({ zenodo_deposit: "failed" })).toEqual([
      "The Zenodo deposit of the new ESDC quarter failed. The next run tries again; check the ZENODO_TOKEN secret and the run log.",
    ]);
    for (const quiet of ["posted", "already posted", "no new postings", "first pass", "bulk pass", "not run", "dry run"]) {
      expect(with_({ bluesky_post: quiet }), quiet).toEqual([]);
    }
    for (const quiet of ["deposited", "no new quarter", "no token", "no data", "not run"]) {
      expect(with_({ zenodo_deposit: quiet }), quiet).toEqual([]);
    }
    const all = with_({ x_post: "failed", bluesky_post: "failed", zenodo_deposit: "failed" });
    expect(all).toHaveLength(3);
  });

  it("flags a failed search sync, a failed roll-up and a rolled-back deploy, and nothing else they report", () => {
    const with_ = (extra: object) => collectAlerts({ ...healthy, status: { ...healthy.status, ...extra } });
    expect(with_({ search_sync: "failed" })).toEqual([
      "The search database sync failed. The next run sends the same changes again; check the run log.",
    ]);
    expect(with_({ views_rollup: "failed" })).toEqual([
      "The audience roll-up failed. The next run catches up; check the CLOUDFLARE_ANALYTICS_TOKEN secret and the run log.",
    ]);
    expect(with_({ deploy_rolled_back: true })).toEqual([
      "The site answered with server errors after the last deploy, so the run rolled the Worker back to the version before it. The site shows the previous data until a later run deploys again; check the run log.",
    ]);
    for (const quiet of ["synced", "nothing to send", "not run"]) {
      expect(with_({ search_sync: quiet }), quiet).toEqual([]);
    }
    for (const quiet of ["rolled up", "no data", "no token", "not run"]) {
      expect(with_({ views_rollup: quiet }), quiet).toEqual([]);
    }
    expect(with_({ deploy_rolled_back: false })).toEqual([]);
    expect(with_({ search_sync: "failed", views_rollup: "failed", deploy_rolled_back: true })).toHaveLength(3);
  });

  it("reads the resilience fields from status.json and drops them when they have the wrong type", () => {
    const fields = { search_sync: "failed", views_rollup: "rolled up", deploy_rolled_back: true };
    const read = readStatus({ ...healthy.status, ...fields, smoke: "broken", checks: { due: false } });
    expect(read).toEqual({ status: { ...healthy.status, ...fields }, problem: null });
    expect(collectAlerts({ ...healthy, status: read.status })).toHaveLength(2);
    // "true" as text, or a number, is not a rollback.
    const odd = readStatus({ ...healthy.status, search_sync: 0, views_rollup: ["failed"], deploy_rolled_back: "true" });
    expect(odd).toEqual({ status: healthy.status, problem: null });
    expect(collectAlerts({ ...healthy, status: odd.status })).toEqual([]);
  });

  it("reads the new status fields and ignores them when they have the wrong type", () => {
    const read = readStatus({ ...healthy.status, bluesky_post: "posted", zenodo_deposit: "failed" });
    expect(read).toEqual({ status: { ...healthy.status, bluesky_post: "posted", zenodo_deposit: "failed" }, problem: null });
    const odd = readStatus({ ...healthy.status, bluesky_post: 1, zenodo_deposit: { x: 1 } });
    expect(odd.problem).toBeNull();
    expect(odd.status).toEqual(healthy.status);
    // A status written before these fields existed stays healthy.
    expect(collectAlerts({ ...healthy, status: readStatus(healthy.status).status })).toEqual([]);
  });

  it("builds a plain-text email that names every item", () => {
    const raw = buildEmail("alerts@lmiawatch.ca", "owner@example.com", ["one thing", "another"], now);
    expect(raw).toContain("From: LMIA Watch <alerts@lmiawatch.ca>\r\nTo: owner@example.com\r\nSubject: LMIA Watch: 2 items need attention");
    expect(raw).toContain("Content-Type: text/plain; charset=utf-8\r\n\r\nDaily check at 2026-10-20T06:00 UTC found:");
    expect(raw).toContain("1. one thing\r\n2. another");
    expect(raw).toContain("https://github.com/LMIAwatch/lmia-watch/actions");
    expect(buildEmail("a@b.ca", "c@d.ca", ["x"], now)).toContain("1 item need attention");
  });
});

describe("daily check against a status file of unexpected shape", () => {
  it("reads a well-formed status unchanged", () => {
    expect(readStatus(healthy.status)).toEqual({ status: healthy.status, problem: null });
  });

  it("turns every odd shape into an alert, never an exception", () => {
    for (const raw of [null, [], "text", 42, true]) {
      const { status, problem } = readStatus(raw);
      expect(status).toBeNull();
      expect(problem).toContain("not a JSON object");
    }
    const odd = readStatus({ run_at: 1760000000, stages: { jobbank: true }, x_post: 3 });
    expect(odd.problem).toContain("run_at, stages");
    const alerts = collectAlerts({ ...healthy, status: odd.status, statusProblem: odd.problem });
    expect(alerts).toEqual(["The run status (status.json) in R2 has unreadable fields (run_at, stages)."]);
    const chars = readStatus({ run_at: "2026-10-20T00:48:00Z", stages: "ok" });
    expect(chars.problem).toContain("stages");
    expect(collectAlerts({ ...healthy, status: chars.status, statusProblem: chars.problem })).toHaveLength(1);
  });

  it("counts an unreadable stage entry as a failed stage", () => {
    const { status, problem } = readStatus({
      run_at: "2026-10-20T00:48:00Z",
      stages: [null, "x", { source: 5, ok: "yes", detail: { long: true } }, { source: "esdc", ok: true }],
    });
    expect(problem).toBeNull();
    expect(collectAlerts({ ...healthy, status })).toEqual([
      'Stage "unknown" failed in the last run: unreadable stage entry.',
      'Stage "unknown" failed in the last run: unreadable stage entry.',
      'Stage "unknown" failed in the last run.',
    ]);
  });

  it("flags a data date that is not a date", () => {
    expect(collectAlerts({ ...healthy, dataAsOf: "yesterday" })).toEqual(["The data date in stats.json (yesterday) is not a date."]);
  });

  it("gathers from a bucket that returns junk or fails", async () => {
    const bucket = (statusBody: string | null, headFails = false) =>
      ({
        head: async () => {
          if (headFails) throw new Error("R2 down");
          return { uploaded: new Date("2026-10-20T00:50:00Z") };
        },
        get: async () => (statusBody === null ? null : { text: async () => statusBody }),
      }) as unknown as R2Bucket;
    const base = testEnv();
    const junk = await gatherInputs({ ...base, DATA: bucket("{not json") }, now);
    expect(junk.status).toBeNull();
    expect(junk.statusProblem).toContain("could not be read");
    expect(collectAlerts(junk).join(" ")).toContain("could not be read");
    const down = await gatherInputs({ ...base, DATA: bucket(JSON.stringify(healthy.status), true) }, now);
    expect(down.statusProblem).toContain("The data bucket (R2) could not be read");
    const shapes = await runWatchdog({ ...base, DATA: bucket('{"stages":{"a":1}}') }, now);
    expect(shapes.sent).toBe(false);
    expect(shapes.alerts.join(" ")).toContain("unreadable fields (run_at, stages)");
  });
});
