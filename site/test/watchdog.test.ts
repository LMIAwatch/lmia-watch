import { describe, expect, it } from "vitest";
import { buildEmail, collectAlerts } from "../src/watchdog";

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

  it("builds a plain-text email that names every item", () => {
    const raw = buildEmail("alerts@lmiawatch.ca", "owner@example.com", ["one thing", "another"], now);
    expect(raw).toContain("From: LMIA Watch <alerts@lmiawatch.ca>\r\nTo: owner@example.com\r\nSubject: LMIA Watch: 2 items need attention");
    expect(raw).toContain("Content-Type: text/plain; charset=utf-8\r\n\r\nDaily check at 2026-10-20T06:00 UTC found:");
    expect(raw).toContain("1. one thing\r\n2. another");
    expect(raw).toContain("https://github.com/LMIAwatch/lmia-watch/actions");
    expect(buildEmail("a@b.ca", "c@d.ca", ["x"], now)).toContain("1 item need attention");
  });
});
