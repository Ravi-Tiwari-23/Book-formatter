from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from statistics import median

from .models import BlockKind, SemanticBlock, SemanticKind, StructuredBlock


_CHAPTER = re.compile(r"^(अध्याय|chapter|भाग|part)\s*[\d०-९IVXivx:-]*", re.IGNORECASE)
_LIST = re.compile(r"^(?:[-*•]|\d+[.)]|[०-९]+[.)])\s+")
_NUMBERED_ITEM = re.compile(r"^(?:remedy\s*)?(\d+(?:\.\d+)*)\s*(?:[.)\-:]\s*|\s+)(\S.+)$", re.IGNORECASE)
_VERSE_MARKERS = ("॥", "ॐ", "श्लोक", "मंत्र")


def infer_hierarchy(
    blocks: list[SemanticBlock],
    *,
    toc_titles: set[str] | None = None,
) -> list[SemanticBlock]:
    """Infer headings only when multiple independent layout signals agree."""

    toc = {_normalized(value) for value in (toc_titles or set())}
    repeated_pages: dict[str, set[int]] = {}
    for block in blocks:
        repeated_pages.setdefault(_normalized(block.text), set()).add(block.page_number)
    repeated = {text for text, pages in repeated_pages.items() if text and len(pages) >= 2}
    body_sizes = [
        block.font_size
        for block in blocks
        if block.font_size and len(block.text.split()) >= 7 and block.kind == SemanticKind.PARAGRAPH
    ]
    body_size = median(body_sizes) if body_sizes else 11.0
    result: list[SemanticBlock] = []
    for index, block in enumerate(blocks):
        text = " ".join(block.text.split())
        folded = _normalized(text)
        words = text.split()
        explicit = bool(_CHAPTER.match(text))
        numbered = bool(_NUMBERED_ITEM.match(text))
        supported = folded in toc
        special_heading = block.kind in {
            SemanticKind.ABSTRACT,
            SemanticKind.CONCLUSION,
            SemanticKind.REFERENCES,
        }
        preserved = block.kind in {
            SemanticKind.TABLE,
            SemanticKind.FIGURE,
            SemanticKind.CAPTION,
            SemanticKind.LIST,
            SemanticKind.KEYWORDS,
        }
        negative = (
            preserved
            or folded in repeated
            or any(marker in text for marker in _VERSE_MARKERS)
            or (text.endswith((".", "।", "?", "!")) and not explicit)
            or len(words) > 18
        )
        following = _has_following_content(blocks, index)
        if not following and block.kind not in {SemanticKind.TITLE} and not special_heading:
            negative = True
        ratio = block.font_size / body_size if block.font_size else 1.0
        score = 0
        score += 5 if explicit else 0
        score += 4 if special_heading else 0
        score += 4 if supported else 0
        score += 2 if ratio >= 1.25 else 0
        score += 1 if block.bold else 0
        score += 2 if len(words) <= 10 else 0
        score += 1 if numbered else 0
        score += 2 if following else 0
        if negative or score < 5:
            if preserved:
                result.append(replace(block, include_in_toc=False))
            else:
                result.append(
                    replace(
                        block,
                        kind=SemanticKind.PARAGRAPH,
                        level=0,
                        include_in_toc=False,
                        confidence=min(block.confidence, 0.49),
                        start_new_page=False,
                    )
                )
            continue
        kind = block.kind if special_heading else SemanticKind.CHAPTER if explicit else SemanticKind.SECTION
        if re.match(r"^\d+\.\d+(?:\.\d+)*\b", text):
            kind = SemanticKind.SUBSECTION
        confidence = min(0.98, 0.48 + score * 0.05)
        result.append(
            replace(
                block,
                kind=kind,
                level=1 if kind == SemanticKind.CHAPTER else 3 if kind == SemanticKind.SUBSECTION else 2,
                include_in_toc=confidence >= 0.65,
                confidence=confidence,
                start_new_page=kind == SemanticKind.CHAPTER,
            )
        )
    return result


def validate_hierarchy(
    blocks: list[SemanticBlock],
    *,
    page_count: int | None = None,
) -> list[SemanticBlock]:
    """Demote duplicate and implausibly dense generated contents entries."""

    result = list(blocks)
    seen: set[str] = set()
    for index, block in enumerate(result):
        if not block.include_in_toc:
            continue
        key = _normalized(block.text)
        if not key or key in seen or block.kind in {SemanticKind.TABLE, SemanticKind.LIST}:
            result[index] = replace(block, kind=SemanticKind.PARAGRAPH, level=0, include_in_toc=False)
        else:
            seen.add(key)
    maximum = max(3, (page_count or max((block.page_number for block in result), default=1)) * 2)
    toc_indices = [index for index, block in enumerate(result) if block.include_in_toc]
    if len(toc_indices) > maximum:
        demote = sorted(toc_indices, key=lambda index: (result[index].confidence, -index))[: len(toc_indices) - maximum]
        for index in demote:
            block = result[index]
            result[index] = replace(block, kind=SemanticKind.PARAGRAPH, level=0, include_in_toc=False)
    return result


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _has_following_content(blocks: list[SemanticBlock], index: int) -> bool:
    for following in blocks[index + 1:index + 4]:
        if following.kind in {SemanticKind.FIGURE, SemanticKind.CAPTION}:
            continue
        words = following.text.split()
        return len(following.text) >= 30 or len(words) >= 6
    return False


def detect_structure(text: str) -> list[StructuredBlock]:
    paragraphs = ["\n".join(line.rstrip() for line in p.splitlines()).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    blocks: list[StructuredBlock] = []
    for index, paragraph in enumerate(paragraphs):
        single_line = "\n" not in paragraph
        words = paragraph.split()
        following = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        has_following_body = len(following) >= 40 or len(following.split()) >= 7
        if index == 0 and single_line and len(words) <= 12:
            kind, level = BlockKind.BOOK_TITLE, 0
        elif _CHAPTER.match(paragraph):
            kind, level = BlockKind.CHAPTER, 1
        elif any(marker in paragraph for marker in _VERSE_MARKERS) or ("\n" in paragraph and len(words) <= 40):
            kind, level = BlockKind.VERSE, 0
        elif single_line and len(words) <= 12 and has_following_body and not paragraph.endswith(('.', '।', '?', '!')) and _NUMBERED_ITEM.match(paragraph):
            kind, level = BlockKind.NUMBERED_ITEM, 3
        elif _LIST.match(paragraph):
            kind, level = BlockKind.LIST, 0
        elif single_line and len(words) <= 6 and has_following_body and not paragraph.isupper():
            kind, level = BlockKind.HEADING, 2
        elif single_line and len(words) <= 10 and has_following_body and not paragraph.isupper() and not paragraph.endswith(("।", ".", "?", "!")):
            kind, level = BlockKind.SUBHEADING, 3
        else:
            kind, level = BlockKind.BODY, 0
        blocks.append(StructuredBlock(kind, paragraph, level=level))
    return blocks

