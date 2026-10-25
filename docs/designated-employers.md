# Designated-employer lists

Under the Atlantic Immigration Program (AIP) and the Rural Community and
Francophone Community Immigration Pilots (RCIP, FCIP), a designated or
recommended employer can support a permanent-residence application without an
LMIA. The provinces and the pilot communities publish their lists; IRCC keeps
none. The site reads each list nightly, matches listed names to employer
profiles, and shows a match on the profile as a public record ("Designated
employer, Atlantic Immigration Program (Newfoundland and Labrador), listed
since ..."), with counts per list on `/international` and the lists with their
terms on the Data page. Code: `pipeline/lmia_pipeline/sources/registers.py`
(the registry `REGISTERS`, parsers, matching), cards in
`site/src/pages/employer.tsx`.

## The lists (found 2026-10-25)

None is under an open licence. The provincial lists sit under each
government's website terms; the community lists under their sites'
copyright. The site shows a matched employer's listing with a link to the list
and the count per list, and does not republish the lists.

| Key | Program, place | Format, PDF rule | State on 2026-10-25 |
|---|---|---|---|
| `aip_nb` | AIP, New Brunswick (gnb.ca PDF, bilingual) | PDF, bullet | read |
| `aip_ns` | AIP, Nova Scotia (liveinnovascotia.com, PDF of 2024-07) | PDF, bullet | the host refused connections |
| `aip_pe` | AIP, Prince Edward Island (princeedwardisland.ca, HTML list) | HTML | answers a bot challenge page |
| `aip_nl` | AIP, Newfoundland and Labrador (gov.nl.ca, HTML table with location and designation date) | HTML | 404 during a provincial site disruption |
| `rcip_pictou_county` | RCIP, Pictou County NS (link found on pcrcip.ca/employers/) | PDF, table with a status column | read |
| `rcip_north_bay` | RCIP, North Bay ON (JSON its page loads) | JSON | read |
| `rcip_sudbury`, `fcip_sudbury` | RCIP and FCIP, Sudbury ON (one page, two panels, with addresses) | HTML | read |
| `rcip_timmins`, `fcip_timmins` | RCIP and FCIP, Timmins ON (one PDF; the pilot column splits it) | PDF, table with a pilot column | read |
| `rcip_sault_ste_marie` | RCIP, Sault Ste. Marie ON | HTML | read |
| `rcip_thunder_bay` | RCIP, Thunder Bay ON (legal name, hyphen, trade name; address) | PDF, table with an address, wrapped names joined | read |
| `rcip_steinbach` | RCIP, Steinbach MB | PDF, one name a line | read |
| `rcip_altona_rhineland` | RCIP, Altona/Rhineland MB | HTML | read |
| `rcip_brandon` | RCIP, Brandon MB | HTML | TLS fails (the server omits its intermediate certificate) |
| `rcip_moose_jaw` | RCIP, Moose Jaw SK (link found on its candidates page) | PDF, two names a line | read, with wrapped names split |
| `rcip_claresholm` | RCIP, Claresholm AB (name, sector, hiring) | HTML | read |
| `rcip_west_kootenay` | RCIP, West Kootenay BC (town after the name, "Last updated" date) | HTML | read |
| `rcip_north_okanagan_shuswap` | RCIP, North Okanagan Shuswap BC (link found on its resources page) | PDF, table with a sector column | read |
| `rcip_peace_liard` | RCIP, Peace Liard BC (numbered, operating name) | PDF, numbered table | read |
| `fcip_acadian_peninsula` | FCIP, Acadian Peninsula NB (French, "name - town") | PDF, one name a line with its place | read |
| `fcip_superior_east` | FCIP, Superior East ON (the list under its heading) | HTML | read |
| `fcip_st_pierre_jolys` | FCIP, St. Pierre-Jolys MB | PDF, bullet | read |
| `fcip_kelowna` | FCIP, Kelowna BC | HTML | read |

The live read of 2026-10-25 stored 3,521 rows from 20 lists (ten HTML or JSON,
ten PDF). Moose Jaw's PDF flows two names a line and wraps long names, so some
of its rows are fragments of names; they match no employer, but they count in
that list's total.
The person test (`matching.is_person_name`) left out between a quarter and a
third of the rows of some community lists (two or three plain words with no
business word read as a person, which errs toward dropping a business).

## Reading

One request a list each night, through a client of the stage's own (two
attempts per request, failures kept out of the shared circuit breaker), with
the download cache's ETag revalidation. HTML lists are parsed with the
selector recorded for them (`selector`, `name_selector`,
`location_selector`, a `keep` pattern, a `split` rule for a town or sector on
the name, or `after`, the list under a heading); status notes such as "not
hiring at the moment" are removed from names; "X o/a Y", and a trade name and
a legal name joined by a long dash, give a legal and a trade name. A read that yields no rows, a bot
challenge, or under half the rows of the last good read is a layout problem;
a list that cannot be fetched is failing. Either way the last good rows stay
(`designated_lists.rows`, `designated_employers.last_seen`).

PDF lists are read with pypdf (pure Python, pinned in `pyproject.toml`) in its
layout mode, which keeps a table's columns apart by runs of spaces. Each line
is split into cells and the name taken by the list's rule (`pdf_mode`:
`bullet`, `table` with `pdf_name_cell`, `pdf_keep_last` and the other `pdf_*`
fields, `lines`, `columns`); headings, footers and lines that fit no rule are
skipped. The file's current address is found on its page by `link_pattern`
where the name changes with each revision. A read with fewer than 5 rows, or
with more than 60 percent fewer than the last good read, is a layout problem
and the last good rows stay; a file pypdf cannot read at all is "not yet
readable". `tests/fixtures/register_<key>.pdf` holds one real page of each
layout, chosen so that no row on it reads as a person.

## Notices (never failures), on a change of state only

- A list the night it stops being read (fetch failure or layout problem) and
  the night it is read again; nothing on the nights between.
- The set of lists not yet readable, whenever it changes.

Both are attention items in status.json (`notices`) and in the watchdog's
email, and leave the run ok. Every night, without an attention item, the lists
in each state are in the stage's summary line (LAST_RUN.md) and in
status.json's `registers.not_read`. The stage itself fails only on an exception.

## Matching

Every night, within the list's province, never across provinces
(`matching.grade`): the list's name normalizes to the employer's name and the
row's location (or one of its comma-separated parts, or the pilot community)
equals a city on the employer's records: exact (`name_city`); the name and the
province only: probable (`name_province`), not for a common name; a trade name
with the place: probable (`trade_name_city`). The profile row says "listed
since" the first night the site read the employer on the list (which can be
later than the designation) and gives the list's designation date where it
has one.

## Adding or fixing a list

Edit `REGISTERS`: a new list needs its key, program, province, community,
page address, format, terms key and selector. A community that moves its list
or changes its page markup shows as a failing or layout notice; fix the entry,
and the next night reads it again. A list that becomes HTML or a data file
moves from `pdf` to `html` or `json` with a selector.
