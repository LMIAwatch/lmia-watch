"""The daily post with awkward names, no provinces, missing fonts and odd API answers."""

import pytest

from lmia_pipeline import social, social_card
from lmia_pipeline.social import Digest, EmployerLine, compose, x_length
from test_social import CREDS, FakeJSON, FakePoster, seed


def digest(employers, provinces=None):
    return Digest(
        data_date="2026-10-17", postings=12, positions=40, positions_known=12,
        provinces=provinces if provinces is not None else ["BC", "ON"],
        employers=employers, top_employers=employers, province_counts={p: 1 for p in (provinces or [])},
    )


def test_names_with_newlines_emoji_and_300_characters_compose_within_the_limit():
    names = [
        "Acme\nFarms\r\nLtd\tWest",
        "Bakery \U0001F950 & Sons \U0001F1E8\U0001F1E6",
        "A" * 300,
    ]
    d = digest([EmployerLine(n, "Abbotsford", "BC", 10 - i) for i, n in enumerate(names)])
    text = compose(d, link=None)
    assert x_length(text) <= social.MAX_CHARS
    assert "\r" not in text and "\t" not in text
    lines = text.split("\n")
    assert "Acme Farms Ltd West, Abbotsford BC: 10" in lines
    # The 300-character name does not fit and is dropped from the end first.
    assert not any(line.startswith("AAAA") for line in lines)


def test_zero_provinces_and_no_employers_still_compose():
    d = digest([], provinces=[])
    text = compose(d, link=None)
    assert text.startswith('Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 12 postings')
    assert "In " not in text


def test_a_name_that_is_only_whitespace_does_not_break_the_line():
    text = compose(digest([EmployerLine(" \n ", None, None, 3)]), link=None)
    assert x_length(text) <= social.MAX_CHARS


def test_the_card_renders_without_the_brand_fonts(conn, monkeypatch, tmp_path):
    seed(conn)
    monkeypatch.setattr(social_card, "FONT_DIR", tmp_path / "no-fonts-here")
    card = social.card_for(social.collect(conn))
    png = social_card.render_card(card)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_upload_that_answers_html_posts_the_text_alone(conn, tmp_path):
    seed(conn)
    poster = FakePoster(upload=FakeJSON(200, None, text="<html>Bad gateway</html>"))
    outcome = social.run(conn, out_dir=tmp_path, env=CREDS, session=poster)
    assert outcome == "posted"
    tweet = poster.tweets()[0]["json"]
    assert "media" not in tweet


def test_a_post_that_answers_html_with_success_is_recorded_once(conn, tmp_path):
    seed(conn)
    poster = FakePoster(response=FakeJSON(201, None, text="<html>Created</html>"))
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=poster) == "posted"
    assert social.run(conn, out_dir=tmp_path, env=CREDS, session=FakePoster()) == "already posted"
