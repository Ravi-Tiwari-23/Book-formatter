from pathlib import Path

from bookloom.metadata import extract_reference_metadata, reference_information_text
from bookloom.models import ExtractedDocument, ExtractedPage


def _document(*pages: str) -> ExtractedDocument:
    return ExtractedDocument(
        path=Path("reference.pdf"),
        pages=[
            ExtractedPage(page_number=index, text=text, used_ocr=False)
            for index, text in enumerate(pages, start=1)
        ],
        sha256="reference-sha",
    )


def test_reference_metadata_extracts_labeled_author_publisher_and_doi():
    metadata = extract_reference_metadata(
        _document(
            """33 Quick Vastu Remedies
Author:-
Nitien Pamrar, Vastu Consultant
Published by:-
Plusvalue International""",
            "Read the paper at https://doi.org/10.1234/VASTU.2026.7.",
        )
    )

    assert metadata.title == "33 Quick Vastu Remedies"
    assert metadata.author == "Nitien Pamrar, Vastu Consultant"
    assert metadata.publisher == "Plusvalue International"
    assert metadata.doi == "10.1234/VASTU.2026.7"
    assert metadata.confidence["author"] == "HIGH"
    assert metadata.confidence["doi"] == "HIGH"


def test_reference_metadata_never_invents_missing_author_or_doi():
    metadata = extract_reference_metadata(
        _document("A reference with an organization and website only\nwww.example.org")
    )

    assert metadata.author is None
    assert metadata.doi is None
    rendered = reference_information_text(metadata)
    assert "Author: Not identified in the supplied reference" in rendered
    assert "DOI: Not available in the supplied reference" in rendered

