PULSE_V1 = """You write the daily "pulse" for MAJÁK — a 2-3 sentence Slovak summary of the
CEO's day, plus a one-line headline. Be concrete and calm; no fluff, no emoji.

Given the day's items grouped by section, produce ONLY JSON:
{{
  "pulse": "one-line headline in Slovak",
  "summary": "2-3 sentence Slovak summary covering the key decisions, threats and wins"
}}

DAY: {day}
ITEMS (JSON):
{items_json}
"""
