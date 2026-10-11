from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Decision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    EDIT = "EDIT"
    KEEP_SOURCE = "KEEP_SOURCE"
    USE_REFERENCE = "USE_REFERENCE"


@dataclass(frozen=True, slots=True)
class ProcessingOptions:
    """User-selected processing options captured at job creation time."""

    tesseract_path: str | None = None
    generated_cover: bool = True
    preserve_source_pages: tuple[int, ...] = ()


@dataclass(slots=True)
class ProcessingJob:
    """All mutable state belonging to one source/reference processing run."""

    id: str
    source_upload_name: str
    source_path: Path
    reference_upload_name: str
    reference_path: Path
    options: ProcessingOptions
    review_overrides: dict[str, str] = field(default_factory=dict)
    approval_state: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class BlockKind(str, Enum):
    DOCUMENT_TITLE = "document_title"
    MAJOR_SECTION = "major_section"
    SECTION = "section"
    SUBSECTION = "subsection"
    NUMBERED_ITEM = "numbered_item"
    BODY_PARAGRAPH = "body_paragraph"
    BULLET_LIST = "bullet_list"
    REFERENCE = "reference"
    HEADER = "header"
    FOOTER = "footer"
    UNKNOWN = "unknown"
    BOOK_TITLE = "book_title"
    CHAPTER = "chapter"
    HEADING = "heading"
    SUBHEADING = "subheading"
    BODY = "body"
    QUOTE = "quote"
    VERSE = "verse"
    LIST = "list"
    TABLE = "table"
    FOOTNOTE = "footnote"
    CAPTION = "caption"
    IMAGE = "image"
    REMEDY = "remedy"
    DISCLAIMER = "disclaimer"
    REFERENCE_INFO = "reference_info"


@dataclass(slots=True)
class ExtractedImage:
    page_number: int
    xref: int
    extension: str
    data: bytes
    digest: str
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str
    used_ocr: bool
    ocr_confidence: float | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)
    images: list[ExtractedImage] = field(default_factory=list)
    width: float | None = None
    height: float | None = None
    method: str = "NATIVE"
    ocr_cache_hit: bool = False


@dataclass(slots=True)
class ExtractedDocument:
    path: Path
    pages: list[ExtractedPage]
    sha256: str
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def paragraphs(self) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        for page in self.pages:
            for paragraph in page.text.split("\n\n"):
                clean = " ".join(paragraph.split())
                if clean:
                    result.append((page.page_number, clean))
        return result


@dataclass(slots=True)
class Correction:
    id: str
    source_text: str
    reference_text: str | None
    suggested_text: str
    final_text: str | None
    source_page: int
    reference_page: int | None
    confidence: Confidence
    reason: str
    category: str
    status: ReviewStatus = ReviewStatus.PENDING
    decision: Decision | None = None
    review_required: bool = False
    source_section: int | None = None
    reference_section: int | None = None

    @property
    def correction_state(self) -> str:
        if self.category in {"EXACT_MATCH", "SAFE_MATCH"}:
            return "SAFE_CORRECTION"
        if self.suggested_text != self.source_text and not self.review_required:
            return "LIKELY_CORRECTION"
        return "REQUIRES_REVIEW"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StructuredBlock:
    kind: BlockKind
    text: str
    level: int = 0
    page_number: int | None = None
    image_path: str | None = None
    source_id: str | None = None
    chapter_id: str | None = None
    confidence: float = 1.0
    start_new_page: bool = False
    include_in_toc: bool = True
    bbox: tuple[float, float, float, float] | None = None
    table_rows: list[list[str]] | None = None


@dataclass(slots=True)
class BookSection:
    number: int | None
    title: str
    paragraphs: list[str]
    page_start: int
    page_end: int
    kind: str = "section"
    raw_text: str = ""
    normalized_text: str = ""
    display_number: str = ""
    level: int = 2
    confidence: float = 0.5
    start_new_page: bool = False
    include_in_toc: bool = True
    bbox: tuple[float, float, float, float] | None = None

    @property
    def source_page_start(self) -> int:
        return self.page_start

    @property
    def reference_page_start(self) -> int:
        return self.page_start


