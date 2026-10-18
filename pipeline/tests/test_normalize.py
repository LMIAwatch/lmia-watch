from lmia_pipeline.normalize import (
    employer_id, norm_name, parse_address, parse_jobbank_date, parse_noc, parse_salary_text,
    period_end_date, period_from_text, period_quarters, period_start_date, province_code,
)


def test_norm_name_strips_legal_forms_and_punctuation():
    assert norm_name("PinkCloud Services Ltd.") == "pinkcloud services"
    assert norm_name("PINKCLOUD SERVICES LTD.") == "pinkcloud services"
    assert norm_name("EMT LIMITED PARTNERSHIP") == "emt"
    assert norm_name("Associated Engineering (B.C.) Ltd.") == "associated engineering b c"
    assert norm_name("Restaurant St-Hubert Sept-Îles") == "restaurant st hubert sept îles"
    assert norm_name("  Jealous   Fruits Ltd. ") == "jealous fruits"
    assert norm_name(None) == ""


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
