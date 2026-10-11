from __future__ import annotations

import re

from .models import BlockKind, StructuredBlock


_CHAPTER = re.compile(r"^(अध्याय|chapter|भाग|part)\s*[\d०-९IVXivx:-]*", re.IGNORECASE)
_LIST = re.compile(r"^(?:[-*•]|\d+[.)]|[०-९]+[.)])\s+")
_NUMBERED_ITEM = re.compile(r"^(?:remedy\s*)?(\d+(?:\.\d+)*)\s*(?:[.)\-:]\s*|\s+)(\S.+)$", re.IGNORECASE)
_VERSE_MARKERS = ("॥", "ॐ", "श्लोक", "मंत्र")


def detect_structure(text: str) -> list[StructuredBlock]:
    paragraphs = ["\n".join(line.rstrip() for line in p.splitlines()).strip() for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]
    blocks: list[StructuredBlock] = []
    for index, paragraph in enumerate(paragraphs):
        single_line = "\n" not in paragraph
        words = paragraph.split()
        if index == 0 and single_line and len(words) <= 12:
            kind, level = BlockKind.BOOK_TITLE, 0
        elif _CHAPTER.match(paragraph):
            kind, level = BlockKind.CHAPTER, 1
        elif single_line and len(words) <= 12 and not paragraph.endswith(('.', '।', '?', '!')) and _NUMBERED_ITEM.match(paragraph):
            kind, level = BlockKind.NUMBERED_ITEM, 3
        elif any(marker in paragraph for marker in _VERSE_MARKERS) or ("\n" in paragraph and len(words) <= 40):
            kind, level = BlockKind.VERSE, 0
        elif _LIST.match(paragraph):
            kind, level = BlockKind.LIST, 0
        elif single_line and len(words) <= 6:
            kind, level = BlockKind.HEADING, 2
        elif single_line and len(words) <= 10 and not paragraph.endswith(("।", ".", "?", "!")):
            kind, level = BlockKind.SUBHEADING, 3
        else:
            kind, level = BlockKind.BODY, 0
        blocks.append(StructuredBlock(kind, paragraph, level=level))
    return blocks

