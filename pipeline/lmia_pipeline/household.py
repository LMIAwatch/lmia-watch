"""Keep private households out of the ESDC lists.

ESDC's positive and negative lists say they leave out personal names, yet some
get through: a person who hired a home child care provider or a home support
worker, listed under the person's own name. A private home is not a business
and the person is not a public employer, so those rows are kept out the way
Job Bank household postings are (exclusions.is_private_household): not loaded,
not counted, not shown. The mirrored files stay as ESDC published them; only
the parsed rows are affected.

A row is a household when both hold:

1. The occupation is a household one: NOC 2011 4411 and 4412 or their NOC 2021
   successors 44100 and 44101, by code when the row carries one, otherwise by
   the title (HOUSEHOLD_TITLE_RE).
2. The employer name reads as one or two people (reads_as_person): no legal
   form, no trade-name marker, no business word, and two to four name words.

A name alone is not enough. The lists carry thousands of farms, trucking firms
and shops registered under the owner's name, and a sole proprietorship called
"Jan de Vries" that grows berries is a business the lists rightly show. An
occupation alone is not enough either: of the 417 rows with a household
occupation in the files from 2016 to 2026 Q1, more than nine in ten name a home
care agency, a care home, a co-operative, a society or a health authority,
which are employers like any other. The rule therefore needs both.

The 2014 and 2015 files name no occupation, so the rule cannot apply to them;
those rows stay as published.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping

from .exclusions import BUSINESS_TOKENS, name_words
from .normalize import LEGAL_SUFFIXES, fold_accents, has_legal_form, is_numbered_company, split_trade_name

HOUSEHOLD_NOC_CODES = frozenset({"4411", "4412", "44100", "44101"})

# Used only when a row has no occupation code. Every file since 2016 writes
# the code and the English title together, in exactly these four forms:
#   4411-Home child care providers
#   4412-Home support workers, housekeepers and related occupations
#   44100-Home child care providers
#   44101-Home support workers, caregivers and related occupations
# The French forms are the NOC titles for the same codes ("Gardiens/gardiennes
# d'enfants en milieu familial"; "Aides familiaux résidants/aides familiales
# résidantes, aides de maintien à domicile et personnel assimilé"; "Aides de
# maintien à domicile, aides familiaux/aides familiales et personnel
# assimilé"), plus the single-job words the same groups cover. Titles are
# compared with accents folded. "Executive housekeepers" (NOC 6312, 62021) run
# hotels and are not a household occupation, and "gouvernante" is left out for
# the same reason.
HOUSEHOLD_TITLE_RE = re.compile(
    r"home child ?care providers?"
    r"|home support workers?"
    r"|(?<!executive )housekeepers?"
    r"|nann(?:y|ies)"
    r"|(?:live-in )?care ?givers?"
    r"|baby-?sitters?"
    r"|parents?'? helpers?"
    r"|gardien(?:ne)?s?(?:/gardiennes?)? d'enfants"
    r"|aides? de maintien a domicile"
    r"|aides?[ -]famili(?:aux|ales?|al)"
    r"|aides? parenta(?:l|ux)"
    r"|nourrices?"
    r"|bonnes? d'enfants",
    re.I,
)

# Words that mark a business. The Job Bank list (exclusions.BUSINESS_TOKENS)
# is the base, less the words that are also common names or name particles:
# a person called White, West or de Vries hiring a nanny must still read as a
# person. "and" and "et" join two people here, so they are not business words.
NAME_LIKE_WORDS = {
    "and", "et", "de", "du", "des", "la", "le",
    "white", "black", "green", "red", "blue", "golden", "best", "house", "lodge",
    "barber", "glass", "steel", "fish", "honey", "berry", "marine", "temple",
    "church", "west", "east", "north", "south",
}

# Added from the employers with a household occupation in the files from 2016
# to 2026 Q1: home care agencies, care homes, co-operatives, societies, health
# authorities, First Nations, municipalities and firms that sponsor a nanny for
# a client. "law" stays a business word because firms appear as "<surname>
# Law"; the cost is that a household named, say, "Ann Law" would be kept.
CARE_SECTOR_WORDS = {
    "care", "caring", "carehome", "caregiver", "caregivers", "nanny", "nannies",
    "childcare", "homecare", "homemakers", "home", "healthcare", "nursing",
    "nurse", "nurses", "rehab", "support", "supports", "supportive", "assistance",
    "assisted", "living", "lifestyles", "senior", "seniors", "retirement",
    "residence", "residences", "residential", "resthome", "manor", "estate",
    "estates", "villa", "village", "community", "communities", "resources",
    "agency", "employment", "personnel", "immigration", "institute", "ministry",
    "cooperative", "coop", "solidarite", "aide", "soutien", "domicile", "foyer",
    "development", "law", "legal", "special", "needs", "independence",
    "independent", "families", "nation", "nations", "county", "municipality",
    "city", "district", "government", "authority", "ciusss", "cisss", "program",
    "programs", "concierge", "lodging", "hotels", "entertainment", "parenting",
    "facility", "facilities", "relations", "supply", "retreat", "glamping",
    "comfort", "staff",
    # Child care and placement businesses as the lists name them under the
    # neighbouring early childhood occupations, in both languages.
    "dayhome", "dayhomes", "preschool", "montessori", "playschool", "kids",
    "children", "placement", "recruitment", "recruiting", "garderie",
    "garderies", "cpe", "agence", "gestion", "ressource", "ressources",
    "habitation", "soins", "sante", "accueil", "accueils", "entretien",
    "menage", "chateau", "manoir",
}


def _key(word: str) -> str:
    """'Ltée' -> 'ltee', 'S.E.N.C' -> 'senc', "O'Neil" -> 'oneil': the form words are compared in."""
    return re.sub(r"['’.]", "", fold_accents(word.casefold()))


BUSINESS_WORDS = frozenset({_key(w) for w in BUSINESS_TOKENS} - NAME_LIKE_WORDS | CARE_SECTOR_WORDS)
LEGAL_WORDS = frozenset(LEGAL_SUFFIXES)

# Words that join a name without being one: particles and honorifics. They
# neither count toward the two to four words nor mark a business.
NAME_PARTICLES = {
    "de", "da", "das", "do", "dos", "du", "del", "della", "di", "van", "von", "der",
    "den", "ter", "ten", "la", "le", "st", "ste", "bin", "binti", "ibn", "al", "el",
    "y", "mr", "mrs", "ms", "miss", "dr", "mme", "mlle",
}

# A household sometimes describes itself next to the name ("Private
# Childcare/Reyes Family"); the description is set aside before the name is
# read, and "family" or "famille" counts as a name word.
HOUSEHOLD_PHRASE_RE = re.compile(
    r"\bprivate (?:child ?care|household|home|residence|family)\b|\b(?:household|particulier|menage prive)\b",
    re.I,
)
# What joins two people in one name: "A, B", "A and B", "A & B", "A / B",
# "A (B)".
PERSON_SEPARATOR_RE = re.compile(r"\s*(?:[,;/&()+]|\band\b|\bet\b)\s*", re.I)


def _person_shape(words: list[str]) -> bool:
    """Two to four name words besides particles, at least one longer than an initial."""
    counted = [w for w in words if _key(w) not in NAME_PARTICLES]
    if not 2 <= len(counted) <= 4:
        return False
    return any(len(_key(w)) >= 2 for w in counted)


def reads_as_person(name: str | None) -> bool:
    """True when an employer name reads as one or two people and not as a business.

    The business words are built for names that already carry a household
    occupation, where the choice is between a person and a care business. On
    its own this is not a general test for a person's name: across all
    occupations it would read many short trade names ("Silo Films") as people.
    """
    if not name or not name.strip():
        return False
    text = re.sub(r"\s+", " ", fold_accents(name)).strip()
    if is_numbered_company(text) or has_legal_form(text) or re.search(r"[\d@#]", text):
        return False
    # "John Smith o/a Smith Farms": a trade name means a business.
    if split_trade_name(text)[1] is not None:
        return False
    text = HOUSEHOLD_PHRASE_RE.sub(" ", text)
    words = name_words(text)
    keys = [_key(w) for w in words]
    if not keys or any(k in LEGAL_WORDS or k in BUSINESS_WORDS for k in keys):
        return False
    if _person_shape([w for w, k in zip(words, keys) if k not in {"and", "et"}]):
        return True
    # Two people of two or three words each ("Maria Clara Santos, Jose Luis
    # Santos") run past four words; read each side as its own person.
    parts = [p for p in PERSON_SEPARATOR_RE.split(text) if name_words(p)]
    return 2 <= len(parts) <= 3 and all(_person_shape(name_words(p)) for p in parts)


def is_household_occupation(noc_code: str | None, noc_title: str | None) -> bool:
    code = (noc_code or "").strip()
    if code:
        return code in HOUSEHOLD_NOC_CODES
    if not noc_title:
        return False
    title = re.sub(r"\s+", " ", fold_accents(noc_title).replace("’", "'"))
    return HOUSEHOLD_TITLE_RE.search(title) is not None


def is_household_record(
    employer_raw: str | None,
    noc_code: str | None,
    noc_title: str | None,
    address_raw: str | None = None,
) -> bool:
    """True for an ESDC list row whose employer is a private household.

    address_raw is taken so a caller hands over the whole row, but it does not
    change the answer: the files that name an occupation (2016 on) give only
    a city and postal code, which cannot tell a home from a business.
    """
    return is_household_occupation(noc_code, noc_title) and reads_as_person(employer_raw)


def is_household_row(rec: Mapping) -> bool:
    """is_household_record on a normalize_row() dict or an esdc_records row."""
    return is_household_record(rec["employer_raw"], rec["noc_code"], rec["noc_title"], rec["address_raw"])


def remove_household_rows(conn: sqlite3.Connection) -> dict[str, int]:
    """Delete household rows loaded before the rule existed.

    Idempotent, like esdc.remove_summary_rows: the esdc stage runs it every
    night and once the rows are gone it finds nothing. Employers left with no
    list row, posting or finding are deleted with their names, registry
    matches, registry checks and indicators; the loaded-row count of each
    touched resource is recounted. status.recompute, which runs after the
    sources, recounts everything else.
    """
    placeholders = ",".join("?" * len(HOUSEHOLD_NOC_CODES))
    candidates = conn.execute(
        "SELECT id, employer_id, resource_id, employer_raw, address_raw, noc_code, noc_title, positions "
        f"FROM esdc_records WHERE noc_code IN ({placeholders}) OR (noc_code IS NULL AND noc_title IS NOT NULL)",
        sorted(HOUSEHOLD_NOC_CODES),
    ).fetchall()
    doomed = [r for r in candidates if is_household_row(r)]
    if not doomed:
        return {"rows": 0, "positions": 0, "employers": 0}
    conn.executemany("DELETE FROM esdc_records WHERE id = ?", [(r["id"],) for r in doomed])
    for rid in sorted({r["resource_id"] for r in doomed}):
        conn.execute(
            "UPDATE esdc_resources SET rows_loaded = (SELECT COUNT(*) FROM esdc_records WHERE resource_id = ?) "
            "WHERE resource_id = ?",
            (rid, rid),
        )
    orphans = [
        (eid,) for eid in sorted({r["employer_id"] for r in doomed})
        if not conn.execute(
            "SELECT 1 FROM esdc_records WHERE employer_id = ? UNION ALL SELECT 1 FROM jobbank_postings WHERE employer_id = ? "
            "UNION ALL SELECT 1 FROM findings WHERE employer_id = ? LIMIT 1",
            (eid, eid, eid),
        ).fetchone()
    ]
    for table in ("employer_names", "registry_matches", "registry_checks", "indicators"):
        conn.executemany(f"DELETE FROM {table} WHERE employer_id = ?", orphans)
    conn.executemany("DELETE FROM employers WHERE id = ?", orphans)
    conn.commit()
    return {
        "rows": len(doomed),
        "positions": sum(r["positions"] or 0 for r in doomed),
        "employers": len(orphans),
    }
