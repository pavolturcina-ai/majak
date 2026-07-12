from majak.config import settings
from majak.ingest.people import score_names


def test_exact_match_is_one():
    assert score_names("pavol turcina", "pavol turcina") == 1.0


def test_word_order_is_ignored():
    assert score_names("pavol turcina", "turcina pavol") >= settings.person_match_link


def test_typo_stays_above_link_threshold():
    # A single-letter typo should still auto-link (>= 0.92).
    assert score_names("pavol turcna", "pavol turcina") >= settings.person_match_link


def test_different_people_land_below_review_threshold():
    assert score_names("pavol turcina", "jan novak") < settings.person_match_review


def test_partial_name_is_ambiguous_band():
    # First name only vs full name — should be uncertain, not an auto-link.
    score = score_names("pavol", "pavol turcina")
    assert score < settings.person_match_link


def test_empty_names_score_zero():
    assert score_names("", "pavol") == 0.0
    assert score_names("pavol", "") == 0.0
