import io
import json

import pymupdf
from PIL import Image

from truelogger.config import load_book_profile
from truelogger.models import (
    BlockKind,
    BookSection,
    Decision,
    ExtractedDocument,
    ExtractedImage,
    ExtractedPage,
    StructuredBlock,
)
from truelogger.pipeline import ValidationProject
from truelogger.pipeline import ProjectPipeline


def _book_pdf(path, *, reference=False):
    image = Image.new("RGB", (20, 20), "blue" if reference else "red")
    data = io.BytesIO()
    image.save(data, format="PNG")
    document = pymupdf.open()
    page = document.new_page()
    text = (
        "1. Goddess Annapurna\nKeep the idol in the kitchen.\n"
        "2. Yellow Crystal Lotus\nPlace the lotus in the living room.\n"
        "3. Vastu Pyramid\nKeep the pyramid in the north zone."
    )
    page.insert_textbox(pymupdf.Rect(60, 60, 500, 300), text, fontsize=11)
    page.insert_image(pymupdf.Rect(60, 320, 100, 360), stream=data.getvalue())
    document.save(path)


def _numbered_book_pdf(path):
    document = pymupdf.open()
    contents = document.new_page()
    contents.insert_textbox(
        pymupdf.Rect(50, 50, 540, 790),
        "Contents\n" + "\n".join(f"{number}. Contents Remedy {number}" for number in range(1, 18)),
        fontsize=8,
    )
    for start in (1, 12, 23):
        page = document.new_page()
        stop = min(34, start + 11)
        page.insert_textbox(
            pymupdf.Rect(50, 50, 540, 790),
            "\n".join(
                f"{number}. Actual Remedy {number}\nBody text for actual remedy {number}."
                for number in range(start, stop)
            ),
            fontsize=8,
        )
    document.save(path)


def test_pipeline_keeps_reference_text_only_and_tracks_reference_image_hashes(tmp_path):
    source = tmp_path / "33 Quick Vastu Remedies.pdf"
    reference = tmp_path / "33 Quick Vastu Remedies(1).pdf"
    _book_pdf(source)
    _book_pdf(reference, reference=True)
    project = ProjectPipeline(tmp_path / "cache").analyze(source, reference)
    assert len(project.source_sections) == 3
    assert len(project.reference_sections) == 3
    assert all(not page.images for page in project.reference.pages)
    assert project.reference_image_fingerprints
    assert project.source_image_fingerprints.isdisjoint(project.reference_image_fingerprints)


def test_pipeline_counts_only_canonical_33_remedies(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _numbered_book_pdf(source)
    _numbered_book_pdf(reference)

    project = ProjectPipeline(tmp_path / "cache").analyze(source, reference)

    assert [section.number for section in project.source_sections] == list(range(1, 34))
    assert [section.number for section in project.reference_sections] == list(range(1, 34))
    assert project.document_profile.toc_pages == [1]
    assert all(section.kind == "numbered_item" for section in project.source_sections)


def test_profile_build_uses_production_names_and_records_zero_reference_images(tmp_path):
    source = tmp_path / "33 Quick Vastu Remedies.pdf"
    reference = tmp_path / "33 Quick Vastu Remedies(1).pdf"
    _book_pdf(source)
    _book_pdf(reference, reference=True)
    pipeline = ProjectPipeline(tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    for correction in list(project.corrections):
        project.decide(correction.id, Decision.KEEP_SOURCE)
    profile = load_book_profile()

    artifacts = pipeline.build(project, tmp_path / "output", profile=profile, production=False)

    assert artifacts.pdf.name == "33-Quick-Vastu-Remedies-TRUELOGER-Test.pdf"
    assert artifacts.approved_text_json.exists()
    assert artifacts.reference_text_json.exists()
    assert artifacts.source_structure_json.exists()
    reference_data = json.loads(artifacts.reference_text_json.read_text(encoding="utf-8"))
    assert reference_data[0]["number"] == 1
    assert "images" not in reference_data[0]
    manifest = json.loads(artifacts.manifest.read_text(encoding="utf-8"))
    assert manifest["source_filename"] == source.name
    assert manifest["reference_filename"] == reference.name
    assert manifest["reference_images_imported"] == 0
    assert manifest["detected_source_sections"] == 3
    assert manifest["detected_reference_sections"] == 3


def test_source_image_is_inserted_inside_its_remedy_instead_of_at_book_end(tmp_path):
    payload = io.BytesIO()
    Image.new("RGB", (80, 60), "gold").save(payload, format="PNG")
    image = ExtractedImage(
        page_number=1,
        xref=1,
        extension="png",
        data=payload.getvalue(),
        digest="image-one",
        bbox=(60, 100, 140, 160),
    )
    page = ExtractedPage(
        page_number=1,
        text="1. First Remedy\nBody one\n2. Second Remedy\nBody two",
        used_ocr=False,
        width=595,
        height=842,
        blocks=[
            {"bbox": (60, 60, 200, 80), "text": "1. First Remedy", "type": 0},
            {"bbox": (60, 400, 220, 420), "text": "2. Second Remedy", "type": 0},
        ],
        images=[image],
    )
    source = ExtractedDocument(tmp_path / "source.pdf", [page], "source")
    reference = ExtractedDocument(tmp_path / "reference.pdf", [], "reference")
    project = ValidationProject(
        source=source,
        reference=reference,
        corrections=[],
        source_sections=[
            BookSection(1, "First Remedy", ["Body one"], 1, 1),
            BookSection(2, "Second Remedy", ["Body two"], 1, 1),
        ],
    )
    blocks = [
        StructuredBlock(BlockKind.REMEDY, "01\nFirst Remedy", chapter_id="1"),
        StructuredBlock(BlockKind.BODY, "Body one", chapter_id="1"),
        StructuredBlock(BlockKind.REMEDY, "02\nSecond Remedy", chapter_id="2"),
        StructuredBlock(BlockKind.BODY, "Body two", chapter_id="2"),
    ]

    arranged, _ = ProjectPipeline(tmp_path / "cache")._append_images(blocks, project, tmp_path / "out")

    kinds = [(block.kind, block.chapter_id) for block in arranged]
    assert kinds.index((BlockKind.IMAGE, "1")) < kinds.index((BlockKind.REMEDY, "2"))


def test_unassociated_front_matter_graphic_is_not_appended_to_last_remedy(tmp_path):
    payload = io.BytesIO()
    Image.new("RGB", (80, 60), "purple").save(payload, format="PNG")
    image = ExtractedImage(1, 1, "png", payload.getvalue(), "front-logo", (60, 100, 140, 160))
    front_page = ExtractedPage(
        page_number=1,
        text="Title page",
        used_ocr=False,
        width=595,
        height=842,
        images=[image],
    )
    source = ExtractedDocument(tmp_path / "source.pdf", [front_page], "source")
    reference = ExtractedDocument(tmp_path / "reference.pdf", [], "reference")
    project = ValidationProject(
        source=source,
        reference=reference,
        corrections=[],
        source_sections=[BookSection(1, "First Remedy", ["Body"], 2, 2)],
    )
    blocks = [
        StructuredBlock(BlockKind.REMEDY, "01\nFirst Remedy", chapter_id="1"),
        StructuredBlock(BlockKind.BODY, "Body", chapter_id="1"),
    ]

    arranged, records = ProjectPipeline(tmp_path / "cache")._append_images(
        blocks, project, tmp_path / "out"
    )

    assert all(block.kind != BlockKind.IMAGE for block in arranged)
    assert records == []


