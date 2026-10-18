"""Name, address, date and code normalization used by every source."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime

# Trailing tokens that distinguish a legal form, not a business. Stripped
# repeatedly from the end so "x services ltd" and "x services limited
# partnership" both normalize to "x services".
LEGAL_SUFFIXES = {
    "ltd", "ltee", "ltée", "limited", "limitee", "limitée", "inc", "incorporated",
    "incorporee", "incorporée", "corp", "corporation", "ulc", "llp", "llc", "lp",
    "co", "company", "cie", "compagnie", "senc", "sencrl", "enr", "enrg",
    "partnership", "plc",
}

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
NOC_RE = re.compile(r"^\s*(?:NOC\s*)?(\d{4,5})\s*[-:.]?\s*(.*?)\s*$")
PERIOD_RE = re.compile(r"(20\d\d)\s*[-_ ]?q([1-4])(?:\s*[-_ ]?q([1-4]))?", re.I)
YEAR_RE = re.compile(r"(20\d\d)")

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def norm_name(raw: str | None) -> str:
    """Casefolded, punctuation-free name without its legal suffix."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.replace("_", " ")
    tokens = text.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


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
    if not raw:
        return None, None, None
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
    parts = [p.strip() for p in text.split(",") if p.strip()]
    city = parts[-1] if parts else None
    if city:
        city = city.title() if city.isupper() or city.islower() else city
    return city, province, postal


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
    for word, code in (("hour", "HOUR"), ("annual", "YEAR"), ("year", "YEAR"),
                       ("week", "WEEK"), ("month", "MONTH"), ("bi-week", "BIWEEK"), ("day", "DAY")):
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
    except ValueError:
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
