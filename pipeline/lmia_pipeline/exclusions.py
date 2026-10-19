"""Decide which Job Bank postings must never be stored.

Private households hire caregivers and home support workers under the
employer's own name. Those postings are public on Job Bank, but publishing a
person's name and home area as an "employer" is not what this project is for.
ESDC's lists say they leave personal names out, yet some households get
through; household.py keeps those out on the same reasoning, sharing the
tokens below. The rule errs toward dropping: a borderline business lost from
the pending list costs little, a named individual costs a lot.
"""

from __future__ import annotations

import re

HOUSEHOLD_TITLE_RE = re.compile(
    r"caregiver|care giver|child\s*care|childcare|nanny|nannies|babysit|"
    r"home\s*support|home\s*care|homecare|housekeep|domestic|live-?in|"
    r"personal support worker|home attendant|attendant for persons|companion|"
    r"au pair|private home|private household|elder(?:ly)? care|senior care|"
    r"home child",
    re.I,
)

# Any of these words marks a name as a business. Lower case, compared by token.
BUSINESS_TOKENS = {
    "inc", "inc.", "ltd", "ltée", "ltee", "limited", "limitee", "limitée", "corp",
    "corporation", "co", "company", "cie", "ulc", "llp", "llc", "lp", "enr",
    "senc", "group", "groupe", "holdings", "enterprises", "entreprises",
    "partners", "partnership", "bros", "brothers", "sons", "international",
    "the", "le", "la", "les", "des", "du", "de", "chez", "and", "et",
    "farm", "farms", "ferme", "fermes", "ranch", "orchard", "orchards", "verger",
    "greenhouse", "greenhouses", "serres", "nursery", "nurseries", "dairy",
    "berry", "berries", "fruit", "fruits", "produce", "seeds", "mushrooms",
    "restaurant", "restaurants", "resto", "cafe", "café", "bistro", "grill",
    "kitchen", "cuisine", "sushi", "pizza", "pizzeria", "burger", "burgers",
    "diner", "pub", "bar", "bakery", "boulangerie", "foods", "food", "catering",
    "hotel", "motel", "inn", "lodge", "resort", "suites", "hospitality",
    "market", "mart", "store", "stores", "shop", "boutique", "convenience",
    "prices", "retail", "supermarket", "grocery", "depanneur", "dépanneur",
    "transport", "transports", "trucking", "logistics", "freight", "express",
    "carriers", "movers", "moving", "delivery", "taxi", "auto", "automotive",
    "motors", "tire", "tires", "garage", "repair", "repairs", "mechanical",
    "electric", "electrical", "plumbing", "heating", "roofing", "painting",
    "landscaping", "cleaning", "janitorial", "maintenance", "construction",
    "contracting", "contractors", "builders", "homes", "developments",
    "security", "staffing", "consulting", "consultants", "solutions", "systems",
    "technologies", "technology", "tech", "software", "labs", "studio", "studios",
    "design", "designs", "media", "productions", "dental", "medical", "pharmacy",
    "clinic", "clinique", "health", "physio", "wellness", "centre", "center",
    "academy", "college", "university", "school", "école", "daycare", "learning",
    "hospital", "foundation", "ministries", "church", "temple", "mosque", "society",
    "association", "club", "salon", "spa", "nails", "beauty", "barber", "hair",
    "trust", "services", "service", "industries", "industrial", "manufacturing",
    "mfg", "machine", "machining", "welding", "fabrication", "steel", "metal",
    "plastics", "packaging", "printing", "print", "signs", "glass", "lumber",
    "timber", "forestry", "logging", "mining", "energy", "oilfield", "marine",
    "fisheries", "seafood", "seafoods", "fish", "aquaculture", "cannery",
    "winery", "vineyard", "vineyards", "brewery", "distillery", "ventures",
    "investments", "capital", "realty", "properties", "property", "management",
    "chalet", "resto-bar", "bar-b-q", "bbq", "wok", "noodle", "house", "maison",
    "canada", "canadian", "bc", "alberta", "ontario", "quebec", "québec",
    "west", "east", "north", "south", "coast", "pacific", "atlantic", "prairie",
    "global", "national", "regional", "premier", "premium", "quality", "best",
    "first", "new", "royal", "golden", "green", "blue", "red", "white", "black",
    "cattle", "poultry", "eggs", "honey", "apiary", "apiaries", "gardens", "garden",
}


# A word of a name: letters, with an apostrophe, dot or hyphen inside it
# ("O'Neil", "J.R.", "Marie-Claude"). Shared with household.py.
NAME_WORD_RE = re.compile(r"[^\W\d_]+(?:['’.-][^\W\d_]+)*")


def name_words(text: str) -> list[str]:
    return NAME_WORD_RE.findall(text)


def looks_like_person(name: str | None) -> bool:
    """Two or three plain words with no business marker reads as a person."""
    if not name:
        return False
    text = name.strip()
    if re.search(r"[\d&+/@#]", text):
        return False
    tokens = name_words(text)
    if len(tokens) not in (2, 3):
        return False
    lowered = [t.lower().strip(".") for t in tokens]
    if any(t in BUSINESS_TOKENS for t in lowered):
        return False
    # Initials such as "J. Smith" or "J.R. Smith" read as a person.
    return True


def is_private_household(employer_raw: str | None, title: str | None) -> bool:
    """True when the posting must be dropped before storage."""
    if title and HOUSEHOLD_TITLE_RE.search(title):
        return True
    return looks_like_person(employer_raw)
