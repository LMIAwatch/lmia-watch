-- LMIA Watch database schema. One file, used by both halves:
--   * the pipeline (Python) creates and fills a local SQLite file with it, then
--     exports batched SQL for Cloudflare D1;
--   * the site (Cloudflare Worker) reads D1 through it and writes only the two
--     site-owned tables at the bottom (employer_responses, corrections, donations).
-- Keep every column documented. D1 is SQLite, so stay inside SQLite syntax and
-- do not rely on PRAGMA statements.

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- keys the site reads: data_as_of (ISO date), jobbank_last_run (ISO datetime),
-- esdc_latest_period (2026Q1), esdc_latest_published (ISO date), rules_version,
-- count_pending, count_approved_records, count_approved_positions,
-- count_refused_records, count_findings

-- One row per merged employer. Identity = normalized name + province.
CREATE TABLE IF NOT EXISTS employers (
  id TEXT PRIMARY KEY,                           -- 'emp-' + first 10 hex of sha1(norm_name || '|' || province)
  display_name TEXT NOT NULL,                    -- most recently seen raw spelling
  norm_name TEXT NOT NULL,
  province TEXT,                                 -- AB BC MB NB NL NS NT NU ON PE QC SK YT, 'XX' = head office outside Canada, NULL unknown
  city TEXT,
  postal_code TEXT,                              -- 'A1A 1A1' form or NULL
  street TEXT,                                   -- only when an employer entered one on Job Bank
  current_status TEXT NOT NULL DEFAULT 'none',   -- pending | approved | refused | lapsed | none
  status_changed_at TEXT,
  first_seen TEXT,                               -- earliest record date across sources
  last_seen TEXT,                                -- latest record date across sources
  pending_count INTEGER NOT NULL DEFAULT 0,      -- postings with flag_current = 'requested'
  approved_lmias INTEGER NOT NULL DEFAULT 0,     -- sum over positive-list rows
  approved_positions INTEGER NOT NULL DEFAULT 0,
  refused_lmias INTEGER NOT NULL DEFAULT 0,
  refused_positions INTEGER NOT NULL DEFAULT 0,
  finding_count INTEGER NOT NULL DEFAULT 0,
  indicator_count INTEGER NOT NULL DEFAULT 0,    -- indicators in state 'triggered'
  registry_grade TEXT NOT NULL DEFAULT 'none',   -- exact | probable | possible | none
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_employers_norm ON employers(norm_name);
CREATE INDEX IF NOT EXISTS idx_employers_prov_status ON employers(province, current_status);
CREATE INDEX IF NOT EXISTS idx_employers_postal ON employers(postal_code);
CREATE INDEX IF NOT EXISTS idx_employers_last_seen ON employers(last_seen);

-- Every raw spelling seen for an employer, with where it came from.
CREATE TABLE IF NOT EXISTS employer_names (
  employer_id TEXT NOT NULL REFERENCES employers(id),
  raw_name TEXT NOT NULL,
  source TEXT NOT NULL,                          -- jobbank | esdc_positive | esdc_negative | ircc | registry
  PRIMARY KEY (employer_id, raw_name, source)
);

-- One row per Job Bank posting that has ever carried an LMIA flag.
CREATE TABLE IF NOT EXISTS jobbank_postings (
  posting_id INTEGER PRIMARY KEY,
  employer_id TEXT NOT NULL REFERENCES employers(id),
  employer_raw TEXT NOT NULL,
  title TEXT,
  noc_code TEXT,                                 -- NOC 2021 five-digit code when the page gives it
  noc_title TEXT,
  street TEXT,
  city TEXT,
  province TEXT,
  postal_code TEXT,
  wage_min REAL,
  wage_max REAL,
  wage_unit TEXT,                                -- HOUR | YEAR | WEEK | MONTH | other as given
  vacancies INTEGER,
  date_posted TEXT,                              -- ISO date
  valid_through TEXT,                            -- ISO date
  first_seen TEXT NOT NULL,                      -- ISO datetime of the first scrape that saw it
  last_seen TEXT NOT NULL,                       -- ISO datetime of the latest scrape that saw it
  flag_current TEXT NOT NULL,                    -- requested | approved | gone
  flag_first TEXT NOT NULL,                      -- requested | approved
  approved_seen_at TEXT,                         -- first scrape that saw the approved flag
  detail_fetched_at TEXT,                        -- NULL until the posting page itself was parsed
  url TEXT NOT NULL,
  updated_at TEXT NOT NULL                       -- any write to the row, for incremental export
);
CREATE INDEX IF NOT EXISTS idx_postings_employer ON jobbank_postings(employer_id);
CREATE INDEX IF NOT EXISTS idx_postings_flag_date ON jobbank_postings(flag_current, date_posted);
CREATE INDEX IF NOT EXISTS idx_postings_prov_flag ON jobbank_postings(province, flag_current);
CREATE INDEX IF NOT EXISTS idx_postings_postal ON jobbank_postings(postal_code);

-- Append-only log: one row per posting per scrape that saw it. The flag
-- disappears from Job Bank once a decision lands, so this log is the only
-- durable record that an application was ever pending.
CREATE TABLE IF NOT EXISTS jobbank_observations (
  posting_id INTEGER NOT NULL,
  observed_at TEXT NOT NULL,
  flag TEXT NOT NULL,                            -- requested | approved
  facet TEXT NOT NULL,                           -- Job Bank filter value: 101010 requested, 101020 approved
  PRIMARY KEY (posting_id, observed_at)
);

-- One row per line of an ESDC quarterly list (positive or negative).
CREATE TABLE IF NOT EXISTS esdc_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  list TEXT NOT NULL,                            -- positive | negative
  period TEXT NOT NULL,                          -- '2026Q1'; '2017Q1-Q2' for the combined file; '2015' for annual files
  employer_id TEXT NOT NULL REFERENCES employers(id),
  employer_raw TEXT NOT NULL,
  province TEXT,                                 -- two-letter, 'XX' head office outside Canada, NULL unknown
  province_raw TEXT,
  stream TEXT,                                   -- as published, trimmed
  address_raw TEXT,
  city TEXT,
  postal_code TEXT,
  noc_code TEXT,
  noc_title TEXT,
  incorporate_status TEXT,
  lmias INTEGER,                                 -- approved (positive) or requested (negative)
  positions INTEGER,
  resource_id TEXT NOT NULL,                     -- CKAN resource id the row came from
  row_hash TEXT NOT NULL UNIQUE                  -- sha1 over list, resource_id and the raw row
);
CREATE INDEX IF NOT EXISTS idx_esdc_employer ON esdc_records(employer_id, period);
CREATE INDEX IF NOT EXISTS idx_esdc_list_period ON esdc_records(list, period, province);
CREATE INDEX IF NOT EXISTS idx_esdc_noc ON esdc_records(noc_code);
CREATE INDEX IF NOT EXISTS idx_esdc_postal ON esdc_records(postal_code);

-- ESDC resource files we have loaded (provenance and the Data page's mirror).
CREATE TABLE IF NOT EXISTS esdc_resources (
  resource_id TEXT PRIMARY KEY,
  dataset TEXT NOT NULL,                         -- positive | negative
  period TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  published TEXT,                                -- CKAN created date, ISO
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  rows_loaded INTEGER NOT NULL,
  loaded_at TEXT NOT NULL
);

-- IRCC "Employers who have been found non-compliant", as published.
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employer_id TEXT REFERENCES employers(id),     -- NULL when no employer matched
  operating_name TEXT,
  legal_name TEXT,
  address TEXT,
  reasons TEXT,
  decision_date TEXT,
  penalty TEXT,
  status TEXT,
  row_hash TEXT NOT NULL UNIQUE,
  fetched_at TEXT NOT NULL
);

-- Corporate registry lookups.
CREATE TABLE IF NOT EXISTS registry_matches (
  employer_id TEXT NOT NULL REFERENCES employers(id),
  registry TEXT NOT NULL,                        -- bc_orgbook | corporations_canada
  registry_id TEXT NOT NULL,                     -- e.g. BC1596446
  legal_name TEXT,
  entity_type TEXT,
  status TEXT,
  registered_on TEXT,                            -- ISO date
  grade TEXT NOT NULL,                           -- exact | probable | possible
  checked_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, registry, registry_id)
);

-- Indicator state per employer. Basis is the plain sentence the profile shows.
CREATE TABLE IF NOT EXISTS indicators (
  employer_id TEXT NOT NULL REFERENCES employers(id),
  indicator TEXT NOT NULL,                       -- newly_incorporated | repeat_applicant | wage_at_floor | low_wage_high_unemployment | high_volume | refused_then_reposted
  state TEXT NOT NULL,                           -- triggered | not_triggered | not_applicable | not_evaluated
  basis TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, indicator)
);

-- Forward sortation area centroids for the map (first three postal characters).
CREATE TABLE IF NOT EXISTS fsa_centroids (
  fsa TEXT PRIMARY KEY,
  province TEXT NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL
);

-- Pipeline run log.
CREATE TABLE IF NOT EXISTS sources_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL,
  source TEXT NOT NULL,                          -- jobbank | esdc | ircc | registry | indicators | export
  detail TEXT,
  rows_in INTEGER,
  rows_new INTEGER,
  excluded INTEGER,                              -- private-household postings dropped (count only, never names)
  ok INTEGER NOT NULL
);

-- ---------------------------------------------------------------------------
-- Pipeline-local bookkeeping. Lives only in the local SQLite file; never
-- exported to D1 and never read by the site.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS d1_sync (
  table_name TEXT PRIMARY KEY,
  high_water TEXT NOT NULL                       -- last exported updated_at / id / observed_at per table
);

CREATE TABLE IF NOT EXISTS registry_checks (
  employer_id TEXT NOT NULL,
  registry TEXT NOT NULL,
  checked_at TEXT NOT NULL,                      -- a lookup with no match is still a check
  PRIMARY KEY (employer_id, registry)
);

-- Corporations Canada open-data extract (business corporations under the
-- Canada Business Corporations Act), matched to employers by normalized name.
CREATE TABLE IF NOT EXISTS federal_corporations (
  number TEXT PRIMARY KEY,
  legal_name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  status TEXT,                                   -- Active | Inactive | Dissolved
  registered_on TEXT,                            -- anniversary date: incorporation or continuance
  city TEXT,
  province TEXT,
  postal_code TEXT,
  source_url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_federal_norm ON federal_corporations(norm_name);

-- ---------------------------------------------------------------------------
-- Site-owned tables. The pipeline never writes, deletes or exports these.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employer_responses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employer_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  contact_name TEXT,
  contact_email TEXT,
  statement TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0,
  published INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_responses_employer ON employer_responses(employer_id, published);

CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employer_id TEXT,
  record_ref TEXT,                               -- free text: 'Job Bank 50456228', 'esdc row 1234'
  received_at TEXT NOT NULL,
  request TEXT NOT NULL,
  contact_email TEXT,
  resolution TEXT,
  resolved_at TEXT,
  published INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_corrections_employer ON corrections(employer_id, published);

-- Payment notices from the donation page's webhook. Amount, time and kind
-- only: the donor's name, email and message are dropped before anything is
-- stored. The support page sums these for its figures.
CREATE TABLE IF NOT EXISTS donations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  transaction_id TEXT NOT NULL UNIQUE,           -- the payment page's id; a repeated notice is ignored
  received_at TEXT NOT NULL,                     -- ISO datetime from the notice
  kind TEXT NOT NULL,                            -- Donation, Subscription, Shop Order, Commission
  amount_cents INTEGER NOT NULL,                 -- gross, in the currency given
  currency TEXT NOT NULL,                        -- ISO 4217, e.g. CAD
  recurring INTEGER NOT NULL DEFAULT 0,          -- 1 for a membership payment
  first_payment INTEGER NOT NULL DEFAULT 0,      -- 1 for the first payment of a membership
  created_at TEXT NOT NULL                       -- when the site stored it
);
CREATE INDEX IF NOT EXISTS idx_donations_received ON donations(received_at);
