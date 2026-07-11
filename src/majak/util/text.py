"""Pure text helpers shared across the pipeline (no external deps)."""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_NON_NAME_RE = re.compile(r"[^a-z0-9\s'-]")


def strip_accents(value: str) -> str:
    """Remove diacritics: 'Turčina' -> 'Turcina'."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(value: str) -> str:
    """Lowercase, accent-strip, drop punctuation, collapse whitespace.

    Used both when storing people/aliases and when resolving a raw mention, so
    the two always agree on the comparison key.
    """
    folded = strip_accents(value).lower()
    folded = _NON_NAME_RE.sub(" ", folded)
    return _WS_RE.sub(" ", folded).strip()


def collapse_whitespace(value: str) -> str:
    """Normalize runs of whitespace to single spaces and trim."""
    return _WS_RE.sub(" ", value).strip()


def clean_text(value: str) -> str:
    """Normalize newlines and trim trailing whitespace on each line."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in value.split("\n")]
    # Collapse 3+ blank lines to a single blank line.
    out: list[str] = []
    blank = 0
    for line in lines:
        if line.strip() == "":
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(line)
    return "\n".join(out).strip()


def chunk_text(value: str, *, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split text into overlapping chunks for embedding, preferring paragraph breaks."""
    value = value.strip()
    if not value:
        return []
    if len(value) <= max_chars:
        return [value]

    chunks: list[str] = []
    start = 0
    n = len(value)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # Prefer to break on a paragraph or sentence boundary within the window.
            window = value[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                idx = window.rfind(sep)
                if idx > max_chars // 2:
                    end = start + idx + len(sep)
                    break
        chunks.append(value[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]
