import io

import pymupdf
import pytest
from PIL import Image

from bookloom.differences import DifferenceType, compare_sections
from bookloom.extraction import extract_pdf
from bookloom.models import BookSection, Confidence, Correction, ReviewStatus
from bookloom.provenance import ImageFirewallError, verify_image_firewall
from bookloom.sections import align_sections, detect_document_sections, detect_sections
from bookloom.validation import build_corrections
from bookloom.matching import MatchCategory, PassageMatch
from bookloom.blockers import BuildBlockedError, validate_production_readiness


def _document_with_image(path):
    image = Image.new("RGB", (30, 30), "red")
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Reference textual content for validation only.")
    page.insert_image(pymupdf.Rect(72, 90, 130, 148), stream=payload.getvalue())
    document.save(path)


def test_reference_text_only_mode_never_extracts_images(tmp_path):
    path = tmp_path / "reference.pdf"
    _document_with_image(path)
    extracted = extract_pdf(path, text_only=True)
    assert extracted.pages[0].text.startswith("Reference textual content")
    assert extracted.pages[0].images == []


def test_detects_all_33_numbered_remedies_across_page_boundaries():
    pages = []
    for number in range(1, 34):
        pages.append((number, f"{number}. Remedy Title {number}\nBody for remedy {number}."))
    sections = detect_sections(pages)
    assert [section.number for section in sections] == list(range(1, 34))
    assert sections[32].title == "Remedy Title 33"


def test_document_detection_ignores_contents_and_nested_numbered_lists():
    contents = "\n".join(
        ["TRUELOGER.COM", "Contents"]
        + [f"{number}. Contents Remedy {number}" for number in range(1, 18)]
    )
    body_lines = ["Book introduction and publication information"]
    for number in range(1, 34):
        body_lines.extend(
            [
                f"{number}. Actual Remedy {number}",
                f"Meaningful body text for remedy {number}.",
            ]
        )
        if number in {8, 21, 26, 29}:
            body_lines.extend(["1. Nested instruction", "2. Another nested instruction"])

    detection = detect_document_sections([(1, contents), (2, "\n".join(body_lines))])

    assert [section.number for section in detection.remedies] == list(range(1, 34))
    assert detection.front_matter
    assert "Contents" in detection.front_matter[0].raw_text


def test_document_detection_finds_heading_embedded_after_previous_text():
    lines = []
    for number in range(1, 31):
        lines.extend([f"{number}. Remedy {number}", f"Body {number}"])
    lines.extend(
        [
            "Closing text for the previous remedy. 31. Sun Remedy",
            "Body 31",
            "32. Wind Remedy",
            "Body 32",
            "33. Final Remedy",
            "Body 33",
        ]
    )

    detection = detect_document_sections([(1, "\n".join(lines))])

    assert [section.number for section in detection.remedies] == list(range(1, 34))
    assert detection.remedies[30].title == "Sun Remedy"


def test_document_detection_reflows_visual_lines_within_paragraphs():
    pages = [
        (
            1,
            "1. First Remedy\nThis is wrapped\nacross two visual lines.\n\n"
            "Second paragraph stays separate.\n"
            + "\n".join(
                f"{number}. Remedy {number}\nBody for remedy {number}."
                for number in range(2, 34)
            ),
        )
    ]

    detection = detect_document_sections(pages)

    assert detection.remedies[0].paragraphs == [
        "This is wrapped across two visual lines.",
        "Second paragraph stays separate.",
    ]


def test_document_detection_removes_variable_page_footers():
    pages = []
    for page_number, start in enumerate((1, 12, 23), start=1):
        stop = min(34, start + 11)
        text = "\n\n".join(
            f"{number}. Remedy {number}\nBody for remedy {number}."
            for number in range(start, stop)
        )
        pages.append((page_number, f"{text}\n\nTRUELOGER.COM {page_number}"))

    detection = detect_document_sections(pages)

    assert all(
        "TRUELOGER.COM" not in paragraph
        for section in detection.remedies
        for paragraph in section.paragraphs
    )


def test_document_detection_removes_doubled_header_extraction_artifacts():
    lines = []
    for number in range(1, 34):
        lines.extend([f"{number}. Remedy {number}", f"Body for remedy {number}."])
        if number == 12:
            lines.append("33 Quick Vastu Remedies33 Quick Vastu Remedies")
        if number == 24:
            lines.append("3333 QuickQuick VastuVastu RemediesRemedies")

    detection = detect_document_sections([(1, "\n\n".join(lines))])

    all_text = " ".join(
        detection.remedies[11].paragraphs + detection.remedies[23].paragraphs
    )
    assert "Remedies33" not in all_text
    assert "QuickQuick" not in all_text


def test_section_alignment_prefers_number_over_page_number():
    source = [BookSection(1, "Goddess Annapurna", ["Source text"], 8, 8)]
    reference = [BookSection(1, "Goddess Annapurna", ["Reference text"], 2, 2)]
    matches = align_sections(source, reference)
    assert matches[0].source.source_page_start == 8
    assert matches[0].reference.reference_page_start == 2
    assert matches[0].matched_by == "number"


def test_reference_only_sentence_is_possible_missing_content():
    source = BookSection(1, "Goddess Annapurna", ["Keep the idol in the kitchen."], 3, 3)
    reference = BookSection(
        1,
        "Goddess Annapurna",
        ["Keep the idol in the kitchen. Face it east."],
        5,
        5,
    )
    differences = compare_sections(source, reference)
    assert any(item.type == DifferenceType.POSSIBLE_MISSING_CONTENT for item in differences)
    assert all(item.review_required for item in differences if item.type == DifferenceType.POSSIBLE_MISSING_CONTENT)


def test_reference_grammar_error_is_not_blindly_suggested():
    match = PassageMatch(
        "The temple is well kept.",
        "The temple are well kept.",
        1,
        4,
        95,
        MatchCategory.MINOR_DIFFERENCE,
    )
    correction = build_corrections([match], protected_terms=set())[0]
    assert correction.suggested_text == match.source_text
    assert correction.review_required is True


def test_reference_image_firewall_rejects_reference_only_asset():
    with pytest.raises(ImageFirewallError):
        verify_image_firewall(
            output_fingerprints={"reference-pixel-hash"},
            source_fingerprints={"source-pixel-hash"},
            reference_fingerprints={"reference-pixel-hash"},
        )


def test_production_build_uses_safe_review_defaults_but_blocks_structural_issues():
    correction = Correction(
        id="x",
        source_text="source",
        reference_text="reference",
        suggested_text="source",
        final_text=None,
        source_page=1,
        reference_page=1,
        confidence=Confidence.LOW,
        reason="review",
        category="WORDING_DIFFERENCE",
        status=ReviewStatus.PENDING,
        review_required=True,
    )
    with pytest.raises(BuildBlockedError) as error:
        validate_production_readiness(
            sections=[BookSection(1, "Only one", ["Text"], 1, 1)],
            corrections=[correction],
            expected_section_numbers=set(range(1, 34)),
            protected_assets_present=False,
            reference_images_included=0,
            fonts_ok=True,
        )
    assert "missing remedy sections" in str(error.value)
    assert "unresolved review items" not in str(error.value)
    assert "protected TRUELOGER assets" in str(error.value)

