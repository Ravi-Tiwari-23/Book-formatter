from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz, process


class MatchCategory(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    SAFE_MATCH = "SAFE_MATCH"
    MINOR_DIFFERENCE = "MINOR_DIFFERENCE"
    SPELLING_DIFFERENCE = "SPELLING_DIFFERENCE"
    GRAMMAR_DIFFERENCE = "GRAMMAR_DIFFERENCE"
    REFERENCE_DIFFERENCE = "REFERENCE_DIFFERENCE"
    SOURCE_ONLY = "SOURCE_ONLY"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    UNCERTAIN_MATCH = "UNCERTAIN_MATCH"


@dataclass(slots=True)
class PassageMatch:
    source_text: str
    reference_text: str | None
    source_page: int
    reference_page: int | None
    score: float
    category: MatchCategory


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_safe_text(value: str) -> str:
    value = normalize_text(value).replace("\u00ad", "")
    value = re.sub(r"\s+([।,.!?;:])", r"\1", value)
    value = re.sub(r"([([{])\s+", r"\1", value)
    value = re.sub(r"\s+([)\]}])", r"\1", value)
    return value


def _category(source: str, reference: str, score: float) -> MatchCategory:
    if normalize_text(source) == normalize_text(reference):
        return MatchCategory.EXACT_MATCH
    source_words = normalize_text(source).split()
    reference_words = normalize_text(reference).split()
    if score >= 92 and abs(len(source_words) - len(reference_words)) <= 1:
        return MatchCategory.SPELLING_DIFFERENCE
    if score >= 82:
        return MatchCategory.MINOR_DIFFERENCE
    if score >= 65:
        return MatchCategory.UNCERTAIN_MATCH
    return MatchCategory.SOURCE_ONLY


def match_paragraphs(
    source: list[tuple[int, str]],
    reference: list[tuple[int, str]],
    *,
    minimum_score: float = 60,
    sequence_window: int = 12,
    metrics: dict[str, int] | None = None,
) -> list[PassageMatch]:
    """Monotonic fuzzy alignment using content and nearby sequence context."""
    if not reference:
        return [PassageMatch(text, None, page, None, 0, MatchCategory.SOURCE_ONLY) for page, text in source]
    reference_texts = [normalize_text(text) for _, text in reference]
    safe_reference_texts = [normalize_safe_text(text) for _, text in reference]
    cursor = 0
    matches: list[PassageMatch] = []
    for source_page, source_text in source:
        start = max(0, cursor - 2)
        stop = min(len(reference), max(cursor + sequence_window, start + 1))
        candidates = reference_texts[start:stop]
        normalized_source = normalize_text(source_text)
        if normalized_source in candidates:
            relative_index = candidates.index(normalized_source)
            index = start + relative_index
            cursor = max(cursor, index + 1)
            reference_page, reference_text = reference[index]
            if metrics is not None:
                metrics["exact_fast_paths"] = metrics.get("exact_fast_paths", 0) + 1
            matches.append(
                PassageMatch(
                    source_text,
                    reference_text,
                    source_page,
                    reference_page,
                    100.0,
                    MatchCategory.EXACT_MATCH,
                )
            )
            continue
        safe_source = normalize_safe_text(source_text)
        safe_candidates = safe_reference_texts[start:stop]
        if safe_source in safe_candidates:
            relative_index = safe_candidates.index(safe_source)
            index = start + relative_index
            cursor = max(cursor, index + 1)
            reference_page, reference_text = reference[index]
            if metrics is not None:
                metrics["safe_fast_paths"] = metrics.get("safe_fast_paths", 0) + 1
            matches.append(
                PassageMatch(
                    source_text,
                    reference_text,
                    source_page,
                    reference_page,
                    100.0,
                    MatchCategory.SAFE_MATCH,
                )
            )
            continue
        if metrics is not None:
            metrics["fuzzy_comparisons"] = metrics.get("fuzzy_comparisons", 0) + len(candidates)
        best = process.extractOne(
            normalized_source, candidates, scorer=fuzz.WRatio, score_cutoff=minimum_score
        )
        if best is None:
            matches.append(PassageMatch(source_text, None, source_page, None, 0, MatchCategory.SOURCE_ONLY))
            continue
        _, score, relative_index = best
        index = start + relative_index
        cursor = max(cursor, index + 1)
        reference_page, reference_text = reference[index]
        matches.append(
            PassageMatch(
                source_text,
                reference_text,
                source_page,
                reference_page,
                float(score),
                _category(source_text, reference_text, score),
            )
        )
    return matches

