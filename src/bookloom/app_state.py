from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


DOCUMENT_STATE_DEFAULTS = {
    "job": None,
    "project": None,
    "artifacts": None,
    "text_finalized": False,
    "finalized_text_sha256": None,
    "integrity_report": None,
    "integrity_report_key": None,
    "document_approval": None,
    "pdf_preview_loaded": False,
}


def initialize_document_state(state: MutableMapping[str, Any]) -> None:
    for key, value in DOCUMENT_STATE_DEFAULTS.items():
        state.setdefault(key, value)


def reset_document_state(state: MutableMapping[str, Any]) -> None:
    for key, value in DOCUMENT_STATE_DEFAULTS.items():
        state[key] = value


def workflow_stage(project: Any | None, artifacts: Any | None) -> str:
    if project is None:
        return "upload"
    if artifacts is not None:
        return "download"
    if getattr(project, "approval", None) is not None:
        return "build"
    return "review"
