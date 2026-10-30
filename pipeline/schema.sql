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
-- last disagreed; see search_db.py), program_<series>_checked_at (the last read
-- of each program-conditions page; see sources/program.py)

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
  detail_fetched_at TEXT,                        -- NULL until the posting page itself was parsed, found removed
                                                 -- (404 or 410) or given up after repeated passing failures
  detail_attempts INTEGER NOT NULL DEFAULT 0,    -- posting-page fetches that failed for a passing reason (5xx, timeout,
                                                 -- connection); the page stays queued while this is at most 3
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
  source TEXT NOT NULL,                          -- jobbank | jobbank_intl | high_wage | registers | esdc | ircc | registry | wages | lfs | program_times |
                                                 -- program_cma | program_thresholds | geography | indicators | export
  detail TEXT,
  rows_in INTEGER,
  rows_new INTEGER,
  excluded INTEGER,                              -- private-household postings dropped (count only, never names)
  ok INTEGER NOT NULL,
  notice TEXT                                    -- an item needing attention that is not a failure (a reference list that
                                                 -- changed, a list not yet readable); NULL when none. Reported in status.json
                                                 -- as notices, which raise an attention item without marking the run failed
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

-- The employer directory's pages (directory.py) as last exported, by path,
-- each with a hash of its rows and the data date on which that hash last
-- changed. The sitemap gives that date as the page's lastmod, so a page whose
-- rows stayed the same keeps its date; a page no longer written is deleted.
CREATE TABLE IF NOT EXISTS directory_pages (
  path TEXT PRIMARY KEY,                         -- '/places/bc/employers' (page 1), '/places/bc/employers/2'
  code TEXT NOT NULL,                            -- the directory: 'bc', ..., 'yt', or 'other' (XX and no province)
  page INTEGER NOT NULL,                         -- from 1
  hash TEXT NOT NULL,                            -- directory.page_hash of the page's rows
  changed_on TEXT NOT NULL                       -- ISO date: the data date of the export that first wrote this hash
);

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
  source_url TEXT NOT NULL,
  business_number TEXT                           -- nine digits (normalize.business_number), NULL when blank or not a valid BN
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

-- Program conditions (sources/program.py): what three Temporary Foreign Worker
-- Program pages on canada.ca state is in force. One row per edition, never
-- overwritten: a read that finds a period's figures unchanged adds nothing, and
-- one that finds them changed adds a new edition beside the old one.
CREATE TABLE IF NOT EXISTS program_editions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  series TEXT NOT NULL,                          -- processing_times | cma_refusal | wage_thresholds
  period TEXT NOT NULL,                          -- 'YYYY-MM' the processing times measure; for the other two the ISO date the edition took effect
  in_force_to TEXT,                              -- the last day in force the page states (ISO date); NULL when it states none
  threshold REAL,                                -- the cut-off the page states (cma_refusal: 6.0 percent); NULL for the other series
  published TEXT,                                -- the page's own date for its last update when this edition was first read (ISO date)
  source_url TEXT NOT NULL,                      -- the English canada.ca page it was read from
  read_at TEXT NOT NULL,                         -- ISO datetime of the first read that found this edition
  sha256 TEXT NOT NULL,                          -- over the period, dates, threshold and figures (not the labels)
  items INTEGER NOT NULL                         -- rows in program_figures
);
-- A few editions a quarter, so no secondary index.

-- The figures of one edition.
CREATE TABLE IF NOT EXISTS program_figures (
  edition_id INTEGER NOT NULL REFERENCES program_editions(id),
  key TEXT NOT NULL,                             -- stream ('high_wage'), 2021 Census CMA code ('602') or province code ('AB')
  label TEXT NOT NULL,                           -- the row's name as the page writes it ('Low-wage stream', 'Winnipeg, Manitoba', 'Alberta')
  value REAL NOT NULL,                           -- average business days, unemployment rate in percent, or hourly threshold in dollars
  PRIMARY KEY (edition_id, key)
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
-- Public records joined to employer profiles (sources/grants.py,
-- sources/alberta_records.py, sources/fmcsa.py, rules in sources/matching.py).
-- Each source keeps only the records whose name could be an employer's, and
-- never a record of an individual or a sole proprietorship. The match tables
-- are rebuilt whole by each night's matching and carry no foreign key, so an
-- employer deleted or renamed between two nights leaves nothing that blocks
-- the deletion; the export reads them only for employers that exist. The
-- tables have no secondary index: they are small, and the joins probe the
-- employers' name index (idx_employers_norm) from their side. Shown on
-- profiles as records; none of them feeds the indicators.
-- ---------------------------------------------------------------------------

-- Proactive disclosure of federal grants and contributions (open.canada.ca
-- dataset 432527ab-7aac-45b5-81d6-7597107a7013, Open Government Licence,
-- Canada): one row per agreement, at its latest amendment.
CREATE TABLE IF NOT EXISTS federal_grants (
  agreement_key TEXT PRIMARY KEY,                -- owner_org || ',' || ref_number: the department and its reference number
  ref_number TEXT NOT NULL,                      -- the department's reference number for the agreement
  amendment_number INTEGER NOT NULL,             -- the amendment the row was taken from (0 = the original agreement)
  owner_org TEXT NOT NULL,                       -- department code as published, e.g. aafc-aac
  department_en TEXT,                            -- department name, English part of owner_org_title
  department_fr TEXT,                            -- department name, French part of owner_org_title
  recipient_type TEXT,                           -- A Indigenous, F for-profit, G government, I international, N not-for-profit,
                                                 -- O other, S academia; NULL on older rows (P, individuals and sole
                                                 -- proprietorships, is never stored)
  business_number TEXT,                          -- the recipient's nine-digit BN (normalize.business_number), NULL when absent or invalid
  legal_name TEXT NOT NULL,                      -- recipient legal name as published (the English part when both languages are given)
  norm_name TEXT NOT NULL,                       -- normalize.norm_name of legal_name
  operating_name TEXT,                           -- recipient operating name; NULL when blank or when it reads as a person
  operating_norm TEXT,                           -- normalize.norm_name of operating_name
  city TEXT,
  province TEXT,                                 -- two-letter code, from the record or its postal code; NULL outside Canada
  postal_code TEXT,                              -- 'A1A 1A1' form or NULL
  program_en TEXT,                               -- program name
  program_fr TEXT,
  agreement_type TEXT,                           -- G grant, C contribution, O other transfer payment
  agreement_value REAL,                          -- dollars, as amended
  start_date TEXT,                               -- ISO date
  end_date TEXT,                                 -- ISO date
  loaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grant_matches (
  employer_id TEXT NOT NULL,
  agreement_key TEXT NOT NULL,                   -- federal_grants.agreement_key
  grade TEXT NOT NULL,                           -- exact | probable (sources/matching.py)
  basis TEXT NOT NULL,                           -- business_number | name_postal_area | name_province | operating_name_postal_area
  matched_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, agreement_key)
);

-- Alberta Employer Records (open.alberta.ca/opendata/employer-records, Open
-- Government Licence, Alberta): the injury figures of each employer's
-- workers' compensation account, one row per account, year and name. An
-- account listed under two names (a numbered company and the name it
-- operates under, or a former name) has a row for each, with the same
-- figures.
CREATE TABLE IF NOT EXISTS alberta_employer_records (
  emp_key TEXT NOT NULL,                         -- the publisher's key for the account (an opaque identifier, not the WCB number)
  year INTEGER NOT NULL,                         -- YEAR_NO
  employer_name TEXT NOT NULL,                   -- EMPLOYER_NAME as published
  norm_name TEXT NOT NULL,
  trade_name TEXT,                               -- TRADE_NAME; NULL when blank or when it reads as a person
  trade_norm TEXT,
  city TEXT,                                     -- CITY_NAME as published (upper case)
  industry TEXT,                                 -- WCB industry name
  industry_code TEXT,                            -- WCB industry code
  person_years REAL,                             -- full-time equivalents reported to the WCB
  lost_time_claims INTEGER,
  lost_time_rate REAL,                           -- lost-time claims per 100 person-years, as published
  disabling_injuries INTEGER,
  disabling_rate REAL,                           -- disabling injuries per 100 person-years, as published
  fatalities INTEGER,                            -- fatality claims accepted in the year
  cor_year INTEGER,                              -- COR_YEAR: the certificate of recognition year when published; NULL otherwise
  resource_id TEXT NOT NULL,                     -- CKAN resource id of the workbook
  PRIMARY KEY (emp_key, year, norm_name)
);

CREATE TABLE IF NOT EXISTS alberta_matches (
  employer_id TEXT NOT NULL,
  emp_key TEXT NOT NULL,                         -- alberta_employer_records.emp_key
  account_name TEXT NOT NULL,                    -- the account's name that matched (alberta_employer_records.employer_name)
  grade TEXT NOT NULL,                           -- exact | probable
  basis TEXT NOT NULL,                           -- name_city | name_province | trade_name_city
  matched_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, emp_key)
);

-- US FMCSA Company Census (data.transportation.gov dataset az4n-8mr2, a work
-- of the US government, public domain): motor carriers with a Canadian
-- physical address. Officer names, phone, fax and email are never fetched.
CREATE TABLE IF NOT EXISTS fmcsa_carriers (
  dot_number INTEGER PRIMARY KEY,                -- USDOT number
  legal_name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  dba_name TEXT,                                 -- doing-business-as name; NULL when blank or when it reads as a person
  dba_norm TEXT,
  city TEXT,
  province TEXT,                                 -- two-letter code (PHY_STATE)
  postal_code TEXT,                              -- 'A1A 1A1' form or NULL (older records give only CANADA)
  status TEXT,                                   -- A active, I inactive, P pending (STATUS_CODE)
  power_units INTEGER,                           -- POWER_UNITS
  drivers INTEGER,                               -- TOTAL_DRIVERS
  safety_rating TEXT,                            -- S satisfactory, C conditional, U unsatisfactory; NULL not rated
  safety_rating_date TEXT,                       -- ISO date
  record_date TEXT,                              -- MCS150_DATE: the carrier's latest census update, ISO date
  added_on TEXT,                                 -- ADD_DATE, ISO date
  carrier_operation TEXT,                        -- A interstate, B intrastate with hazardous materials, C other intrastate
  loaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fmcsa_matches (
  employer_id TEXT NOT NULL,
  dot_number INTEGER NOT NULL,                   -- fmcsa_carriers.dot_number
  grade TEXT NOT NULL,                           -- exact | probable
  basis TEXT NOT NULL,                           -- name_postal_code | name_province | dba_postal_code
  matched_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, dot_number)
);

-- ---------------------------------------------------------------------------
-- Job Bank postings open to international candidates (sources/jobbank_intl.py,
-- grades in intl.py). The employer chose "Canadians and international
-- candidates" as the posting's intended applicants (search facet fglo=1). From
-- 2026-11-03 a job offer used for Express Entry needs no LMIA, so these
-- postings are where such offers can still be seen. Signals, not findings: a
-- posting does not show that a job offer was made. No employer row is created
-- for these postings; employer_id is filled only when the employer identity
-- (normalize.employer_id of the name and province) names an employer that
-- already exists. Postings of private households are dropped before anything
-- is written, as on the LMIA crawl.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobbank_intl_postings (
  posting_id INTEGER PRIMARY KEY,                -- Job Bank posting id
  employer_raw TEXT NOT NULL,                    -- the employer name the listing or feed gives
  employer_id TEXT,                              -- an existing employers.id with the same identity; NULL when none
  title TEXT,
  noc_code TEXT,                                 -- NOC 2021 code the employer chose (posting page); NULL until read
  city TEXT,
  province TEXT,                                 -- two-letter code
  postal_code TEXT,
  wage_min REAL,
  wage_max REAL,
  wage_unit TEXT,
  date_posted TEXT,                              -- ISO date (posting page, else the feed or listing)
  valid_through TEXT,                            -- ISO date the posting page gives
  first_seen TEXT NOT NULL,                      -- ISO datetime of the first pass that saw it
  last_seen TEXT NOT NULL,                       -- ISO datetime of the latest pass that saw it
  found_by TEXT NOT NULL,                        -- feed (the nightly Atom feed) | sweep (the weekly facet sweep) | recent (the
                                                 -- last-48-hours search pages read when the feed was full)
  in_facet INTEGER NOT NULL DEFAULT 1,           -- 0 once a complete weekly sweep no longer lists it
  gone_at TEXT,                                  -- ISO datetime of the sweep that first missed it; NULL while listed
  audience TEXT NOT NULL DEFAULT 'unknown',      -- the posting page's "Who can apply": international | authorized | canadians | unknown
  audience_text TEXT,                            -- that block's list items as read, joined by ' | '
  lmia TEXT NOT NULL DEFAULT 'unknown',          -- requested | approved | none | unknown: requested or approved once any source
                                                 -- (listing flag, posting page, the LMIA crawl's jobbank_postings) showed it
  employment_terms TEXT,                         -- the posting page's terms of employment as read ('Permanent employment Full time')
  full_time INTEGER,                             -- 1 or 0 from employment_terms; NULL until read
  permanent INTEGER,                             -- 1 or 0 from employment_terms; NULL until read
  ee_phrases TEXT,                               -- JSON list of Express Entry phrases matched in the posting's own text
  pr_phrases TEXT,                               -- JSON list of permanent-residence support phrases matched
  exempt_phrases TEXT,                           -- JSON list of "LMIA exempt" or "LMIA not required" phrases matched
  grade TEXT,                                    -- A | B | C (intl.grade_posting); NULL with an LMIA request, before the page is read,
                                                 -- or when the page no longer says international
  grade_reasons TEXT,                            -- JSON list of reason keys behind the grade (intl.REASONS)
  detail_fetched_at TEXT,                        -- NULL until the posting page was fetched, found removed (404 or 410)
                                                 -- or given up after repeated passing failures
  detail_attempts INTEGER NOT NULL DEFAULT 0,    -- posting-page fetches that failed for a passing reason (5xx, timeout,
                                                 -- connection); the page stays queued while this is at most 3
  url TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intl_employer ON jobbank_intl_postings(employer_id);
CREATE INDEX IF NOT EXISTS idx_intl_facet_date ON jobbank_intl_postings(in_facet, date_posted);

-- IRCC's list of high-wage occupations as adopted (sources/high_wage.py): a new
-- edition each time the page changes and passes the sanity checks, never
-- overwritten. The newest is the version grades use; before the first, the
-- committed file data/high_wage_nocs.json.
CREATE TABLE IF NOT EXISTS high_wage_editions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sha256 TEXT NOT NULL,                          -- high_wage.fingerprint of the code:points pairs
  read_on TEXT NOT NULL,                         -- ISO date the edition was first read (the version date shown)
  page_modified TEXT,                            -- the page's dcterms.modified date
  source_url TEXT NOT NULL,
  count INTEGER NOT NULL,
  occupations TEXT NOT NULL,                     -- JSON list of {noc, title, points}
  adopted_at TEXT NOT NULL                       -- ISO datetime of the run that adopted it
);

-- One row per day and count the facet's first search page states: the
-- whole facet (total), with an LMIA requested or approved, posted in the
-- last 48 hours or 30 days, and the authorized-workers facet beside it. A
-- daily series that needs no posting page, so it is complete from its first day.
CREATE TABLE IF NOT EXISTS jobbank_facet_counts (
  day TEXT NOT NULL,                             -- UTC date of the read
  key TEXT NOT NULL,                             -- total | lmia_requested | lmia_approved | last_48h | last_30d | authorized
  value INTEGER NOT NULL,
  PRIMARY KEY (day, key)
);

-- Published lists of designated employers (sources/registers.py): the
-- Atlantic Immigration Program by province and the Rural Community and
-- Francophone Community Immigration Pilots by community. One row per list
-- with its state; the rows themselves below. A list that cannot be read one
-- night keeps its last good rows.
CREATE TABLE IF NOT EXISTS designated_lists (
  key TEXT PRIMARY KEY,                          -- registers.REGISTERS key, e.g. aip_nl, rcip_sudbury
  program TEXT NOT NULL,                         -- AIP | RCIP | FCIP
  jurisdiction TEXT NOT NULL,                    -- province code
  community TEXT,                                -- pilot community; NULL for AIP
  source_url TEXT NOT NULL,                      -- the page or file last read (a PDF link found on its page)
  format TEXT NOT NULL,                          -- html | json | pdf
  state TEXT NOT NULL,                           -- ok | unreadable (a PDF) | failing (not fetched) | layout (fetched, not parsed)
                                                 -- | blocked (a bot challenge page) | snapshot (the copy loaded by hand in use)
  rows INTEGER NOT NULL DEFAULT 0,               -- rows on the last good read
  list_date TEXT,                                -- the list's own date when it states one (ISO date)
  last_ok_at TEXT,                               -- ISO datetime of the last good read (a copy loaded by hand: its load day)
  last_attempt_at TEXT,
  fail_streak INTEGER NOT NULL DEFAULT 0,        -- nights in a row the read failed
  detail TEXT,                                   -- why the last read failed, or what it found
  sha256 TEXT                                    -- of the last body read (a PDF's change shows here)
);

CREATE TABLE IF NOT EXISTS designated_employers (
  list_key TEXT NOT NULL,                        -- designated_lists.key
  employer_name TEXT NOT NULL,                   -- the name as listed (a status note such as "not hiring" removed)
  norm_name TEXT NOT NULL,                       -- normalize.norm_name of the legal part of the name
  trade_name TEXT,                               -- the part after "o/a" or "dba", when the list gives one
  trade_norm TEXT,
  location TEXT,                                 -- the location the list gives (city, address or community), as written
  designated_on TEXT,                            -- the designation date the list gives for the row (ISO date)
  first_seen TEXT NOT NULL,                      -- ISO datetime of the first read that listed it
  last_seen TEXT NOT NULL,                       -- ISO datetime of the latest read that listed it
  PRIMARY KEY (list_key, employer_name)
);

CREATE TABLE IF NOT EXISTS designated_matches (
  employer_id TEXT NOT NULL,
  list_key TEXT NOT NULL,
  employer_name TEXT NOT NULL,                   -- designated_employers.employer_name that matched
  grade TEXT NOT NULL,                           -- exact | probable (sources/matching.py)
  basis TEXT NOT NULL,                           -- name_city | name_province | trade_name_city
  matched_at TEXT NOT NULL,
  PRIMARY KEY (employer_id, list_key, employer_name)
);

-- Government notices (sources/notices.py): IRCC and ESDC news items on
-- Canada.ca whose title or summary, in either language, contains one of the
-- program terms. Read nightly from the departments' English and French news
-- feeds; the two languages of an item are paired on the feed's timestamp.
-- Only matched items are stored, as published (the summary without its
-- dateline). A NULL French title means no French item paired (the site shows
-- the English with a note), a NULL English one the reverse. Rows are never
-- deleted; the site lists the last 12 months.
CREATE TABLE IF NOT EXISTS gov_notices (
  id TEXT PRIMARY KEY,                           -- first 16 hex characters of the SHA-1 of the canada.ca URL (English, else French)
  department TEXT NOT NULL,                      -- ircc | esdc
  item_type TEXT NOT NULL,                       -- news_release | backgrounder | statement | speech | media_advisory | other
  published_at TEXT NOT NULL,                    -- the feed's timestamp as published, with its offset
  published TEXT NOT NULL,                       -- its date (YYYY-MM-DD), as the department dated it
  title_en TEXT,
  summary_en TEXT,
  url_en TEXT,
  title_fr TEXT,
  summary_fr TEXT,
  url_fr TEXT,
  terms_en TEXT,                                 -- JSON list of the terms the English title or summary contains
  terms_fr TEXT,                                 -- the same for the French
  first_seen TEXT NOT NULL,                      -- ISO datetime of the run that first stored it
  last_seen TEXT NOT NULL                        -- ISO datetime of the latest run that read it
);

-- One row per news feed read for gov_notices, with the state of its last read.
-- A feed that cannot be read keeps the items already stored.
CREATE TABLE IF NOT EXISTS gov_notice_feeds (
  key TEXT PRIMARY KEY,                          -- ircc_en | ircc_fr | esdc_en | esdc_fr
  state TEXT NOT NULL,                           -- ok | failing
  checked_at TEXT NOT NULL,                      -- ISO datetime of the last read
  last_ok_at TEXT,                               -- ISO datetime of the last good read
  entries INTEGER NOT NULL DEFAULT 0,            -- items in the last good read
  detail TEXT                                    -- why the last read failed, or what it found
);

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
