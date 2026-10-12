from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any
import re

import pymupdf
from pypdf import PdfReader

from .assets import verify_protected_pages
from .models import BlockKind, StructuredBlock
from .integrity import (
    IntegrityDifferenceType,
    TextUnit,
    verify_rendered_pdf,
)


def verify_image_occurrences(
    expected_records: list[dict[str, Any]],
    rendered_blocks: list[StructuredBlock],
) -> dict[str, Any]:
    expected = [record["occurrence_id"] for record in expected_records]
    actual = [
        block.source_id
        for block in rendered_blocks
        if block.kind == BlockKind.IMAGE and block.source_id
    ]
    duplicate = sorted({identity for identity in actual if actual.count(identity) > 1})
    missing = [identity for identity in expected if identity not in actual]
    unexpected = [identity for identity in actual if identity not in expected]
    common_expected = [identity for identity in expected if identity in actual]
    common_actual = [identity for identity in actual if identity in expected]
    return {
        "valid": not (missing or duplicate or unexpected or common_expected != common_actual),
        "expected": expected,
        "rendered": actual,
        "missing": missing,
        "duplicate": duplicate,
        "unexpected": unexpected,
        "misordered": common_expected != common_actual,
    }


def _page_signature(page: pymupdf.Page) -> str | None:
    """Return a stable signature for content-rich pages, ignoring page folios."""
    lines = [
        re.sub(r"\s+", " ", line).strip().casefold()
        for line in page.get_text("text").splitlines()
    ]
    text = "\n".join(line for line in lines if line and not line.isdigit())
    if len(text) < 40:
        return None
    image_parts = sorted(
        str(info.get("digest", b"").hex() if isinstance(info.get("digest"), bytes) else info.get("digest", ""))
        for info in page.get_image_info(hashes=True)
    )
    payload = f"{text}\n{'|'.join(image_parts)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _representative_pages(
    page_facts: list[dict[str, Any]],
) -> dict[str, int]:
    if not page_facts:
        return {}
    roles: dict[str, int] = {"cover": 1, "final": int(page_facts[-1]["page"])}
    for fact in page_facts:
        number = int(fact["page"])
        text = str(fact["text"])
        folded = text.casefold()
        if "contents" not in roles and re.search(r"\bcontents?\b", folded):
            roles["contents"] = number
        if (
            "chapter" not in roles
            and number != roles.get("contents")
            and re.search(r"\bchapter\s+(?:\d+|[ivxlcdm]+|one|two|three)\b", folded)
        ):
            roles["chapter"] = number
        if "table" not in roles and (
            re.search(r"\btable\b", folded)
            or ("column" in folded and "value" in folded)
        ):
            roles["table"] = number
        if "references" not in roles and re.search(r"\b(?:references|bibliography)\b", folded):
            roles["references"] = number
        if "compact_item" not in roles and re.search(r"(?m)^\s*\d{1,3}\s*$", text):
            roles["compact_item"] = number
        if "image" not in roles and fact["image_count"]:
            roles["image"] = number
    excluded = {roles.get("cover"), roles.get("contents")}
    first_body = next(
        (
            int(fact["page"])
            for fact in page_facts
            if fact["page"] not in excluded and len(str(fact["text"]).strip()) >= 20
        ),
        None,
    )
    if first_body is not None:
        roles["first_body"] = first_body
    return roles


def _issue(code: str, message: str, pages: list[int], *, severity: str = "error") -> dict[str, Any]:
    return {"code": code, "severity": severity, "pages": pages, "message": message}


def verify_pdf(
    pdf_path: str | Path,
    *,
    protected_records: list[dict[str, Any]] | None = None,
    render_directory: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(pdf_path)
    reader = PdfReader(source)
    if not reader.pages:
        raise ValueError("Generated PDF has no pages")
    protected_records = protected_records or []
    verify_protected_pages(source, protected_records)
    font_names: set[str] = set()
    blank_pages: list[int] = []
    almost_empty_pages: list[int] = []
    page_sizes: list[dict[str, float | int]] = []
    page_size_mismatches: list[int] = []
    image_caption_issues: list[int] = []
    overflow_pages: list[int] = []
    orphan_heading_pages: list[int] = []
    toc_invalid_targets: list[int] = []
    toc_page_number_mismatches: list[dict[str, Any]] = []
    chapter_top_violations: list[dict[str, Any]] = []
    duplicate_page_groups: list[list[int]] = []
    missing_glyph_pages: list[int] = []
    suspicious_image_only_pages: list[int] = []
    table_footer_collision_pages: list[int] = []
    cover_numbered = False
    page_facts: list[dict[str, Any]] = []
    page_signatures: dict[str, list[int]] = {}
    toc_links_checked = 0
    with pymupdf.open(source) as document:
        expected_width = float(document[0].rect.width)
        expected_height = float(document[0].rect.height)
        outline_titles = {
            re.sub(r"\s+", " ", item[1]).strip().casefold()
            for item in document.get_toc(simple=True)
            if len(item) >= 3
        }
        chapter_destinations = [
            (item[1], int(item[2]) - 1)
            for item in document.get_toc(simple=True)
            if len(item) >= 3
            and int(item[0]) == 1
            and item[1].casefold() not in {"document content", "contents"}
        ]
        if render_directory:
            render_target = Path(render_directory)
            render_target.mkdir(parents=True, exist_ok=True)
            for stale in render_target.glob("page-*.png"):
                stale.unlink()
        for number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            image_infos = [
                info
                for info in page.get_image_info(xrefs=True)
                if info.get("bbox") and pymupdf.Rect(info["bbox"]).get_area() > 1
            ]
            page_facts.append(
                {"page": number, "text": text, "image_count": len(image_infos)}
            )
            signature = _page_signature(page)
            if signature:
                page_signatures.setdefault(signature, []).append(number)
            if "\ufffd" in text or "□" in text or "\x00" in text:
                missing_glyph_pages.append(number)
            if not text and not image_infos:
                blank_pages.append(number)
            width = float(page.rect.width)
            height = float(page.rect.height)
            page_sizes.append({"page": number, "width_pt": width, "height_pt": height})
            if abs(width - expected_width) > 0.5 or abs(height - expected_height) > 0.5:
                page_size_mismatches.append(number)

            text_blocks = [block for block in page.get_text("blocks", sort=True) if block[6] == 0]
            text_area = sum(
                max(0.0, float(block[2] - block[0])) * max(0.0, float(block[3] - block[1]))
                for block in text_blocks
            )
            image_area = 0.0
            for image in image_infos:
                rect = pymupdf.Rect(image["bbox"])
                image_area += max(0.0, rect.width) * max(0.0, rect.height)
                if not page.rect.contains(rect):
                    overflow_pages.append(number)
            coverage = (text_area + image_area) / max(1.0, width * height)
            image_coverage = image_area / max(1.0, width * height)
            intentional = number <= max(1, len(protected_records)) or any(
                marker in text.casefold()
                for marker in ("contents", "reference information", "chapter")
            )
            if coverage < 0.025 and not intentional:
                almost_empty_pages.append(number)
            if number > max(1, len(protected_records)) and not text and image_coverage >= 0.65:
                suspicious_image_only_pages.append(number)

            if number == 1:
                cover_numbered = any(
                    float(block[1]) >= height * 0.88
                    and re.fullmatch(r"\s*\d+\s*", str(block[4]))
                    for block in text_blocks
                )

            table_like = bool(re.search(r"\btable\b", text, re.IGNORECASE)) or (
                "column" in text.casefold() and "value" in text.casefold()
            )
            if table_like and any(
                float(block[3]) >= height * 0.92
                and not re.fullmatch(r"\s*\d+\s*", str(block[4]))
                for block in text_blocks
            ):
                table_footer_collision_pages.append(number)

            if number > len(protected_records) and image_infos and not re.search(
                r"source(?: image)?\s*(?:-|–|—|:)\s*(?:page|.+,\s*p\.)",
                text,
                re.IGNORECASE,
            ):
                image_caption_issues.append(number)

            for block in text_blocks:
                if block[0] < -0.5 or block[1] < -0.5 or block[2] > width + 0.5 or block[3] > height + 0.5:
                    overflow_pages.append(number)
            if text_blocks and number < len(document):
                last = text_blocks[-1]
                last_text = re.sub(r"\s+", " ", str(last[4])).strip().casefold()
                if last[3] > height * 0.78 and last_text in outline_titles:
                    orphan_heading_pages.append(number)

            for chapter_title, target_page in chapter_destinations:
                if target_page != number - 1:
                    continue
                title_key = re.sub(r"\s+", " ", chapter_title).strip().casefold()
                matching = next(
                    (
                        block for block in text_blocks
                        if title_key in re.sub(r"\s+", " ", str(block[4])).strip().casefold()
                    ),
                    None,
                )
                if matching:
                    top_mm = float(matching[1]) * 25.4 / 72
                    if not 22 <= top_mm <= 28:
                        chapter_top_violations.append(
                            {"page": number, "title": chapter_title, "top_mm": round(top_mm, 2)}
                        )

            page_links = page.get_links()
            if page_links:
                seen_rows: set[tuple[int, int]] = set()
                for link in page_links:
                    target = link.get("page", -1)
                    if target is not None and (target < 0 or target >= len(document)):
                        toc_invalid_targets.append(number)
                        continue
                    rect = pymupdf.Rect(link.get("from", (0, 0, 0, 0)))
                    if target is None or rect.width < width * 0.5:
                        continue
                    row_key = (int(target), round(rect.y0))
                    if row_key in seen_rows:
                        continue
                    seen_rows.add(row_key)
                    row_text = re.sub(r"\s+", " ", page.get_textbox(rect)).strip()
                    printed = re.search(r"(\d+)\s*$", row_text)
                    toc_links_checked += 1
                    if not printed or int(printed.group(1)) != int(target) + 1:
                        toc_page_number_mismatches.append(
                            {
                                "toc_page": number,
                                "entry": row_text,
                                "printed_page": int(printed.group(1)) if printed else None,
                                "actual_page": int(target) + 1,
                            }
                        )
            for font in page.get_fonts(full=True):
                font_names.add(font[3])
            if render_directory:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4), alpha=False)
                pixmap.save(Path(render_directory) / f"page-{number:04d}.png")
        duplicate_page_groups = sorted(
            pages for pages in page_signatures.values() if len(pages) > 1
        )
    issues: list[dict[str, Any]] = []
    checks = (
        ("BLANK_PAGE", "Blank page detected.", blank_pages, "error"),
        ("NEAR_EMPTY_PAGE", "Page has unusually little visible content.", almost_empty_pages, "warning"),
        ("PAGE_SIZE_MISMATCH", "Page size differs from the production page size.", page_size_mismatches, "error"),
        ("IMAGE_CAPTION", "An image is missing its source caption.", image_caption_issues, "error"),
        ("PAGE_OVERFLOW", "Content extends beyond the page boundary.", overflow_pages, "error"),
        ("ORPHAN_HEADING", "A heading is stranded at the bottom of a page.", orphan_heading_pages, "error"),
        ("INVALID_TOC_TARGET", "A contents link points outside the document.", toc_invalid_targets, "error"),
        ("MISSING_GLYPH", "A replacement or missing-glyph marker is visible.", missing_glyph_pages, "error"),
        ("SUSPICIOUS_IMAGE_ONLY_PAGE", "A non-cover page is almost entirely an unexplained image.", suspicious_image_only_pages, "error"),
        ("TABLE_FOOTER_COLLISION", "Table content reaches the reserved footer band.", table_footer_collision_pages, "error"),
    )
    for code, message, pages, severity in checks:
        if pages:
            issues.append(_issue(code, message, sorted(set(pages)), severity=severity))
    for pages in duplicate_page_groups:
        issues.append(_issue("DUPLICATE_PAGE", "Pages have identical production content.", pages))
    if cover_numbered:
        issues.append(_issue("COVER_NUMBERED", "The cover must not display a page number.", [1]))
    if toc_page_number_mismatches:
        issues.append(
            _issue(
                "TOC_PAGE_MISMATCH",
                "A printed contents page number does not match its link target.",
                sorted({int(item["toc_page"]) for item in toc_page_number_mismatches}),
            )
        )
    if chapter_top_violations:
        issues.append(
            _issue(
                "CHAPTER_TOP_BAND",
                "A chapter heading falls outside the configured top band.",
                sorted({int(item["page"]) for item in chapter_top_violations}),
            )
        )
    fatal_issues = [issue for issue in issues if issue["severity"] == "error"]
    report = {
        "valid": not fatal_issues,
        "page_count": len(reader.pages),
        "bookmarks_present": bool(reader.outline),
        "fonts": sorted(font_names),
        "blank_pages": blank_pages,
        "almost_empty_pages": sorted(set(almost_empty_pages)),
        "expected_page_size_pt": {
            "width": expected_width,
            "height": expected_height,
        },
        "page_sizes": page_sizes,
        "page_size_mismatches": sorted(set(page_size_mismatches)),
        "image_caption_issues": sorted(set(image_caption_issues)),
        "overflow_pages": sorted(set(overflow_pages)),
        "orphan_heading_pages": sorted(set(orphan_heading_pages)),
        "toc_invalid_targets": sorted(set(toc_invalid_targets)),
        "toc_links_checked": toc_links_checked,
        "toc_page_number_mismatches": toc_page_number_mismatches,
        "chapter_top_violations": chapter_top_violations,
        "duplicate_page_groups": duplicate_page_groups,
        "missing_glyph_pages": sorted(set(missing_glyph_pages)),
        "suspicious_image_only_pages": sorted(set(suspicious_image_only_pages)),
        "table_footer_collision_pages": sorted(set(table_footer_collision_pages)),
        "cover_numbered": cover_numbered,
        "representative_pages": _representative_pages(page_facts),
        "issues": issues,
        "protected_pages_verified": len(protected_records),
    }
    return report


def write_verification_report(report: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def verify_text_integrity(
    pdf_path: str | Path, approved_fragments: list[str]
) -> dict[str, Any]:
    units = [
        TextUnit(
            id=f"paragraph-{index}",
            chapter_id="book",
            chapter_title="Book",
            order=index,
            text=fragment,
        )
        for index, fragment in enumerate(approved_fragments)
        if fragment.strip()
    ]
    report = verify_rendered_pdf(pdf_path, units)
    result = report.to_dict()
    result.update(
        {
            "missing": [
                issue.expected_text
                for issue in report.issues
                if issue.difference_type == IntegrityDifferenceType.MISSING
            ],
            "duplicated": [
                issue.expected_text
                for issue in report.issues
                if issue.difference_type == IntegrityDifferenceType.DUPLICATED
            ],
            "out_of_order": any(
                issue.difference_type == IntegrityDifferenceType.ORDER_CHANGED
                for issue in report.issues
            ),
            "checked_fragments": report.checked_units,
        }
    )
    return result

