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


@pytest.mark.asyncio
async def test_normalize_text_passthrough():
    from majak.ingest.normalize import normalize
    from majak.models.schemas import RawInput

    norm = await normalize(RawInput(kind="text", text="  Nejaký   text \r\n\r\n\r\n koniec "))
    assert norm.text == "Nejaký text\n\nkoniec"
