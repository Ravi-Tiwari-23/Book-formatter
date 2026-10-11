from bookloom.models import SemanticBlock, SemanticKind
from bookloom.structure import infer_hierarchy, validate_hierarchy


def _block(
    text: str,
    order: int,
    *,
    page: int = 1,
    size: float = 11,
    bold: bool = False,
    kind: SemanticKind = SemanticKind.PARAGRAPH,
) -> SemanticBlock:
    return SemanticBlock(
        f"b-{order}", kind, text, page, order,
        (50, 40 + order * 40, 540, 60 + order * 40),
        font_size=size, bold=bold,
    )


def test_combined_evidence_keeps_real_chapters_and_major_sections() -> None:
    blocks = [
        _block("Chapter 1: Foundations", 0, size=20, bold=True),
        _block("Substantial body content follows this chapter heading and explains the subject.", 1),
        _block("Design Principles", 2, size=17, bold=True),
        _block("Another substantial paragraph follows the unnumbered major section.", 3),
    ]

    inferred = infer_hierarchy(blocks)

    assert inferred[0].kind == SemanticKind.CHAPTER
    assert inferred[0].include_in_toc is True
    assert inferred[2].kind == SemanticKind.SECTION
    assert inferred[2].include_in_toc is True


def test_numbering_or_uppercase_alone_does_not_create_headings() -> None:
    blocks = [
        _block("1. This is a numbered prose sentence that ends normally.", 0),
        _block("IMPORTANT", 1),
        _block("A short trailing fragment.", 2),
    ]

    inferred = infer_hierarchy(blocks)

    assert all(block.kind not in {SemanticKind.CHAPTER, SemanticKind.SECTION, SemanticKind.SUBSECTION} for block in inferred)
    assert not any(block.include_in_toc for block in inferred)


def test_source_toc_support_can_confirm_a_compact_remedy_heading() -> None:
    blocks = [
        _block("12. Balance the North Zone", 0, size=12.5, bold=True),
        _block("This body paragraph contains the practical remedy explanation.", 1),
    ]

    inferred = infer_hierarchy(blocks, toc_titles={"12. balance the north zone"})

    assert inferred[0].kind == SemanticKind.SECTION
    assert inferred[0].include_in_toc is True
    assert inferred[0].confidence >= 0.85


def test_negative_evidence_demotes_furniture_tables_verses_and_empty_headings() -> None:
    blocks = [
        _block("BOOK TITLE", 0, page=1, size=11),
        _block("BOOK TITLE", 1, page=2, size=11),
        _block("Column heading", 2, kind=SemanticKind.TABLE, bold=True),
        _block("ॐ नमः शिवाय॥", 3, bold=True),
        _block("Lonely Heading", 4, size=18, bold=True),
    ]

    inferred = infer_hierarchy(blocks)

    assert not any(block.include_in_toc for block in inferred)
    assert inferred[2].kind == SemanticKind.TABLE


def test_hierarchy_validation_rejects_implausibly_dense_toc() -> None:
    blocks = [
        _block(f"Heading {index}", index, page=(index // 2) + 1, size=16, bold=True, kind=SemanticKind.SECTION)
        for index in range(10)
    ]
    for block in blocks:
        block.include_in_toc = True
        block.confidence = 0.65

    validated = validate_hierarchy(blocks, page_count=3)

    assert sum(block.include_in_toc for block in validated) <= 6
