from pathlib import Path

from bookloom.metadata import DocumentMetadata, merge_metadata
from bookloom.models import (
    ExtractedDocument,
    ExtractedImage,
    ExtractedPage,
    PageType,
    SemanticKind,
)
from bookloom.semantic import build_document_model, classify_page_type


def _image(*, bbox=(0.0, 0.0, 500.0, 700.0)) -> ExtractedImage:
    return ExtractedImage(1, 7, "png", b"image", "digest", bbox)


def test_page_type_distinguishes_native_scanned_and_mixed() -> None:
    assert classify_page_type("Readable native paragraph", [], 500, 700, False) == PageType.NATIVE
    assert classify_page_type("OCR result", [_image()], 500, 700, True) == PageType.SCANNED
    assert classify_page_type("Readable native paragraph", [_image(bbox=(0, 100, 500, 500))], 500, 700, False) == PageType.MIXED


def test_document_model_has_stable_ids_reading_order_and_first_class_blocks() -> None:
    pages = [
        ExtractedPage(
            page_number=1,
            text="Abstract\nA short summary.\nKeywords: vastu, home",
            used_ocr=False,
            blocks=[
                {"text": "Abstract", "bbox": (50, 40, 200, 60), "font_size": 18, "bold": True},
                {"text": "A short summary.", "bbox": (50, 70, 500, 90), "font_size": 11},
                {"text": "Keywords: vastu, home", "bbox": (50, 100, 500, 120), "font_size": 11},
                {"text": "One Two", "bbox": (50, 140, 500, 200), "table_rows": [["One", "Two"], ["1", "2"]]},
                {"text": "Conclusion", "bbox": (50, 230, 220, 250), "font_size": 18, "bold": True},
                {"text": "References", "bbox": (50, 300, 220, 320), "font_size": 18, "bold": True},
            ],
            images=[_image(bbox=(80, 340, 300, 500))],
            width=595,
            height=842,
        )
    ]
    document = ExtractedDocument(Path("source.pdf"), pages, "stable-source-sha")

    first = build_document_model(document)
    second = build_document_model(document)

    assert [block.id for block in first.blocks] == [block.id for block in second.blocks]
    assert [block.order for block in first.blocks] == list(range(len(first.blocks)))
    kinds = {block.kind for block in first.blocks}
    assert {SemanticKind.ABSTRACT, SemanticKind.KEYWORDS, SemanticKind.TABLE,
            SemanticKind.FIGURE, SemanticKind.CONCLUSION, SemanticKind.REFERENCES} <= kinds


def test_metadata_merge_is_source_first_and_reports_material_conflicts() -> None:
    source = DocumentMetadata(
        title="Source Title", author="Source Author", doi="10.1000/source",
        confidence={"title": "HIGH", "author": "HIGH", "doi": "HIGH"},
    )
    reference = DocumentMetadata(
        title="Reference Title", author="Other Author", doi="https://doi.org/10.1000/OTHER",
        publisher="Reference Publisher",
    )

    merged = merge_metadata(source, reference)

    assert merged.metadata.title == "Source Title"
    assert merged.metadata.author == "Source Author"
    assert merged.metadata.doi == "10.1000/source"
    assert merged.metadata.publisher == "Reference Publisher"
    assert merged.metadata.provenance["publisher"] == "reference_fallback"
    assert {finding.field for finding in merged.findings} == {"title", "author", "doi"}


def test_missing_doi_is_omitted_instead_of_invented() -> None:
    merged = merge_metadata(DocumentMetadata(title="Book"), DocumentMetadata())

    assert merged.metadata.doi is None
    assert "doi" not in merged.metadata.provenance
