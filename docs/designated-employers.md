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
(the registry `REGISTERS`, parsers, matching, the copies loaded by hand),
cards in `site/src/pages/employer.tsx`.

## The lists (found 2026-10-25)

None is under an open licence. The provincial lists sit under each
government's website terms; the community lists under their sites'
copyright. The site shows a matched employer's listing with a link to the list
and the count per list, and does not republish the lists.

| Key | Program, place | Format, PDF rule | State on 2026-10-25 (changes since in brackets) |
|---|---|---|---|
| `aip_nb` | AIP, New Brunswick (gnb.ca PDF, bilingual) | PDF, bullet | read |
| `aip_ns` | AIP, Nova Scotia (liveinnovascotia.com; the file sits at a 2024-07 path and holds the July 2026 edition) | PDF, bullet | the file's host refused the runner (the page answers) [from 2026-10-30: the copy loaded by hand, see below] |
| `aip_pe` | AIP, Prince Edward Island (princeedwardisland.ca, HTML list) | HTML | answers a bot challenge page [state `blocked` from 2026-10-29] |
| `aip_nl` | AIP, Newfoundland and Labrador (gov.nl.ca, HTML table with location and designation date) | HTML | 404 during a provincial site disruption |
| `rcip_pictou_county` | RCIP, Pictou County NS (link found on pcrcip.ca/employers/) | PDF, table with a status column | read |
| `rcip_north_bay` | RCIP, North Bay ON (JSON its page loads) | JSON | read |
| `rcip_sudbury`, `fcip_sudbury` | RCIP and FCIP, Sudbury ON (one page, two panels, with addresses) | HTML | read |
| `rcip_timmins`, `fcip_timmins` | RCIP and FCIP, Timmins ON (one PDF; the pilot column splits it) | PDF, table with a pilot column | read |
| `rcip_sault_ste_marie` | RCIP, Sault Ste. Marie ON | HTML | read |
| `rcip_thunder_bay` | RCIP, Thunder Bay ON (legal name, hyphen, trade name; address) | PDF, table with an address, wrapped names joined | read |
| `rcip_steinbach` | RCIP, Steinbach MB | PDF, one name a line | read |
| `rcip_altona_rhineland` | RCIP, Altona/Rhineland MB | HTML | read |
| `rcip_brandon` | RCIP, Brandon MB | HTML | TLS fails (the server omits its intermediate certificate) [the intermediate trusted for this host from 2026-10-29, see below] |
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
(`designated_lists.rows`, `designated_employers.last_seen`). A bot challenge
in place of the list is its own state, `blocked` (below).

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

## Lists the runner cannot read as published (2026-10-29)

Three lists failed from the runner for three different reasons, each handled
on its own terms.

### A copy loaded by hand: Nova Scotia (`aip_ns`)

The province's file host refuses connections from the runner's addresses
(the page that links the file answers), while the file opens from an
ordinary machine. A register with `snapshot=True` carries a copy loaded by
hand, kept in the site's private R2 bucket `lmia-watch-data` and never in the
repository (the repository is public and the site does not republish the
lists): `registers/<key>.csv` (columns `name`, `location`, `designated_on`)
and `registers/<key>.json`, the record, with the fields `key`, `source_url`,
`etag`, `last_modified`, `size`, `sha256` (the file as the server sent it),
`list_date`, `loaded_on`, `loaded_by` (`hand`), `parser`, `rows_read`,
`rows_left_out_as_person` and `rows`. `.gitignore` keeps
`pipeline/lmia_pipeline/data/registers/` out of the repository. The registers
stage reads the two objects through the REST API with the run's token
(`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, bucket `BUCKET`;
`resilience.R2Rest.get_bytes`, `registers.r2_snapshots`), and only for a
list whose live read failed. No copy in R2, or no R2 access, leaves the list
as any failed read leaves it (on the runner, Nova Scotia is then
`unreadable` with no rows), with no item; a copy that is there and does not
read is an item needing attention. The Nova Scotia copy: the file
`https://liveinnovascotia.com/sites/default/files/2024-07/Designated_AIP_employers.pdf`
(ETag `"713d2-6562d15681934"`, Last-Modified `Thu, 09 Jul 2026 12:51:32 GMT`,
463,826 bytes), list dated 2026-07-01, loaded on 2026-10-30; 1,573 rows read
by `parse_pdf`, 51 left out as names that read as a person, 1,522 kept. The
copy never holds a name that reads as a person, and the rule is applied again
at load.

Each night the live read is tried first and takes precedence when it
succeeds. When it fails (failing, unreadable, layout or blocked), the copy's
rows become the list's current rows, state `snapshot`: they carry the day the
copy was loaded as their read time (`last_ok_at`, `last_seen`, and
`first_seen` for a new row), so reloading it each night changes nothing. A
live read made after the copy was loaded is at least as new, so when one
exists its rows stay and the failed state stands.

The newer-edition check runs every night for a list with a copy: the list's
page is read for the file's link (`link_pattern`), and the file itself is
asked for (the live read's request). A link other than the copy's address, or
a file that answers as a PDF with another ETag, Last-Modified or size, is an
item needing attention, "Nova Scotia designated-employer list: a newer edition
is published at <url> (modified <date>); load it by hand", which fails the
run's attention step and opens the issue without marking the run failed. An
unchanged link with a file that does not answer raises no item, and neither
does a block page in place of the file. A copy that does not read is an item
too. The result (`unchanged`, `newer`, `unknown`, `read live`) is in the
stage's summary line (LAST_RUN.md), in status.json's `registers.editions`
and, for an item, `registers.attention`; it is stored in `meta` under
`register_edition:<key>`.

To load a new edition: download the file from a machine the server answers,
note its ETag and Last-Modified (`curl -sI <url>`), and from `pipeline/` run
`python scripts/load_register_snapshot.py aip_ns --from <file> --url <url>
--etag '<etag>' --last-modified '<date>'` with the deploy token in the
environment (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`); without
`--from` it downloads the file itself. It parses the file locally with the
parser the nightly run uses, leaves out the names that read as a person,
uploads `registers/<key>.csv` and then `registers/<key>.json` to R2
(`R2Rest.upload`) and reads them back. `--out <folder>` writes the two
objects to a folder outside the repository instead (it refuses one inside),
for an upload by other means. Nothing is committed, neither the objects nor
the PDF. The next night the check reads unchanged and the issue closes.

The site says so: on `/international` the state reads "List dated 2026-07-01,
loaded by hand 2026-10-30" and a sentence under the totals gives the list's
date, the load day and the reason, and that the run checks every night for a
newer edition; the methodology's designated-employer paragraph carries the
same sentence; the Data page's licence row for the lists carries its first
part; a profile's listing from the copy reads "Listed on the list dated
2026-07-01, loaded by hand on 2026-10-30". All of it comes from the export
(`snapshot` on the list's row and on the profile row), so it follows the
state and disappears the night a live read succeeds.

### A site that blocks automated readers: Prince Edward Island (`aip_pe`)

The province's site answers every automated client with a Radware bot
challenge, from the runner and from a home connection alike. Nothing is done
to get past it. A challenge page in place of a list (`CHALLENGE_RE` on a body
that yields no rows, or on a body that is not the PDF expected) sets the state
`blocked`. The list is still asked for once a night, so it is read again the
night the block is lifted; a change of state stays a notice. On
`/international` the state reads "The province's site blocks automated
readers" with a blank count (never 0), and the methodology block's limits
name the list. A blocked list that was read before keeps its last good rows.

### A missing intermediate certificate: Brandon (`rcip_brandon`)

Diagnosed 2026-10-29: `economicdevelopmentbrandon.com` sends only its own
certificate (issued by "GlobalSign GCC R6 AlphaSSL CA 2025") and leaves out
the intermediate. OpenSSL with certifi's roots (the runner, and `requests` on
any machine) answers "unable to get local issuer certificate"; a Windows
client completes the chain from its own intermediate store, which is why the
site opens in a browser. The server negotiates TLS 1.2 with
ECDHE-RSA-AES256-GCM-SHA384 and needs neither `OP_LEGACY_SERVER_CONNECT` nor
a lower security level. `Register.tls_intermediate` names a PEM file in
`pipeline/lmia_pipeline/data/certs/` (the intermediate, downloaded from the
certificate's Authority Information Access address, valid to 2027-05-21);
`registers.make_client` mounts an adapter for that one host whose context is
the default verifying context plus that certificate (`http.ContextAdapter`,
`http.intermediate_context`). Host name checking and verification stay on,
every other host keeps the default adapter, and the shared client is never
touched. When the site's certificate is renewed under another intermediate,
the read fails again (a notice) and the PEM file needs the new intermediate.

## Notices (never failures), on a change of state only

- A list the night it stops being read (fetch failure, layout problem or a
  bot challenge) and the night it is read again; nothing on the nights
  between.
- A list the night its copy loaded by hand comes into use.
- The set of lists not yet readable, whenever it changes (a list that leaves
  it for its copy loaded by hand is not called readable again).

All are notices: information in status.json (`notices`), LAST_RUN.md and
the daily check's email, never an item needing attention, so the run's last
step passes, no issue opens and the run stays ok. Every night, without a notice, the lists
in each state are in the stage's summary line (LAST_RUN.md) and in
status.json's `registers.not_read`. The stage itself fails only on an
exception. The one item needing attention this stage raises is a newer
edition of a list loaded by hand, or a copy that does not read (above).

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
