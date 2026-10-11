from dataclasses import replace

import pytest

from bookloom.models import Confidence, Correction, Decision
from bookloom.review import (
    apply_override,
    approve_document,
    default_decision_for,
    effective_decision,
    effective_text,
    finalize_text,
)


def _finding(
    *,
    confidence: Confidence = Confidence.HIGH,
    category: str = "SPELLING_DIFFERENCE",
    source: str = "teh house",
    suggestion: str = "the house",
    reference: str | None = "the house",
    reason: str = "Spelling correction confirmed by reference",
) -> Correction:
    return Correction(
        id=f"{category}-{confidence.value}",
        source_text=source,
        reference_text=reference,
        suggested_text=suggestion,
        final_text=None,
        source_page=2,
        reference_page=4,
        confidence=confidence,
        reason=reason,
        category=category,
    )


@pytest.mark.parametrize(
    "category",
    ["OCR_CORRECTION", "SPELLING_DIFFERENCE", "PUNCTUATION_DIFFERENCE"],
)
def test_high_confidence_safe_corrections_default_to_accept(category: str) -> None:
    finding = _finding(category=category)

    assert default_decision_for(finding) == Decision.ACCEPT
    assert effective_text(finding) == "the house"


@pytest.mark.parametrize(
    ("category", "reason"),
    [
        ("SEMANTIC_DIFFERENCE", "Meaning may have changed"),
        ("POSSIBLE_MISSING_CONTENT", "Missing content in source"),
        ("METADATA_CONFLICT", "Conflicting author or DOI"),
        ("NUMBER_CONFLICT", "Conflicting number"),
    ],
)
def test_risky_findings_default_to_keep_source(category: str, reason: str) -> None:
    finding = _finding(category=category, reason=reason)

    assert default_decision_for(finding) == Decision.KEEP_SOURCE
    assert effective_text(finding) == finding.source_text


def test_low_confidence_defaults_to_keep_source() -> None:
    finding = _finding(confidence=Confidence.LOW)

    assert default_decision_for(finding) == Decision.KEEP_SOURCE


def test_explicit_override_wins_over_default() -> None:
    finding = apply_override(_finding(), Decision.KEEP_SOURCE)

    assert effective_decision(finding) == Decision.KEEP_SOURCE
    assert effective_text(finding) == finding.source_text


def test_untouched_findings_can_receive_one_document_approval() -> None:
    findings = [_finding(), _finding(confidence=Confidence.LOW, category="UNCERTAIN")]

    approval = approve_document(findings)

    assert approval.finding_count == 2
    assert approval.override_count == 0
    assert approval.default_count == 2
    assert finalize_text(findings) == "the house\n\nteh house"


def test_empty_manual_edit_is_the_only_local_approval_blocker() -> None:
    invalid = replace(_finding(), user_decision=Decision.EDIT, manual_text="")

    with pytest.raises(ValueError, match="manual edit"):
        approve_document([invalid])
