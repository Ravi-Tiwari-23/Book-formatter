from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz

from .matching import normalize_text
from .models import BookSection, Confidence


class DifferenceType(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    SOURCE_ONLY = "SOURCE_ONLY"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    SPELLING_CANDIDATE = "SPELLING_CANDIDATE"
    GRAMMAR_CANDIDATE = "GRAMMAR_CANDIDATE"
    PUNCTUATION_CANDIDATE = "PUNCTUATION_CANDIDATE"
    OCR_SUSPECT = "OCR_SUSPECT"
    WORDING_DIFFERENCE = "WORDING_DIFFERENCE"
    STRUCTURE_DIFFERENCE = "STRUCTURE_DIFFERENCE"
    POSSIBLE_MISSING_CONTENT = "POSSIBLE_MISSING_CONTENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(slots=True)
class Difference:
    type: DifferenceType
    source_text: str
    reference_text: str
    source_page: int
    reference_page: int
    confidence: Confidence
    reason: str
    review_required: bool


def _sentences(text: str) -> list[str]:
    return [normalize_text(value) for value in re.split(r"(?<=[.!?।])\s+|\n+", text) if normalize_text(value)]


def compare_sections(source: BookSection, reference: BookSection) -> list[Difference]:
    source_text = " ".join(source.paragraphs)
    reference_text = " ".join(reference.paragraphs)
    if normalize_text(source_text) == normalize_text(reference_text):
        return [
            Difference(
                DifferenceType.EXACT_MATCH,
                source_text,
                reference_text,
                source.page_start,
                reference.page_start,
                Confidence.HIGH,
                "Normalized section text matches",
                False,
            )
        ]
    result: list[Difference] = []
    source_sentences = _sentences(source_text)
    reference_sentences = _sentences(reference_text)
    for sentence in reference_sentences:
        score = max((fuzz.WRatio(sentence, candidate) for candidate in source_sentences), default=0)
        if score < 72:
            result.append(
                Difference(
                    DifferenceType.POSSIBLE_MISSING_CONTENT,
                    "",
                    sentence,
                    source.page_start,
                    reference.page_start,
                    Confidence.MEDIUM if score >= 45 else Confidence.LOW,
                    "Reference sentence has no reliable source counterpart; do not add without review",
                    True,
                )
            )
    if not result:
        punctuation_only = re.sub(r"[^\w\u0900-\u097f]+", "", source_text.casefold()) == re.sub(
            r"[^\w\u0900-\u097f]+", "", reference_text.casefold()
        )
        difference_type = DifferenceType.PUNCTUATION_CANDIDATE if punctuation_only else DifferenceType.WORDING_DIFFERENCE
        result.append(
            Difference(
                difference_type,
                source_text,
                reference_text,
                source.page_start,
                reference.page_start,
                Confidence.MEDIUM,
                "Reference provides content evidence but is not grammatical authority",
                True,
            )
        )
    return result

