# Alberta Employer Records

Profiles of Alberta employers show Alberta's record of the employer as a
workers' compensation account, matched by name and city, in the section
"Alberta Employer Record" ("Dossier d'employeur de l'Alberta"). The code is
`pipeline/lmia_pipeline/sources/alberta_records.py`, with the rules it shares
with the other public records in `pipeline/lmia_pipeline/sources/matching.py`;
the card is drawn by `site/src/pages/employer.tsx`.

## Source

- Employer Records, Alberta Jobs, Economy, Trade and Immigration:
  https://open.alberta.ca/opendata/employer-records (CKAN listing:
  https://open.alberta.ca/api/3/action/package_show?id=employer-records)
- The file read: "Employer Records, 2020-2024", an XLSX workbook of 53 MB
  dated 2025-12-16, published once a year. Figures are those reported to the
  Workers' Compensation Board by March 31 for employers required to hold an
  account.
- Licence: Open Government Licence, Alberta (https://open.alberta.ca/licence).
  Attribution: "Contains information licensed under the Open Government
  Licence, Alberta." The Data page's licence table and the site footer credit
  it.

## What is read and kept

Only the sheet whose name starts with "Injury" ("Injury (2020-2024)", 841,761
rows, one per account and year). Columns kept: `EMP_KEY` (the publisher's
opaque key for the account), `EMPLOYER_NAME`, `TRADE_NAME`, `CITY_NAME`,
`WCB_INDUSTRY_NAME`, `WCB_INDUSTRY_CODE`, `COR_YEAR`, `YEAR_NO`,
`PERSON_YEARS_COUNT`, `LOST_TIME_CLAIM_COUNT`, `LOST_TIME_CLAIM_RATE`,
`ANNUAL_FATALITY_COUNT`, `ANNUAL_DISABLING_INJURIES_COUNT`,
`DISABLING_INJURIES_RATE`. Not kept: the fatality split by cause. Not read:
the workbook's other sheets (orders, penalties, tickets, investigations,
acceptances, approvals, convictions).

Kept, in `alberta_employer_records`: the rows of accounts whose normalized
legal or trade name equals the name of an employer in Alberta. Some accounts
are listed under two names for the same year with the same figures (1,394
account-years in the 2020-2024 file: a numbered company and the name it
operates under, or a former name and the current one); each name is kept as
a row and matched. The 2020-2024 file leaves `TRADE_NAME` and `COR_YEAR`
empty on every row and `CITY_NAME` empty on 22 percent of rows.

Never stored: an account any of whose names reads as one or two people
(`matching.is_person_name`). The file has no legal-form column, so this is how
sole proprietors, who register under their own name, are left out. A trade
name that reads as a person is dropped from the row. Only the count of
accounts left out is logged.

## Cadence

The listing is read at most every 30 days. The workbook is downloaded when
the listing shows a new or changed file, and otherwise when the last load is
91 days old, so an Alberta employer first seen since then is matched within a
quarter. Matching runs every night against the stored rows. A failed request
is recorded as a failed stage and tried again the next night; the rows
already loaded stay. A workbook without the Injury sheet or its columns stops
the stage and keeps the previous table.

## Join rule

Alberta employers only.

| Grade | Condition | Basis shown |
|---|---|---|
| exact | One of the account's names normalizes to the employer's name, and its city agrees with a city on the employer's own records | name and city |
| probable | The name agrees and the city differs or is blank; not for a name of one word or of generic business words only | name and province |
| probable | The trade name agrees, together with the city | trade name and city |

An employer outside Alberta is never compared. Cities are compared with
accents, case and punctuation set aside, and "Saint" read as "St".

## On the profile

The card shows, for each matched account (best first, at most three): the
account name that matched, the latest year and the first year on file, the
city, the WCB industry, person-years (full-time equivalents), lost-time
claims and disabling injuries with their rates per 100 person-years when the
file gives one, fatalities, the certificate of recognition year ("Not given in
this release" while the file leaves it empty) and the match. It carries the
sentence that this is Alberta's record of the employer as a workers'
compensation account, matched by name and city, and links to the dataset.

The home page names these records in its lede and in "How to Read This Site",
linked to the public-records paragraph of the Data page; `stats.json`'s
`counts` carries `alberta_employers`, the employers with a matched account.

## What a record does not mean

- A match is not an identity: an Alberta account with the same name in
  another city is graded probable and can belong to another business.
- Claims, injuries and fatalities are counts of accepted workers'
  compensation claims. They are not findings of fault, and they depend on the
  size and kind of work: read them with the person-years and the industry.
- A blank cell is shown as "not given": the file gives no figure, which is not
  the same as a published zero.
- Nothing here is about the Temporary Foreign Worker Program, and no
  indicator reads it.
