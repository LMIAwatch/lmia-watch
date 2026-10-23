"""Shared rules for joining public records to employers.

Three sources attach records to employer profiles: federal grants and
contributions (grants.py), Alberta's employer injury records
(alberta_records.py) and the US carrier census (fmcsa.py). None of them
shares an identifier with the LMIA lists, so a record is joined to an
employer by its normalized name and a place, graded like the registries
(registry_federal.py, registry_quebec.py):

* exact: the record's legal name normalizes to the employer's name and the
  record's place key agrees with a place on the employer's own records (the
  postal area for grants, the city for Alberta, the postal code for the
  carrier census);
* probable: the legal name agrees and only the province does, or a name the
  record operates under agrees together with the place key.

A name alone never makes a match. Nothing is joined across provinces, and a
name that is one word or made only of generic business words ("Sunrise",
"West Coast Services") needs the place key, since a province holds many
businesses called that. A match points to a record that may concern the same
business; it is not an identity, and the profile says so beside each one.

Private individuals are never stored (rule 3 of the project): a record whose
legal name reads as one or two people is dropped before anything is written,
and an operating name that reads as a person is not kept.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from ..exclusions import BUSINESS_TOKENS
from ..household import BUSINESS_WORDS, CARE_SECTOR_WORDS, reads_as_person
from ..normalize import POSTAL_RE, PROVINCE_CODES, fold_accents, format_postal, province_code, split_trade_name
from .registry_quebec import POSTAL_PROVINCE

EXACT = "exact"
PROBABLE = "probable"
GRADE_RANK = {EXACT: 0, PROBABLE: 1}

# household.BUSINESS_WORDS reads "law" as a firm, because law firms sponsor
# nannies for clients. In these files it is a surname as often ("John A
# Smith, Ann Law" received a grant as two people), and a person read as a
# business would be published.
PUBLIC_BUSINESS_WORDS = BUSINESS_WORDS - {"law"}

# Words that name a kind of business, a place or a quality rather than one
# business. A name made only of these is common: "Canadian Farms", "West
# Coast Services", "Golden Group".
GENERIC_WORDS = frozenset(
    re.sub(r"[^\w]", "", fold_accents(w).casefold())
    for w in BUSINESS_TOKENS | CARE_SECTOR_WORDS | {
        "enterprise", "holding", "trading", "sales", "supply", "supplies", "products", "equipment", "agencies",
        "contracting", "contractor", "trucking", "transportation", "carrier", "lines", "freight", "farming",
        "ventures", "acres", "valley", "river", "mountain", "lake", "creek", "hills", "country", "city",
        "northern", "southern", "eastern", "western", "central", "united", "american", "general", "star",
        "sun", "sunrise", "sunset", "eagle", "maple", "pine", "oak", "cedar", "rose", "diamond", "silver",
        "metro", "urban", "alpine", "summit", "pioneer", "heritage", "family", "friends", "brothers",
    }
)

def first_language(text: object) -> str:
    """'Blue Buoy Foods Limited|Blue Buoy Foods Limited' -> 'Blue Buoy Foods Limited'.

    Some disclosures write a field in both languages joined by '|'; the first
    part is kept, with runs of white space made one.
    """
    return re.sub(r"\s+", " ", str(text or "").split("|", 1)[0]).strip()


def is_person_name(name: object) -> bool:
    """True when a record's name reads as one or two people (household.reads_as_person)."""
    text = first_language(name)
    if not text:
        return False
    return reads_as_person(split_trade_name(text)[0], business_words=PUBLIC_BUSINESS_WORDS)


def business_name(name: object) -> str | None:
    """A name fit to store: None when blank or when it reads as a person."""
    text = first_language(name)
    return text if text and not is_person_name(text) else None


def is_common_name(norm: str) -> bool:
    """A normalized name too common to match on the province alone."""
    tokens = norm.split()
    if not tokens:
        return True
    # A numbered company, or a name carrying a number, is specific.
    if any(ch.isdigit() for ch in norm):
        return False
    if len(tokens) == 1:
        return True
    return all(t in GENERIC_WORDS for t in tokens)


def postal_code(raw: object) -> str | None:
    """'V4G0A2', '\\nv4g 0a2' -> 'V4G 0A2'; None when the text holds no Canadian postal code."""
    m = POSTAL_RE.search(str(raw or ""))
    return format_postal(m.group(1), m.group(2)) if m else None


def province_of(raw: object, postal: str | None) -> str | None:
    """A two-letter province from the record, else from its postal code's first letter."""
    code = province_code(first_language(raw)) if raw else None
    if code in PROVINCE_CODES:
        return code
    return POSTAL_PROVINCE.get(postal[0]) if postal else None


def fold_city(raw: object) -> str:
    """'ST. ALBERT', 'Saint-Albert' and 'St Albert' all read 'st albert'."""
    text = re.sub(r"[^\w\s]", " ", fold_accents(first_language(raw)).casefold()).replace("_", " ")
    words = {"saint": "st", "sainte": "ste"}
    return " ".join(words.get(w, w) for w in text.split())


def grade(kind: str, strong: bool, weak: bool, norm: str) -> str | None:
    """The grade of one record for one employer, or None for no match.

    kind is 'legal' when the record's legal name agrees and 'other' when a
    name it operates under does; strong is the place key agreeing, weak the
    province alone.
    """
    if kind == "legal":
        if strong:
            return EXACT
        return PROBABLE if weak and not is_common_name(norm) else None
    return PROBABLE if strong and not is_common_name(norm) else None


@dataclass
class Places:
    """The places on an employer's own records: its row, its list rows and its postings."""

    province: str | None = None
    postals: set[str] = field(default_factory=set)
    cities: set[str] = field(default_factory=set)

    @property
    def areas(self) -> set[str]:
        return {p[:3] for p in self.postals}

    def add(self, city: object, postal: object) -> None:
        code = postal_code(postal)
        if code:
            self.postals.add(code)
        folded = fold_city(city)
        if folded:
            self.cities.add(folded)


def employer_places(conn: sqlite3.Connection, ids: set[str] | list[str]) -> dict[str, Places]:
    out: dict[str, Places] = {}
    ordered = sorted(set(ids))
    for i in range(0, len(ordered), 500):
        chunk = ordered[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT id, province, city, postal_code FROM employers WHERE id IN ({marks})", chunk):
            places = out.setdefault(r[0], Places())
            places.province = r[1]
            places.add(r[2], r[3])
        for table in ("esdc_records", "jobbank_postings"):
            for r in conn.execute(f"SELECT employer_id, city, postal_code FROM {table} WHERE employer_id IN ({marks})",
                                  chunk):
                out.setdefault(r[0], Places()).add(r[1], r[2])
    return out


def employer_names(conn: sqlite3.Connection, province: str | None = None) -> set[str]:
    """Every normalized employer name, or those of one province: what a load keeps."""
    sql = "SELECT DISTINCT norm_name FROM employers WHERE norm_name != ''"
    if province is None:
        return {r[0] for r in conn.execute(sql)}
    return {r[0] for r in conn.execute(sql + " AND province = ?", (province,))}


def replace_matches(conn: sqlite3.Connection, table: str, key_column: str,
                    rows: list[tuple[str, object, str, str]], stamp: str) -> int:
    """Rewrite a match table whole: (employer_id, record key, grade, basis) rows."""
    conn.execute(f"DELETE FROM {table}")
    conn.executemany(
        f"INSERT INTO {table} (employer_id, {key_column}, grade, basis, matched_at) VALUES (?, ?, ?, ?, ?)",
        [(eid, key, g, basis, stamp) for eid, key, g, basis in rows],
    )
    conn.commit()
    return len(rows)
