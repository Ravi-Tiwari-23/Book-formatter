from __future__ import annotations

from dataclasses import replace

from .models import Correction, Decision, ReviewStatus


def apply_decision(
    correction: Correction, decision: Decision, *, manual_text: str | None = None
) -> Correction:
    if decision == Decision.EDIT:
        if not manual_text or not manual_text.strip():
            raise ValueError("Manual text is required for EDIT")
        final = manual_text.strip()
    elif decision == Decision.USE_REFERENCE:
        if not correction.reference_text:
            raise ValueError("This correction has no reference text")
        final = correction.reference_text
    elif decision == Decision.ACCEPT:
        final = correction.suggested_text
    else:
        final = correction.source_text
    status = ReviewStatus.REJECTED if decision == Decision.REJECT else ReviewStatus.APPROVED
    return replace(correction, decision=decision, final_text=final, status=status)


def finalize_text(corrections: list[Correction]) -> str:
    pending = [item.id for item in corrections if item.status == ReviewStatus.PENDING]
    if pending:
        raise ValueError(f"Cannot finalize text: {len(pending)} correction(s) pending")
    return "\n\n".join(item.final_text or item.source_text for item in corrections)

