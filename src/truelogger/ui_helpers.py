from __future__ import annotations

import math
import hashlib
from collections.abc import MutableMapping
from typing import Any, TypeVar, TYPE_CHECKING

from .models import ReviewStatus

if TYPE_CHECKING:
    from .models import Correction
    from .pipeline import ValidationProject


T = TypeVar("T")


def paginate(values: list[T], *, page_number: int, page_size: int = 25) -> tuple[list[T], int]:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    total_pages = max(1, math.ceil(len(values) / page_size))
    current = min(max(1, page_number), total_pages)
    start = (current - 1) * page_size
    return values[start:start + page_size], total_pages


def correction_counts(values) -> dict[str, int]:
    exact = sum(item.category == "EXACT_MATCH" for item in values)
    safe = sum(item.category == "SAFE_MATCH" for item in values)
    spelling = sum(
        item.category in {"SPELLING_DIFFERENCE", "SPELLING_CANDIDATE"}
        for item in values
    )
    grammar = sum(
        item.category in {"GRAMMAR_DIFFERENCE", "GRAMMAR_CANDIDATE"}
        for item in values
    )
    return {
        "exact": exact,
        "safe_auto_approved": safe,
        "spelling": spelling,
        "grammar": grammar,
        "meaningful": len(values) - exact - safe,
        "needs_manual_review": sum(
            item.status == ReviewStatus.PENDING for item in values
        ),
    }


def approved_text_sha256(corrections: list["Correction"]) -> str:
    approved = "\n\n".join(item.final_text or item.source_text for item in corrections)
    return hashlib.sha256(approved.encode("utf-8")).hexdigest()


def finalization_is_current(
    state: MutableMapping[str, Any], corrections: list["Correction"]
) -> bool:
    finalized = state.get("finalized_text_sha256")
    return bool(finalized) and finalized == approved_text_sha256(corrections)


def invalidate_approved_state(
    state: MutableMapping[str, Any],
    project: "ValidationProject",
    *,
    clear_structure: bool,
) -> None:
    state["text_finalized"] = False
    state["finalized_text_sha256"] = None
    state["artifacts"] = None
    state["integrity_report"] = None
    state["integrity_report_key"] = None
    if clear_structure:
        project.structure_override = None


def current_integrity_report(
    state: MutableMapping[str, Any], approved_hash: str
) -> Any | None:
    if state.get("integrity_report_key") != approved_hash:
        return None
    return state.get("integrity_report")
