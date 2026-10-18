import pytest

from lmia_pipeline.exclusions import is_private_household, looks_like_person


@pytest.mark.parametrize("employer, title", [
    ("Luigi Gallo", "home support worker"),
    ("Nidhi Dua", "child caregiver - private home"),
    ("Jia Ji Liu", "home child care provider"),
    ("Manoj K. Talwar", "family caregiver"),
    ("Jane Smith", "cook"),
    ("Mary Ann Jones", "cleaner"),
    ("Bright Horizons Daycare", "nanny"),
])
def test_dropped(employer, title):
    assert is_private_household(employer, title) is True


@pytest.mark.parametrize("employer, title", [
    ("Amazing Prices", "retail store supervisor"),
    ("Bolivar Farms", "Christmas tree shearer"),
    ("HananTransport", "class 1 truck driver"),
    ("Harveys/Swiss Chalet", "cook"),
    ("Arseno", "custom upholsterer"),
    ("IV CROWNS GROUP CORP.", "cleaner"),
    ("Les Pavillons LaSalle", "cook"),
    ("PinkCloud Cleaning & Home Services", "cleaning service manager"),
    ("Restaurant St-Hubert Sept-Îles", "cook"),
    ("Tremel Greenhouses", "greenhouse worker"),
    ("S & S Orchards Ltd", "fruit farm worker"),
    ("Edsa Mini Mart", "assistant store manager"),
])
def test_kept(employer, title):
    assert is_private_household(employer, title) is False


def test_looks_like_person_edge_cases():
    assert looks_like_person("") is False
    assert looks_like_person(None) is False
    assert looks_like_person("A B C D") is False
    assert looks_like_person("15243921 CANADA INC.") is False
