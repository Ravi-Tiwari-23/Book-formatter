"""Per-document structural inference. No book names or expected item counts."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import re

from .models import BookSection, ExtractedDocument
from .matching import normalize_text

NUMBER = re.compile(r"^(\d+(?:\.\d+)*|[०-९]+)[.)\-:]?\s+(.+)$")
CHAPTER = re.compile(r"^(?:chapter|part|अध्याय|भाग)\s+(?:\d+|[ivxlcdm]+|[०-९]+)\b", re.I)
TOC = {"contents", "table of contents", "index", "विषय सूची", "विषय-सूची", "अनुक्रमणिका"}


@dataclass
class DocumentProfile:
    title: str = "Document"
    document_type: str = "document"
    language: str = "english"
    width_pt: float = 595.28
    height_pt: float = 841.89
    cover_pages: list[int] = field(default_factory=list)
    toc_pages: list[int] = field(default_factory=list)
    toc_titles: list[str] = field(default_factory=list)
    hierarchy: dict = field(default_factory=dict)
    major_heading_new_page: bool = False
    numbered_items_compact: bool = False
    body_font_size: float = 11
    style_variant: str = "minimal"
    sections: list[BookSection] = field(default_factory=list)
    image_associations: list[dict] = field(default_factory=list)
    low_confidence_blocks: list[dict] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def style(self, base: dict) -> dict:
        result = dict(base)
        result["style_variant"] = self.style_variant
        result["language"] = "hi" if self.language in {"hindi", "mixed"} else "en"
        return result


def _key(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def analyze_document(document: ExtractedDocument) -> DocumentProfile:
    profile = DocumentProfile()
    geometry = Counter((round(p.width or 595.28, 2), round(p.height or 841.89, 2)) for p in document.pages)
    if geometry:
        profile.width_pt, profile.height_pt = geometry.most_common(1)[0][0]
    complete_text = " ".join(p.text for p in document.pages)
    hindi = len(re.findall(r"[\u0900-\u097f]", complete_text))
    latin = len(re.findall(r"[A-Za-z]", complete_text))
    profile.language = "mixed" if hindi and latin > hindi * .15 else "hindi" if hindi else "english"
    profile.ocr_pages = [p.page_number for p in document.pages if p.used_ocr]
    sizes = Counter()
    lines = []
    for page in document.pages:
        records = [b for b in page.blocks if b.get("type", 0) == 0 and b.get("text", "").strip()]
        if not records:
            records = [{"text": line, "bbox": (40, 40 + i * 14, (page.width or 595) - 40, 54 + i * 14)}
                       for i, line in enumerate(page.text.splitlines()) if line.strip()]
        for block in records:
            text = normalize_text(block["text"])
            size = float(block.get("font_size", 0))
            if size:
                sizes[round(size, 1)] += len(text)
            lines.append({**block, "text": text, "page": page.page_number, "height": page.height or 842})
            if block.get("table_rows"):
                profile.tables.append({"source_page": page.page_number, "text": text, "bbox": block["bbox"], "rows": block["table_rows"]})
        # An index heading partway through a metadata/body page is not evidence
        # that the entire page can be discarded as navigation.
        if any(_key(b["text"]) in TOC for b in records[:4]):
            profile.toc_pages.append(page.page_number)
    profile.body_font_size = sizes.most_common(1)[0][0] if sizes else 11

    # Repetition is furniture evidence only at page edges.
    repeated = defaultdict(set)
    for line in lines:
        bbox = line["bbox"]
        if bbox[1] < line["height"] * .12 or bbox[3] > line["height"] * .88:
            repeated[_key(line["text"])].add(line["page"])
    noise = {text for text, pages in repeated.items() if len(pages) >= 2}
    toc_titles = set()
    for line in lines:
        if line["page"] in profile.toc_pages:
            label = re.sub(r"\s*\.{2,}\s*\d+\s*$|\s+\d+\s*$", "", line["text"])
            toc_titles.add(_key(label))
    profile.toc_titles = sorted(toc_titles)

    first = [line for line in lines if line["page"] == 1]
    if first and 1 not in profile.toc_pages:
        title_line = max(first, key=lambda l: (l.get("font_size", 0), -len(l["text"])))
        body_chars = sum(len(l["text"]) for l in first if l.get("font_size", 0) <= profile.body_font_size * 1.05)
        large_title = title_line.get("font_size", 0) >= profile.body_font_size * 1.5
        cover_composition = (large_title and body_chars < 280 and len(first) < 22
                             and not NUMBER.match(title_line["text"]) and not CHAPTER.match(title_line["text"]))
        if cover_composition and len(document.pages) > 1:
            profile.cover_pages = [1]
            profile.title = title_line["text"]
            # Preserve a consecutive illustrated title/half-title composition
            # too, but stop as soon as normal prose or navigation begins.
            for page in document.pages[1:]:
                page_lines = [line for line in lines if line['page'] == page.page_number]
                if not page_lines or page.page_number in profile.toc_pages:
                    break
                largest = max(page_lines, key=lambda line: line.get('font_size', 0))
                text_length = sum(len(line['text']) for line in page_lines)
                if (text_length < 200 and len(page_lines) < 10 and page.images
                        and largest.get('font_size', 0) >= profile.body_font_size * 1.5
                        and not NUMBER.match(largest['text']) and not CHAPTER.match(largest['text'])):
                    profile.cover_pages.append(page.page_number)
                else:
                    break

    content = []
    for line in lines:
        if line["page"] in profile.cover_pages or line["page"] in profile.toc_pages:
            continue
        bbox = line["bbox"]
        edge = bbox[1] < line["height"] * .12 or bbox[3] > line["height"] * .88
        if edge and not NUMBER.match(line["text"]) and (_key(line["text"]) in noise
                     or re.fullmatch(r"(?:page\s*)?\d+", line["text"], re.I)):
            continue
        content.append(line)

    numbered = [i for i, line in enumerate(content) if NUMBER.match(line["text"]) and len(line["text"].split()) <= 24]
    numbering_sequence = len(numbered) >= 2
    candidates = {}
    for i, line in enumerate(content):
        text = line["text"]
        if line.get("table_rows"):
            continue
        number = NUMBER.match(text)
        size = line.get("font_size", 0)
        relative = size / profile.body_font_size if size else 1
        words = len(text.split())
        previous = content[i - 1] if i else None
        gap = line["bbox"][1] - previous["bbox"][3] if previous and previous["page"] == line["page"] else 30
        following = content[i + 1] if i + 1 < len(content) else None
        title_like = words <= 24 and not text.endswith((".", "।", "?", "!"))
        short_followed = words <= 9 and following and len(following["text"].split()) > words
        explicit = bool(CHAPTER.match(text))
        toc_match = _key(text) in toc_titles
        score = (2 if relative >= 1.35 else 0) + int(bool(line.get("bold"))) + (2 if gap >= 15 else 0) + (3 if toc_match else 0)
        # Numbering needs independent context, not just a numeric prefix.
        numeric_heading = bool(number and title_like and (relative >= 1.12 or line.get("bold") or toc_match or (numbering_sequence and short_followed)))
        styled_heading = title_like and (words <= 10 or relative >= 1.5) and relative >= 1.15 and (line.get("bold") or gap >= 5 or toc_match)
        if explicit or numeric_heading or styled_heading or (title_like and toc_match):
            candidates[i] = {"score": score, "number": number.group(1) if number else "", "relative": relative, "explicit": explicit,
                             "top": line["bbox"][1] < line["height"] * .18, "toc": toc_match}
        elif number or (text.isupper() and words < 15):
            profile.low_confidence_blocks.append({"page": line["page"], "text": text, "confidence": .35, "type": "unknown"})

    top_ratio = sum(c["top"] for c in candidates.values()) / max(1, len(candidates))
    indices = list(candidates)
    active = None
    paragraph = []
    last_line = None

    def flush():
        nonlocal paragraph
        if paragraph and active:
            active.paragraphs.append(normalize_text(" ".join(paragraph)))
        paragraph = []

    for i, line in enumerate(content):
        if i in candidates:
            flush()
            c = candidates[i]
            end = next((j for j in indices if j > i), len(content))
            following_chars = sum(len(l["text"]) for l in content[i + 1:end])
            score = c["score"] + (3 if c["top"] and top_ratio >= .7 else 0) + (2 if following_chars >= 900 else 0)
            chapter = c["explicit"] or (score >= 7 and following_chars >= 500 and c["top"])
            kind = "chapter" if chapter else "numbered_item" if c["number"] else "section"
            if not chapter and c["number"] and "." in c["number"]:
                kind = "subsection"
            confidence = .96 if c["explicit"] else min(.95, .55 + score * .05)
            section_id = len([s for s in profile.sections if s.title]) + 1
            active = BookSection(section_id, line["text"], [], line["page"], line["page"],
                                 kind=kind, display_number=c["number"], level=1 if chapter else 3 if kind in {"numbered_item", "subsection"} else 2,
                                 confidence=confidence, start_new_page=chapter, include_in_toc=kind != "subsection" or c["toc"], bbox=tuple(line["bbox"]))
            profile.sections.append(active)
        else:
            if active is None:
                active = BookSection(0, "", [], line["page"], line["page"], kind="body_paragraph", include_in_toc=False)
                profile.sections.append(active)
            if line.get("table_rows") or (last_line and (last_line.get("table_rows") or line["page"] != last_line["page"] or line["bbox"][1] - last_line["bbox"][3] > max(4, profile.body_font_size * .55))):
                flush()
            paragraph.append(line["text"])
            if line.get("table_rows"):
                flush()
        active.page_end = line["page"]
        last_line = line
    flush()
    for section in profile.sections:
        section.raw_text = "\n\n".join(section.paragraphs)
        section.normalized_text = normalize_text(section.raw_text)
    kinds = Counter(s.kind for s in profile.sections)
    profile.major_heading_new_page = bool(kinds["chapter"])
    profile.numbered_items_compact = bool(kinds["numbered_item"])
    profile.document_type = "chapter_book" if kinds["chapter"] else "compact_guide" if kinds["numbered_item"] else "reference_document" if kinds["section"] else "document"
    profile.style_variant = "classic_book" if kinds["chapter"] else "traditional" if kinds["numbered_item"] else "modern_reference" if kinds["section"] else "minimal"
    profile.hierarchy = {f"level_{level}": sorted({s.kind for s in profile.sections if s.level == level}) for level in (1, 2, 3)}
    if profile.title == "Document" and profile.sections and profile.sections[0].title:
        profile.title = profile.sections[0].title

    for page in document.pages:
        for image in page.images:
            box = image.bbox
            area = max(0, box[2] - box[0]) * max(0, box[3] - box[1]) if box else 0
            fraction = area / max(1, (page.width or 595) * (page.height or 842))
            category = "content_image"
            if page.page_number in profile.cover_pages:
                category = "logo"
            elif fraction > .8:
                category = "page_artifact" if page.used_ocr else "background"
            elif fraction < .002:
                category = "decorative_element"
            elif box and (box[3] < (page.height or 842) * .12 or box[1] > (page.height or 842) * .88):
                category = "header_graphic" if box[3] < (page.height or 842) * .12 else "footer_graphic"
            candidates_on_page = [s for s in profile.sections if s.page_start <= page.page_number <= s.page_end]
            parent = None
            if candidates_on_page and box:
                # Prefer the section whose heading precedes the image on this
                # page, considering vertical and horizontal distance together.
                def distance(section):
                    if section.page_start < page.page_number or not section.bbox:
                        return abs(box[1]) + 50
                    x0, y0, x1, y1 = section.bbox
                    return abs(box[1] - y1) + max(0, x0 - box[2], box[0] - x1) + (500 if y0 > box[3] else 0)
                parent = min(candidates_on_page, key=distance)
            profile.image_associations.append({"digest": image.digest, "source_page": page.page_number, "bbox": box,
                "parent_section_id": str(parent.number) if parent else None, "confidence": .9 if parent and len(candidates_on_page) == 1 else .7 if parent else .2, "classification": category})
    return profile
