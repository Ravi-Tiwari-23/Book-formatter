from __future__ import annotations

from .models import Decision


DECISION_LABELS = {
    Decision.ACCEPT: "Accept suggestion",
    Decision.REJECT: "Keep source (reject)",
    Decision.EDIT: "Use my edit",
    Decision.KEEP_SOURCE: "Keep source",
    Decision.USE_REFERENCE: "Use reference text",
}


def decision_label(value: Decision | None) -> str:
    return "Use safe default" if value is None else DECISION_LABELS[value]


def approval_summary(corrections) -> dict[str, int]:
    overrides = sum(bool(item.user_decision or item.decision) for item in corrections)
    attention = sum(item.severity == "Needs attention" for item in corrections)
    return {
        "findings": len(corrections),
        "defaults": len(corrections) - overrides,
        "overrides": overrides,
        "attention": attention,
    }
