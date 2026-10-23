"""Name, address, date and code normalization used by every source."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime

# Bump whenever norm_name or split_trade_name changes what a name normalizes
# to. Employer ids are a hash of the normalized name, so the pipeline compares
# this with meta.normalize_version and re-derives every id once (migrate.py).
NORMALIZE_VERSION = 2

# Trailing tokens that distinguish a legal form, not a business. Stripped
# repeatedly from the end so "x services ltd" and "x services limited
# partnership" both normalize to "x services". Accents are folded first, so
# "ltée" arrives here as "ltee" and "S.E.C." as "sec".
LEGAL_SUFFIXES = {
    "ltd", "ltee", "limited", "limitee", "inc", "incorporated", "incorporee",
    "corp", "corporation", "ulc", "llp", "llc", "lp", "co", "company", "cie",
    "compagnie", "senc", "sencrl", "sec", "enr", "enrg", "partnership", "plc",
}

# Jurisdiction words in numbered company names ("0704250 B.C. Ltd.",
# "101184720 SK Ltd", "1174724 Ont. Inc.", "9123-4567 Québec inc."), mapped to
# one spelling so the same number in the same province is one employer.
NUMBERED_JURISDICTIONS: dict[tuple[str, ...], str] = {
    ("bc",): "bc", ("british", "columbia"): "bc",
    ("alberta",): "alberta", ("alta",): "alberta", ("ab",): "alberta",
    ("saskatchewan",): "saskatchewan", ("sask",): "saskatchewan", ("sk",): "saskatchewan",
    ("manitoba",): "manitoba", ("man",): "manitoba", ("mb",): "manitoba",
    ("ontario",): "ontario", ("ont",): "ontario", ("on",): "ontario",
    ("quebec",): "quebec", ("que",): "quebec", ("qc",): "quebec",
    ("new", "brunswick"): "nb", ("nb",): "nb",
    ("nova", "scotia"): "nova scotia", ("ns",): "nova scotia",
    ("prince", "edward", "island"): "pei", ("pei",): "pei", ("pe",): "pei",
    ("northwest", "territories"): "nwt", ("nwt",): "nwt", ("nt",): "nwt",
    ("yukon",): "yukon", ("yt",): "yukon",
    ("nunavut",): "nunavut", ("nu",): "nunavut",
    ("canada",): "canada", ("can",): "canada", ("cda",): "canada",
}
NUMBERED_MIN_DIGITS = 5

# "&" is punctuation and drops out, so "and" and "et" drop out too: "Smith &
# Sons", "Smith and Sons" and "Smith Sons" are one name.
CONNECTORS = {"and", "et"}

# A trade-name marker starts a word: after a space, a bracket or other
# punctuation, or after a dot that ends a word of two letters or more
# ("Ltd.o/a") or stands alone ("Ltd .o/a"). A dot after a single letter does
# not count, which keeps "G.O.A.T." from reading as "o.a.".
_MARK_BEFORE = r"(?:(?<![\w.])|(?<=\w\w\.)|(?<=\s\.))"
_TRADE_MARKERS = [
    r"d\.\s*b\.\s*a\.?(?!\w)",                       # d.b.a. and d.b.a
    r"d\s*/\s*b\s*/\s*a(?!\w)",                      # d/b/a
    r"dba(?!\w)",
    r"o\s*/\s*a(?!\w)",                              # o/a
    r"o\.\s*a\.(?!\w)",                              # o.a.
    r"t\s*/\s*a(?!\w)",                              # t/a, trading as
    r"(?:operating|doing\s+business|trading)\s+as(?!\w)",
    r"carrying\s+on\s+business\s+(?:as|under\s+the\s+name(?:\s+of)?|under)(?!\w)",
    r"c\.\s*o\.\s*b\.?(?!\w)",                       # c.o.b., carrying on business
    r"faisant\s+affaires?\s+(?:sous|comme)(?:\s+(?:le\s+nom|la\s+raison\s+sociale))?"
    r"(?:\s+de(?!\w)|\s+d['’]|(?!\w))",
    r"f\.\s*a\.\s*s\.(?:\s*n\.)?(?!\w)",             # f.a.s. and f.a.s.n., faisant affaire sous (le nom)
    r"(?:op[eé]rant|exploitant)\s+sous\s+(?:le\s+nom|la\s+raison\s+sociale)"
    r"(?:\s+de(?!\w)|\s+d['’]|(?!\w))",
]
# "c/o" names whoever the mail goes to (often a person), not a trade name, so
# what follows it is dropped rather than recorded.
_CARE_OF_MARKERS = [r"c\s*/\s*o(?!\w)", r"care\s+of(?!\w)"]
MARKER_RE = re.compile(
    _MARK_BEFORE
    + "(?:(?P<trade>" + "|".join(_TRADE_MARKERS) + ")"
    + "|(?P<care>" + "|".join(_CARE_OF_MARKERS) + ")"
    # Bare "cob" is a word in some names ("Cob Roller Farms"), so it counts only
    # straight after a legal form ("GPC Investments Limited cob Comfort Inn").
    + r"|(?P<cob>cob(?!\w)))",
    re.I,
)
_HAS_WORD = re.compile(r"[^\W_]")
_QUOTES = "\"'“”‘’«»�"

# Single letters each followed by a dot ("B.C.", "U.S.A.", "S.E.C.", "B. C.")
# form one abbreviation. The dots are removed so "B.C." reads "bc", as most
# sources spell it, rather than the two tokens "b c". A last letter without
# its dot joins only when nothing separates it ("B.C Ltd"), so the initials in
# "W.J. O'Neil" stay apart from the surname.
ABBREV_RE = re.compile(
    r"(?<![^\W\d_])(?:[^\W\d_]\.(?:\s(?=[^\W\d_]\.))?)+(?:(?<=\.)[^\W\d_](?![^\W\d_]))?"
)
# An apostrophe inside a word is removed, not turned into a space, so
# "Horton's" and "Hortons", "O'Neil" and "ONeil" agree.
APOSTROPHE_RE = re.compile(r"(?<=[^\W\d_])['’‘`´](?=[^\W\d_])")

PROVINCES: dict[str, str] = {
    "alberta": "AB", "british columbia": "BC", "colombie-britannique": "BC",
    "manitoba": "MB", "new brunswick": "NB", "nouveau-brunswick": "NB",
    "newfoundland and labrador": "NL", "newfoundland": "NL", "terre-neuve-et-labrador": "NL",
    "nova scotia": "NS", "nouvelle-ecosse": "NS", "nouvelle-écosse": "NS",
    "northwest territories": "NT", "territoires du nord-ouest": "NT",
    "nunavut": "NU", "ontario": "ON", "prince edward island": "PE",
    "ile-du-prince-edouard": "PE", "île-du-prince-édouard": "PE",
    "quebec": "QC", "québec": "QC", "saskatchewan": "SK", "yukon": "YT",
    "yukon territory": "YT",
}
PROVINCE_CODES = set(PROVINCES.values())

# Statistics Canada's two-digit province codes (the first digits of every
# census geography code) and the English names the site shows.
PRUID_PROVINCE: dict[str, str] = {
    "10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC", "35": "ON",
    "46": "MB", "47": "SK", "48": "AB", "59": "BC", "60": "YT", "61": "NT", "62": "NU",
}
PROVINCE_NAMES: dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}

POSTAL_RE = re.compile(
    r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s*(\d[ABCEGHJ-NPRSTV-Z]\d)\b", re.I
)
# Four or five digits and not a sixth: a longer number is not a NOC code
# and must not read as a five-digit code with a title starting in a digit.
NOC_RE = re.compile(r"^\s*(?:NOC\s*)?(\d{4,5})(?!\d)\s*[-:.]?\s*(.*?)\s*$")
PERIOD_RE = re.compile(r"(20\d\d)\s*[-_ ]?q([1-4])(?:\s*[-_ ]?q([1-4]))?", re.I)
YEAR_RE = re.compile(r"(20\d\d)")

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


# En and em dashes, built here so the module holds neither character.
_DASHES = chr(0x2013) + chr(0x2014)
_LEGAL_TAIL = " ,;:-/\\(" + _DASHES
_OPERATING_HEAD = " ,;:-)/\\." + _DASHES
_OPERATING_TAIL = " ,;:-/\\" + _DASHES


def _clean_legal(text: str) -> str:
    text = text.rstrip(_LEGAL_TAIL)
    # "Ltd .o/a" leaves a stray dot after a space.
    return re.sub(r"\s+\.+$", "", text).rstrip(_LEGAL_TAIL).strip()


def _clean_operating(text: str) -> str:
    text = text.strip().lstrip(_OPERATING_HEAD).rstrip(_OPERATING_TAIL)
    # "(o/a NTE)" leaves an unbalanced closing bracket behind.
    while text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].rstrip(" ,;:")
    return text.strip(_QUOTES + " ")


def has_legal_form(text: str | None) -> bool:
    """True when a name ends in a legal form (Ltd., Inc., Ltée, S.E.N.C.)."""
    if not text:
        return False
    text = ABBREV_RE.sub(_join_abbreviation, fold_accents(text.casefold()))
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    return bool(tokens) and tokens[-1] in LEGAL_SUFFIXES


def is_numbered_company(text: str | None) -> bool:
    """'0704250 B.C. Ltd.', '9123-4567 Québec inc.': a company named by its number."""
    if not text:
        return False
    m = re.match(r"\s*(\d[\d\s-]*)", text)
    return bool(m) and len(re.sub(r"\D", "", m.group(1))) >= NUMBERED_MIN_DIGITS


def split_trade_name(raw: str | None) -> tuple[str, str | None]:
    """'0704250 BC Ltd. dba Assi Supermarket' -> ('0704250 BC Ltd.', 'Assi Supermarket').

    The part before the first trade-name marker (dba, d/b/a, o/a, t/a,
    operating as, doing business as, trading as, carrying on business as,
    c.o.b., faisant affaire sous, f.a.s.) is the legal name, which is the
    identity; the part after it is the operating name. After "c/o" the second
    part is dropped. A marker with nothing on one side is not a split, and a
    name without a marker comes back whole with None.
    """
    if not raw:
        return "", None
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw)).strip()
    for m in MARKER_RE.finditer(text):
        legal = _clean_legal(text[: m.start()])
        if not _HAS_WORD.search(legal):
            continue
        if m.group("cob") and not has_legal_form(legal):
            continue
        rest = text[m.end():]
        if not _HAS_WORD.search(rest):
            continue
        if m.group("care"):
            return legal, None
        operating = _clean_operating(rest)
        # "dba t/a Picardie Farms": a second marker straight after the first.
        while (again := MARKER_RE.match(operating)) and again.group("trade"):
            operating = _clean_operating(operating[again.end():])
        if not _HAS_WORD.search(operating):
            continue
        return legal, operating
    return text, None


def fold_accents(text: str) -> str:
    """'québec ltée' -> 'quebec ltee'. Sources spell one name with and without accents."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped).replace("œ", "oe").replace("æ", "ae")


def _join_abbreviation(m: re.Match) -> str:
    letters = re.sub(r"[.\s]", "", m.group(0))
    # A lone initial keeps its word break ("G.Mann" reads like "G. Mann"), and a
    # closing dot still separates what follows ("B.C.Ltd" reads "bc ltd").
    if len(letters) < 2 or m.group(0).endswith("."):
        return letters + " "
    return letters


def _join_initials(tokens: list[str]) -> list[str]:
    """['j', 'm', 'peeters'] -> ['jm', 'peeters']: 'J M Peeters' agrees with 'J.M. Peeters'."""
    out: list[str] = []
    run: list[str] = []
    for tok in tokens + [""]:
        if len(tok) == 1 and tok.isalpha():
            run.append(tok)
            continue
        if run:
            out.append("".join(run))
            run = []
        if tok:
            out.append(tok)
    return out


def _canon_numbered(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and tokens[i].isdigit():
        i += 1
    if i == 0 or len("".join(tokens[:i])) < NUMBERED_MIN_DIGITS:
        return tokens
    for width in (3, 2, 1):
        key = tuple(tokens[i:i + width])
        if len(key) == width and key in NUMBERED_JURISDICTIONS:
            return tokens[:i] + NUMBERED_JURISDICTIONS[key].split() + tokens[i + width:]
    return tokens


def norm_legal(text: str | None) -> str:
    """Normalize a name taken as a legal name as it stands, with no trade-name split."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text).casefold()
    text = ABBREV_RE.sub(_join_abbreviation, text)
    text = APOSTROPHE_RE.sub("", text)
    text = fold_accents(text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.replace("_", " ")
    tokens = text.split()
    if any(tok not in CONNECTORS for tok in tokens):
        tokens = [tok for tok in tokens if tok not in CONNECTORS]
    tokens = _canon_numbered(_join_initials(tokens))
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def norm_name(raw: str | None) -> str:
    """Identity form of a name: '0704250 B.C. Ltd. o/a Assi Supermarket' -> '0704250 bc'.

    In order: the legal part only (split_trade_name); casefold; dots out of
    single-letter abbreviations and apostrophes out of words; accents folded;
    other punctuation to spaces; "and" and "et" dropped; runs of single
    letters joined; the jurisdiction in a numbered company name spelled one
    way; legal suffixes stripped from the end.
    """
    if not raw:
        return ""
    legal, _ = split_trade_name(raw)
    return norm_legal(legal)


def employer_id(norm: str, province: str | None) -> str:
    digest = hashlib.sha1(f"{norm}|{province or ''}".encode("utf-8")).hexdigest()
    return f"emp-{digest[:10]}"


def province_code(raw: str | None) -> str | None:
    """Two-letter code from a full name or code; 'XX' for head office outside Canada."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if "outside of canada" in text.lower() or "outside canada" in text.lower():
        return "XX"
    upper = text.upper()
    if upper in PROVINCE_CODES:
        return upper
    key = unicodedata.normalize("NFC", text).casefold()
    key = re.sub(r"\s+", " ", key)
    return PROVINCES.get(key)


def format_postal(first: str, second: str) -> str:
    return f"{first.upper()} {second.upper()}"


def parse_address(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """'City, PR A1A 1A1' -> (city, province, postal_code), each None when absent."""
    parts, province, postal = _address_parts(raw)
    city = parts[-1] if parts else None
    if city:
        city = city.title() if city.isupper() or city.islower() else city
    return city, province, postal


def parse_street(raw: str | None) -> str | None:
    """'A-5593 Kingsway, Burnaby, BC' -> 'A-5593 Kingsway': whatever precedes the city."""
    parts, _, _ = _address_parts(raw)
    return ", ".join(parts[:-1]) if len(parts) >= 2 else None


def _address_parts(raw: str | None) -> tuple[list[str], str | None, str | None]:
    """Comma parts left after the postal code and province are taken off the end."""
    if not raw:
        return [], None, None
    text = re.sub(r"\s+", " ", raw).strip()
    postal = None
    m = POSTAL_RE.search(text)
    if m:
        postal = format_postal(m.group(1), m.group(2))
        text = (text[: m.start()] + text[m.end():]).strip(" ,")
    province = None
    m2 = re.search(r",\s*([A-Za-z]{2})\s*$", text)
    if m2 and m2.group(1).upper() in PROVINCE_CODES:
        province = m2.group(1).upper()
        text = text[: m2.start()].strip(" ,")
    else:
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) >= 2:
            code = province_code(parts[-1])
            if code:
                province = code
                text = ", ".join(parts[:-1])
    # Older files carry a full street address; the city is the last part.
    return [p.strip() for p in text.split(",") if p.strip()], province, postal


def parse_noc(raw: str | None) -> tuple[str | None, str | None]:
    """'63200-Cooks' or 'NOC 60040' -> (code, title)."""
    if not raw:
        return None, None
    m = NOC_RE.match(raw)
    if not m:
        return None, raw.strip() or None
    return m.group(1), (m.group(2) or None)


def parse_jobbank_date(raw: str | None) -> str | None:
    """'October 10, 2026' or 'Posted on October 08, 2026' -> '2026-10-10'."""
    if not raw:
        return None
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", raw)
    if not m:
        iso = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
        return iso.group(1) if iso else None
    month = MONTHS.get(m.group(1).lower())
    if not month:
        return None
    return date(int(m.group(3)), month, int(m.group(2))).isoformat()


def parse_salary_text(raw: str | None) -> tuple[float | None, float | None, str | None]:
    """'$16.60 to $22.10 hourly (to be negotiated)' -> (16.6, 22.1, 'HOUR')."""
    if not raw:
        return None, None, None
    text = raw.replace(",", "")
    nums = [float(n) for n in re.findall(r"\$\s*(\d+(?:\.\d+)?)", text)]
    if not nums:
        return None, None, None
    lower = text.lower()
    unit = None
    # The compound words come first: "week" sits inside "bi-weekly" and "month"
    # inside "semi-monthly", so checked later they would read as weekly or
    # monthly pay, at twice or half the period.
    for word, code in (("bi-week", "BIWEEK"), ("biweek", "BIWEEK"), ("bi week", "BIWEEK"),
                       ("semi-month", "SEMIMONTH"), ("semimonth", "SEMIMONTH"), ("semi month", "SEMIMONTH"),
                       ("hour", "HOUR"), ("annual", "YEAR"), ("year", "YEAR"),
                       ("week", "WEEK"), ("month", "MONTH"), ("daily", "DAY"), ("day", "DAY")):
        if word in lower:
            unit = code
            break
    return nums[0], (nums[1] if len(nums) > 1 else nums[0]), unit


def period_from_text(text: str) -> str | None:
    """Resource name or URL -> '2026Q1', '2017Q1-Q2' or '2015'."""
    if not text:
        return None
    m = PERIOD_RE.search(text)
    if m:
        year, q1, q2 = m.group(1), m.group(2), m.group(3)
        if q2 and q2 != q1:
            return f"{year}Q{q1}-Q{q2}"
        return f"{year}Q{q1}"
    m = YEAR_RE.search(text)
    return m.group(1) if m else None


def period_quarters(period: str) -> list[tuple[int, int]]:
    """Expand a period label to the (year, quarter) pairs it covers."""
    m = re.match(r"^(\d{4})Q([1-4])(?:-Q([1-4]))?$", period)
    if m:
        year, q1 = int(m.group(1)), int(m.group(2))
        q2 = int(m.group(3)) if m.group(3) else q1
        return [(year, q) for q in range(q1, q2 + 1)]
    if re.match(r"^\d{4}$", period):
        return [(int(period), q) for q in (1, 2, 3, 4)]
    return []


def period_sort_key(period: str) -> tuple[int, int]:
    quarters = period_quarters(period)
    return quarters[-1] if quarters else (0, 0)


def period_start_date(period: str) -> str | None:
    quarters = period_quarters(period)
    if not quarters:
        return None
    year, q = quarters[0]
    return date(year, 3 * (q - 1) + 1, 1).isoformat()


def period_end_date(period: str) -> str | None:
    quarters = period_quarters(period)
    if not quarters:
        return None
    year, q = quarters[-1]
    month = 3 * q
    last = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, last).isoformat()


def to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, OverflowError):
        # "nan" fails as a ValueError and "inf" as an OverflowError at int();
        # neither is a count.
        return None


def iso_date(value: object) -> str | None:
    """Best-effort ISO date from a datetime, date or common string forms."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    return parse_jobbank_date(text)
