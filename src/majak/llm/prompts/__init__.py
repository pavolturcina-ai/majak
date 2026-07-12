"""Versioned prompt templates.

Each prompt is a module-level string with a version suffix so we can track which
template produced a given extraction. Bump the version when the wording changes.
"""

from majak.llm.prompts.classify import CLASSIFY_V1
from majak.llm.prompts.dossier import DOSSIER_QUESTIONS_V1
from majak.llm.prompts.extract import EXTRACT_V1
from majak.llm.prompts.pulse import PULSE_V1
from majak.llm.prompts.vision import VISION_OCR_V1

__all__ = [
    "CLASSIFY_V1",
    "EXTRACT_V1",
    "PULSE_V1",
    "DOSSIER_QUESTIONS_V1",
    "VISION_OCR_V1",
]
