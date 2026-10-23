# Federal grants and contributions

Employer profiles show the federal grants and contributions that departments
disclosed to a recipient matched to the employer, in the section "Federal
Funding Received" ("Financement fédéral reçu"). The code is
`pipeline/lmia_pipeline/sources/grants.py`, with the rules it shares with the
other public records in `pipeline/lmia_pipeline/sources/matching.py`; the
section is drawn by `site/src/pages/employer.tsx`.

## Source

- Proactive Disclosure - Grants and Contributions, open.canada.ca dataset
  `432527ab-7aac-45b5-81d6-7597107a7013`:
  https://open.canada.ca/data/en/dataset/432527ab-7aac-45b5-81d6-7597107a7013
- The file read: `grants.csv` (resource `1d15a62f-5656-49ad-8c88-f40ce689d831`),
  2.3 GB on 2026-10-22, one row per agreement and per amendment. Departments
  add their agreements each quarter.
- Licence: Open Government Licence, Canada
  (https://open.canada.ca/en/open-government-licence-canada). The Data page's
  licence table and the site footer credit it.

## What is read and kept

Columns read: `ref_number`, `amendment_number`, `agreement_type`,
`recipient_type`, `recipient_business_number`, `recipient_legal_name`,
`recipient_operating_name`, `recipient_country`, `recipient_province`,
`recipient_city`, `recipient_postal_code`, `prog_name_en`, `prog_name_fr`,
`agreement_value`, `agreement_start_date`, `agreement_end_date`, `owner_org`,
`owner_org_title`. Not read: titles, descriptions, expected results, program
purposes, additional information, the research organization, the federal
riding, the NAICS code and foreign currency values.

Kept, in the table `federal_grants`: agreements with a Canadian recipient
whose normalized legal or operating name equals an employer's normalized
name, or whose business number is that of a federal corporation matched to
an employer. One row per agreement (department and reference number), taken
from its highest amendment, whose value is the amended total. A field written
in both languages ("Name|Name") keeps its first part; a province written into
the city ("Headingley, Manitoba") is read from there.

Never stored: rows of recipient type P (individuals and sole
proprietorships), and any row whose legal name reads as one or two people
(`matching.is_person_name`: the household test of `household.py`, with "law"
read as a surname). An operating name that reads as a person is dropped from
the row. Only the count of rows left out is logged.

Business numbers: the nine digits before any program account
("123456789RC0001" reads 123456789). The ninth digit is a check digit; a
number that fails it (119 of 18,156 in the first 40 MB of the file) or a
placeholder such as 000000000 is not used.

## Cadence

The file is downloaded at most once a quarter (91 days; the date is kept in
the database under `grants_loaded_at`, since the nightly runner starts with an
empty cache), streamed to `data/raw/grants/grants.csv`, read row by row and
deleted. Matching runs every night against the stored rows, so a new employer
whose name is already in the table is matched the next night, and one whose
name is not is matched after the next download.

A failed download is recorded as a failed stage (the run status lists it) and
tried again the next night; the agreements already loaded stay and are still
matched. A file without the columns above stops the stage and keeps the
previous table.

## Join rule

| Grade | Condition | Basis shown |
|---|---|---|
| exact or probable | The agreement carries the business number of the federal corporation matched to the employer (`registry_matches` and `federal_corporations`), at that registry match's grade | business number of its federal corporation |
| exact | The recipient's legal name normalizes to the employer's name, and the postal areas (first three characters) agree with one on the employer's own records (its row, its list rows, its postings) | name and postal area |
| probable | The legal name agrees and only the province does; not for a name of one word or of generic business words only | name and province |
| probable | The recipient's operating name agrees, together with the postal area | operating name and postal area |

A name alone never matches, and nothing is matched across provinces. An
agreement whose valid business number differs from the one the employer's
federal corporation has is never joined by name: it belongs to another
business with the same name.

## On the profile

The section lists the newest agreements first by start date, at most 20, and
says how many older matched agreements are not listed, with a link to the
dataset. Each row gives the start date, the program, the department, the
value, the match (grade and basis) and the agreement's record in the
government's search:
`https://search.open.canada.ca/grants/record/<department>%2C<reference number>%2Ccurrent`,
the form the search's own result links use (the agreement as last amended;
a numbered amendment in that place answers an empty page, checked
2026-10-23). The search indexes the dataset on its own schedule: an agreement
from the latest quarter can be absent from it for a time (on 2026-10-23
SSHRC's 2026-27 Q1 batch was in the dataset and not in the search), and its
record page then has no body while the dataset download carries the row.
The profile JSON carries the same rows (`grants`) and the full count
(`grants_total`).

## What a record does not mean

- A match is not an identity. It links a published record to a profile; the
  recipient can be another business with the same name, and the profile says
  so beside the table.
- A grant or contribution is a transfer under a program's terms. It says
  nothing about the employer's use of the Temporary Foreign Worker Program,
  and no indicator reads it.
- The value is the agreement's value as disclosed, as amended, not the amount
  paid. A contribution can be repayable.
- No record does not mean no funding: an agreement disclosed under another
  name, by a department that discloses late, or after the last quarterly load
  is not shown.
