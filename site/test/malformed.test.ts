// Every page added since the release pages, fed each of its data files in
// many broken shapes: a field missing, null, of the wrong type, an empty or
// junk list, a list element emptied. Whatever the file holds, the page must
// answer with a page (200), "not published" (503), "not found" (404) or a
// redirect, never a server error and never a request that runs on.
import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { fakeAssets, testEnv } from "./assets";
import aliases from "./fixtures/aliases-a00.json";
import facets from "./fixtures/facets.json";
import feedIndex from "./fixtures/feeds-index.json";
import occIndex from "./fixtures/occupations-index.json";
import occ63200 from "./fixtures/occupation-63200.json";
import occ65201 from "./fixtures/occupation-65201.json";
import mb from "./fixtures/place-mb.json";
import winnipeg from "./fixtures/place-mb-winnipeg.json";
import winnipegCma from "./fixtures/place-mb-winnipeg-cma.json";
import placesIndex from "./fixtures/places-index.json";
import profiles from "./fixtures/profiles-a00.json";
import rankingsYear from "./fixtures/rankings-2026.json";
import rankingsAll from "./fixtures/rankings-all.json";
import release from "./fixtures/release-2026-q1.json";
import releaseIndex from "./fixtures/releases-index.json";
import first from "./fixtures/search-latest.json";
import stats from "./fixtures/stats.json";
import national from "./fixtures/trends-national.json";
import pending from "./fixtures/trends-pending.json";
import provinces from "./fixtures/trends-provinces.json";
import streams from "./fixtures/trends-streams.json";

const WITH_CITATION = {
  ...stats,
  citation: { title: "LMIA Watch", concept_doi: "10.5281/zenodo.101", doi: "10.5281/zenodo.105", version: "2026Q1", published: "2026-10-19" },
};

// Each data file and the pages that read it.
const CASES: { file: string; data: unknown; paths: string[] }[] = [
  { file: "releases/index.json", data: releaseIndex, paths: ["/releases"] },
  { file: "releases/2026-q1.json", data: release, paths: ["/releases/2026-q1"] },
  { file: "rankings/all.json", data: rankingsAll, paths: ["/rankings"] },
  { file: "rankings/2026.json", data: rankingsYear, paths: ["/rankings/2026"] },
  { file: "trends/national.json", data: national, paths: ["/trends"] },
  { file: "trends/streams.json", data: streams, paths: ["/trends/streams"] },
  { file: "trends/provinces.json", data: provinces, paths: ["/trends/provinces"] },
  { file: "trends/pending.json", data: pending, paths: ["/trends/pending"] },
  { file: "occupations/index.json", data: occIndex, paths: ["/occupations"] },
  { file: "occupations/63200.json", data: occ63200, paths: ["/occupations/63200"] },
  // Published tables of what postings offered, with a regional row, so the region fields are fuzzed too.
  { file: "occupations/65201.json", data: occ65201, paths: ["/occupations/65201"] },
  { file: "places/index.json", data: placesIndex, paths: ["/places"] },
  { file: "places/mb.json", data: mb, paths: ["/places/mb"] },
  { file: "places/mb/winnipeg.json", data: winnipeg, paths: ["/places/mb/winnipeg"] },
  { file: "places/mb/winnipeg-cma.json", data: winnipegCma, paths: ["/places/mb/winnipeg-cma"] },
  { file: "feeds/index.json", data: feedIndex, paths: ["/feeds"] },
  { file: "stats.json", data: WITH_CITATION, paths: ["/data", "/methodology", "/", "/search"] },
  // The search page's first rows and counts; the home page reads the counts too.
  { file: "search/first.json", data: first, paths: ["/search", "/"] },
  { file: "search/facets.json", data: facets, paths: ["/search", "/"] },
  // A profile shard: the page, its form and the API answer 200 or 404.
  {
    file: "profiles/a00.json",
    data: profiles,
    paths: ["/employers/emp-a000000001", "/employers/emp-a000000001/respond", "/api/employers/emp-a000000001"],
  },
  // A retired id's shard: the profile page, its form and the API redirect or answer 404.
  {
    file: "aliases/a00.json",
    data: aliases,
    paths: ["/employers/emp-a00dead001", "/employers/emp-a00dead001/respond", "/api/employers/emp-a00dead001"],
  },
];

const JUNK: unknown[] = [null, "x", 7, -1, true, [], {}, [null], [{}], ["x"], "2026-1x-40"];

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v));
}

// The variants of one file: whole-file junk, then each top-level field and
// each field of the first element of each top-level list (and of each list
// one level further down) replaced by every junk value or removed.
function variants(data: unknown): { label: string; body: string }[] {
  const out: { label: string; body: string }[] = [];
  const add = (label: string, v: unknown) => out.push({ label, body: JSON.stringify(v) });
  for (const j of JUNK) add(`file=${JSON.stringify(j)}`, j);
  out.push({ label: "truncated", body: JSON.stringify(data).slice(0, 40) });
  if (!data || typeof data !== "object" || Array.isArray(data)) return out;
  const obj = data as Record<string, unknown>;
  const mutateAt = (path: (string | number)[], label: string) => {
    for (const j of [...JUNK, undefined]) {
      const copy = clone(obj) as any;
      let at = copy;
      for (const k of path.slice(0, -1)) at = at[k];
      const last = path[path.length - 1];
      if (j === undefined) {
        if (Array.isArray(at)) at.splice(last as number, 1);
        else delete at[last];
      } else at[last] = j;
      add(`${label}=${j === undefined ? "(removed)" : JSON.stringify(j)}`, copy);
    }
  };
  for (const [k, v] of Object.entries(obj)) {
    mutateAt([k], k);
    if (v && typeof v === "object" && !Array.isArray(v)) {
      for (const [k2, v2] of Object.entries(v)) {
        mutateAt([k, k2], `${k}.${k2}`);
        if (Array.isArray(v2) && v2.length && v2[0] && typeof v2[0] === "object") {
          for (const k3 of Object.keys(v2[0])) mutateAt([k, k2, 0, k3], `${k}.${k2}[0].${k3}`);
        }
      }
    }
    if (Array.isArray(v) && v.length) {
      mutateAt([k, 0], `${k}[0]`);
      if (v[0] && typeof v[0] === "object" && !Array.isArray(v[0])) {
        for (const [k2, v2] of Object.entries(v[0])) {
          mutateAt([k, 0, k2], `${k}[0].${k2}`);
          if (Array.isArray(v2) && v2.length && v2[0] && typeof v2[0] === "object" && !Array.isArray(v2[0])) {
            for (const k3 of Object.keys(v2[0])) mutateAt([k, 0, k2, 0, k3], `${k}[0].${k2}[0].${k3}`);
          }
        }
      }
    }
  }
  return out;
}

function assetsServing(file: string, body: string): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url).pathname.replace(/^\/data\//, "");
      if (path === file) return new Response(body, { headers: { "content-type": "application/json" } });
      const known = CASES.find((c) => c.file === path);
      if (known) return new Response(JSON.stringify(known.data), { headers: { "content-type": "application/json" } });
      return fakeAssets.fetch(input as Request);
    },
  } as unknown as Fetcher;
}

// A fresh documentation address per request, so the per-address limits never answer first.
let address = 1;
const visitor = () => ({ "cf-connecting-ip": `2001:db8::${(address++).toString(16)}` });

describe("pages fed a broken data file", () => {
  for (const { file, data, paths } of CASES) {
    it(`${file}: never a server error`, async () => {
      const failures: string[] = [];
      for (const v of variants(data)) {
        for (const path of paths) {
          for (const lang of ["en", "fr"]) {
            const res = await app.request(`${path}?lang=${lang}`, { headers: visitor() }, testEnv(assetsServing(file, v.body)));
            if (![200, 301, 404, 503].includes(res.status)) failures.push(`${path} (${lang}) ${v.label}: ${res.status}`);
            await res.arrayBuffer();
          }
        }
      }
      expect(failures).toEqual([]);
    }, 120_000);
  }
});
