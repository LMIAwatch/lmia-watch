# Zenodo DOI releases

The nightly workflow can deposit the site's Open Government Licence files on
Zenodo, which gives each release a DOI that papers and articles can cite. The
code is in `pipeline/lmia_pipeline/zenodo.py`. It does nothing until the
repository secret `ZENODO_TOKEN` exists, and it costs nothing.

## What it deposits, and when

One Zenodo record, with one version per ESDC quarter. The run deposits when
the latest ESDC period loaded (`esdc_latest_period`) differs from the one
last deposited, and once at the start when no record exists yet. On every
other night it makes no request to Zenodo at all.

Each version holds four files from that night's export:

| File | Holds |
|---|---|
| `approved_quarterly.csv` | every row of ESDC's positive LMIA employer lists |
| `refused_quarterly.csv` | every row of ESDC's negative lists, same layout |
| `esdc_resources.csv` | the ESDC source files loaded, with their SHA-256 checksums |
| `README.txt` | the version, the sources, the licence and attribution, and each file's columns, rows and checksum |

These are the files derived from ESDC's lists alone, which are published
under the Open Government Licence, Canada. The other downloads stay out:
`pending_observations.csv` and `findings.csv` are Job Bank and IRCC material
reproduced under canada.ca's terms, and `employers.csv` and `indicators.csv`
mix in Job Bank postings, IRCC findings and registry matches, including the
Quebec register, which is CC BY-NC-SA.

The metadata: title "LMIA Watch: ESDC positive and negative LMIA employer
lists, derived files", creator `LMIA Watch`, version the quarter (for
example `2026Q1`), licence Open Government Licence - Canada, keywords, and
related identifiers for the site, the Methodology page and the two ESDC
datasets on open.canada.ca.

The run records the version DOI and the concept DOI (which always resolves
to the newest version) in the database. The next night's export writes them
into `stats.json`, and the Data and Methodology pages then show a "How to
cite" block. Until a DOI exists the block is hidden.

## A DOI is permanent

A published Zenodo version cannot be deleted. It can only be superseded by a
newer version, and its DOI keeps resolving to it, with a note that a newer
version exists. So:

- Test on the sandbox first (step 2). Its test DOIs do not resolve, and the
  pipeline keeps sandbox records apart from production ones, so a trial never
  reaches the site.
- The code publishes only after every file has uploaded and the metadata is
  set. A failure on the way discards the draft, so a half-made version is
  never published.

## 1. Pseudonymity

Zenodo accounts can be opened by signing in with GitHub, so the project's
GitHub account serves and no new email address or password is needed.
Zenodo receives the GitHub account's public profile and its sign-in address
(the plus-alias), which Zenodo does not show on records. The records name
`LMIA Watch` as creator, with no ORCID and no affiliation.

Use the project's browser profile, signed in to the project's GitHub
account, and never a personal one.

## 2. Sandbox first

1. Open `sandbox.zenodo.org`, Log in, Log in with GitHub. Authorize the
   Zenodo application for the project's GitHub account.
2. In the account settings, Profile: set the name to `LMIA Watch` or leave
   it empty, and keep the profile private if Zenodo offers the choice.
3. Applications, Personal access tokens, New token. Name: `nightly
   workflow`. Scopes: `deposit:write` and `deposit:actions`, nothing else.
   Create, and copy the token (it is shown once).
4. GitHub, the repository, Settings, Secrets and variables, Actions:
   - Secrets tab: `ZENODO_TOKEN`, the sandbox token.
   - Variables tab: `ZENODO_SANDBOX`, value `true`.
5. The next scheduled run makes the first sandbox record, since none exists
   yet. The step "Deposit a new ESDC quarter on Zenodo" in the Actions run
   logs the result and the test DOI.
6. Check the record on sandbox.zenodo.org (your uploads): four files, the
   version, the licence shown as Open Government Licence - Canada, the
   description and the related links. If Zenodo refused a field, the step
   log quotes its answer (for example `set the metadata: HTTP 400 ...`), and
   the draft was discarded.

Optional, before step 4, from the project account's own machine:

```
cd pipeline
pip install -e .[dev]
python -m lmia_pipeline deposit-zenodo --db ../data/lmia.sqlite --dry-run
```

This checks the CSV export (`data/out/csv`), lists the files and their row
counts, and calls nothing. It needs no token.

## 3. Production

1. Open `zenodo.org` (a separate site from the sandbox, with its own
   accounts), Log in with GitHub, and set the profile as in step 2.
2. Make a production token with the same two scopes.
3. Replace the `ZENODO_TOKEN` secret with the production token, and delete
   the `ZENODO_SANDBOX` variable (or set it to `false`).
4. The next scheduled run makes the production record, whatever the quarter,
   since no production record exists yet. After that it adds a version only
   when a new ESDC quarter is loaded, about four times a year.

## What a published record looks like

The record page on zenodo.org shows the title, `LMIA Watch` as creator, the
publication date, the version (the quarter), the licence, the description
with its file list, the keywords, the related links and the four files with
their sizes and checksums. The side panel shows the version's DOI
(`10.5281/zenodo.<number>`), a "Cite all versions" DOI (the concept DOI),
the list of versions, and citation formats.

## When something goes wrong

- A failed deposit (Zenodo down, a refused field, a revoked token) discards
  the draft, writes `failed` as `zenodo_deposit` in the run status, lists it
  in the workflow's last step (so the run is marked failed and GitHub
  emails), and the Worker's daily check emails the alert address. The quarter
  is not recorded, so the next night tries again. The database save and the
  rest of the run carry on either way.
- A version Zenodo published that the database does not know of (the answer
  to the publish was lost on the way back, or the night's database save
  failed after the deposit and the run restored the night before's copy):
  before making a draft, the job asks Zenodo what it already holds and adopts
  a published version of the quarter instead of depositing a second one,
  recording its DOIs and writing `already deposited` as `zenodo_deposit`.
  When Zenodo cannot answer that question, nothing is deposited that night
  and the outcome is `failed`.
- A version with a mistake: correct the data, then either wait for the next
  quarter or publish a corrected version by hand on the record's page (New
  version). The nightly job always builds on the newest version, including
  one made by hand.
- Stopping: delete the `ZENODO_TOKEN` secret. To revoke access, delete the
  token on Zenodo's Applications page.

## Sources (read 2026-10-18)

- Zenodo REST API (base URLs, token scopes, create, upload to the bucket,
  metadata, publish, new version, deletion only of unpublished drafts, rate
  limits): `developers.zenodo.org`
- Open Government Licence - Canada: `open.canada.ca/en/open-government-licence-canada`;
  SPDX identifier `OGL-Canada-2.0` (`spdx.org/licenses/OGL-Canada-2.0`)
