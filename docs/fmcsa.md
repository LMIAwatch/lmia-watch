# US FMCSA Company Census

Profiles show the US Federal Motor Carrier Safety Administration's census
record of a motor carrier with a Canadian address when one is matched to the
employer, in the section "US Carrier Record" ("Dossier de transporteur aux
États-Unis"). A Canadian carrier needs a USDOT number to haul into the United
States, so trucking employers are the ones that usually have a record. The
code is `pipeline/lmia_pipeline/sources/fmcsa.py`, with the rules it shares
with the other public records in `pipeline/lmia_pipeline/sources/matching.py`;
the card is drawn by `site/src/pages/employer.tsx`.

## Source

- Company Census File, Federal Motor Carrier Safety Administration,
  data.transportation.gov dataset `az4n-8mr2` (Socrata):
  https://data.transportation.gov/d/az4n-8mr2. Metadata:
  https://data.transportation.gov/api/views/az4n-8mr2.json; API:
  https://data.transportation.gov/resource/az4n-8mr2.json
- 4.4 million carriers, updated daily.
- Licence: a work of the United States government, in the public domain (the
  catalogue gives its rights as public). Credited on the Data page and in the
  footer; FMCSA does not endorse the site.

## What is read and kept

Requested from the API, and nothing else: rows where `phy_country='CA'`
(`$where`), with only these columns (`$select`): `dot_number`, `legal_name`,
`dba_name`, `phy_city`, `phy_state`, `phy_zip`, `phy_country`, `power_units`,
`total_drivers`, `safety_rating`, `safety_rating_date`, `status_code`,
`mcs150_date`, `add_date`, `business_org_desc`, `carrier_operation`. The
company officers (`company_officer_1`, `company_officer_2`), `phone`,
`cell_phone`, `fax` and `email_address` are never requested, so they are
never downloaded, let alone stored. The street address is not requested
either. Pages of 50,000 rows ordered by USDOT number are read until a short
page.

Kept, in `fmcsa_carriers`: carriers whose normalized legal or DBA name equals
the name of an employer in the same province (`phy_state`). Postal codes are
reformatted ("L5T 1B9"); older records give only "CANADA" and keep none.
Dates are read as ISO dates.

Never stored: a carrier whose business organization is INDIVIDUAL (a sole
proprietor), or whose legal name reads as one or two people
(`matching.is_person_name`). A DBA name that reads as a person is dropped from
the row. Only the count left out is logged.

## Cadence

Read at most once a month (30 days; the date is kept in the database under
`fmcsa_loaded_at`). Matching runs every night against the stored rows. A
failed request is recorded as a failed stage and tried again the next night;
the carriers already loaded stay. An answer that is not a list of records, or
that holds no Canadian carrier at all, stops the stage and keeps the previous
table.

## Join rule

| Grade | Condition | Basis shown |
|---|---|---|
| exact | The legal name normalizes to the employer's name, and the postal code equals one on the employer's own records (its row, its list rows, its postings) | name and postal code |
| probable | The name and province agree but not the postal code, or the record has none; not for a name of one word or of generic business words only | name and province |
| probable | The DBA name agrees, together with the postal code | operating name and postal code |

Nothing is matched across provinces, and a name alone never matches.

## On the profile

The card shows, for each matched record (best first, at most three: exact
before probable, active before inactive, newest record first): the USDOT
number linked to the carrier's snapshot on FMCSA's SAFER system
(`https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string=<number>`),
the legal and DBA names, the status (active, inactive, pending), power units,
drivers, the safety rating with its date ("Not rated" when there is none),
the record's date (the MCS-150 date, the carrier's latest update of its
census record) and the match.

## What a record does not mean

- A match is not an identity: a carrier with the same name elsewhere in the
  province is graded probable and can be another business.
- Power units and drivers are what the carrier reported on its census form
  at the record's date; they can be out of date.
- Most carriers are not rated. "Not rated" is the usual state and says
  nothing either way; a rating comes from an FMCSA compliance review and can
  be decades old (its date is shown).
- Nothing here is about the Temporary Foreign Worker Program, and no
  indicator reads it.
