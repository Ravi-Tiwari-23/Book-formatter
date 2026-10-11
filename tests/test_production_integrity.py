import json
from pathlib import Path

import pymupdf
import pytest

from bookloom.integrity import ProductionIntegrityError
from bookloom.models import (
    BookSection,
    BlockKind,
    Confidence,
    Correction,
    Decision,
    ExtractedDocument,
    ReviewStatus,
    StructuredBlock,
)
from bookloom.pipeline import (
    ProjectPipeline,
    ValidationProject,
    canonical_text_units,
    synchronize_renderer_blocks,
)


def _project(tmp_path: Path, approved: str = "Approved corrected paragraph.") -> ValidationProject:
    source = ExtractedDocument(tmp_path / "source.pdf", [], "source-hash")
    reference = ExtractedDocument(tmp_path / "reference.pdf", [], "reference-hash")
    correction = Correction(
        id="correction-1",
        source_text="Raw OCR paragraf.",
        reference_text="Reference-only paragraph.",
        suggested_text=approved,
        final_text=approved,
        source_page=1,
        reference_page=1,
        confidence=Confidence.HIGH,
        reason="Approved correction",
        category="SPELLING_DIFFERENCE",
        status=ReviewStatus.APPROVED,
        decision=Decision.EDIT,
        source_section=1,
        reference_section=1,
    )
    section = BookSection(
        number=1,
        title="Goddess Annapurna",
        paragraphs=["Raw OCR paragraf."],
        page_start=1,
        page_end=1,
    )
    return ValidationProject(
        source=source,
        reference=reference,
        corrections=[correction],
        source_sections=[section],
    )


def test_canonical_units_use_approved_source_text_not_raw_ocr_or_reference(tmp_path):
    project = _project(tmp_path)

    units = canonical_text_units(project, None)

    assert [unit.id for unit in units] == ["correction-1"]
    assert [unit.text for unit in units] == ["Approved corrected paragraph."]
    assert all("Reference-only" not in unit.text for unit in units)
    assert units[0].chapter_title == "Goddess Annapurna"
    assert units[0].source_page == 1
    assert units[0].original_text == "Raw OCR paragraf."
    assert units[0].text == "Approved corrected paragraph."


def test_stale_same_shape_renderer_text_is_resynchronized_without_losing_kind(tmp_path):
    project = _project(tmp_path)
    project.structure_override = [
        StructuredBlock(BlockKind.BOOK_TITLE, "Book"),
        StructuredBlock(BlockKind.LIST, "Stale OCR paragraf."),
    ]

    blocks, changed = synchronize_renderer_blocks(
        project, canonical_text_units(project, None), None, None
    )

    assert changed is True
    assert blocks[1].kind == BlockKind.LIST
    assert blocks[1].text == "Approved corrected paragraph."
    assert blocks[1].source_id == "correction-1"


def test_split_or_merged_override_regenerates_canonical_default_blocks(tmp_path):
    project = _project(tmp_path)
    project.structure_override = [
        StructuredBlock(BlockKind.BODY, "First stale half"),
        StructuredBlock(BlockKind.BODY, "Second stale half"),
    ]

    blocks, changed = synchronize_renderer_blocks(
        project, canonical_text_units(project, None), None, None
    )

    body = [block for block in blocks if block.source_id == "correction-1"]
    assert changed is True
    assert len(body) == 1
    assert body[0].text == "Approved corrected paragraph."


def test_exact_renderer_override_is_not_changed(tmp_path):
    project = _project(tmp_path)
    project.structure_override = [
        StructuredBlock(
            BlockKind.BODY,
            "Approved corrected paragraph.",
            source_id="correction-1",
            chapter_id="1",
        )
    ]

    blocks, changed = synchronize_renderer_blocks(
        project, canonical_text_units(project, None), None, None
    )

    assert changed is False
    assert blocks is project.structure_override


def test_production_failure_persists_report_before_domain_error(tmp_path, monkeypatch):
    project = _project(tmp_path)
    pipeline = ProjectPipeline(tmp_path / "cache")

    def render_corrupt(_blocks, output_path, **_kwargs):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Corrupted renderer output.")
        document.save(output_path)
        document.close()
        return Path(output_path)

    monkeypatch.setattr("bookloom.pipeline.render_book", render_corrupt)

    with pytest.raises(ProductionIntegrityError) as caught:
        pipeline.build(project, tmp_path / "output", production=True)

    report_path = tmp_path / "output" / "verification-report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["text_integrity"]["passed"] is False
    assert report["text_integrity"]["post_render"]["issues"]
    issue = report["text_integrity"]["post_render"]["issues"][0]
    assert issue["chapter_title"] == "Goddess Annapurna"
    assert issue["expected_sha256"]
    assert issue["expected_length"]
    assert str(tmp_path) not in str(caught.value)


def test_successful_build_records_both_integrity_gates(tmp_path):
    project = _project(tmp_path)
    pipeline = ProjectPipeline(tmp_path / "cache")

    artifacts = pipeline.build(project, tmp_path / "output", production=True)

    report = json.loads(artifacts.verification_report.read_text(encoding="utf-8"))
    integrity = report["text_integrity"]
    assert integrity["passed"] is True
    assert integrity["pre_render"]["passed"] is True
    assert integrity["post_render"]["passed"] is True
