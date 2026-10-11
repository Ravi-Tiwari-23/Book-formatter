import json

import pymupdf

from bookloom.models import Decision
from bookloom.pipeline import ProjectPipeline
from bookloom.verification import verify_pdf


def _pdf(path, text):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)


def test_complete_pipeline_writes_required_outputs(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    output = tmp_path / "output"
    _pdf(source, "This is a smal source paragraph with enough text.")
    _pdf(reference, "This is a small source paragraph with enough text.")
    pipeline = ProjectPipeline(cache_dir=tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    for item in project.corrections:
        project.decide(item.id, Decision.ACCEPT)

    artifacts = pipeline.build(project, output)

    expected = {
        "final-book.pdf",
        "validation-report.md",
        "corrections.json",
        "final-approved-text.md",
        "build-manifest.json",
        "verification-report.json",
    }
    assert expected <= {path.name for path in output.iterdir()}
    manifest = json.loads(artifacts.manifest.read_text(encoding="utf-8"))
    assert manifest["source_pdf_sha256"]
    assert manifest["reference_pdf_sha256"]
    assert manifest["output_pdf_sha256"]
    assert manifest["page_count"] == 2
    verification = json.loads(artifacts.verification_report.read_text(encoding="utf-8"))
    assert verification["blank_pages"] == []


def test_layout_qa_flags_inconsistent_page_dimensions(tmp_path):
    pdf = tmp_path / "mixed-sizes.pdf"
    document = pymupdf.open()
    document.new_page(width=420, height=595).insert_text((72, 72), "Page one")
    document.new_page(width=595, height=842).insert_text((72, 72), "Page two")
    document.save(pdf)
    document.close()

    report = verify_pdf(pdf)

    assert report["valid"] is False
    assert report["page_size_mismatches"] == [2]

