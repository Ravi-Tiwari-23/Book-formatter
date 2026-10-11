from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Confidence


@dataclass(frozen=True, slots=True)
class GrammarFinding:
    rule_id: str
    original_text: str
    suggested_text: str
    confidence: Confidence
    explanation: str


_DUPLICATE = re.compile(r"(?<!\S)([^\s]+)(?:\s+\1)(?=\s|$)", re.IGNORECASE)


def validate_grammar(text: str, protected_terms: set[str]) -> list[GrammarFinding]:
    """Return only high-precision grammar findings; never rewrite prose."""
    if any(marker in text for marker in ("ॐ", "॥", "श्लोक", "मंत्र")):
        return []
    if any(term and term in text for term in protected_terms):
        return []
    deduplicated = _DUPLICATE.sub(r"\1", text)
    if deduplicated != text:
        return [
            GrammarFinding(
                rule_id="duplicate-token",
                original_text=text,
                suggested_text=deduplicated,
                confidence=Confidence.MEDIUM,
                explanation="Adjacent duplicate token; conservative grammar rule",
            )
        ]
    return []

