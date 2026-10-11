from __future__ import annotations

import hashlib
import re

from .matching import MatchCategory, PassageMatch, normalize_text
from .grammar import validate_grammar
from .models import Confidence, Correction, Decision, ReviewStatus
from .review import default_decision_for


_CLEAR_RULES = {
    "बहोत": "बहुत",
    "है। है।": "है।",
}


def _contains_protected_difference(match: PassageMatch, terms: set[str]) -> bool:
    combined = f"{match.source_text} {match.reference_text or ''}"
    return any(term and term in combined for term in terms) and normalize_text(
        match.source_text
    ) != normalize_text(match.reference_text or "")


def _rule_suggestion(text: str, protected_terms: set[str]) -> tuple[str, str] | None:
    grammar = validate_grammar(text, protected_terms)
    if grammar:
        finding = grammar[0]
        return finding.suggested_text, finding.explanation
    updated = text
    reasons: list[str] = []
    for wrong, right in _CLEAR_RULES.items():
        if wrong in updated and wrong not in protected_terms:
            updated = updated.replace(wrong, right)
            reasons.append(f"Rule-based correction: {wrong} -> {right}")
    updated = re.sub(r"[ \t]+([।,.!?])", r"\1", updated)
    if updated != text and not reasons:
        reasons.append("Punctuation spacing rule")
    return (updated, "; ".join(reasons)) if updated != text else None


def build_corrections(matches: list[PassageMatch], protected_terms: set[str]) -> list[Correction]:
    corrections: list[Correction] = []
    for index, match in enumerate(matches):
        if match.category in {MatchCategory.EXACT_MATCH, MatchCategory.SAFE_MATCH}:
            suggested = match.source_text
            confidence = Confidence.HIGH
            reason = (
                "Exact reference match"
                if match.category == MatchCategory.EXACT_MATCH
                else "Safe non-semantic extraction/spacing difference"
            )
        elif match.reference_text and match.score >= 82:
            rule = _rule_suggestion(match.source_text, protected_terms)
            suggested = rule[0] if rule else match.source_text
            rule_confirmed_by_reference = bool(
                rule
                and match.score >= 90
                and normalize_text(rule[0]) == normalize_text(match.reference_text)
            )
            confidence = (
                Confidence.HIGH if rule_confirmed_by_reference else
                Confidence.MEDIUM if rule else Confidence.LOW
            )
            reason = (
                f"{rule[1]}; reference supports context" if rule else
                "Reference differs but is not grammatical authority; manual review required"
            )
        else:
            rule = _rule_suggestion(match.source_text, protected_terms)
            suggested, reason = rule or (match.source_text, "Weak or missing reference evidence")
            confidence = Confidence.MEDIUM if rule else Confidence.LOW

        protected = _contains_protected_difference(match, protected_terms)
        weak = match.reference_text is None or match.score < 82
        unproven_reference_change = bool(
            match.reference_text
            and normalize_text(match.source_text) != normalize_text(match.reference_text)
            and suggested == match.source_text
        )
        review_required = protected or weak or unproven_reference_change or match.category == MatchCategory.UNCERTAIN_MATCH
        if match.category in {MatchCategory.EXACT_MATCH, MatchCategory.SAFE_MATCH}:
            review_required = False
        if protected:
            confidence = Confidence.LOW
            reason = "Protected traditional/religious term differs; manual review required"
            suggested = match.source_text

        digest = hashlib.sha1(
            f"{match.source_page}:{index}:{match.source_text}".encode("utf-8")
        ).hexdigest()[:12]
        correction = Correction(
                id=digest,
                source_text=match.source_text,
                reference_text=match.reference_text,
                suggested_text=suggested,
                final_text=None,
                source_page=match.source_page,
                reference_page=match.reference_page,
                confidence=confidence,
                reason=reason,
                category=match.category.value,
                review_required=review_required,
            )
        correction.default_decision = default_decision_for(correction)
        if match.category in {MatchCategory.EXACT_MATCH, MatchCategory.SAFE_MATCH}:
            correction.status = ReviewStatus.APPROVED
            correction.final_text = match.source_text
        corrections.append(correction)
    return corrections

