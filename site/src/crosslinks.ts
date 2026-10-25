// Links from an employer profile to the place and occupation pages that cover
// its records: the province page in the breadcrumb, the city page on the city
// name, the occupation page on each NOC code. Most profiles have no other
// inbound link than the sitemap, and these give the place and occupation
// pages links from every profile they cover.
//
// A link is written only where the page exists and is indexed: a city page
// is listed in its province's file (places/<pp>.json, which lists every city
// page of the province; places/index.json lists only the largest 25), and an
// occupation page in occupations/index.json. A missing or unreadable file
// means no link, never an error. The lookups built from a file are kept per
// parsed file in a WeakMap: loadJson hands back the same frozen object while
// the file stays in its cache with an unchanged ETag, so a lookup is built
// once per parsed copy, and a deploy that changes the file brings a new
// object and a new lookup (the old one goes with the old object).

import { loadJson } from "./data";
import type { Env } from "./env";
import { isNum, isObj, isStr } from "./valid";

// The thirteen provinces and territories, each with a page at /places/<pp>.
// XX (head office outside Canada) has none.
const PLACE_PROVINCES = new Set(["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]);

export function provincePath(province: string | null | undefined): string | null {
  return province && PLACE_PROVINCES.has(province) ? `/places/${province.toLowerCase()}` : null;
}

// A city name folded the way the pipeline folds it into a page slug
// (places.slugify): accents and other combining marks stripped, lower case,
// apostrophes dropped, any other run of characters outside a to z and 0 to 9
// made one space, and "saint"/"sainte" written "st"/"ste". "St. John's",
// "ST JOHNS" and the slug "st-johns" all read "st johns".
export function placeKey(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/\p{Mn}/gu, "")
    .toLowerCase()
    .replace(/œ/g, "oe")
    .replace(/æ/g, "ae")
    .replace(/['’]/g, "")
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
    .map((w) => (w === "saint" ? "st" : w === "sainte" ? "ste" : w))
    .join(" ");
}

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// folded name -> slug, for the city pages one province file lists.
const cityLookups = new WeakMap<object, Map<string, string>>();

function cityLookup(file: Record<string, any>): Map<string, string> {
  let lookup = cityLookups.get(file);
  if (lookup) return lookup;
  lookup = new Map();
  const threshold = isNum(file.threshold) ? file.threshold : 0;
  for (const c of Array.isArray(file.cities) ? file.cities : []) {
    if (!isObj(c) || !isStr(c.slug) || !SLUG_RE.test(c.slug) || !isStr(c.name)) continue;
    // The pipeline lists a city only from the threshold up, with no flag; a
    // flag, where an entry carries one, decides.
    const indexed = c.indexed === undefined ? isNum(c.records) && c.records >= threshold : c.indexed === true;
    if (!indexed) continue;
    for (const key of [placeKey(c.slug), placeKey(c.name)]) if (key && !lookup.has(key)) lookup.set(key, c.slug);
  }
  cityLookups.set(file, lookup);
  return lookup;
}

// The city's page, or null when the province has no page for that city.
export async function cityPath(env: Env, province: string | null, city: string | null): Promise<string | null> {
  const key = city ? placeKey(city) : "";
  if (!province || !PLACE_PROVINCES.has(province) || !key) return null;
  const pp = province.toLowerCase();
  try {
    const file = await loadJson<unknown>(env, `places/${pp}.json`);
    if (!isObj(file)) return null;
    const slug = cityLookup(file).get(key);
    return slug ? `/places/${pp}/${slug}` : null;
  } catch (e) {
    console.error(`city link ${province}: ${String(e).slice(0, 200)}`);
    return null;
  }
}

export interface OccupationTitle {
  en: string;
  fr: string;
}

// NOC 2021 code -> title, for the indexed occupation pages.
export type OccupationLinks = ReadonlyMap<string, OccupationTitle | null>;

const NO_OCCUPATIONS: OccupationLinks = new Map();
const NOC_RE = /^[0-9]{5}$/;
const occupationLookups = new WeakMap<object, Map<string, OccupationTitle | null>>();

function occupationLookup(file: Record<string, any>): Map<string, OccupationTitle | null> {
  let lookup = occupationLookups.get(file);
  if (lookup) return lookup;
  lookup = new Map();
  const threshold = isNum(file.threshold) ? file.threshold : 0;
  for (const r of Array.isArray(file.rows) ? file.rows : []) {
    if (!isObj(r) || !isStr(r.noc) || !NOC_RE.test(r.noc)) continue;
    const indexed = r.indexed === undefined ? isNum(r.records) && r.records >= threshold : r.indexed === true;
    if (!indexed) continue;
    const title = isObj(r.title) && isStr(r.title.en) && isStr(r.title.fr) ? { en: r.title.en, fr: r.title.fr } : null;
    lookup.set(r.noc, title);
  }
  occupationLookups.set(file, lookup);
  return lookup;
}

export async function occupationLinks(env: Env): Promise<OccupationLinks> {
  try {
    const file = await loadJson<unknown>(env, "occupations/index.json");
    return isObj(file) ? occupationLookup(file) : NO_OCCUPATIONS;
  } catch (e) {
    console.error(`occupation links: ${String(e).slice(0, 200)}`);
    return NO_OCCUPATIONS;
  }
}
