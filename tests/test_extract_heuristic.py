"""The heuristic extractor must always ground its units (verbatim quote)."""

from majak.ingest.extract import _heuristic_units
from majak.ingest.normalize import NormalizedInput


def test_heuristic_extracts_grounded_task_from_segments():
    norm = NormalizedInput(
        text="",
        segments=[
            {"speaker": "Pavol", "ts": "0:12", "text": "Musíme poslať faktúru klientovi zajtra."},
            {"speaker": "Jana", "ts": "0:20", "text": "Rozhodli sme sa ísť s dodávateľom Acme."},
            {"speaker": "Pavol", "ts": "0:40", "text": "Je tu riziko, že projekt mešká."},
        ],
    )
    units = _heuristic_units(norm)
    assert units, "expected at least one unit"
    # Every unit is grounded with a verbatim quote + locator.
    for u in units:
        assert u.grounding, f"ungrounded unit: {u.title}"
        assert u.grounding[0].quote
        assert u.grounding[0].locator

    sections = {u.section for u in units}
    assert "top" in sections      # 'musíme poslať'
    assert "decision" in sections  # 'rozhodli sme'
    assert "threat" in sections    # 'riziko ... mešká'


def test_heuristic_quote_is_verbatim():
    line = "Musíme poslať faktúru klientovi zajtra."
    norm = NormalizedInput(text="", segments=[{"speaker": "Pavol", "ts": "1:00", "text": line}])
    units = _heuristic_units(norm)
    assert units[0].grounding[0].quote == line


def test_heuristic_on_plain_lines():
    norm = NormalizedInput(text="Treba pripraviť ponuku.\nToto je len poznámka bez akcie o počasí.")
    units = _heuristic_units(norm)
    assert any("ponuk" in u.title.lower() for u in units)
