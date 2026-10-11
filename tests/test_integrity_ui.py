from streamlit.testing.v1 import AppTest

from truelogger.models import StructuredBlock, BlockKind
from truelogger.pipeline import canonical_text_units
from truelogger.ui_helpers import (
    approved_text_sha256,
    current_integrity_report,
    finalization_is_current,
    invalidate_approved_state,
)

from test_production_integrity import _project


def test_integrity_failure_panel_is_actionable_without_traceback():
    script = r'''
import streamlit as st
from truelogger.integrity import (
    IntegrityDifferenceType, IntegrityIssue, IntegrityReport,
    ProductionIntegrityError,
)
from truelogger.integrity_ui import render_integrity_failure

issues = [
    IntegrityIssue(
        canonical_id="one", chapter_id="1", chapter_title="Goddess Annapurna",
        unit_order=0, difference_type=IntegrityDifferenceType.MISSING,
        expected_text="Approved first paragraph.", expected_sha256="abc",
        expected_length=25, difference_excerpt="Possible missing text",
    ),
    IntegrityIssue(
        canonical_id="two", chapter_id="3", chapter_title="Vastu Bricks",
        unit_order=1, difference_type=IntegrityDifferenceType.MODIFIED,
        expected_text="Approved second paragraph.", actual_text="Changed paragraph.",
        expected_sha256="def", actual_sha256="ghi", expected_length=26,
        actual_length=18, difference_excerpt="Changed paragraph",
    ),
]
report = IntegrityReport("POST_RENDER", False, 2, 2, issues)
render_integrity_failure(ProductionIntegrityError(report))
'''

    at = AppTest.from_string(script).run()

    assert not at.exception
    values = [node.value for node in at.error] + [node.value for node in at.markdown]
    assert any("FINAL BUILD BLOCKED" in str(value) for value in values)
    assert any("2 issues" in str(value) for value in values)
    assert any("Goddess Annapurna" in expander.label for expander in at.expander)
    assert any("Vastu Bricks" in expander.label for expander in at.expander)
    assert not any("Traceback" in str(value) for value in values)
    assert at.get("download_button")


def test_integrity_failure_allows_multiple_findings_for_one_unit():
    script = r'''
from truelogger.integrity import (
    IntegrityDifferenceType, IntegrityIssue, IntegrityReport,
    ProductionIntegrityError,
)
from truelogger.integrity_ui import render_integrity_failure

shared = dict(
    canonical_id="same-unit", chapter_id="1", chapter_title="Chapter",
    unit_order=18, expected_text="Approved paragraph.",
    expected_sha256="expected", actual_sha256="actual",
)
issues = [
    IntegrityIssue(
        **shared, difference_type=IntegrityDifferenceType.MODIFIED,
        actual_text="Changed paragraph.", difference_excerpt="Changed",
    ),
    IntegrityIssue(
        **shared, difference_type=IntegrityDifferenceType.ORDER_CHANGED,
        actual_text="Changed paragraph.", difference_excerpt="Moved",
    ),
]
report = IntegrityReport("POST_RENDER", False, 1, 1, issues)
render_integrity_failure(ProductionIntegrityError(report))
'''

    at = AppTest.from_string(script).run()

    assert not at.exception
    assert len(at.text_area) == 2
    assert len(at.button) == 8


def test_finalization_uses_current_approved_hash(tmp_path):
    project = _project(tmp_path)
    state = {"finalized_text_sha256": approved_text_sha256(project.corrections)}

    assert finalization_is_current(state, project.corrections) is True

    project.corrections[0].final_text = "A newly approved edit."

    assert finalization_is_current(state, project.corrections) is False


def test_invalidation_clears_artifacts_reports_and_stale_structure(tmp_path):
    project = _project(tmp_path)
    project.structure_override = [StructuredBlock(BlockKind.BODY, "Stale")]
    state = {
        "text_finalized": True,
        "finalized_text_sha256": "old",
        "artifacts": object(),
        "integrity_report": {"passed": False},
        "integrity_report_key": "old",
    }

    invalidate_approved_state(state, project, clear_structure=True)

    assert state["text_finalized"] is False
    assert state["finalized_text_sha256"] is None
    assert state["artifacts"] is None
    assert state["integrity_report"] is None
    assert state["integrity_report_key"] is None
    assert project.structure_override is None


def test_old_integrity_report_is_ignored_after_approved_text_changes(tmp_path):
    project = _project(tmp_path)
    old_hash = approved_text_sha256(project.corrections)
    state = {
        "integrity_report": {"passed": False},
        "integrity_report_key": old_hash,
    }
    assert current_integrity_report(state, old_hash) == {"passed": False}

    project.corrections[0].final_text = "New approved text."
    new_hash = approved_text_sha256(project.corrections)

    assert current_integrity_report(state, new_hash) is None


def test_canonical_unit_id_can_resolve_review_action(tmp_path):
    project = _project(tmp_path)
    units = canonical_text_units(project, None)

    assert units[0].id == project.corrections[0].id
