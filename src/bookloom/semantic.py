from __future__ import annotations

import hashlib
import re

from .models import (
    DocumentModel,
    ExtractedDocument,
    ExtractedImage,
    PageType,
    SemanticBlock,
    SemanticKind,
    StructuredBlock,
)


_SPECIAL_HEADINGS = {
    "abstract": SemanticKind.ABSTRACT,
    "सार": SemanticKind.ABSTRACT,
    "conclusion": SemanticKind.CONCLUSION,
    "conclusions": SemanticKind.CONCLUSION,
    "निष्कर्ष": SemanticKind.CONCLUSION,
    "references": SemanticKind.REFERENCES,
    "bibliography": SemanticKind.REFERENCES,
    "संदर्भ": SemanticKind.REFERENCES,
}


def classify_page_type(
    native_text: str,
    images: list[ExtractedImage],
    width: float,
    height: float,
    used_ocr: bool,
) -> PageType:
    if used_ocr:
        return PageType.SCANNED
    page_area = max(1.0, width * height)
    meaningful_raster = any(
        image.bbox
        and max(0.0, image.bbox[2] - image.bbox[0])
        * max(0.0, image.bbox[3] - image.bbox[1])
        / page_area
        >= 0.15
        for image in images
    )
    if native_text.strip() and meaningful_raster:
        return PageType.MIXED
    return PageType.NATIVE


def build_document_model(
    document: ExtractedDocument,
    *,
    metadata=None,
    language: str = "english",
) -> DocumentModel:
    blocks: list[SemanticBlock] = []
    page_types: dict[int, PageType] = {}
    order = 0
    for page in document.pages:
        width, height = page.width or 595.28, page.height or 841.89
        page_type = PageType(page.method) if page.method in PageType._value2member_map_ else classify_page_type(
            page.text, page.images, width, height, page.used_ocr
        )
        page_types[page.page_number] = page_type
        events: list[tuple[float, float, str, object]] = []
        native_blocks = page.blocks or [
            {"text": line, "bbox": (40, 40 + index * 16, width - 40, 54 + index * 16)}
            for index, line in enumerate(page.text.splitlines())
            if line.strip()
        ]
        for index, block in enumerate(native_blocks):
            bbox = tuple(block.get("bbox", (0, index * 16, width, index * 16 + 14)))
            events.append((float(bbox[1]), float(bbox[0]), "text", block))
        for image in page.images:
            bbox = image.bbox or (0.0, height - 1.0, width, height)
            events.append((float(bbox[1]), float(bbox[0]), "image", image))
        events.sort(key=lambda event: (round(event[0], 2), round(event[1], 2), event[2]))
        for event_index, (_, _, event_type, payload) in enumerate(events):
            if event_type == "image":
                image = payload
                kind = SemanticKind.FIGURE
                text = ""
                bbox = image.bbox
                table_rows = None
                digest_source = image.digest
            else:
                block = payload
                text = " ".join(str(block.get("text", "")).split())
                if not text:
                    continue
                bbox = tuple(block.get("bbox")) if block.get("bbox") else None
                table_rows = block.get("table_rows")
                kind = _semantic_kind(text, block)
                digest_source = text
            identity = hashlib.sha1(
                f"{document.sha256}:{page.page_number}:{event_index}:{kind.value}:{digest_source}".encode("utf-8")
            ).hexdigest()[:16]
            blocks.append(
                SemanticBlock(
                    id=identity,
                    kind=kind,
                    text=text,
                    page_number=page.page_number,
                    order=order,
                    bbox=bbox,
                    level=_level(kind),
                    table_rows=table_rows,
                    image_digest=payload.digest if event_type == "image" else None,
                )
            )
            order += 1
    return DocumentModel(document.sha256, blocks, page_types, metadata, language)


def document_model_from_structured_blocks(
    source_sha256: str,
    blocks: list[StructuredBlock],
    *,
    page_types: dict[int, PageType] | None = None,
    metadata=None,
    language: str = "english",
) -> DocumentModel:
    reverse = {
        "book_title": SemanticKind.TITLE,
        "chapter": SemanticKind.CHAPTER,
        "major_section": SemanticKind.CHAPTER,
        "section": SemanticKind.SECTION,
        "heading": SemanticKind.SECTION,
        "numbered_item": SemanticKind.SECTION,
        "remedy": SemanticKind.SECTION,
        "subsection": SemanticKind.SUBSECTION,
        "subheading": SemanticKind.SUBSECTION,
        "bullet_list": SemanticKind.LIST,
        "list": SemanticKind.LIST,
        "table": SemanticKind.TABLE,
        "image": SemanticKind.FIGURE,
        "caption": SemanticKind.CAPTION,
    }
    semantic = []
    for order, block in enumerate(blocks):
        kind = reverse.get(block.kind.value, SemanticKind.PARAGRAPH)
        semantic.append(
            SemanticBlock(
                id=block.source_id or hashlib.sha1(
                    f"{source_sha256}:{order}:{block.kind.value}:{block.text}".encode("utf-8")
                ).hexdigest()[:16],
                kind=kind,
                text=block.text,
                page_number=block.page_number or 0,
                order=order,
                bbox=block.bbox,
                level=block.level,
                table_rows=block.table_rows,
                image_path=block.image_path,
                confidence=block.confidence,
                source_id=block.source_id,
                chapter_id=block.chapter_id,
                start_new_page=block.start_new_page,
                include_in_toc=block.include_in_toc,
            )
        )
    return DocumentModel(source_sha256, semantic, page_types or {}, metadata, language)


def _semantic_kind(text: str, block: dict) -> SemanticKind:
    folded = text.casefold().strip(" :–—-")
    if block.get("table_rows"):
        return SemanticKind.TABLE
    if folded in _SPECIAL_HEADINGS:
        return _SPECIAL_HEADINGS[folded]
    if re.match(r"^(keywords?|मुख्य शब्द)\s*[:：]", text, re.IGNORECASE):
        return SemanticKind.KEYWORDS
    if re.match(r"^\d+(?:\.\d+)*[.)\-:]?\s+\S+", text) and len(text.split()) <= 14:
        return SemanticKind.SECTION
    if re.match(r"^(?:[-*•]|\d+[.)])\s+", text):
        return SemanticKind.LIST
    if re.match(r"^(?:figure|fig\.|चित्र)\s*\d+", text, re.IGNORECASE):
        return SemanticKind.CAPTION
    if re.match(r"^(?:chapter|अध्याय)\b", text, re.IGNORECASE):
        return SemanticKind.CHAPTER
    if block.get("bold") and len(text.split()) <= 14 or float(block.get("font_size", 0)) >= 15:
        return SemanticKind.SECTION
    return SemanticKind.PARAGRAPH


def _level(kind: SemanticKind) -> int:
    if kind in {SemanticKind.TITLE, SemanticKind.CHAPTER}:
        return 1
    if kind in {SemanticKind.SECTION, SemanticKind.ABSTRACT, SemanticKind.CONCLUSION, SemanticKind.REFERENCES}:
        return 2
    if kind in {SemanticKind.SUBSECTION, SemanticKind.KEYWORDS}:
        return 3
    return 0
