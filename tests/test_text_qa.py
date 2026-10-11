import unicodedata

import pymupdf

from bookloom.integrity import (
    IntegrityDifferenceType,
    TextUnit,
    compare_text_units,
    extract_pdf_body_text,
    normalize_integrity_text,
    verify_rendered_pdf,
)
from bookloom.verification import verify_text_integrity


def _unit(identity: str, text: str, order: int = 0, chapter: str = "01") -> TextUnit:
    return TextUnit(
        id=identity,
        chapter_id=chapter,
        chapter_title=f"Chapter {chapter}",
        order=order,
        text=text,
    )


def test_integrity_normalization_accepts_formatting_only_differences():
    expected = '“This is a north-east sentence”\u00a0wrapped across\nlines.'
    actual = '"This is a north- east sentence" wrapped   across lines.\u200b'

    assert normalize_integrity_text(expected) == normalize_integrity_text(actual)


def test_integrity_normalization_accepts_unicode_and_soft_hyphen_differences():
    composed = "Café हिन्दी"
    decomposed = unicodedata.normalize("NFD", composed).replace("fé", "f\u00adé")

    assert normalize_integrity_text(composed) == normalize_integrity_text(decomposed)


def test_integrity_normalization_preserves_real_word_changes():
    assert normalize_integrity_text("approved colour") != normalize_integrity_text(
        "approved color"
    )


def test_integrity_normalization_accepts_pdf_punctuation_spacing_case_and_devanagari():
    expected = "Owner’s PUNISHMENTS/actions — वास्तु शास्त्र"
    rendered = unicodedata.normalize(
        "NFD", "owner's punishments/ actions - वास्तु शास्त्र"
    )

    assert normalize_integrity_text(expected, for_matching=True) == normalize_integrity_text(
        rendered, for_matching=True
    )


def test_exact_hindi_english_and_mixed_units_pass():
    expected = [
        _unit("hi", "यह स्वीकृत हिन्दी पाठ है।", 0),
        _unit("en", "This is approved English text.", 1),
        _unit("mixed", "वास्तु energy उत्तर दिशा में है।", 2),
    ]

    report = compare_text_units(expected, list(expected), stage="PRE_RENDER")

    assert report.passed is True
    assert report.checked_units == 3
    assert report.issues == []


def test_approved_spelling_is_compared_to_renderer_not_raw_ocr():
    raw_ocr = _unit("p1", "A smal source paragraph")
    approved = _unit("p1", "A small source paragraph")
    renderer = _unit("p1", "A small source paragraph")

    report = compare_text_units([approved], [renderer], stage="PRE_RENDER")

    assert raw_ocr.text != approved.text
    assert report.passed is True


def test_structured_comparison_classifies_all_integrity_failures():
    expected = [
        _unit("missing", "Missing paragraph", 0),
        _unit("duplicate", "Duplicate paragraph", 1),
        _unit("modified", "Approved wording", 2),
        _unit("first", "First ordered paragraph", 3),
        _unit("second", "Second ordered paragraph", 4),
    ]
    actual = [
        _unit("duplicate", "Duplicate paragraph", 0),
        _unit("duplicate", "Duplicate paragraph", 1),
        _unit("modified", "Changed wording", 2),
        _unit("second", "Second ordered paragraph", 3),
        _unit("first", "First ordered paragraph", 4),
        _unit("unexpected", "Inserted paragraph", 5),
    ]

    report = compare_text_units(expected, actual, stage="PRE_RENDER")
    kinds = {issue.difference_type for issue in report.issues}

    assert report.passed is False
    assert kinds == {
        IntegrityDifferenceType.MISSING,
        IntegrityDifferenceType.DUPLICATED,
        IntegrityDifferenceType.MODIFIED,
        IntegrityDifferenceType.UNEXPECTED,
        IntegrityDifferenceType.ORDER_CHANGED,
    }
    modified = next(
        issue
        for issue in report.issues
        if issue.difference_type == IntegrityDifferenceType.MODIFIED
    )
    assert modified.expected_sha256 != modified.actual_sha256
    assert modified.expected_length == len("Approved wording")
    assert modified.actual_length == len("Changed wording")
    assert modified.chapter_title == "Chapter 01"


def test_repeated_phrase_in_distinct_units_is_not_a_duplicate():
    expected = [
        _unit("a", "Shared phrase with first ending.", 0),
        _unit("b", "Shared phrase with second ending.", 1),
    ]

    report = compare_text_units(expected, list(expected), stage="PRE_RENDER")

    assert report.passed is True


def test_empty_units_are_not_checked():
    expected = [_unit("empty", "  "), _unit("body", "Body", 1)]
    actual = [_unit("body", "Body", 0)]

    report = compare_text_units(expected, actual, stage="PRE_RENDER")

    assert report.passed is True
    assert report.checked_units == 1


def test_text_qa_detects_missing_and_duplicate_content(tmp_path):
    path = tmp_path / "text.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "First approved paragraph. First approved paragraph.")
    document.save(path)
    report = verify_text_integrity(
        path,
        ["First approved paragraph.", "Second approved paragraph."],
    )
    assert report["missing"] == ["Second approved paragraph."]
    assert report["duplicated"] == ["First approved paragraph."]
    assert report["passed"] is False


def _save_pages(path, pages):
    document = pymupdf.open()
    for blocks in pages:
        page = document.new_page(width=595, height=842)
        for x, y, text in blocks:
            page.insert_text((x, y), text)
    document.save(path)
    document.close()


def test_pdf_verification_ignores_toc_page_numbers_headers_and_footers(tmp_path):
    path = tmp_path / "furniture.pdf"
    _save_pages(
        path,
        [
            [(72, 72, "Contents"), (72, 110, "Alpha body sentence ........ 2")],
            [
                (72, 24, "TRUELOGGER BOOK"),
                (72, 100, "Alpha body sentence."),
                (290, 824, "2"),
                (72, 836, "CONFIDENTIAL PREVIEW"),
            ],
            [
                (72, 24, "TRUELOGGER BOOK"),
                (72, 100, "Install 3 arrows in the north- east direction."),
                (290, 824, "3"),
                (72, 836, "CONFIDENTIAL PREVIEW"),
            ],
        ],
    )
    expected = [
        _unit("a", "Alpha body sentence.", 0),
        _unit("b", "Install 3 arrows in the north-east direction.", 1),
    ]

    report = verify_rendered_pdf(path, expected, excluded_leading_pages=1)
    extracted = extract_pdf_body_text(path, excluded_leading_pages=1)

    assert report.passed is True
    assert "Install 3 arrows" in extracted
    assert "TRUELOGGER BOOK" not in extracted
    assert "CONFIDENTIAL PREVIEW" not in extracted


def test_pdf_verification_accepts_paragraph_split_by_page_number(tmp_path):
    path = tmp_path / "page-break.pdf"
    _save_pages(
        path,
        [
            [(72, 100, "A long approved paragraph crosses the"), (290, 824, "7")],
            [(72, 100, "page boundary without changing words."), (290, 824, "8")],
        ],
    )
    expected = [
        _unit(
            "long",
            "A long approved paragraph crosses the page boundary without changing words.",
        )
    ]

    report = verify_rendered_pdf(path, expected)

    assert report.passed is True


def test_pdf_verification_excludes_generated_labels(tmp_path):
    path = tmp_path / "generated.pdf"
    _save_pages(
        path,
        [[(72, 72, "REMEDY 01"), (72, 100, "GODDESS ANNAPURNA"), (72, 140, "Approved body.")]],
    )

    report = verify_rendered_pdf(
        path,
        [_unit("body", "Approved body.")],
        excluded_texts=["REMEDY 01", "Goddess Annapurna"],
    )

    assert report.passed is True


def test_pdf_verification_detects_missing_duplicate_unexpected_modified_and_order(tmp_path):
    path = tmp_path / "corrupt.pdf"
    _save_pages(
        path,
        [
            [
                (72, 72, "Second approved paragraph."),
                (72, 100, "First changed paragraph."),
                (72, 128, "Second approved paragraph."),
                (72, 156, "Inserted unrelated paragraph."),
            ]
        ],
    )
    expected = [
        _unit("first", "First approved paragraph.", 0),
        _unit("second", "Second approved paragraph.", 1),
        _unit("missing", "Completely absent paragraph.", 2),
    ]

    report = verify_rendered_pdf(path, expected)
    kinds = {issue.difference_type for issue in report.issues}

    assert report.passed is False
    assert IntegrityDifferenceType.MODIFIED in kinds
    assert IntegrityDifferenceType.MISSING in kinds
    assert IntegrityDifferenceType.DUPLICATED in kinds
    assert IntegrityDifferenceType.UNEXPECTED in kinds
    assert IntegrityDifferenceType.ORDER_CHANGED in kinds


def test_pdf_verification_does_not_double_count_nested_approved_text(tmp_path):
    path = tmp_path / "nested-approved-text.pdf"
    _save_pages(
        path,
        [[
            (72, 72, "Journal header Body paragraph continues here."),
            (72, 100, "Journal header"),
        ]],
    )
    expected = [
        _unit("body", "Journal header Body paragraph continues here.", 0),
        _unit("header", "Journal header", 1),
    ]

    report = verify_rendered_pdf(path, expected)

    assert report.passed is True, report.to_dict()


def test_pdf_verification_accepts_reported_table_extraction_variants(tmp_path):
    path = tmp_path / "vastu-table.pdf"
    rendered = (
        "Roadfrom Results Nature of effects. Ligitation and government "
        "punishments/ actions can be initiated. Owner's business improves."
    )
    approved = (
        "Roadfrom Results Nature of effects. Ligitation and government "
        "punishments/actions can be initiated. Owner’s business improves."
    )
    _save_pages(
        path,
        [[
            (72, 100, "Roadfrom Results Nature of effects."),
            (72, 120, "Ligitation and government punishments/ actions can be initiated."),
            (72, 140, "Owner's business improves."),
        ]],
    )

    report = verify_rendered_pdf(
        path,
        [
            TextUnit(
                "vastu-table",
                "11",
                "Vastu Sashtra – Land & plot",
                0,
                approved,
                source_page=12,
                original_text=approved,
            )
        ],
    )

    assert report.passed is True, report.to_dict()
    assert report.issues == []


def test_missing_pdf_content_is_fatal_and_reports_source_page(tmp_path):
    path = tmp_path / "missing.pdf"
    _save_pages(path, [[(72, 100, "First approved paragraph.")]])
    expected = [
        TextUnit("first", "1", "Chapter", 0, "First approved paragraph.", source_page=3),
        TextUnit("missing", "1", "Chapter", 1, "Lost paragraph.", source_page=4),
    ]

    report = verify_rendered_pdf(path, expected)
    issue = next(item for item in report.issues if item.canonical_id == "missing")

    assert report.passed is False
    assert issue.severity == "ERROR"
    assert issue.source_page == 4
    assert issue.output_page is None
    assert issue.reason == "Approved content was not found in the generated PDF"
