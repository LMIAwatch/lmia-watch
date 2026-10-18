// The site's data is a set of JSON files the pipeline writes and the deploy
// ships as static assets under /data/. The Worker reads them through the
// assets binding; nothing here touches a database.

import type { Env } from "./env";

export interface SearchRow {
  kind: "posting" | "esdc";
  ref: number;
  employer_id: string;
  employer: string;
  job: string | null;
  noc: string | null;
  street: string | null;
  city: string | null;
  prov: string | null;
  postal: string | null;
  wage_min: number | null;
  wage_max: number | null;
  unit: string | null;
  date: string | null;
  period: string | null;
  positions: number | null;
  status: string;
  stream: string | null;
  source: string;
  sort_date: string;
  ind: string[];
}

export interface Stats {
  data_as_of: string | null;
  jobbank_last_run: string | null;
  esdc_latest_period: string;
  esdc_latest_published: string | null;
  rules_version: string | null;
  search_from_period: string;
  search_years: number[];
  counts: {
    pending: number;
    approved_records: number;
    approved_positions: number;
    refused_records: number;
    findings: number;
    employers: number;
  };
  by_stream: { k: string; n: number }[];
  by_province: { k: string; n: number }[];
  recent_pending: SearchRow[];
  recent_approved: SearchRow[];
  top_approvals: { employer_id: string; employer: string; city: string | null; prov: string | null; stream: string | null; positions: number }[];
  resources: { dataset: string; period: string; published: string | null; rows_loaded: number; loaded_at: string }[];
  runs: { run_at: string; source: string; detail: string | null; rows_new: number | null; ok: number }[];
}

export interface Profile {
  employer: {
    id: string; display_name: string; province: string | null; city: string | null; postal_code: string | null;
    street: string | null; street_source?: string | null; current_status: string; status_changed_at: string | null;
    first_seen: string | null;
    last_seen: string | null; pending_count: number; approved_lmias: number; approved_positions: number;
    refused_lmias: number; refused_positions: number; finding_count: number; indicator_count: number;
    registry_grade: string; updated_at: string;
  };
  names: { name: string; source: string }[];
  postings: {
    posting_id: number; employer_raw: string; title: string | null; noc_code: string | null; street: string | null;
    city: string | null; province: string | null; postal_code: string | null; wage_min: number | null;
    wage_max: number | null; wage_unit: string | null; vacancies: number | null; date_posted: string | null;
    valid_through: string | null; first_seen: string; last_seen: string; flag_current: string;
    approved_seen_at: string | null; url: string;
  }[];
  esdc: {
    id: number; list: string; period: string; employer_raw: string; province: string | null; stream: string | null;
    city: string | null; postal_code: string | null; noc_code: string | null; noc_title: string | null;
    incorporate_status: string | null; lmias: number | null; positions: number | null; resource_id: string;
    published: string | null;
  }[];
  registry: {
    registry: string; registry_id: string; legal_name: string | null; entity_type: string | null; status: string | null;
    registered_on: string | null; grade: string; checked_at: string;
  }[];
  indicators: { indicator: string; state: string; basis: string; rule_version: string; computed_at: string }[];
  findings: {
    operating_name: string | null; legal_name: string | null; address: string | null; reasons: string | null;
    decision_date: string | null; penalty: string | null; status: string | null;
  }[];
}

export interface Facets {
  default: { total: number; status: Record<string, number>; prov: Record<string, number>; status_prov: Record<string, number> };
  long: {
    total: number; status: Record<string, number>; prov: Record<string, number>;
    prov_year: Record<string, number>; status_prov: Record<string, number>;
  };
  files: Record<string, { rows: number; bytes: number }>;
  first_rows: number;
}

export interface Cluster {
  fsa: string; prov: string; lat: number; lon: number; pending: number; approved: number; refused: number;
}

export interface Area extends Omit<Cluster, "pending" | "approved" | "refused"> {
  total: number;
  rows: SearchRow[];
}

export const EMPLOYER_ID_RE = /^emp-[0-9a-f]{10}$/;

const POSITIVE_DATASET = "90fed587-1364-4f33-a9ee-208181dc0b97";
const NEGATIVE_DATASET = "f82f66f2-a22b-4511-bccf-e1d74db39ae5";

export function esdcSource(list: string, resourceId: string): string {
  return `https://open.canada.ca/data/en/dataset/${list === "positive" ? POSITIVE_DATASET : NEGATIVE_DATASET}/resource/${resourceId}`;
}

export async function assetResponse(env: Env, path: string): Promise<Response | null> {
  if (!env.ASSETS) return null;
  const res = await env.ASSETS.fetch(new Request(`https://assets.invalid/data/${path}`));
  return res.ok ? res : null;
}

export async function loadJson<T>(env: Env, path: string): Promise<T | null> {
  const res = await assetResponse(env, path);
  if (!res) return null;
  return (await res.json()) as T;
}

export function loadStats(env: Env): Promise<Stats | null> {
  return loadJson<Stats>(env, "stats.json");
}

export function loadFacets(env: Env): Promise<Facets | null> {
  return loadJson<Facets>(env, "search/facets.json");
}

// The newest rows of the default scope: small enough to parse on the server
// (about 150 KB raw for 500 rows) so a plain visit renders without JavaScript.
export function loadFirst(env: Env): Promise<SearchRow[] | null> {
  return loadJson<SearchRow[]>(env, "search/first.json");
}

export async function loadProfile(env: Env, id: string): Promise<Profile | null> {
  if (!EMPLOYER_ID_RE.test(id)) return null;
  const shard = await loadJson<Record<string, Profile>>(env, `profiles/${id.slice(4, 7)}.json`);
  return shard?.[id] ?? null;
}
