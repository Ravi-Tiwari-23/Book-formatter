from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import re

import pymupdf
from pypdf import PdfReader

from .assets import verify_protected_pages
from .integrity import (
    IntegrityDifferenceType,
    TextUnit,
    verify_rendered_pdf,
)


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
    toc_links_checked = 0
    with pymupdf.open(source) as document:
        expected_width = float(document[0].rect.width)
        expected_height = float(document[0].rect.height)
        outline_titles = {
            re.sub(r"\s+", " ", item[1]).strip().casefold()
            for item in document.get_toc(simple=True)
            if len(item) >= 3
        }
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
            intentional = number <= max(1, len(protected_records)) or any(
                marker in text.casefold()
                for marker in ("contents", "reference information", "chapter")
            )
            if coverage < 0.025 and not intentional:
                almost_empty_pages.append(number)

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
    report = {
        "valid": not (
            blank_pages
            or page_size_mismatches
            or image_caption_issues
            or overflow_pages
            or orphan_heading_pages
            or toc_invalid_targets
            or toc_page_number_mismatches
        ),
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

