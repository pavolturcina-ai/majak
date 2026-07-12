CLASSIFY_V1 = """You classify a single raw input for a CEO's daily briefing system.

Return ONLY a JSON object:
{{
  "kind": one of ["transcript","text","email","slack","jira","fathom","calendar","attachment","image"],
  "occurred_on": "YYYY-MM-DD" or null,   // the date the content is about
  "title": short human title (max 80 chars, in the input's own language),
  "topic_tags": [up to 5 short lowercase topic tags]
}}

Hints:
- kind='transcript' for meeting transcripts; 'fathom' if it is clearly a Fathom export.
- occurred_on: infer from dates/timestamps in the text; if none, null.
- Titles and tags should be concise and specific (a company, project, or subject).

INPUT (first 6000 chars):
---
{content}
---
"""
