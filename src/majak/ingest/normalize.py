"""Normalize any input into clean text.

Supports: plain text, HTML (incl. meeting-transcript exports), docx, pdf, eml,
and images (via Claude vision, optional Tesseract fallback). Heavy parser
imports are lazy so unused formats don't add import cost.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from majak.llm.client import get_llm
from majak.llm.prompts import VISION_OCR_V1
from majak.models.schemas import RawInput
from majak.util.text import clean_text, collapse_whitespace

logger = logging.getLogger(__name__)


@dataclass
class NormalizedInput:
    text: str
    title: str | None = None
    # Structured transcript lines when we can recover them: (speaker, ts, text).
    segments: list[dict] = field(default_factory=list)
    ocr_text: str | None = None


async def normalize(raw: RawInput) -> NormalizedInput:
    """Dispatch on the input shape and return clean text (+ optional structure)."""
    if raw.text is not None:
        cleaned = clean_text(raw.text)
        segments: list[dict] = []
        # ASR/Fathom transcripts arrive as plain text (timestamp / speaker / text).
        if raw.kind in ("transcript", "fathom"):
            segments = parse_asr_segments(raw.text)
        return NormalizedInput(text=cleaned, title=raw.title, segments=segments)

    if raw.html is not None:
        return _from_html(raw.html, raw.title)

    if raw.image_bytes is not None:
        text = await _from_image(raw.image_bytes)
        return NormalizedInput(text=clean_text(text), title=raw.title, ocr_text=text)

    if raw.file_bytes is not None:
        return _from_file(raw.file_bytes, raw.file_name or "", raw.mime or "", raw.title)

    return NormalizedInput(text="", title=raw.title)


# ── HTML (including transcript exports) ───────────────────────────────────────
def _from_html(html: str, title: str | None) -> NormalizedInput:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    page_title = title or (soup.title.string.strip() if soup.title and soup.title.string else None)

    segments = _extract_transcript_segments(soup)
    if segments:
        text = "\n".join(_format_segment(s) for s in segments)
        return NormalizedInput(text=clean_text(text), title=page_title, segments=segments)

    text = soup.get_text(separator="\n")
    return NormalizedInput(text=clean_text(text), title=page_title)


def _extract_transcript_segments(soup) -> list[dict]:
    """Recover (speaker, timestamp, text) lines from common transcript exports.

    Looks for elements tagged with speaker/timestamp classes; falls back to
    'Name  0:12' line patterns. Returns [] when nothing transcript-like is found.
    """
    segments: list[dict] = []

    # Pattern A: explicit blocks with data attributes / classes.
    for block in soup.select(
        "[data-speaker], .transcript-line, .transcript__line, .speaker-block, .caption"
    ):
        speaker = block.get("data-speaker")
        ts = block.get("data-timestamp") or block.get("data-time")
        if not speaker:
            sp_el = block.select_one(".speaker, .name, .transcript__speaker")
            speaker = sp_el.get_text(strip=True) if sp_el else None
        if not ts:
            ts_el = block.select_one(".timestamp, .time, .transcript__time")
            ts = ts_el.get_text(strip=True) if ts_el else None
        txt_el = block.select_one(".text, .transcript__text, .content") or block
        text = collapse_whitespace(txt_el.get_text(separator=" "))
        if text:
            segments.append({"speaker": speaker, "ts": ts, "text": text})

    if segments:
        return segments

    # Pattern B: heuristic on plain text lines like "Speaker Name  00:12  ...".
    line_re = re.compile(r"^(?P<speaker>[A-ZÀ-ž][\w .'-]{1,40}?)\s+(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<text>.+)$")
    for line in soup.get_text(separator="\n").split("\n"):
        m = line_re.match(line.strip())
        if m:
            segments.append(
                {"speaker": m.group("speaker").strip(), "ts": m.group("ts"), "text": m.group("text").strip()}
            )
    return segments


_TS_LINE_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
# A speaker line: a short name-like line, no sentence-ending punctuation.
_SPEAKER_LINE_RE = re.compile(r"^[A-ZÀ-Ž][\w .'’-]{1,44}$")


def parse_asr_segments(text: str) -> list[dict]:
    """Parse the 'timestamp / speaker / text' layout common to ASR + Fathom exports.

        00:00:00
        Janči Hroncák
        No dobre, ahojte...
        00:00:25
        Pavol Turčina
        Zdá sa, že...

    Returns [{speaker, ts, text}]; [] when the text isn't in this shape.
    """
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    segments: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _TS_LINE_RE.match(line):
            ts = line
            # Next non-empty line should be the speaker.
            j = i + 1
            while j < n and not lines[j]:
                j += 1
            speaker = None
            if j < n and _SPEAKER_LINE_RE.match(lines[j]) and not _TS_LINE_RE.match(lines[j]):
                speaker = lines[j]
                j += 1
            # Collect text until the next timestamp line.
            body: list[str] = []
            while j < n and not _TS_LINE_RE.match(lines[j]):
                if lines[j]:
                    body.append(lines[j])
                j += 1
            body_text = re.sub(r"\s+", " ", " ".join(body)).strip()
            if body_text:
                segments.append({"speaker": speaker, "ts": ts, "text": body_text})
            i = j
        else:
            i += 1
    # Require a few segments before trusting the parse (avoids false positives).
    return segments if len(segments) >= 3 else []


def _format_segment(seg: dict) -> str:
    speaker = seg.get("speaker") or "?"
    ts = seg.get("ts")
    prefix = f"[{ts}] {speaker}:" if ts else f"{speaker}:"
    return f"{prefix} {seg['text']}"


# ── Files: docx / pdf / eml ───────────────────────────────────────────────────
def _from_file(data: bytes, name: str, mime: str, title: str | None) -> NormalizedInput:
    lname = name.lower()
    if lname.endswith(".docx") or "wordprocessingml" in mime:
        return NormalizedInput(text=_from_docx(data), title=title or name)
    if lname.endswith(".pdf") or mime == "application/pdf":
        return NormalizedInput(text=_from_pdf(data), title=title or name)
    if lname.endswith(".eml") or mime == "message/rfc822":
        return _from_eml(data, title)
    if lname.endswith((".html", ".htm")) or mime == "text/html":
        return _from_html(data.decode("utf-8", errors="replace"), title)
    # Default: decode as text.
    return NormalizedInput(text=clean_text(data.decode("utf-8", errors="replace")), title=title or name)


def _from_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return clean_text("\n".join(parts))


def _from_pdf(data: bytes) -> str:
    import fitz  # pymupdf

    text_parts: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))
    return clean_text("\n".join(text_parts))


def _from_eml(data: bytes, title: str | None) -> NormalizedInput:
    import mailparser

    parsed = mailparser.parse_from_bytes(data)
    subject = parsed.subject or title
    body = parsed.text_plain[0] if parsed.text_plain else (parsed.body or "")
    header = f"From: {parsed.from_}\nTo: {parsed.to}\nSubject: {subject}\n\n"
    return NormalizedInput(text=clean_text(header + body), title=subject)


# ── Images: Claude vision, Tesseract fallback ─────────────────────────────────
async def _from_image(data: bytes) -> str:
    llm = get_llm()
    if llm.available:
        try:
            return await llm.complete(VISION_OCR_V1, route="vision", images=[data], max_tokens=2048)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision OCR failed, trying Tesseract: %s", exc)
    return _tesseract(data)


def _tesseract(data: bytes) -> str:
    try:
        import io

        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tesseract OCR unavailable: %s", exc)
        return ""
