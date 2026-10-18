import pytest

from lmia_pipeline.normalize import (
    employer_id, fold_accents, has_legal_form, is_numbered_company, norm_legal, norm_name, parse_address,
    parse_jobbank_date, parse_noc, parse_salary_text, parse_street, period_end_date, period_from_text,
    period_quarters, period_start_date, province_code, split_trade_name,
)


def test_norm_name_strips_legal_forms_and_punctuation():
    assert norm_name("PinkCloud Services Ltd.") == "pinkcloud services"
    assert norm_name("PINKCLOUD SERVICES LTD.") == "pinkcloud services"
    assert norm_name("EMT LIMITED PARTNERSHIP") == "emt"
    assert norm_name("Associated Engineering (B.C.) Ltd.") == "associated engineering bc"
    assert norm_name("Restaurant St-Hubert Sept-Îles") == "restaurant st hubert sept iles"
    assert norm_name("  Jealous   Fruits Ltd. ") == "jealous fruits"
    assert norm_name(None) == ""
    assert norm_name("") == ""
    assert norm_name("   ") == ""


@pytest.mark.parametrize("raw, legal, operating", [
    # The owner's case and its spellings in the lists.
    ("0704250 BC Ltd. dba Assi Supermarket", "0704250 BC Ltd.", "Assi Supermarket"),
    ("0704250 BC Ltd. o/a Assi Supermarket", "0704250 BC Ltd.", "Assi Supermarket"),
    ("0704250 BC LTD DBA ASSI SUPERMARKET", "0704250 BC LTD", "ASSI SUPERMARKET"),
    # Every English marker.
    ("Exel Canada Ltd. d/b/a DHL Supply Chain", "Exel Canada Ltd.", "DHL Supply Chain"),
    ("The TDL Group Corp. d.b.a. Tim Hortons", "The TDL Group Corp.", "Tim Hortons"),
    ("CLPros, LLC d.b.a Crealyst-US", "CLPros, LLC", "Crealyst-US"),
    ("0950223 BC LTD.  D.B.A. Browns Town Centre", "0950223 BC LTD.", "Browns Town Centre"),
    ("1833889 Ontario Inc.\\ O.A. AM Consulting group", "1833889 Ontario Inc.", "AM Consulting group"),
    ("Lapline Ltd T/A: Bartech Marine Engineering", "Lapline Ltd", "Bartech Marine Engineering"),
    ("Intermoor Ltd (trading as ChainCo)", "Intermoor Ltd", "ChainCo"),
    ("2621956 Ontario Inc. operating as Lazer Technologies", "2621956 Ontario Inc.", "Lazer Technologies"),
    ("Creative Film Management International operating  as CFM", "Creative Film Management International", "CFM"),
    ('ContextLogic Technologies Inc. (doing business as "Wish")', "ContextLogic Technologies Inc.", "Wish"),
    ("X Holdings Ltd. carrying on business as Y Foods", "X Holdings Ltd.", "Y Foods"),
    ("X Holdings Ltd. carrying on business under the name of Y Foods", "X Holdings Ltd.", "Y Foods"),
    ("X Holdings Ltd. c.o.b. Y Foods", "X Holdings Ltd.", "Y Foods"),
    ("GPC Investments Limited cob Comfort Inn Halifax", "GPC Investments Limited", "Comfort Inn Halifax"),
    # French markers.
    ("9123-4567 Québec inc. faisant affaire sous le nom de Érablière du Nord", "9123-4567 Québec inc.",
     "Érablière du Nord"),
    ("Gestion Tremblay inc. faisant affaires sous le nom Resto Chez Paul", "Gestion Tremblay inc.", "Resto Chez Paul"),
    ("Gestion Tremblay inc. faisant affaire sous Resto Chez Paul", "Gestion Tremblay inc.", "Resto Chez Paul"),
    ("Gestion d’Arbre inc. exploitant sous le nom d’Arbres Plus", "Gestion d’Arbre inc.", "Arbres Plus"),
    ("Ferme Lévesque S.E.N.C. f.a.s. Les Jardins Lévesque", "Ferme Lévesque S.E.N.C.", "Les Jardins Lévesque"),
    ("Ferme Lévesque S.E.N.C. f.a.s.n. Les Jardins", "Ferme Lévesque S.E.N.C.", "Les Jardins"),
    # Brackets, quotes and glued punctuation.
    ("Nguyen Technologies & Electrical Equipment (O/A NTE)", "Nguyen Technologies & Electrical Equipment", "NTE"),
    ("Holt Glass Ltd (dba) Cruise Ship Glass", "Holt Glass Ltd", "Cruise Ship Glass"),
    ("2149120 Ontario Inc (d.b.a Little Caesars)", "2149120 Ontario Inc", "Little Caesars"),
    ('Diamond Paws Inc. (operating as "Aspect")', "Diamond Paws Inc.", "Aspect"),
    ("101184720 SK Ltd dba IGA (Leader, SK)", "101184720 SK Ltd", "IGA (Leader, SK)"),
    ("1776957 Ontario Ltd.(t/a) Blu Rist.", "1776957 Ontario Ltd.", "Blu Rist."),
    ("3012352 Manitoba Ltd.o/a Wendell Honey Farms", "3012352 Manitoba Ltd.", "Wendell Honey Farms"),
    ("Hole Group Holdings Inc.dba They Produce", "Hole Group Holdings Inc.", "They Produce"),
    ("ACNE Media, Inc.dba: ACNE Production", "ACNE Media, Inc.", "ACNE Production"),
    ("Glare Holdings Ltd .o/a Sun Trucking", "Glare Holdings Ltd", "Sun Trucking"),
    ("2553147 Ontario Inc/ Trading as Ontario Aluminum & Glass", "2553147 Ontario Inc", "Ontario Aluminum & Glass"),
    ("Versapay ULC, d.b.a Versapay Corporation", "Versapay ULC", "Versapay Corporation"),
    # The first marker splits; a second one straight after it is dropped.
    ("Jean Farms Ltd. dba t/a Picardie Farms", "Jean Farms Ltd.", "Picardie Farms"),
    ("Court Productions Inc o/a Game of Love aka Family Court", "Court Productions Inc",
     "Game of Love aka Family Court"),
    # A marker inside the operating name stays there.
    ("1595434 Alberta Inc o/a Fas Gas Short Stop", "1595434 Alberta Inc", "Fas Gas Short Stop"),
])
def test_split_trade_name(raw, legal, operating):
    assert split_trade_name(raw) == (legal, operating)


@pytest.mark.parametrize("raw", [
    "Cob Roller Farms Ltd.",             # "cob" is a word, not after a legal form
    "Golden Cob Farms",                  # same
    "The G.O.A.T. Barbers Inc",          # "O.A." inside an abbreviation
    "F.A.S.T. Logistics Inc.",           # "F.A.S." inside an abbreviation
    "C.O.B.R.A. Security Ltd",           # "C.O.B." inside an abbreviation
    "DBA Consulting Ltd",                # a marker with nothing before it
    "O/A Something",
    "Something o/a",                     # a marker with nothing after it
    "Pro/Am Golf Inc.",                  # "o/a" glued to a word
    "OJ's Aspen Restaurant Inco/a Original Joes",
    "Fas Gas Plus",
    "Maersk Line A/S",
])
def test_split_trade_name_leaves_these_whole(raw):
    assert split_trade_name(raw) == (raw.strip(), None)


def test_split_trade_name_care_of_drops_the_second_part():
    assert split_trade_name("937742 Ontario Inc c/o M.Bergman") == ("937742 Ontario Inc", None)
    assert split_trade_name("UVEA Marine Services c/o Compagnie du Ponant") == ("UVEA Marine Services", None)
    assert split_trade_name("X Farms Ltd. care of Y") == ("X Farms Ltd.", None)
    assert split_trade_name(None) == ("", None)
    assert split_trade_name("   ") == ("", None)
    assert split_trade_name("  Spaced   Out  Ltd  ") == ("Spaced Out Ltd", None)


def test_trade_names_share_the_legal_identity():
    spellings = [
        "0704250 BC Ltd.", "0704250 B.C. LTD.", "0704250 B.C LTD", "0704250 B C Ltd", "0704250 BC Ltd",
        "0704250 BC Ltd. dba Assi Supermarket", "0704250 BC Ltd. o/a Assi Supermarket",
        "0704250 British Columbia Ltd.", "0704250 B.C. Ltd. (o/a Assi Supermarket)",
    ]
    assert {norm_name(s) for s in spellings} == {"0704250 bc"}


@pytest.mark.parametrize("raw, norm", [
    # Dots inside abbreviations are removed, never turned into spaces.
    ("0704250 B.C. LTD.", "0704250 bc"),
    ("Associated Engineering (B.C.) Ltd.", "associated engineering bc"),
    ("U.S.A. Foods Inc.", "usa foods"),
    ("A. B. Contracting Ltd", "ab contracting"),
    ("The G.O.A.T. Barbers Inc", "the goat barbers"),
    ("1116089 B.C.Ltd.", "1116089 bc"),
    ("N.Y.W.Enterprises Inc.", "nyw enterprises"),
    ("Par B.L.eux", "par bl eux"),
    # A lone initial keeps its word break; initials stay apart from a surname.
    ("G.Mann Farms Ltd.", "g mann farms"),
    ("G. Mann Farms Ltd.", "g mann farms"),
    ("W.J. O'Neil & Sons Ltd.", "wj oneil sons"),
    ("St. John's Bakery Ltd", "st johns bakery"),
    # Runs of single letters join, so spaced and dotted initials agree.
    ("J M Peeters Nurseries Ltd", "jm peeters nurseries"),
    ("J.M. Peeters Nurseries Ltd.", "jm peeters nurseries"),
    ("H R  Marshall Farms Ltd", "hr marshall farms"),
    ("J & K Farms", "jk farms"),
    ("J and K Farms", "jk farms"),
    # Apostrophes inside words go; "&", "and" and "et" drop out.
    ("Tim Horton's", "tim hortons"),
    ("Tim Hortons", "tim hortons"),
    ("McDonald’s Restaurants of Canada Limited", "mcdonalds restaurants of canada"),
    ("Smith & Sons Ltd.", "smith sons"),
    ("Smith and Sons Ltd.", "smith sons"),
    ("Smith Sons Ltd.", "smith sons"),
    ("Ferme R. Mailloux et Fils Inc.", "ferme r mailloux fils"),
    # Accents fold.
    ("Pêcheries Nikan S.E.C.", "pecheries nikan"),
    ("FGL VÉGIARD INC", "fgl vegiard"),
    ("Ferme Bœuf Inc", "ferme boeuf"),
    ("Les Entreprises Gérard Côté Ltée", "les entreprises gerard cote"),
    # French legal forms.
    ("Ferme Célijean S.E.N.C.", "ferme celijean"),
    ("Ferme Agraymond s e n c", "ferme agraymond"),
    ("Cabinet X S.E.N.C.R.L.", "cabinet x"),
    ("Olymel S.E.C.", "olymel"),
    ("Boulangerie Rivard Enr.", "boulangerie rivard"),
    ("Ferme Lait et Miel inc.", "ferme lait miel"),
    ("Pâtisserie Au Palet D'or (1996) Inc.", "patisserie au palet dor 1996"),
    # The legal part is the identity.
    ("Seacastle Enterprises Inc. o/a Burger King", "seacastle enterprises"),
    ("9123-4567 Québec inc. f.a.s. Garage Pépin", "9123 4567 quebec"),
])
def test_norm_name_rules(raw, norm):
    assert norm_name(raw) == norm


@pytest.mark.parametrize("spellings, norm", [
    (["101184720 Saskatchewan Ltd.", "101184720 SK Ltd", "101184720 Sask. Ltd."], "101184720 saskatchewan"),
    (["1174724 Ontario Inc.", "1174724 Ont. Inc.", "1174724 ON Inc"], "1174724 ontario"),
    (["1630232 Alberta Ltd.", "1630232 AB Ltd", "1630232 Alta Ltd."], "1630232 alberta"),
    (["5628874 Manitoba Ltd.", "5628874 MB Ltd", "5628874 Man. Ltd."], "5628874 manitoba"),
    (["9123-4567 Québec inc.", "9123-4567 Quebec Inc", "9123-4567 QC inc."], "9123 4567 quebec"),
    (["692059 N.B. Inc.", "692059 NB Inc", "692059 New Brunswick Inc."], "692059 nb"),
    (["3234567 Nova Scotia Limited", "3234567 N.S. Ltd."], "3234567 nova scotia"),
    (["7286139 Canada Ltd.", "7286139 Can. Ltd."], "7286139 canada"),
    (["12345 P.E.I. Inc.", "12345 PEI Inc"], "12345 pei"),
])
def test_numbered_companies(spellings, norm):
    assert {norm_name(s) for s in spellings} == {norm}


def test_numbered_rule_needs_a_company_number():
    # Short numbers are street numbers or years, not company numbers.
    assert norm_name("2009 Ontario Cherry Farm") == "2009 ontario cherry farm"
    assert norm_name("500 Can Supply Ltd") == "500 can supply"
    # The jurisdiction must follow the number straight away.
    assert norm_name("1234567 Ontario Holdings Inc.") == "1234567 ontario holdings"


def test_legal_form_and_company_number_helpers():
    assert has_legal_form("Golden Koi Food Ltd.")
    assert has_legal_form("Ferme du Doc Inc.")
    assert has_legal_form("Pêcheries Lebreton & Fils Ltée")
    assert has_legal_form("Ferme Agraymond S.E.N.C")
    assert not has_legal_form("Jeff Gillin")
    assert not has_legal_form("Sushi 5")
    assert not has_legal_form(None)
    assert is_numbered_company("0704250 B.C. Ltd.")
    assert is_numbered_company("9123-4567 Québec inc.")
    assert not is_numbered_company("2009 Ontario Cherry Farm")
    assert not is_numbered_company("Ontario Corp No. 2328333")
    assert not is_numbered_company(None)


def test_norm_legal_does_not_split():
    assert norm_legal("X Ltd. o/a Y") == "x ltd oay"
    assert norm_legal(None) == ""
    assert fold_accents("Québec Ltée") == "Quebec Ltee"


def test_parse_street():
    assert parse_street("A-5593 Kingsway, Burnaby, BC") == "A-5593 Kingsway"
    assert parse_street("115-1199 Lynn Valley Road, North Vancouver, BC, V7J 3H2") == "115-1199 Lynn Valley Road"
    assert parse_street("PO Box 51, 58 Carol Lane,, Marchland, MB") == "PO Box 51, 58 Carol Lane"
    assert parse_street("2-2261 rue du Souvenir, , Montréal, QC") == "2-2261 rue du Souvenir"
    assert parse_street("Box 20, 215 Water Street, Suite 511, St. John's, NL  A1C 6C9") == (
        "Box 20, 215 Water Street, Suite 511")
    assert parse_street("Burnaby, BC") is None
    assert parse_street("Vancouver, BC V6B 1A1") is None
    assert parse_street(None) is None
    assert parse_street("") is None


def test_employer_id_is_stable_and_province_sensitive():
    a = employer_id("jealous fruits", "BC")
    assert a == employer_id("jealous fruits", "BC")
    assert a.startswith("emp-") and len(a) == 14
    assert a != employer_id("jealous fruits", "ON")


def test_province_code():
    assert province_code("British Columbia") == "BC"
    assert province_code("Newfoundland and Labrador                 ") == "NL"
    assert province_code("qc") == "QC"
    assert province_code("Employers carrying on business in Canada with Head Office outside of Canada") == "XX"
    assert province_code("Not a province") is None
    assert province_code("") is None


def test_parse_address_variants():
    assert parse_address("St. John’s, NL A1B 1W3") == ("St. John’s", "NL", "A1B 1W3")
    assert parse_address("COME-BY-CHANCE, NL A0B 1N0") == ("Come-By-Chance", "NL", "A0B 1N0")
    assert parse_address("Vancouver, BC") == ("Vancouver", "BC", None)
    assert parse_address("Box 20, 215 Water Street, Suite 511, St. John's, NL  A1C 6C9") == (
        "St. John's", "NL", "A1C 6C9")
    assert parse_address("GRAND FALLS - WINDSOR, NL A2A 2E1") == ("Grand Falls - Windsor", "NL", "A2A 2E1")
    assert parse_address("brackendale, bc v0n1h0") == ("Brackendale", "BC", "V0N 1H0")
    assert parse_address(None) == (None, None, None)
    assert parse_address("   ") == (None, None, None)


def test_parse_noc():
    assert parse_noc("63200-Cooks") == ("63200", "Cooks")
    assert parse_noc("3111-Specialist physicians") == ("3111", "Specialist physicians")
    assert parse_noc("NOC 60040") == ("60040", None)
    assert parse_noc("Cooks") == (None, "Cooks")
    assert parse_noc(None) == (None, None)


def test_parse_jobbank_date():
    assert parse_jobbank_date("October 10, 2026") == "2026-10-10"
    assert parse_jobbank_date("Posted on October 08, 2026") == "2026-10-08"
    assert parse_jobbank_date("2026-10-22") == "2026-10-22"
    assert parse_jobbank_date("yesterday") is None


def test_parse_salary_text():
    assert parse_salary_text("$16.60 to $22.10 hourly (to be negotiated)") == (16.6, 22.1, "HOUR")
    assert parse_salary_text("$40.00 hourly") == (40.0, 40.0, "HOUR")
    assert parse_salary_text("$45,000 annually") == (45000.0, 45000.0, "YEAR")
    assert parse_salary_text(None) == (None, None, None)


def test_period_parsing():
    assert period_from_text("2026Q1 employers with a positive LMIA, NOC 2021") == "2026Q1"
    assert period_from_text("2023Q4 employers with a positive LMIA, by program stream, NOC 2011") == "2023Q4"
    assert period_from_text("2017q1q2_positive_en.csv") == "2017Q1-Q2"
    assert period_from_text("2015_positive_employers_en.csv") == "2015"
    assert period_from_text("employer-list2020q22020q2csv202.csv") == "2020Q2"
    assert period_quarters("2017Q1-Q2") == [(2017, 1), (2017, 2)]
    assert period_quarters("2015") == [(2015, 1), (2015, 2), (2015, 3), (2015, 4)]
    assert period_start_date("2026Q1") == "2026-01-01"
    assert period_end_date("2026Q1") == "2026-03-31"
    assert period_end_date("2017Q1-Q2") == "2017-06-30"
