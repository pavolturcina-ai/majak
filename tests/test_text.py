from majak.util.text import (
    chunk_text,
    clean_text,
    collapse_whitespace,
    normalize_name,
    strip_accents,
)


def test_strip_accents_slovak():
    assert strip_accents("Pavol Turčina") == "Pavol Turcina"
    assert strip_accents("Žofia Ďurišová") == "Zofia Durisova"


def test_normalize_name_is_order_and_punctuation_stable():
    assert normalize_name("  Turčina,  Pavol! ") == "turcina pavol"
    assert normalize_name("Pavol   Turcina") == "pavol turcina"


def test_collapse_whitespace():
    assert collapse_whitespace("a\n  b\t c") == "a b c"


def test_clean_text_collapses_blank_lines():
    assert clean_text("a\n\n\n\nb\r\nc") == "a\n\nb\nc"


def test_chunk_text_short_is_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_chunk_text_overlaps_and_covers():
    text = "\n\n".join(f"paragraph {i} " + "x" * 200 for i in range(20))
    chunks = chunk_text(text, max_chars=500, overlap=100)
    assert len(chunks) > 1
    # Every chunk is within bound and non-empty.
    assert all(0 < len(c) <= 500 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("") == []
