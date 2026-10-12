from pathlib import Path

from bookloom.image_analysis import analyze_images
from bookloom.models import (
    BlockKind,
    DocumentModel,
    ExtractedDocument,
    ExtractedImage,
    ExtractedPage,
    PageType,
    SemanticBlock,
    SemanticKind,
    StructuredBlock,
    VisualClass,
)
from bookloom.verification import verify_image_occurrences


def _image(page: int, digest: str, bbox) -> ExtractedImage:
    return ExtractedImage(page, page, "png", digest.encode(), digest, bbox)


def _page(number: int, images, *, used_ocr=False) -> ExtractedPage:
    return ExtractedPage(
        number,
        f"Page {number} body text with enough native content.",
        used_ocr,
        images=images,
        width=600,
        height=800,
        method="SCANNED" if used_ocr else "NATIVE",
    )


def _model(page_count: int) -> DocumentModel:
    blocks = []
    for page in range(1, page_count + 1):
        blocks.extend(
            [
                SemanticBlock(f"h-{page}", SemanticKind.SECTION, f"Section {page}", page, len(blocks), (50, 80, 500, 110), level=2),
                SemanticBlock(f"p-{page}", SemanticKind.PARAGRAPH, f"Body {page}", page, len(blocks) + 1, (50, 140, 500, 190)),
            ]
        )
    return DocumentModel("source-sha", blocks, {page: PageType.NATIVE for page in range(1, page_count + 1)})


def test_repeated_page_edge_logo_is_not_emitted() -> None:
    pages = [_page(number, [_image(number, "logo", (20, 10, 100, 55))]) for number in range(1, 6)]

    results = analyze_images(ExtractedDocument(Path("source.pdf"), pages, "sha"), _model(5))

    assert all(item.classification in {VisualClass.LOGO, VisualClass.FURNITURE} for item in results)
    assert not any(item.emit for item in results)


def test_full_page_scan_is_excluded_from_figure_emission() -> None:
    page = _page(1, [_image(1, "scan", (0, 0, 600, 800))], used_ocr=True)

    result = analyze_images(ExtractedDocument(Path("scan.pdf"), [page], "sha"), _model(1))[0]

    assert result.classification == VisualClass.SCAN
    assert result.emit is False


def test_detected_cover_and_contents_images_are_not_reinserted_as_figures() -> None:
    pages = [
        _page(1, [_image(1, "cover-logo", (150, 120, 450, 220))]),
        _page(2, [_image(2, "contents-decoration", (80, 500, 220, 640))]),
        _page(3, [_image(3, "body-figure", (80, 200, 500, 450))]),
    ]

    results = analyze_images(
        ExtractedDocument(Path("front-matter.pdf"), pages, "sha"),
        _model(3),
        excluded_pages={1, 2},
    )

    assert [item.emit for item in results] == [False, False, True]
    assert all(
        item.classification == VisualClass.COVER_ART for item in results[:2]
    )


def test_meaningful_figures_keep_logical_occurrences_and_reading_order_anchors() -> None:
    pages = [
        _page(1, [_image(1, "figure-a", (100, 115, 400, 135))]),
        _page(2, [_image(2, "figure-b", (100, 200, 500, 500))]),
    ]

    results = analyze_images(ExtractedDocument(Path("figures.pdf"), pages, "sha"), _model(2))

    assert len([item for item in results if item.emit]) == 2
    assert results[0].insert_before_block_id == "p-1"
    assert results[1].insert_after_block_id == "p-2"
    assert results[1].aspect_ratio == 4 / 3


def test_same_content_digest_in_distinct_contexts_remains_two_occurrences() -> None:
    pages = [
        _page(1, [_image(1, "shared-figure", (100, 200, 400, 400))]),
        _page(2, [_image(2, "shared-figure", (100, 220, 400, 420))]),
    ]

    results = analyze_images(ExtractedDocument(Path("shared.pdf"), pages, "sha"), _model(2))

    assert len(results) == 2
    assert len({item.occurrence_id for item in results}) == 2
    assert all(item.emit for item in results)


def test_nearby_caption_is_associated_with_diagram() -> None:
    page = _page(1, [_image(1, "diagram", (80, 200, 500, 450))])
    model = _model(1)
    model.blocks.append(SemanticBlock("caption", SemanticKind.CAPTION, "Figure 1: Energy flow diagram", 1, 2, (80, 460, 500, 480)))

    result = analyze_images(ExtractedDocument(Path("diagram.pdf"), [page], "sha"), model)[0]

    assert result.classification == VisualClass.DIAGRAM
    assert result.caption == "Figure 1: Energy flow diagram"
    assert result.confidence >= 0.8


def test_image_qa_reports_missing_duplicate_and_misordered_occurrences() -> None:
    records = [{"occurrence_id": "one"}, {"occurrence_id": "two"}]
    blocks = [
        StructuredBlock(BlockKind.IMAGE, "Two", source_id="two"),
        StructuredBlock(BlockKind.IMAGE, "Two again", source_id="two"),
    ]

    report = verify_image_occurrences(records, blocks)

    assert report["valid"] is False
    assert report["missing"] == ["one"]
    assert report["duplicate"] == ["two"]
    assert report["misordered"] is True
