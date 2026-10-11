import re

import pymupdf

from bookloom.models import BlockKind, StructuredBlock
from bookloom.rendering import build_book_html, render_book
from bookloom.theme import BookTheme


def _blocks() -> list[StructuredBlock]:
    return [
        StructuredBlock(BlockKind.BOOK_TITLE, "A Better Home"),
        StructuredBlock(BlockKind.CHAPTER, "Chapter 1 · Foundations", level=1, include_in_toc=True),
        StructuredBlock(BlockKind.BODY, "A chapter opening paragraph with enough text for a readable opening."),
    ]


def test_theme_is_fixed_a4_with_compact_top_geometry() -> None:
    theme = BookTheme.load()

    assert theme.page_size == "A4"
    assert 15 <= theme.margin_top_mm <= 16
    assert 22 <= theme.margin_top_mm + theme.chapter_padding_top_mm <= 28


def test_generated_cover_uses_teal_identity_and_omits_missing_doi() -> None:
    style = BookTheme.load().to_style()
    style["metadata"] = {"author": "Ravi Author", "publisher": "Trueloger", "doi": None}

    markup = build_book_html(_blocks(), style)

    assert "collection-cover" in markup
    assert style["cover_color"] in markup
    assert "Ravi Author" in markup
    assert "Trueloger" in markup
    assert "DOI" not in markup


def test_rendered_edition_is_a4_with_compact_chapter_top_and_no_cover_number(tmp_path) -> None:
    output = tmp_path / "reading-edition.pdf"

    render_book(_blocks(), output, style=BookTheme.load().to_style())

    with pymupdf.open(output) as document:
        assert {(round(page.rect.width), round(page.rect.height)) for page in document} == {(595, 842)}
        assert not re.search(r"\b1\b", document[0].get_text("text"))
        chapter_page = next(page for page in document if "chapter opening paragraph" in page.get_text("text"))
        chapter_rect = next(
            pymupdf.Rect(block[:4])
            for block in chapter_page.get_text("blocks")
            if "Foundations" in block[4]
        )
        top_mm = chapter_rect.y0 * 25.4 / 72
        assert 22 <= top_mm <= 28


def test_css_keeps_headings_with_opening_lines_and_styles_structural_content() -> None:
    markup = build_book_html(_blocks(), BookTheme.load().to_style())

    assert "break-after: avoid" in markup
    assert "orphans: 3" in markup
    assert ".source-table" in markup
    assert ".list-item" in markup
    assert "figure img" in markup
    assert "border-top" in markup
