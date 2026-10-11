from pathlib import Path

from bookloom.jobs import create_job
from bookloom.models import ProcessingOptions


def test_jobs_have_isolated_mutable_state(tmp_path: Path) -> None:
    options = ProcessingOptions(tesseract_path="tesseract.exe")
    jobs = [
        create_job(
            f"Source {label}.pdf",
            tmp_path / f"source-{label}.pdf",
            f"Reference {label}.pdf",
            tmp_path / f"reference-{label}.pdf",
            options,
        )
        for label in "ABC"
    ]

    jobs[0].review_overrides["paragraph-1"] = "accepted"
    jobs[0].warnings.append("A-only")
    jobs[0].approval_state["approved"] = True

    assert len({job.id for job in jobs}) == 3
    assert jobs[1].review_overrides == {}
    assert jobs[2].warnings == []
    assert jobs[1].approval_state == {}
    assert jobs[0].source_upload_name == "Source A.pdf"
    assert jobs[0].reference_upload_name == "Reference A.pdf"


def test_job_identity_changes_when_a_new_job_is_created(tmp_path: Path) -> None:
    args = (
        "Source.pdf",
        tmp_path / "source.pdf",
        "Reference.pdf",
        tmp_path / "reference.pdf",
        ProcessingOptions(),
    )

    assert create_job(*args).id != create_job(*args).id
