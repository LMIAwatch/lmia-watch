-- The hosted search database: D1 `lmia-watch-search`, binding SEARCH.
--
-- A database of its own, apart from the forms database (`lmia-watch`, from
-- schema.sql), so a rebuild here can never touch what readers submitted.
-- Written only by the nightly sync (pipeline/lmia_pipeline/search_db.py),
-- which applies this file before every sync: every statement is IF NOT
-- EXISTS, so it changes nothing on a database that has it. A change to a
-- table here reaches an existing database only through a full reload
-- (`search-sync --full`), whose first batch drops both tables and runs this
-- file again.
--
-- One row per ESDC list row since 2014 and per Job Bank posting whose LMIA
-- flag is requested or approved; the same rows and fields the static search
-- files carry (export_static.posting_row and esdc_row).

CREATE TABLE IF NOT EXISTS search_rows (
  rid INTEGER PRIMARY KEY,                       -- esdc_records.id * 2, or posting_id * 2 + 1: never collide, never change
  key TEXT NOT NULL UNIQUE,                      -- 'e:<esdc_records.id>' or 'p:<posting_id>'
  kind TEXT NOT NULL,                            -- esdc | posting
  ref INTEGER NOT NULL,                          -- esdc_records.id or the Job Bank posting id
  employer_id TEXT NOT NULL,
  employer TEXT NOT NULL,                        -- the name as written on the record
  job TEXT,                                      -- the posting's title, or the list row's occupation title
  noc TEXT,
  street TEXT,                                   -- postings only
  city TEXT,
  prov TEXT,                                     -- two letters, XX head office outside Canada, NULL unknown
  postal TEXT,
  wage_min REAL,                                 -- postings only
  wage_max REAL,
  unit TEXT,
  date TEXT,                                     -- the posting date (ISO); NULL on list rows
  period TEXT,                                   -- the list's period ('2026Q1', '2017Q1-Q2', '2015'); NULL on postings
  positions INTEGER,
  status TEXT NOT NULL,                          -- pending | approved | refused
  stream TEXT,
  source TEXT,                                   -- the Job Bank page or the open.canada.ca resource
  sort_date TEXT NOT NULL,                       -- the posting date (else first seen), or the period's last day
  year INTEGER,                                  -- the period's year on a list row, the sort date's year on a posting
  ind TEXT NOT NULL DEFAULT '',                  -- triggered indicator keys, comma separated, or empty
  name_fold TEXT NOT NULL DEFAULT '',            -- employer in lower case without accents, as search.js folds it
  hash TEXT NOT NULL                             -- search_db.row_hash: SHA-1 over every column above
);

-- For the queries the search API runs: newest first with keyset paging,
-- one status or one province newest first, a year range, one employer, one
-- occupation, and the name sort and name prefixes.
CREATE INDEX IF NOT EXISTS search_rows_sort ON search_rows (sort_date DESC, rid);
CREATE INDEX IF NOT EXISTS search_rows_status ON search_rows (status, sort_date DESC);
CREATE INDEX IF NOT EXISTS search_rows_prov ON search_rows (prov, sort_date DESC);
CREATE INDEX IF NOT EXISTS search_rows_year ON search_rows (year);
CREATE INDEX IF NOT EXISTS search_rows_employer ON search_rows (employer_id);
CREATE INDEX IF NOT EXISTS search_rows_noc ON search_rows (noc);
CREATE INDEX IF NOT EXISTS search_rows_name ON search_rows (name_fold);

-- Full-text index over the employer name, the job or occupation title and
-- the city. External content: the text lives once, in search_rows, and the
-- triggers below keep the index in step, so the sync writes search_rows
-- only. remove_diacritics 2 lets "Quebec" find "Québec" and "Montreal"
-- find "Montréal".
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  employer, job, city,
  content = 'search_rows', content_rowid = 'rid',
  tokenize = 'unicode61 remove_diacritics 2'
);

-- An external-content index must be told the old text to remove it, so
-- each trigger passes the row's values as they were. The sync writes rows
-- with INSERT ... ON CONFLICT DO UPDATE, never INSERT OR REPLACE: the rows
-- REPLACE deletes fire no delete trigger unless recursive triggers are on,
-- which would leave the old text indexed. The update trigger runs only when
-- an indexed column changed, so a row whose status or indicators changed
-- costs no index writes.
CREATE TRIGGER IF NOT EXISTS search_rows_ai AFTER INSERT ON search_rows BEGIN
  INSERT INTO search_fts (rowid, employer, job, city) VALUES (new.rid, new.employer, new.job, new.city);
END;

CREATE TRIGGER IF NOT EXISTS search_rows_ad AFTER DELETE ON search_rows BEGIN
  INSERT INTO search_fts (search_fts, rowid, employer, job, city) VALUES ('delete', old.rid, old.employer, old.job, old.city);
END;

CREATE TRIGGER IF NOT EXISTS search_rows_au AFTER UPDATE ON search_rows
WHEN old.rid IS NOT new.rid OR old.employer IS NOT new.employer OR old.job IS NOT new.job OR old.city IS NOT new.city
BEGIN
  INSERT INTO search_fts (search_fts, rowid, employer, job, city) VALUES ('delete', old.rid, old.employer, old.job, old.city);
  INSERT INTO search_fts (rowid, employer, job, city) VALUES (new.rid, new.employer, new.job, new.city);
END;
