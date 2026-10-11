from __future__ import annotations

import json
from typing import Any

import streamlit as st

from .integrity import IntegrityReport, ProductionIntegrityError


def _report_dict(report: IntegrityReport | dict[str, Any]) -> dict[str, Any]:
    return report.to_dict() if isinstance(report, IntegrityReport) else report


def render_integrity_summary(report: IntegrityReport | dict[str, Any]) -> None:
    data = _report_dict(report)
    st.subheader("Text integrity")
    if not data.get("passed"):
        st.warning(f"{len(data.get('issues', []))} issues require review")
        return
    st.success("Approved text verified")
    st.markdown(
        "\n".join(
            [
                f"- :material/check: {data.get('chapters_checked', 0)} chapters checked",
                f"- :material/check: {data.get('checked_units', 0)} paragraphs/list items verified",
                "- :material/check: No approved text missing",
                "- :material/check: No duplicate or unexpected text detected",
            ]
        )
    )


def render_integrity_failure(
    error: ProductionIntegrityError,
) -> dict[str, str] | None:
    report = error.report
    st.error("FINAL BUILD BLOCKED")
    st.markdown(
        f"Text integrity verification found **{len(report.issues)} "
        f"issue{'s' if len(report.issues) != 1 else ''}**."
    )
    action: dict[str, str] | None = None
    for issue_index, issue in enumerate(report.issues):
        label = (
            f"{issue.chapter_title or 'Book'} — "
            f"{issue.difference_type.value.replace('_', ' ').title()}"
        )
        with st.expander(label):
            location = [
                f"Source page: {issue.source_page or 'unknown'}",
                f"Output page: {issue.output_page or 'not found'}",
                f"Severity: {issue.severity}",
            ]
            st.caption(" · ".join(location))
            st.markdown(f"**Reason:** {issue.reason}")
            if issue.original_text and issue.original_text != issue.expected_text:
                st.markdown("**Original extracted text**")
                st.code(issue.original_text, language=None)
            st.markdown("**Expected / approved**")
            st.code(issue.expected_text or "None", language=None)
            st.markdown("**Renderer input / PDF text**")
            st.code(issue.actual_text or "None", language=None)
            st.caption(issue.difference_excerpt)
            # One canonical unit can legitimately produce multiple findings
            # (for example MODIFIED plus ORDER_CHANGED). Include the finding
            # identity and occurrence so every Streamlit widget key is unique.
            issue_key = (
                f"{issue.canonical_id}-{issue.unit_order}-"
                f"{issue.difference_type.value}-{issue_index}"
            )
            edited = st.text_area(
                "Edit approved text",
                value=issue.expected_text,
                key=f"integrity-edit-{issue_key}",
            )
            with st.container(horizontal=True):
                if st.button(
                    "Use approved text",
                    key=f"integrity-approved-{issue_key}",
                    type="primary",
                    icon=":material/sync:",
                ):
                    action = {"action": "USE_APPROVED", "canonical_id": issue.canonical_id}
                if st.button(
                    "Keep current renderer text",
                    key=f"integrity-renderer-{issue_key}",
                    disabled=not bool(issue.actual_text),
                ):
                    action = {
                        "action": "KEEP_RENDERER",
                        "canonical_id": issue.canonical_id,
                        "text": issue.actual_text,
                    }
                if st.button(
                    "Save edit",
                    key=f"integrity-save-{issue_key}",
                    disabled=not bool(edited.strip()),
                ):
                    action = {
                        "action": "EDIT",
                        "canonical_id": issue.canonical_id,
                        "text": edited,
                    }
                st.button(
                    "Mark resolved",
                    key=f"integrity-resolved-{issue_key}",
                    disabled=issue.expected_sha256 != issue.actual_sha256,
                )
    st.download_button(
        "Download QA report",
        data=json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        file_name="production-text-integrity-report.json",
        mime="application/json",
        icon=":material/download:",
    )
    return action
