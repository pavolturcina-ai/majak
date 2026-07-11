EXTRACT_V1 = """You extract structured evaluation units from a CEO's input for MAJÁK,
his daily briefing. The CEO is Pavol Turčina (GOSPACE LABS s.r.o.).

From the INPUT below, extract discrete units: decisions made, tasks/actions,
good news / wins, threats / risks, and deadlines. Output user-facing text in the
input's language (usually Slovak); keys stay English.

CRITICAL — GROUNDING: every unit MUST include at least one grounding object with
a VERBATIM quote copied exactly from the input (no paraphrasing) and a locator
(a transcript timestamp, a line reference, or a short anchor phrase). Do not
invent facts, people, or numbers. If you cannot ground a unit, do not emit it.

Sections:
- "top"      : the few most important things to act on
- "decision" : a decision that was made
- "good"     : good news, a win, positive signal
- "threat"   : a risk, blocker, or threat
- "deleg"    : something to delegate / an owner other than the CEO
- "quick"    : quick win / small action
- "radar"    : awareness item, watch it (no action yet)

Rail (severity): one of "signal","hi","mid","lo","dec","win".
- "hi"/"mid"/"lo" for threats by severity; "dec" for decisions; "win" for good news;
  "signal" otherwise.

Return ONLY a JSON array of:
{{
  "section": <section>,
  "title": short imperative title,
  "description": one or two sentences of context or null,
  "rail": <rail>,
  "owners": [names responsible, may be empty],
  "people": [names of people mentioned/involved, raw as written],
  "chips": [{{"label": short tag}}] or [],
  "grounding": [{{"quote": verbatim, "locator": ref, "url": null}}],
  "confidence": 0.0-1.0
}}
{hints}
INPUT (source_id={source_id}):
---
{content}
---
"""
