from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pypdf import PdfReader

from .models import ExtractedDocument


_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_ISBN = re.compile(
    r"\b(?:ISBN(?:-1[03])?\s*[:\-]?\s*)?((?:97[89][\s-]?)?[0-9][0-9\s-]{8,16}[0-9X])\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TITLE_SIGNAL = re.compile(
    r"\b(book|remed(?:y|ies)|guide|handbook|manual|vastu|शास्त्र|पुस्तक)\b",
    re.IGNORECASE,
)
_EXCLUDED_PERSON_TERMS = re.compile(
    r"\b(publish(?:er|ed)|copyright|website|www\.|photograph|organization|journal)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class DocumentMetadata:
    title: str | None = None
    author: str | None = None
    co_author: str | None = None
    editor: str | None = None
    publisher: str | None = None
    edition: str | None = None
    publication_year: str | None = None
    isbn: str | None = None
    doi: str | None = None
    source_publication: str | None = None
    confidence: dict[str, str] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def has_information(self) -> bool:
        return any(
            (
                self.title,
                self.author,
                self.co_author,
                self.editor,
                self.publisher,
                self.edition,
                self.publication_year,
                self.isbn,
                self.doi,
                self.source_publication,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "co_author": self.co_author,
            "editor": self.editor,
            "publisher": self.publisher,
            "publication_year": self.publication_year,
            "edition": self.edition,
            "isbn": self.isbn,
            "doi": self.doi,
            "source_publication": self.source_publication,
            "confidence": dict(self.confidence),
            "provenance": dict(self.provenance),
        }


ReferenceMetadata = DocumentMetadata


@dataclass(frozen=True, slots=True)
class MetadataFinding:
    field: str
    source_value: str
    reference_value: str
    reason: str


@dataclass(frozen=True, slots=True)
class MetadataMergeResult:
    metadata: DocumentMetadata
    findings: tuple[MetadataFinding, ...]


def _lines(document: ExtractedDocument, maximum_pages: int = 12) -> list[str]:
    result: list[str] = []
    for page in document.pages[:maximum_pages]:
        for raw in page.text.splitlines():
            clean = " ".join(raw.replace("\ufffd", "'").split()).strip(" |")
            if clean:
                result.append(clean)
    return result


def _next_value(lines: list[str], index: int, inline: str) -> str | None:
    value = inline.strip(" :-–—\t")
    if value:
        return value
    for candidate in lines[index + 1:index + 4]:
        if candidate and not re.match(r"^[A-Za-z ]{2,24}\s*[:\-]+\s*$", candidate):
            return candidate
    return None


def _labeled_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    expression = re.compile(
        rf"^(?:{'|'.join(re.escape(label) for label in labels)})\s*(?:[:\-]+\s*)?(.*)$",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = expression.match(line)
        if not match:
            continue
        value = _next_value(lines, index, match.group(1))
        if value and len(value) <= 180:
            return value
    return None


def _pdf_metadata(document: ExtractedDocument) -> dict[str, str]:
    try:
        metadata = PdfReader(document.path).metadata or {}
    except Exception:
        return {}
    result: dict[str, str] = {}
    for source_key, target_key in (("/Title", "title"), ("/Author", "author")):
        value = metadata.get(source_key)
        if value and str(value).strip():
            result[target_key] = " ".join(str(value).split())
    return result


def _plausible_person_name(value: str) -> bool:
    words = value.split()
    if not words or len(words) > 10 or len(value) > 100:
        return False
    latin_letters = [character for character in value if character.isascii() and character.isalpha()]
    if latin_letters and not any(character.isupper() for character in latin_letters):
        return False
    if re.search(r"\b(?:this paper|this study|aims? to|provides?|studying|results?|abstract)\b", value, re.I):
        return False
    return True


def _title_candidate(lines: list[str]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for index, line in enumerate(lines[:50]):
        words = line.split()
        if not 2 <= len(words) <= 14 or len(line) > 120:
            continue
        if line.endswith((".", "?", "!")) or not _TITLE_SIGNAL.search(line):
            continue
        score = 8 if re.search(r"\b(remed(?:y|ies)|book|पुस्तक)\b", line, re.I) else 3
        score += 2 if any(character.isdigit() for character in line) else 0
        score -= index // 10
        candidates.append((score, line))
    return max(candidates, default=(0, ""))[1] or None


def extract_document_metadata(document: ExtractedDocument) -> DocumentMetadata:
    """Conservatively extract bibliographic facts from one supplied document."""
    lines = _lines(document)
    searchable = "\n".join(page.text for page in document.pages)
    pdf_metadata = _pdf_metadata(document)
    result = DocumentMetadata()

    result.title = pdf_metadata.get("title") or _title_candidate(lines)
    if result.title:
        result.confidence["title"] = "HIGH" if "title" in pdf_metadata else "MEDIUM"

    author = _labeled_value(lines, ("author", "written by", "writer"))
    if not author:
        for index, line in enumerate(lines[:60]):
            match = re.match(r"^by\s*[:\-]?\s+(.+)$", line, re.I)
            if match:
                author = _next_value(lines, index, match.group(1))
                break
    author = author or pdf_metadata.get("author")
    if (
        author
        and not _EXCLUDED_PERSON_TERMS.search(author)
        and _plausible_person_name(author)
    ):
        result.author = author
        result.confidence["author"] = "HIGH" if author != pdf_metadata.get("author") else "MEDIUM"

    for field_name, labels in (
        ("co_author", ("co-author", "coauthor")),
        ("editor", ("editor", "edited by")),
        ("publisher", ("publisher", "published by")),
        ("edition", ("edition",)),
        ("source_publication", ("journal", "source publication")),
    ):
        value = _labeled_value(lines, labels)
        if value:
            setattr(result, field_name, value)
            result.confidence[field_name] = "HIGH"

    doi_match = _DOI.search(searchable)
    if doi_match:
        result.doi = doi_match.group(0).rstrip(".,;")
        result.confidence["doi"] = "HIGH"

    isbn_match = _ISBN.search(searchable)
    if isbn_match and re.search(r"ISBN", isbn_match.group(0), re.I):
        result.isbn = re.sub(r"\s+", "", isbn_match.group(1)).replace("--", "-")
        result.confidence["isbn"] = "HIGH"

    edition_line = result.edition or ""
    year_match = _YEAR.search(edition_line)
    if not year_match:
        year_match = next(
            (_YEAR.search(line) for line in lines[:100] if re.search(r"publish|copyright|edition", line, re.I) and _YEAR.search(line)),
            None,
        )
    if year_match:
        result.publication_year = year_match.group(0)
        result.confidence["publication_year"] = "MEDIUM"
    return result


def extract_reference_metadata(document: ExtractedDocument) -> DocumentMetadata:
    """Compatibility wrapper for callers that extract a reference document."""

    return extract_document_metadata(document)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value.strip(), flags=re.I)
    normalized = re.sub(r"^doi\s*:\s*", "", normalized, flags=re.I)
    return normalized.rstrip(".,; ").casefold() or None


def merge_metadata(
    source: DocumentMetadata,
    reference: DocumentMetadata,
) -> MetadataMergeResult:
    """Merge bibliographic facts with source authority and reference fallback."""

    fields = (
        "title", "author", "co_author", "editor", "publisher", "edition",
        "publication_year", "isbn", "doi", "source_publication",
    )
    merged = DocumentMetadata()
    findings: list[MetadataFinding] = []
    for field_name in fields:
        source_value = getattr(source, field_name)
        reference_value = getattr(reference, field_name)
        selected = source_value or reference_value
        if selected:
            if field_name == "doi":
                selected = normalize_doi(selected)
            setattr(merged, field_name, selected)
            authority = "source" if source_value else "reference_fallback"
            merged.provenance[field_name] = authority
            confidence_source = source if source_value else reference
            if field_name in confidence_source.confidence:
                merged.confidence[field_name] = confidence_source.confidence[field_name]
        if source_value and reference_value:
            source_normalized = normalize_doi(source_value) if field_name == "doi" else " ".join(source_value.casefold().split())
            reference_normalized = normalize_doi(reference_value) if field_name == "doi" else " ".join(reference_value.casefold().split())
            if source_normalized != reference_normalized:
                findings.append(
                    MetadataFinding(
                        field=field_name,
                        source_value=source_value,
                        reference_value=reference_value,
                        reason=f"Source and reference {field_name.replace('_', ' ')} differ; source retained",
                    )
                )
    return MetadataMergeResult(merged, tuple(findings))


def reference_information_text(metadata: DocumentMetadata) -> str:
    lines = ["REFERENCE SOURCE"]
    if metadata.title:
        lines.append(f"Reference book: {metadata.title}")
    lines.append(
        f"Author: {metadata.author or 'Not identified in the supplied reference'}"
    )
    if metadata.co_author:
        lines.append(f"Co-author: {metadata.co_author}")
    if metadata.editor:
        lines.append(f"Editor: {metadata.editor}")
    if metadata.publisher:
        lines.append(f"Publisher: {metadata.publisher}")
    if metadata.edition:
        lines.append(f"Edition: {metadata.edition}")
    if metadata.publication_year:
        lines.append(f"Publication year: {metadata.publication_year}")
    if metadata.isbn:
        lines.append(f"ISBN: {metadata.isbn}")
    if metadata.doi:
        lines.append(f"DOI: {metadata.doi}")
    if metadata.source_publication:
        lines.append(f"Source publication: {metadata.source_publication}")
    return "\n".join(lines)

