from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

from .models import Correction, Decision, DocumentApproval, ReviewStatus


REVIEW_POLICY_VERSION = "bookloom-safe-defaults-v1"
_RISK_CATEGORIES = {
    "SEMANTIC_DIFFERENCE", "MEANING_DIFFERENCE", "POSSIBLE_MISSING_CONTENT",
    "REFERENCE_ONLY", "SOURCE_ONLY", "UNCERTAIN_MATCH", "METADATA_CONFLICT",
    "NUMBER_CONFLICT", "AUTHOR_CONFLICT", "DOI_CONFLICT",
}
_SAFE_CATEGORIES = {
    "OCR_CORRECTION", "SPELLING_DIFFERENCE", "SPELLING_CANDIDATE",
    "PUNCTUATION_DIFFERENCE", "GRAMMAR_DIFFERENCE", "GRAMMAR_CANDIDATE",
}


def default_decision_for(correction: Correction) -> Decision:
    category = correction.category.upper()
    reason = correction.reason.casefold()
    risky_language = any(
        token in reason
        for token in ("semantic", "meaning", "missing", "conflict", "author", "doi", "number")
    )
    if correction.confidence.value == "LOW" or category in _RISK_CATEGORIES or risky_language:
        return Decision.KEEP_SOURCE
    if category in {"EXACT_MATCH", "SAFE_MATCH"}:
        return Decision.KEEP_SOURCE
    if correction.confidence.value == "HIGH" and category in _SAFE_CATEGORIES:
        return Decision.ACCEPT
    return Decision.KEEP_SOURCE


def effective_decision(correction: Correction) -> Decision:
    return (
        correction.user_decision
        or correction.decision
        or correction.default_decision
        or default_decision_for(correction)
    )


def effective_text(correction: Correction) -> str:
    decision = effective_decision(correction)
    if decision == Decision.EDIT:
        manual = (correction.manual_text or correction.final_text or "").strip()
        if not manual:
            raise ValueError(f"Finding {correction.id} has an empty manual edit")
        return manual
    if decision == Decision.USE_REFERENCE:
        if not correction.reference_text:
            raise ValueError(f"Finding {correction.id} has no reference text")
        return correction.reference_text
    if decision == Decision.ACCEPT:
        return correction.suggested_text
    return correction.source_text


def apply_override(
    correction: Correction,
    decision: Decision,
    *,
    manual_text: str | None = None,
) -> Correction:
    if decision == Decision.EDIT and not (manual_text or "").strip():
        raise ValueError("Manual text is required for EDIT")
    if decision == Decision.USE_REFERENCE and not correction.reference_text:
        raise ValueError("This correction has no reference text")
    updated = replace(
        correction,
        default_decision=correction.default_decision or default_decision_for(correction),
        user_decision=decision,
        manual_text=manual_text.strip() if manual_text else None,
        decision=decision,
        status=ReviewStatus.REJECTED if decision == Decision.REJECT else ReviewStatus.APPROVED,
    )
    return replace(updated, final_text=effective_text(updated))


def clear_override(correction: Correction) -> Correction:
    return replace(
        correction,
        user_decision=None,
        manual_text=None,
        decision=None,
        final_text=None,
        status=ReviewStatus.PENDING,
        default_decision=correction.default_decision or default_decision_for(correction),
    )


def apply_decision(
    correction: Correction, decision: Decision, *, manual_text: str | None = None
) -> Correction:
    return apply_override(correction, decision, manual_text=manual_text)


def finalize_text(corrections: list[Correction]) -> str:
    return "\n\n".join(effective_text(item) for item in corrections)


def approve_document(corrections: list[Correction]) -> DocumentApproval:
    effective = finalize_text(corrections)
    overrides = [item for item in corrections if item.user_decision or item.decision]
    return DocumentApproval(
        approved_at_utc=datetime.now(timezone.utc).isoformat(),
        policy_version=REVIEW_POLICY_VERSION,
        finding_count=len(corrections),
        default_count=len(corrections) - len(overrides),
        override_count=len(overrides),
        edit_count=sum(effective_decision(item) == Decision.EDIT for item in corrections),
        effective_text_sha256=hashlib.sha256(effective.encode("utf-8")).hexdigest(),
    )
