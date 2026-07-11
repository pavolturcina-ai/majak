import pytest

from majak.ingest.normalize import _extract_transcript_segments, _from_html


def test_from_html_plain_text():
    html = "<html><head><title>Porada</title></head><body><p>Ahoj svet</p></body></html>"
    norm = _from_html(html, None)
    assert norm.title == "Porada"
    assert "Ahoj svet" in norm.text


def test_transcript_segments_via_classes():
    html = """
    <div class="transcript-line" data-speaker="Pavol" data-timestamp="0:12">
      <span class="text">Musíme poslať faktúru klientovi.</span>
    </div>
    <div class="transcript-line" data-speaker="Jana" data-timestamp="0:20">
      <span class="text">Dobre, pripravím to zajtra.</span>
    </div>
    """
    from bs4 import BeautifulSoup

    segs = _extract_transcript_segments(BeautifulSoup(html, "html.parser"))
    assert len(segs) == 2
    assert segs[0]["speaker"] == "Pavol"
    assert segs[0]["ts"] == "0:12"
    assert "faktúru" in segs[0]["text"]


def test_transcript_segments_via_plaintext_pattern():
    html = "<body><pre>Pavol 00:12 Musime poslat fakturu.\nJana 00:20 Dobre.</pre></body>"
    norm = _from_html(html, None)
    assert norm.segments
    assert norm.segments[0]["speaker"] == "Pavol"


def test_html_without_transcript_returns_text_only():
    norm = _from_html("<body><p>len text</p></body>", None)
    assert norm.segments == []
    assert "len text" in norm.text


def test_parse_asr_segments_timestamp_speaker_text_layout():
    from majak.ingest.normalize import parse_asr_segments

    text = (
        "00:00:00\nJanči Hroncák\nNo dobre, ahojte, kde sme skončili?\n"
        "00:00:25\nPavol Turčina\nZdá sa, že ten partner môže byť ten,\nkto má koncesiu.\n"
        "00:01:10\nMiro Šinger\nSúhlasím, poďme na to.\n"
    )
    segs = parse_asr_segments(text)
    assert len(segs) == 3
    assert segs[0]["ts"] == "00:00:00"
    assert segs[0]["speaker"] == "Janči Hroncák"
    # Multi-line body is joined.
    assert segs[1]["text"] == "Zdá sa, že ten partner môže byť ten, kto má koncesiu."
    assert segs[2]["speaker"] == "Miro Šinger"


def test_parse_asr_segments_rejects_non_transcript():
    from majak.ingest.normalize import parse_asr_segments

    assert parse_asr_segments("Toto je len bežná poznámka bez časových značiek.") == []


@pytest.mark.asyncio
async def test_normalize_transcript_text_populates_segments():
    from majak.ingest.normalize import normalize
    from majak.models.schemas import RawInput

    text = "0:05\nPavol Turčina\nMusíme poslať faktúru.\n0:20\nJana\nDobre.\n0:40\nPavol\nĎakujem.\n"
    norm = await normalize(RawInput(kind="transcript", text=text))
    assert len(norm.segments) == 3
    assert norm.segments[0]["speaker"] == "Pavol Turčina"


@pytest.mark.asyncio
async def test_normalize_text_passthrough():
    from majak.ingest.normalize import normalize
    from majak.models.schemas import RawInput

    norm = await normalize(RawInput(kind="text", text="  Nejaký   text \r\n\r\n\r\n koniec "))
    assert norm.text == "Nejaký text\n\nkoniec"
