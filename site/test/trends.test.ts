// The trends page and its views against fixture JSON copied from the
// pipeline's export of the live database (pipeline/lmia_pipeline/trends.py),
// and the chart helpers on their own.
import { describe, expect, it } from "vitest";
import { dayPos, markerRows, niceTicks, quarterPos, yearAxis } from "../src/chart";
import { app } from "../src/index";
import { DESCRIPTION_MAX } from "../src/seo";
import { emptyAssets, fakeAssets, testEnv } from "./assets";
import national from "./fixtures/trends-national.json";
import pending from "./fixtures/trends-pending.json";
import provinces from "./fixtures/trends-provinces.json";
import streams from "./fixtures/trends-streams.json";

// 300 nights, for the long-series checks.
function longSeries(n: number) {
  const points = Array.from({ length: n }, (_, i) => ({
    date: new Date(Date.UTC(2026, 9, 18) + i * 86_400_000).toISOString().slice(0, 10),
    n: 4000 + ((i * 37) % 600),
  }));
  return { points, first: points[0].date, latest: points[points.length - 1].date };
}

function assetsWith(files: Record<string, unknown>): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path in files) {
        const file = files[path];
        if (file === undefined) return new Response("not found", { status: 404 });
        return new Response(JSON.stringify(file), { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input as RequestInfo);
    },
  } as unknown as Fetcher;
}

const FILES = {
  "trends/national.json": national,
  "trends/streams.json": streams,
  "trends/provinces.json": provinces,
  "trends/pending.json": pending,
};
const assets = assetsWith(FILES);

const get = (path: string, env: object = testEnv(assets)) => app.request(path, {}, env);
const html = async (path: string, env?: object) => (await get(path, env)).text();
const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const decode = (s: string) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const text = (page: string) => nbsp(decode(page.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]+>/g, " ")).replace(/\s+/g, " "));
const head = (page: string) => page.slice(0, page.indexOf("</head>"));
const jsonLd = (page: string): any[] =>
  [...page.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]));

const VIEWS = ["/trends", "/trends/streams", "/trends/provinces", "/trends/pending"];
const ESDC_VIEWS = VIEWS.slice(0, 3);

describe("chart helpers", () => {
  it("place dates on a quarter axis", () => {
    expect(quarterPos("2024-01-01")).toBe(2024 * 4);
    expect(quarterPos("2024-04-01")).toBe(2024 * 4 + 1);
    expect(quarterPos("2024-02-15")).toBeCloseTo(2024 * 4 + 45 / 91, 6);
    // A quarter's last day ends where the next quarter begins.
    expect(quarterPos("2024-03-31", true)).toBe(2024 * 4 + 1);
    expect(quarterPos("2024-12-31", true)).toBe(2025 * 4);
    // The 2014 file, June 20 to December 31: a little over two quarters.
    expect(quarterPos("2015-01-01") - quarterPos("2014-06-20")).toBeCloseTo(2 + 11 / 91, 6);
    expect(dayPos("2026-10-19") - dayPos("2026-10-18")).toBe(1);
  });

  it("pick round gridlines that reach the largest value", () => {
    expect(niceTicks(51328)).toEqual([0, 20000, 40000, 60000]);
    expect(niceTicks(4327)).toEqual([0, 2000, 4000, 6000]);
    expect(niceTicks(3)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(0)).toEqual([0, 1]);
    for (const max of [7, 95, 1234, 88888, 250000]) {
      const ticks = niceTicks(max);
      expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(max);
      expect(ticks.every(Number.isInteger)).toBe(true);
    }
  });

  it("stagger marker numbers that would touch", () => {
    const rows = markerRows([{ x: 10, n: 1 }, { x: 10.2, n: 2 }, { x: 13, n: 3 }], [0, 20]);
    expect(rows.map((r) => r.row)).toEqual([0, 1, 0]);
  });

  it("label each year once, at the middle of its part of the axis", () => {
    const axis = yearAxis([quarterPos("2014-06-20"), quarterPos("2026-04-01")]);
    expect(axis.labels.map((l) => l.text)).toEqual(Array.from({ length: 13 }, (_, i) => String(2014 + i)));
    expect(axis.labels.at(-1)?.x).toBeCloseTo(2026 * 4 + 0.5, 6);
    expect(axis.labels.at(-1)?.minor).toBe(false);
    expect(axis.grid[0]).toBe(2015 * 4);
  });
});

describe("all of Canada", () => {
  it("states the year-over-year comparisons in sentences above the charts", async () => {
    const page = await html("/trends");
    const body = text(page);
    expect(page).toContain("<h1>LMIA Trends Since 2014</h1>");
    expect(body).toContain(
      "In 2026 Q1, 33,215 positions were approved on 8,789 rows of ESDC's positive list, against 51,328 on 17,952 rows in 2025 Q1, the same quarter a year earlier (down 35.3 percent).",
    );
    expect(body).toContain("Employers with an approval: 7,880, against 14,906 (down 47.1 percent).");
    expect(body).toContain("Rows on the negative list (refusals): 3,008 in 2026 Q1, against 2,634 in 2025 Q1 (up 14.2 percent).");
    expect(body).toContain("So far 2026 has only its first quarter, so the year to date is the comparison above.");
    expect(body).toContain("In 2025, 164,643 positions were approved on 54,240 rows, against 228,869 on 87,264 rows in 2024 (down 28.1 percent).");
    expect(body).toContain("Refused rows: 9,211, against 4,657 (up 97.8 percent).");
    // The sentences come before the first chart.
    expect(page.indexOf("Year over Year")).toBeLessThan(page.indexOf("<svg viewBox=\"0 0 1000"));
  });

  it("carries the three caveats, the caution block and the uneven early files", async () => {
    const body = text(await html("/trends"));
    expect(body).toContain("Streams exist only from 2017: the 2014 to 2016 files have no stream column, so the view by stream starts with the 2017 Q1 to Q2 file.");
    expect(body).toContain("The 2016 to 2019 files became complete here on 2026-10-19");
    expect(body).toContain("Occupation series break at 2024 Q2: from that file ESDC codes occupations in NOC 2021 instead of NOC 2011");
    expect(body).toContain("The 2014 file covers June 20 to December 31, 2014");
    expect(body).toContain("ESDC published no negative list for 2021 Q2, so the refusals for it are left blank rather than shown as zero.");
    expect(body).toContain("Positions on approved LMIAs are not workers who arrived.");
    expect(body).toContain("Large farms, packers and health authorities lead these tables by design");
    expect(body).not.toMatch(/\b(abuse|abusers?|fraud\w*|violat\w*|offenders?|worst|cheat\w*|wrongdoers?)\b/i);
  });

  it("draws each file as a bar, the long early files lighter, with the rule changes numbered in date order", async () => {
    const page = await html("/trends");
    // Three panels per file chart plus the calendar-year chart.
    expect(page.match(/<svg viewBox="0 0 1000/g)?.length).toBe(4);
    expect(page.match(/role="img"/g)?.length).toBe(4);
    expect(page).toContain('aria-label="Positions approved. Bar chart; the table under the chart gives every figure."');
    // 39 files on three panels, less 2021 Q2 on the refused panel.
    expect(page.match(/<rect class="bar(?: bar-light)?"/g)?.length).toBe(39 * 3 - 1 + 13);
    expect(page).toContain("<title>2015: 82,683 (20,671 per quarter over 4 quarters)</title>");
    expect(page).toContain("<title>2014: 24,429 (11,518 per quarter over 2.1 quarters)</title>");
    expect(page).toContain("<title>2026 Q1: 33,215</title>");
    const list = page.slice(page.indexOf('<ol class="rule-list">'), page.indexOf("</ol>", page.indexOf('<ol class="rule-list">')));
    const labels = [...list.matchAll(/<li value="(\d)"><strong class="nw">([^<]+)<\/strong>/g)].map((m) => [m[1], m[2]]);
    expect(labels).toEqual([["1", "2022-04-04"], ["2", "2024 Q2"], ["3", "2024-05-01"], ["4", "2024-09-26"], ["5", "2024-11-08"]]);
    expect(list).toContain('href="https://www.canada.ca/en/employment-social-development/news/2024/08/minister-boissonnault-reducing-the-number-of-temporary-foreign-workers-in-canada.html"');
    expect(list).toContain('href="https://open.canada.ca/data/en/dataset/90fed587-1364-4f33-a9ee-208181dc0b97"');
    // Five dashed lines on each of the four panels, and five numbers over each chart.
    expect(page.match(/<line class="mark"/g)?.length).toBe(5 * 4);
    expect(page.match(/<div class="chart-marks"/g)?.length).toBe(2);
  });

  it("puts every figure in a table under its chart, each file linked to its release", async () => {
    const page = await html("/trends");
    expect(page).toContain('<a href="/releases/2026-q1">2026 Q1</a>');
    expect(page).toContain('<a href="/releases/2017-q1-q2">2017 Q1 to Q2</a>');
    expect(page).toContain('<a href="/rankings/2025">2025</a>');
    const body = text(page);
    expect(body).toContain("2021 Q2 1 21,813 8,168 7,320 n/a");
    expect(body).toContain("2014 June 20 to December 31 24,429 3,978 3,971 1,300");
    expect(body).toContain("2026 To 2026 Q1 33,215 8,789 7,880 3,008");
    expect(body).toContain("2025 Full year 164,643 54,240 37,227 9,211");
  });

  it("reads in French with French numbers and periods", async () => {
    const page = await html("/trends?lang=fr");
    const body = text(page);
    expect(page).toContain('<html lang="fr">');
    expect(body).toContain("Au T1 2026, 33 215 postes ont été approuvés sur 8 789 inscriptions de la liste positive d’EDSC, contre 51 328 sur 17 952 inscriptions au T1 2025, le même trimestre un an plus tôt (en baisse de 35,3 %).");
    expect(body).toContain("Les volets n’existent qu’à partir de 2017");
    expect(body).toContain("Les séries par profession sont rompues au T2 2024");
    expect(body).toContain("Les postes visés par des EIMT approuvées ne sont pas des travailleurs arrivés.");
    expect(page).toContain('href="https://www.canada.ca/fr/emploi-developpement-social/nouvelles/2024/08/le-ministre-boissonnault-agit-pour-reduire-le-nombre-de-travailleurs-etrangers-temporaires-au-canada.html"');
    expect(page).toContain('href="https://open.canada.ca/data/fr/dataset/90fed587-1364-4f33-a9ee-208181dc0b97"');
    expect(page).toContain('<strong class="nw">T2 2024</strong>');
  });
});

describe("by stream and by province", () => {
  it("compares each stream's latest quarter with the same quarter a year earlier", async () => {
    const page = await html("/trends/streams");
    // The years ESDC published no Permanent Resident Only rows are named as a gap in the files.
    expect(page).toContain("no Permanent Resident Only rows in the files from 2017 Q4 to 2023 Q3");
    const body = text(page);
    expect(page).toContain("<h1>LMIA Trends by Stream</h1>");
    expect(body).toContain("2026 Q1 Against 2025 Q1");
    expect(body).toContain("Primary Agriculture 20,158 18,402 −1,756 −8.7");
    expect(body).toContain("Low Wage 15,652 8,008 −7,644 −48.8");
    expect(body).toContain("All streams 51,328 33,215 −18,113 −35.3");
    // One panel per stream, the series starting with the first file that has a stream. ESDC's
    // stray "Unspecified" (one position in all) would fill a panel of its own scale, so it
    // stays in the tables, and a stream with nothing in either quarter has no comparison row.
    expect(page.match(/<svg viewBox="0 0 1000/g)?.length).toBe(streams.keys.length - 1);
    expect(body).toContain("Other or unspecified: under 0.1 percent of the positions, so in the tables only.");
    expect(body).not.toContain("Other or unspecified 0 0 0");
    expect(page).toContain(">Permanent Resident Only</div>");
    expect(body).toContain("Positions approved in each stream, from the 2017 Q1 to Q2 file, the first to carry a stream column.");
    expect(page).not.toContain('href="/releases/2016"');
    expect(page).toContain("<summary>Refused rows by stream</summary>");
    expect(body).toContain("Each panel has its own scale.");
  });

  it("adds the no-stream column to each table only when a file has such rows", async () => {
    const withMissing = JSON.parse(JSON.stringify(streams));
    withMissing.periods[0].missing = 5;
    withMissing.periods[0].refused_missing = 2;
    const page = await html("/trends/streams", testEnv(assetsWith({ ...FILES, "trends/streams.json": withMissing })));
    expect(page.match(/<th class="num">No stream<\/th>/g)?.length).toBe(2);
    const body = text(page);
    expect(body).toContain("2017 Q1 to Q2 30,349 7,353 9,056 10 724 0 5 47,497");
    expect(body).toContain("2017 Q1 to Q2 188 701 715 0 236 0 2 1,842");
    expect((await html("/trends/streams")).match(/No stream/g)).toBeNull();
  });

  it("draws the provinces in two stacks and names each code", async () => {
    const page = await html("/trends/provinces");
    const body = text(page);
    expect(page).toContain("<h1>LMIA Trends by Province</h1>");
    expect(page.match(/<div class="chart-stack"/g)?.length).toBe(2);
    expect(page.match(/<svg viewBox="0 0 1000/g)?.length).toBe(provinces.keys.length);
    expect(page).toContain('<abbr title="Ontario">ON</abbr>');
    expect(page).toContain('<abbr title="Head office outside Canada">XX</abbr>');
    expect(body).toContain("Columns use the two-letter codes; XX is a head office outside Canada.");
    expect(body).toMatch(/Ontario [\d,]+ [\d,]+ [−+]?[\d,]+ [−+]?\d+\.\d/);
  });
});

describe("Job Bank pending, night by night", () => {
  it("reads well with the first three complete passes", async () => {
    const page = await html("/trends/pending");
    const body = text(page);
    expect(body).toContain("Latest complete pass, 2026-10-20: 4,327 postings, against 4,234 on 2026-10-19 (up 2.2 percent).");
    expect(body).toContain("The series began on 2026-10-18 with the first complete pass and gains a point each night.");
    expect(body).toContain("kept since 2026-10-18");
    // A dot per point while the series is short, a label under each night, and the table newest first.
    expect(page.match(/<line class="dot"/g)?.length).toBe(3);
    expect(page.match(/<polyline class="line"/g)?.length).toBe(1);
    expect(body).toContain("Oct 18");
    expect(body).toMatch(/2026-10-20 4,327 \+93 2026-10-19 4,234 −45 2026-10-18 4,279/);
    expect(page).toContain('href="/search?status=pending"');
    expect(body).toContain("A pass counts when it ran to the end without a failed request");
  });

  it("reads well with three hundred", async () => {
    const page = await html("/trends/pending", testEnv(assetsWith({ ...FILES, "trends/pending.json": longSeries(300) })));
    expect(page.match(/<line class="dot"/g)).toBeNull();
    expect(page.match(/<polyline class="line"/g)?.length).toBe(1);
    // Month labels, every other one dropped on a phone.
    expect(text(page)).toContain("Nov 2026");
    expect(page).toMatch(/class="x-minor"/);
    expect(page.match(/<tr>/g)?.length).toBe(301);
  });

  it("calls a change too small for one decimal about the same", async () => {
    const two = { points: [{ date: "2026-10-22", n: 4362 }, { date: "2026-10-23", n: 4361 }], first: "2026-10-22", latest: "2026-10-23" };
    const page = await html("/trends/pending", testEnv(assetsWith({ ...FILES, "trends/pending.json": two })));
    expect(text(page)).toContain("Latest complete pass, 2026-10-23: 4,361 postings, against 4,362 on 2026-10-22 (about the same).");
    expect(text(await html("/trends/pending?lang=fr", testEnv(assetsWith({ ...FILES, "trends/pending.json": two }))))).toContain("(à peu près inchangé)");
  });

  it("starts with a single point", async () => {
    const one = { points: [{ date: "2026-10-18", n: 4279 }], first: "2026-10-18", latest: "2026-10-18" };
    const page = await html("/trends/pending", testEnv(assetsWith({ ...FILES, "trends/pending.json": one })));
    expect(text(page)).toContain("First complete pass, 2026-10-18: 4,279 postings.");
    expect(page.match(/<line class="dot"/g)?.length).toBe(1);
  });
});

describe("every trends view", () => {
  it("has a title, a short description, canonical and language links, and breadcrumbs", async () => {
    const expected: Record<string, [string, string[]]> = {
      "/trends": ["LMIA Trends Since 2014: Approvals and Refusals by Quarter | LMIA Watch", ["Home", "Trends"]],
      "/trends/streams": ["LMIA Approvals by Stream Since 2017 | LMIA Watch", ["Home", "Trends", "By stream"]],
      "/trends/provinces": ["LMIA Approvals by Province Since 2014 | LMIA Watch", ["Home", "Trends", "By province"]],
      "/trends/pending": ["Job Bank Postings Flagged LMIA Requested, Nightly Count | LMIA Watch", ["Home", "Trends", "Job Bank pending, nightly"]],
    };
    for (const [path, [title, crumbs]] of Object.entries(expected)) {
      for (const lang of ["en", "fr"] as const) {
        const page = await html(lang === "fr" ? `${path}?lang=fr` : path);
        const h = head(page);
        const url = `https://lmiawatch.ca${path}`;
        if (lang === "en") expect(decode(h.match(/<title>([^<]*)<\/title>/)?.[1] ?? ""), path).toBe(title);
        const description = decode(h.match(/<meta name="description" content="([^"]*)"/)?.[1] ?? "");
        expect(description.length, `${path} ${lang}`).toBeGreaterThan(50);
        expect(description.length, `${path} ${lang}`).toBeLessThanOrEqual(DESCRIPTION_MAX);
        expect(h).toContain(`<link rel="canonical" href="${lang === "fr" ? `${url}?lang=fr` : url}"`);
        expect(h).toContain(`<link rel="alternate" hreflang="fr" href="${url}?lang=fr"`);
        expect(h).toContain(`<link rel="alternate" hreflang="x-default" href="${url}"`);
        const crumbList = jsonLd(h).find((d) => d["@type"] === "BreadcrumbList");
        if (lang === "en") expect(crumbList.itemListElement.map((i: any) => i.name), path).toEqual(crumbs);
        expect(crumbList.itemListElement.at(-1).item, path).toBeUndefined();
      }
    }
  });

  it("fills every placeholder, has no em-dash and runs no inline script", async () => {
    for (const base of VIEWS) {
      for (const path of [base, `${base}?lang=fr`]) {
        const page = await html(path);
        const visible = page.replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "");
        expect(visible, path).not.toMatch(/\{\w+\}/);
        expect(page, path).not.toContain(EM_DASH);
        for (const tag of page.match(/<script\b[^>]*>/g) ?? []) {
          expect(/\bsrc="|type="application\/(?:ld\+)?json"/.test(tag), `${path}: ${tag}`).toBe(true);
        }
      }
    }
  });

  it("keeps English off the French pages", async () => {
    const sentinels = ["Year over Year", "About These Series", "Rule Changes on the Charts", "Positions approved", "Reading These Tables",
      "Figures by", "Each panel has its own scale", "Latest complete pass", "All of Canada"];
    const en = (await Promise.all(VIEWS.map((p) => html(p)))).join("\n");
    for (const s of sentinels) expect(en, s).toContain(s);
    for (const base of VIEWS) {
      const fr = await html(`${base}?lang=fr`);
      for (const s of sentinels) expect(fr, `${base} still says "${s}"`).not.toContain(s);
    }
  });

  it("switches views with plain links, the current one marked", async () => {
    for (const path of VIEWS) {
      const page = await html(path);
      const tabs = page.match(/<nav class="view-tabs"[\s\S]*?<\/nav>/)?.[0] ?? "";
      for (const other of VIEWS) expect(tabs).toContain(`href="${other}"`);
      expect(tabs).toContain(`href="${path}" class="active" aria-current="page"`);
    }
  });

  it("answers 404 for an unknown view, and 503 with no data or a missing file", async () => {
    for (const path of ["/trends/national", "/trends/nope", "/trends/STREAMS"]) {
      const res = await get(path);
      expect(res.status, path).toBe(404);
      expect(await res.text()).toContain("No Such Trends View");
    }
    for (const path of VIEWS) expect((await get(path, testEnv(emptyAssets))).status, path).toBe(503);
    const res = await get("/trends/pending", testEnv(assetsWith({ ...FILES, "trends/pending.json": undefined })));
    expect(res.status).toBe(503);
    const body = text(await res.text());
    expect(body).toContain("No complete pass is recorded yet.");
    expect(body).toContain("All of Canada");
  });
});

describe("links to the trends page", () => {
  it("sits in the main navigation after Releases, and is linked from home, the release list and the Data page changelog", async () => {
    const home = await html("/");
    const nav = home.match(/<nav aria-label="[^"]*" class="main-nav"[\s\S]*?<\/nav>/)?.[0] ?? "";
    expect(nav.indexOf('href="/releases"')).toBeLessThan(nav.indexOf('href="/trends"'));
    expect(nav.indexOf('href="/trends"')).toBeLessThan(nav.indexOf('href="/methodology"'));
    expect(nav).toContain(">Trends</a>");
    expect(await html("/?lang=fr")).toContain(">Tendances</a>");
    expect(home.replace(/<nav [\s\S]*?<\/nav>/, "")).toContain('<a href="/trends">Approvals and refusals since 2014, year over year</a>');
    const releases = await html("/releases", testEnv(assetsWith({ ...FILES, "releases/index.json": { releases: [] } })));
    expect(releases).toContain('<a href="/trends">Trends: every release as one series, year over year</a>');
    const data = text(await html("/data"));
    expect(data).toContain("2026-10-20 New Trends page");
    expect(await html("/trends")).toContain('href="/trends" class="active" aria-current="page"');
  });
});

describe("the 2026 rule changes", () => {
  // The files end with 2026 Q1 today; the two changes of 2026 take their
  // place on the charts once the 2026 Q2 and Q3 lists are loaded.
  function laterFiles() {
    const later = JSON.parse(JSON.stringify(national));
    const last = later.periods[later.periods.length - 1];
    later.periods.push(
      { ...last, p: "2026Q2", start: "2026-04-01", end: "2026-06-30", quarters: 1 },
      { ...last, p: "2026Q3", start: "2026-07-01", end: "2026-09-30", quarters: 1 },
    );
    return testEnv(assetsWith({ ...FILES, "trends/national.json": later }));
  }
  const ruleList = (page: string) =>
    page.slice(page.indexOf('<ol class="rule-list">'), page.indexOf("</ol>", page.indexOf('<ol class="rule-list">')));

  it("are numbered after the others once the files reach them, each with its canada.ca sources", async () => {
    const list = ruleList(await html("/trends", laterFiles()));
    const labels = [...list.matchAll(/<li value="(\d)"><strong class="nw">([^<]+)<\/strong>/g)].map((m) => [m[1], m[2]]);
    expect(labels.slice(-2)).toEqual([["6", "2026-04-01"], ["7", "2026-07-17"]]);
    const body = text(list);
    expect(body).toContain("job advertisements must run for at least 8 consecutive weeks in the 3 months before an application, and recruitment must target youth");
    expect(body).toContain("may keep their current share or use a 15 percent cap until 2027-03-31");
    expect(body).toContain("New provincial and territorial hourly wage thresholds (the median hourly wage plus 20 percent");
    for (const href of [
      "https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage/low/requirements.html#duration",
      "https://www.canada.ca/en/employment-social-development/news/2026/03/government-of-canada-taking-action-to-support-rural-employers-under-the-temporary-foreign-worker-program.html",
      "https://www.canada.ca/en/employment-social-development/services/foreign-workers/temporary-measures.html",
      "https://www.canada.ca/en/employment-social-development/services/foreign-workers/median-wage.html#table1",
    ]) expect(list).toContain(`href="${href}"`);
    // Tags became spaces in text(); a comma or full stop after a link is drawn back to it.
    expect(body.replace(/ ([,.])/g, "$1")).toContain(
      "Sources: program requirements for low-wage positions (canada.ca), ESDC news release of 2026-03-13, temporary measures for rural employers (canada.ca).",
    );
  });

  it("link the French pages in French", async () => {
    const list = ruleList(await html("/trends?lang=fr", laterFiles()));
    for (const href of [
      "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/salaire-moyen/bas/exigences.html#duree",
      "https://www.canada.ca/fr/emploi-developpement-social/nouvelles/2026/03/le-gouvernement-du-canada-prend-des-mesures-pour-appuyer-les-employeurs-des-regions-rurales-dans-le-cadre-du-programme-des-travailleurs-etrangers-t.html",
      "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/mesures-temporaires.html",
      "https://www.canada.ca/fr/emploi-developpement-social/services/travailleurs-etrangers/salaire-moyen.html#table1",
    ]) expect(list).toContain(`href="${href}"`);
    expect(text(list)).toContain("au moins 8 semaines consécutives");
  });

  it("stay off the charts while the newest file is 2026 Q1", async () => {
    const list = ruleList(await html("/trends"));
    expect(list).not.toContain("2026-04-01");
    expect(list).not.toContain("2026-07-17");
  });
});
