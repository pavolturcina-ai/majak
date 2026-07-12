DOSSIER_QUESTIONS_V1 = """You prepare a CEO for a meeting. Given a person's profile, the open items
involving them, and recent interactions, propose 3-5 sharp questions the CEO
should ask or points to raise. Slovak, concrete, tied to the open items.

Return ONLY a JSON array of strings.

PERSON: {person_json}
OPEN ITEMS: {open_items_json}
RECENT: {recent_json}
"""
