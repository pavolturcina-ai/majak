"""Extract seed material from an existing evaluation report HTML into seed/raw/.

The Phase-1 report embeds its source material as `const SOURCES = {...}` — the 7
meeting transcripts plus the Slack/Gmail/Jira reference links. This converter
pulls that out and writes it to seed/raw/ so `python -m majak.seed.run` can
ingest it through the real pipeline.

It writes only files derived from the report you pass in; it contains no data of
its own. The written transcripts are sensitive, so seed/raw/ is gitignored.

Usage:
    python -m majak.seed.from_report path/to/report.html [--out seed/raw] [--year 2026]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SOURCES_RE = re.compile(r"const\s+SOURCES\s*=\s*(\{.*?\})\s*;?\s*\n", re.DOTALL)
_DM_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.?")


def _slug(text: str, limit: int = 48) -> str:
    from majak.util.text import strip_accents

    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:limit] or "bez-nazvu"


def _iso_date(day: str, year: int) -> str | None:
    """'10.7.' -> '2026-07-10'."""
    m = _DM_RE.search(day or "")
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    return f"{year:04d}-{mo:02d}-{d:02d}"


def _extract_sources(html: str) -> dict:
    m = _SOURCES_RE.search(html)
    if not m:
        # Fallback: brace-match from 'const SOURCES ='.
        idx = html.find("const SOURCES")
        eq = html.find("=", idx)
        start = html.find("{", eq)
        depth = 0
        for i in range(start, len(html)):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(html[start : i + 1])
        raise ValueError("Could not locate const SOURCES in the report")
    return json.loads(m.group(1))


def convert(report: Path, out_dir: Path, year: int) -> dict:
    html = report.read_text(encoding="utf-8", errors="replace")
    sources = _extract_sources(html)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []

    # 1. Meeting transcripts → one .txt each, dated so the day is recovered.
    meetings = sources.get("meetings", [])
    for i, mtg in enumerate(meetings, start=1):
        iso = _iso_date(mtg.get("day", ""), year) or f"{year}-01-01"
        title = mtg.get("title", f"meeting-{i}")
        transcript = mtg.get("transcript", "").strip()
        if not transcript:
            continue
        fname = f"{iso}_{i:02d}_{_slug(title)}.txt"
        header = f"# {title}\n# {mtg.get('day', '')}\n\n"
        (out_dir / fname).write_text(header + transcript, encoding="utf-8")
        written.append(fname)

    # 2. Slack/Gmail/Jira links → references.json.
    refs = []
    kind_map = {"slack": "slack", "gmail": "email", "jira": "jira"}
    for group, kind in kind_map.items():
        for j, ref in enumerate(sources.get(group, [])):
            iso = _iso_date(ref.get("day", ""), year)
            refs.append(
                {
                    "kind": kind,
                    "connector": f"seed-{group}",
                    "external_id": f"seed-{group}:{j}",
                    "title": ref.get("label", ""),
                    "text": ref.get("label", ""),
                    "url": ref.get("url") or None,
                    "occurred_on": iso,
                }
            )
    if refs:
        (out_dir / "references.json").write_text(
            json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written.append("references.json")

    summary = {
        "transcripts": len(written) - (1 if refs else 0),
        "references": len(refs),
        "files": written,
        "out_dir": str(out_dir),
    }
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Extract seed/raw/* from a report HTML.")
    parser.add_argument("report", help="path to the evaluation report .html")
    parser.add_argument("--out", default="seed/raw", help="output directory")
    parser.add_argument("--year", type=int, default=2026, help="year for D.M. dates")
    args = parser.parse_args()

    summary = convert(Path(args.report), Path(args.out), args.year)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
