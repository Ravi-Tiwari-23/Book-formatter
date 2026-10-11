from pathlib import Path

from streamlit.testing.v1 import AppTest

from bookloom.app_state import reset_document_state, workflow_stage


ROOT = Path(__file__).resolve().parents[1]


def test_home_is_a_staged_bookloom_upload_workflow() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()

    assert not app.exception
    assert app.title[0].value == "Bookloom"
    assert any(item.value == "Start a book" for item in app.subheader)
    assert [item.label for item in app.file_uploader] == ["Source PDF", "Reference PDF"]
    analyze = next(button for button in app.button if button.label == "Analyze PDFs")
    assert analyze.disabled is True
    assert not any(button.label == "Save decision" for button in app.button)
    assert not any(button.label == "Finalize Approved Text" for button in app.button)


def test_document_state_reset_does_not_remove_pipeline_or_system_options() -> None:
    pipeline = object()
    state = {
        "pipeline": pipeline,
        "tesseract_path": "C:/OCR/tesseract.exe",
        "project": object(),
        "artifacts": object(),
        "document_approval": object(),
        "finalized_text_sha256": "old",
    }

    reset_document_state(state)

    assert state["pipeline"] is pipeline
    assert state["tesseract_path"] == "C:/OCR/tesseract.exe"
    assert state["project"] is None
    assert state["artifacts"] is None
    assert state["document_approval"] is None


def test_workflow_stage_tracks_review_approval_and_build() -> None:
    assert workflow_stage(None, None) == "upload"
    assert workflow_stage(object(), None) == "review"

    class Approved:
        approval = object()

    assert workflow_stage(Approved(), None) == "build"
    assert workflow_stage(Approved(), object()) == "download"
