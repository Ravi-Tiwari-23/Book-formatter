from __future__ import annotations

from pathlib import Path

import pymupdf
from PIL import Image

from bookloom.verification import verify_pdf


def _save(document: pymupdf.Document, path) -> None:
    document.save(path)
    document.close()


def test_verification_returns_structured_issues_for_duplicate_and_missing_glyph(tmp_path):
    pdf = tmp_path / "defects.pdf"
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 100), "Repeated production page with enough body content. " * 8)
    third = document.new_page(width=595, height=842)
    font = Path(__file__).parents[1] / "assets" / "fonts" / "NotoSerifDevanagari.ttf"
    third.insert_font(fontname="symbols", fontfile=str(font))
    third.insert_text(
        (72, 100),
        "The renderer emitted a missing glyph marker: □",
        fontname="symbols",
    )
    _save(document, pdf)

    report = verify_pdf(pdf)

    assert report["duplicate_page_groups"] == [[1, 2]]
    assert report["missing_glyph_pages"] == [3]
    assert report["valid"] is False
    assert {issue["code"] for issue in report["issues"]} >= {
        "DUPLICATE_PAGE",
        "MISSING_GLYPH",
    }


def test_verification_flags_unexplained_image_only_page(tmp_path):
    image = tmp_path / "scan.png"
    Image.new("RGB", (600, 850), "white").save(image)
    pdf = tmp_path / "image-only.pdf"
    document = pymupdf.open()
    cover = document.new_page(width=595, height=842)
    cover.insert_text((72, 100), "Cover")
    page = document.new_page(width=595, height=842)
    page.insert_image(page.rect, filename=str(image))
    _save(document, pdf)

    report = verify_pdf(pdf)

    assert report["suspicious_image_only_pages"] == [2]
    assert any(issue["code"] == "SUSPICIOUS_IMAGE_ONLY_PAGE" for issue in report["issues"])


def test_verification_selects_representative_pages_by_semantic_role(tmp_path):
    image = tmp_path / "figure.png"
    Image.new("RGB", (120, 80), "navy").save(image)
    pdf = tmp_path / "representative.pdf"
    document = pymupdf.open()
    texts = [
        "A Book Title",
        "Contents\n1 Chapter One 3",
        "Chapter One\nOpening body paragraph with sufficient publication content.",
        "Table\nColumn A  Column B\nValue 1  Value 2",
        "References\nExample source, 2026.",
    ]
    for text in texts:
        page = document.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(72, 72, 520, 300), text, fontsize=12)
    document[2].insert_image(pymupdf.Rect(100, 320, 300, 453), filename=str(image))
    _save(document, pdf)

    report = verify_pdf(pdf)

    roles = report["representative_pages"]
    assert roles["cover"] == 1
    assert roles["contents"] == 2
    assert roles["first_body"] == 3
    assert roles["chapter"] == 3
    assert roles["image"] == 3
    assert roles["table"] == 4
    assert roles["references"] == 5
    assert roles["final"] == 5


def test_cover_page_number_is_rejected(tmp_path):
    pdf = tmp_path / "numbered-cover.pdf"
    document = pymupdf.open()
    cover = document.new_page(width=595, height=842)
    cover.insert_text((72, 100), "Book Cover")
    cover.insert_text((295, 820), "1")
    body = document.new_page(width=595, height=842)
    body.insert_text((72, 100), "Body paragraph with enough text to identify the page.")
    _save(document, pdf)

    report = verify_pdf(pdf)

    assert report["cover_numbered"] is True
    assert any(issue["code"] == "COVER_NUMBERED" for issue in report["issues"])
