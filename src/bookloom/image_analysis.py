from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

from .models import (
    DocumentModel,
    ExtractedDocument,
    ExtractedImage,
    SemanticImage,
    SemanticKind,
    VisualClass,
)


_CAPTION_SIGNAL = re.compile(
    r"^(?:fig(?:ure)?|diagram|chart|table|चित्र|आरेख)\s*[.:#-]?\s*\d*",
    re.IGNORECASE,
)


def analyze_images(document: ExtractedDocument, model: DocumentModel) -> list[SemanticImage]:
    """Classify every source image using document-wide recurrence and layout."""

    occurrences: list[tuple[object, ExtractedImage]] = [
        (page, image) for page in document.pages for image in page.images
    ]
    digest_pages: dict[str, set[int]] = defaultdict(set)
    digest_positions: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for page, image in occurrences:
        digest_pages[image.digest].add(page.page_number)
        if image.bbox:
            digest_positions[image.digest].append(
                (
                    image.bbox[0] / max(1.0, page.width or 1.0),
                    image.bbox[1] / max(1.0, page.height or 1.0),
                )
            )

    result: list[SemanticImage] = []
    exact_seen: set[tuple] = set()
    for page, image in occurrences:
        exact_key = (image.digest, page.page_number, image.bbox)
        if exact_key in exact_seen:
            continue
        exact_seen.add(exact_key)
        width = page.width or 595.28
        height = page.height or 841.89
        bbox = image.bbox
        image_width = max(0.0, bbox[2] - bbox[0]) if bbox else 0.0
        image_height = max(0.0, bbox[3] - bbox[1]) if bbox else 0.0
        coverage = image_width * image_height / max(1.0, width * height)
        aspect_ratio = image_width / image_height if image_height else 1.0
        recurrence = len(digest_pages[image.digest])
        repeated = recurrence >= max(3, math.ceil(document.page_count * 0.25))
        stable_position = _stable_position(digest_positions[image.digest])
        edge = bool(bbox and (bbox[3] <= height * 0.15 or bbox[1] >= height * 0.85))
        caption_block = _nearest_caption(model, page.page_number, bbox)
        before, after, parent = _anchors(model, page.page_number, bbox)

        if page.used_ocr and coverage >= 0.75:
            classification, emit, confidence = VisualClass.SCAN, False, 0.99
        elif repeated and stable_position and edge:
            classification, emit, confidence = VisualClass.FURNITURE, False, 0.98
        elif repeated and stable_position:
            classification, emit, confidence = VisualClass.WATERMARK, False, 0.92
        elif page.page_number == 1 and coverage >= 0.25:
            classification, emit, confidence = VisualClass.COVER_ART, False, 0.9
        elif (
            page.page_number == 1
            and len(page.text.strip()) < 200
            and not caption_block
            and not any(
                block.page_number == 1
                and block.kind in {SemanticKind.CHAPTER, SemanticKind.SECTION, SemanticKind.SUBSECTION}
                for block in model.blocks
            )
        ):
            classification, emit, confidence = VisualClass.LOGO, False, 0.82
        elif coverage < 0.002:
            classification, emit, confidence = VisualClass.ARTIFACT, False, 0.85
        elif caption_block and re.search(r"diagram|chart|आरेख", caption_block.text, re.I):
            classification, emit, confidence = VisualClass.DIAGRAM, True, 0.9
        elif caption_block and re.search(r"table|तालिका", caption_block.text, re.I):
            classification, emit, confidence = VisualClass.RASTER_TABLE, True, 0.86
        elif coverage >= 0.02:
            classification, emit, confidence = VisualClass.ILLUSTRATION, True, 0.72
        else:
            classification, emit, confidence = VisualClass.UNKNOWN, True, 0.4

        occurrence_id = hashlib.sha1(
            f"{document.sha256}:{page.page_number}:{image.digest}:{bbox}".encode("utf-8")
        ).hexdigest()[:16]
        logical_context = parent or before or after or f"page-{page.page_number}"
        result.append(
            SemanticImage(
                occurrence_id=occurrence_id,
                digest=image.digest,
                classification=classification,
                source_page=page.page_number,
                bbox=bbox,
                coverage=coverage,
                aspect_ratio=aspect_ratio,
                emit=emit,
                confidence=confidence,
                logical_key=f"{image.digest}:{logical_context}",
                insert_before_block_id=before,
                insert_after_block_id=after,
                parent_block_id=parent,
                caption=caption_block.text if caption_block else None,
            )
        )
    return result


def _stable_position(positions: list[tuple[float, float]]) -> bool:
    if len(positions) < 2:
        return False
    xs, ys = zip(*positions)
    return max(xs) - min(xs) <= 0.04 and max(ys) - min(ys) <= 0.04


def _nearest_caption(model: DocumentModel, page_number: int, bbox):
    candidates = [
        block
        for block in model.blocks
        if block.page_number == page_number
        and (block.kind == SemanticKind.CAPTION or _CAPTION_SIGNAL.search(block.text))
    ]
    if not candidates:
        return None
    center = ((bbox[1] + bbox[3]) / 2) if bbox else 0.0
    return min(
        candidates,
        key=lambda block: abs((((block.bbox or (0, 0, 0, 0))[1] + (block.bbox or (0, 0, 0, 0))[3]) / 2) - center),
    )


def _anchors(model: DocumentModel, page_number: int, bbox):
    blocks = [
        block for block in model.blocks
        if block.page_number == page_number and block.kind != SemanticKind.FIGURE and block.bbox
    ]
    if not blocks or not bbox:
        return None, None, None
    preceding = [block for block in blocks if block.bbox[3] <= bbox[1]]
    following = [block for block in blocks if block.bbox[1] >= bbox[3]]
    prior = max(preceding, key=lambda block: block.bbox[3], default=None)
    after = min(following, key=lambda block: block.bbox[1], default=None)
    heading = max(
        [
            block for block in preceding
            if block.kind in {SemanticKind.CHAPTER, SemanticKind.SECTION, SemanticKind.SUBSECTION}
        ],
        key=lambda block: block.bbox[3],
        default=None,
    )
    before_id = after.id if after and (not prior or after.bbox[1] - bbox[3] <= bbox[1] - prior.bbox[3]) else None
    after_id = None if before_id else prior.id if prior else None
    return before_id, after_id, heading.id if heading else None
