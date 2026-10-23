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
-- pipeline-only keys: normalize_version (the name normalization employer ids
-- were derived with; see migrate.py), search_full_at (date of the last full
-- reload of the search database) and search_reload_due (date its row count
-- last disagreed; see search_db.py)

-- One row per merged employer. Identity = normalized legal name + province:
-- the part of a name before "dba", "o/a" and similar markers is the legal name.
CREATE TABLE IF NOT EXISTS employers (
  id TEXT PRIMARY KEY,                           -- 'emp-' + first 10 hex of sha1(norm_name || '|' || province)
  display_name TEXT NOT NULL,                    -- most recently seen raw spelling
  norm_name TEXT NOT NULL,                       -- normalize.norm_name of the legal name
  province TEXT,                                 -- AB BC MB NB NL NS NT NU ON PE QC SK YT, 'XX' = head office outside Canada, NULL unknown
  city TEXT,
  postal_code TEXT,                              -- 'A1A 1A1' form or NULL
  street TEXT,                                   -- from a Job Bank posting page, else from an IRCC finding's address
  street_source TEXT,                            -- jobbank | ircc: where street came from; NULL when street is NULL
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

-- Every raw spelling seen for an employer, with where it came from, plus the
-- operating name split off a raw spelling ("X Ltd. o/a Y" adds "Y") and an
-- IRCC finding's operating and legal names.
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
  loaded_at TEXT NOT NULL,
  parser_version INTEGER NOT NULL DEFAULT 0      -- esdc.PARSER_VERSION the rows were read with; 0 = before versions were recorded
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
CREATE INDEX IF NOT EXISTS idx_findings_employer ON findings(employer_id);

-- Corporate registry lookups.
CREATE TABLE IF NOT EXISTS registry_matches (
  employer_id TEXT NOT NULL REFERENCES employers(id),
  registry TEXT NOT NULL,                        -- bc_orgbook | corporations_canada | quebec_req
  registry_id TEXT NOT NULL,                     -- e.g. BC1596446, a federal corporation number, a Quebec NEQ
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
  source TEXT NOT NULL,                          -- jobbank | esdc | ircc | registry | wages | lfs | geography | indicators | export
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
-- The hosted search sync's ledger (search_db.py): every row of the D1 search
-- database (search_schema.sql) as last confirmed there, by key, with its rid
-- and content hash. Tonight's rows are compared with it, so only changed rows
-- are sent; written only after the workflow applied every batch and read back
-- the expected row count.
CREATE TABLE IF NOT EXISTS search_sync (
  key TEXT PRIMARY KEY,                          -- 'e:<esdc_records.id>' or 'p:<posting_id>'
  rid INTEGER NOT NULL,                          -- search_rows.rid
  hash TEXT NOT NULL                             -- search_db.row_hash of the row as sent
);
-- High-water marks of a D1 copy of the whole database that was never used.
DROP TABLE IF EXISTS d1_sync;

-- Employer ids retired by a normalization change (migrate.py) or by an ESDC
-- file read again under a newer parser (sources/esdc.py), each with the id
-- that took over its records, so a link to an old profile can be sent on.
-- The one table in this block the site sees: export_static writes it, chains
-- followed to the live id, as aliases/<abc>.json.
CREATE TABLE IF NOT EXISTS employer_aliases (
  old_id TEXT PRIMARY KEY,
  new_id TEXT NOT NULL,
  normalize_version INTEGER NOT NULL,            -- the normalization in force when old_id was retired
  created_at TEXT NOT NULL
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

-- Job Bank wage tables loaded from open.canada.ca (ESDC "Wages" dataset),
-- one row per yearly CSV. The newest two are kept, so a posting is compared
-- with the table in force on its posting date.
CREATE TABLE IF NOT EXISTS wage_tables (
  resource_id TEXT PRIMARY KEY,                  -- CKAN resource id of the CSV
  name TEXT NOT NULL,                            -- resource name as published, e.g. '2025 Wages'
  url TEXT NOT NULL,                             -- download URL
  source_modified TEXT,                          -- CKAN last_modified (or created); a change triggers a new download
  revision_date TEXT,                            -- ISO date from the file's revision column; in force from this date
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  rows_loaded INTEGER NOT NULL,                  -- rows with a published median
  loaded_at TEXT NOT NULL
);

-- Job Bank wages: one row per occupation and area that has a published median.
CREATE TABLE IF NOT EXISTS jobbank_wages (
  resource_id TEXT NOT NULL,                     -- wage_tables.resource_id
  noc_code TEXT NOT NULL,                        -- NOC 2021 five-digit code
  area_code TEXT NOT NULL,                       -- '00' Canada, two-digit province code ('46'), or four-digit economic region ('4650')
  province TEXT,                                 -- two-letter code; NULL for Canada
  area_name TEXT NOT NULL,                       -- English area name as published
  median REAL NOT NULL,                          -- median wage in dollars, hourly unless annual = 1
  low REAL,                                      -- low wage as published, same unit
  high REAL,                                     -- high wage as published, same unit
  annual INTEGER NOT NULL,                       -- 1 when Job Bank publishes the occupation at an annual rate
  reference_period TEXT,                         -- survey years behind the figure, e.g. '2023-2024'
  PRIMARY KEY (resource_id, noc_code, area_code)
);

-- Labour Force Survey unemployment rate by census metropolitan area
-- (Statistics Canada table 14-10-0459-01, three-month moving average,
-- unadjusted: the series ESDC's low-wage refusal table carries).
CREATE TABLE IF NOT EXISTS lfs_unemployment (
  cma_uid TEXT NOT NULL,                         -- 2021 Census CMA code, three digits ('602' Winnipeg, '505' Ottawa-Gatineau)
  ref_month TEXT NOT NULL,                       -- 'YYYY-MM', the last month of the three-month window
  rate REAL NOT NULL,                            -- unemployment rate, percent
  cma_name TEXT NOT NULL,                        -- English name without the province, e.g. 'Winnipeg'
  vector TEXT,                                   -- Statistics Canada vector id, e.g. 'v1643280007'
  PRIMARY KEY (cma_uid, ref_month)
);

-- Forward sortation area to 2021 Census economic region and census
-- metropolitan area, derived from the boundary files (sources/geography.py).
-- Rebuilt only when the boundary files or the centroids change.
CREATE TABLE IF NOT EXISTS fsa_regions (
  fsa TEXT PRIMARY KEY,                          -- first three postal characters
  er_uid TEXT,                                   -- economic region code ('4650'); NULL when the point fell in none
  er_name TEXT,                                  -- English economic region name ('Winnipeg', 'Lower Mainland--Southwest')
  cma_uid TEXT,                                  -- CMA code ('602'); NULL outside every census metropolitan area
  cma_name TEXT,                                 -- English CMA name from the boundary file
  lat REAL NOT NULL,                             -- the point that was placed
  lon REAL NOT NULL,
  method TEXT NOT NULL                           -- centroid (GeoNames point inside the FSA boundary) | boundary (interior point of the
                                                 -- FSA boundary) | centroid_unchecked (no 2021 boundary); '+nearest' when the region
                                                 -- came from the nearest boundary within 10 km (the point lay offshore)
);

-- Registraire des entreprises du Québec open-data extract (CC BY-NC-SA 4.0),
-- loaded weekly: one row per name in force of an enterprise registered, or
-- struck off since 2012, kept only when it normalizes like a Quebec
-- employer's name. Sole proprietorships are not loaded.
CREATE TABLE IF NOT EXISTS quebec_enterprises (
  neq TEXT NOT NULL,                             -- Quebec enterprise number, ten digits
  name TEXT NOT NULL,                            -- the name as registered
  norm_name TEXT NOT NULL,
  name_kind TEXT NOT NULL,                       -- legal (the legal name or its other-language version) | other (a name it operates under)
  legal_name TEXT NOT NULL,                      -- the enterprise's current legal name
  status TEXT,                                   -- Active | Struck off
  form TEXT,                                     -- legal form code: CIE, SENC, SEC, APE, COP, SOC...
  registered_on TEXT,                            -- registration date (DAT_IMMAT)
  postal_code TEXT,                              -- domicile address
  province TEXT,                                 -- from the domicile postal code
  PRIMARY KEY (neq, norm_name)
);
CREATE INDEX IF NOT EXISTS idx_quebec_norm ON quebec_enterprises(norm_name);

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

-- ---------------------------------------------------------------------------
-- Pipeline-local reference tables for the occupation and place pages
-- (sources/vacancies.py). Never exported to D1 and never read by the site.
-- ---------------------------------------------------------------------------

-- Statistics Canada Job Vacancy and Wage Survey, table 14-10-0444-01 (job
-- vacancies and average offered hourly wage by NOC 2021 unit group, quarterly,
-- Statistics Canada Open Licence). The newest eight quarters in the table are
-- kept. A figure the survey publishes for two small economic regions combined
-- is stored under each member region's code, so a lookup by fsa_regions.er_uid
-- finds it.
CREATE TABLE IF NOT EXISTS statcan_vacancies (
  noc_code TEXT NOT NULL,                        -- NOC 2021 five-digit unit group, or 'total' for all occupations
  area_code TEXT NOT NULL,                       -- '00' Canada, two-digit province code ('46') or four-digit economic region ('4650'), as in jobbank_wages
  ref_quarter TEXT NOT NULL,                     -- '2026Q2'
  area_name TEXT NOT NULL,                       -- English name as published, without the province ('Winnipeg', 'South Central and North Central')
  combined INTEGER NOT NULL DEFAULT 0,           -- 1 when the survey publishes this region only together with a neighbour
  vacancies INTEGER,                             -- job vacancies; NULL when not published for the quarter
  vacancies_quality TEXT,                        -- Statistics Canada quality letter, A (excellent) to E (use with caution)
  offered_wage REAL,                             -- average offered hourly wage in dollars; NULL when not published
  offered_wage_quality TEXT,                     -- quality letter of the wage, A to E
  PRIMARY KEY (noc_code, area_code, ref_quarter)
);

-- NOC 2021 Version 1.0 classification structure (Statistics Canada Open
-- Licence): occupation titles and definitions in English and French, read once.
CREATE TABLE IF NOT EXISTS noc_titles (
  noc_code TEXT PRIMARY KEY,                     -- one digit (broad category, '6') to five digits (unit group, '63200')
  level INTEGER NOT NULL,                        -- 1 broad category, 2 major group, 3 sub-major group, 4 minor group, 5 unit group
  title_en TEXT NOT NULL,                        -- class title as published ('Cooks')
  title_fr TEXT NOT NULL,                        -- French class title ('Cuisiniers/cuisinières')
  definition_en TEXT,                            -- class definition as published
  definition_fr TEXT
);
