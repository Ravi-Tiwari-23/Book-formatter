from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject


class AssetClass(str, Enum):
    PROTECTED_BRANDING = "PROTECTED_BRANDING"
    PROTECTED_PHOTO = "PROTECTED_PHOTO"
    DECORATIVE = "DECORATIVE"
    CONTENT_IMAGE = "CONTENT_IMAGE"
    UNKNOWN = "UNKNOWN"


def classify_source_image(
    page_number: int,
    bbox: tuple[float, float, float, float] | None,
    page_width: float,
    page_height: float,
) -> AssetClass:
    if not bbox or page_width <= 0 or page_height <= 0:
        return AssetClass.UNKNOWN
    x0, y0, x1, y1 = bbox
    coverage = max(0, x1 - x0) * max(0, y1 - y0) / (page_width * page_height)
    if page_number == 1 and coverage >= 0.25:
        return AssetClass.PROTECTED_BRANDING
    if coverage >= 0.25:
        return AssetClass.PROTECTED_PHOTO
    if y1 <= page_height * 0.15 or y0 >= page_height * 0.85:
        return AssetClass.DECORATIVE
    if coverage >= 0.02:
        return AssetClass.CONTENT_IMAGE
    return AssetClass.UNKNOWN


def page_content_sha256(page: Any) -> str:
    contents = page.get_contents()
    data = contents.get_data() if contents else b""
    return hashlib.sha256(data).hexdigest()


def prepend_protected_pages(
    source_pdf: str | Path,
    formatted_pdf: str | Path,
    output_pdf: str | Path,
    page_numbers: list[int],
    *,
    target_page_size: tuple[float, float] | None = None,
    replace_leading_pages: bool = False,
) -> list[dict[str, Any]]:
    """Prepend source pages, optionally fitting them to one uniform book page size."""
    source = PdfReader(source_pdf)
    formatted = PdfReader(formatted_pdf)
    if target_page_size is not None and formatted.pages:
        # The renderer's CSS page size can contain fractional points. Use that
        # exact media box so a nominal A5/A4 rounding difference cannot fail QA.
        target_page_size = (
            float(formatted.pages[0].mediabox.width),
            float(formatted.pages[0].mediabox.height),
        )
    writer = PdfWriter()
    records: list[dict[str, Any]] = []
    for number in sorted(set(page_numbers)):
        if number < 1 or number > len(source.pages):
            raise ValueError(f"Protected page {number} is outside the source PDF")
        source_page = source.pages[number - 1]
        source_digest = page_content_sha256(source_page)
        if target_page_size is None:
            writer.add_page(source_page)
            records.append(
                {
                    "source_page": number,
                    "source_content_sha256": source_digest,
                    "content_sha256": source_digest,
                    "fit_mode": "original",
                }
            )
            continue

        target_width, target_height = target_page_size
        source_width = float(source_page.mediabox.width)
        source_height = float(source_page.mediabox.height)
        scale = max(target_width / source_width, target_height / source_height)
        translate_x = (target_width - source_width * scale) / 2
        translate_y = (target_height - source_height * scale) / 2
        fitted = PageObject.create_blank_page(width=target_width, height=target_height)
        fitted.merge_transformed_page(
            source_page,
            Transformation().scale(scale).translate(translate_x, translate_y),
        )
        writer.add_page(fitted)
        records.append(
            {
                "source_page": number,
                "source_content_sha256": source_digest,
                "content_sha256": page_content_sha256(fitted),
                "fit_mode": "cover",
                "scale": scale,
                "target_width_pt": target_width,
                "target_height_pt": target_height,
            }
        )
    formatted_start = len(records) if replace_leading_pages else 0
    if formatted_start > len(formatted.pages):
        raise ValueError("Formatted PDF does not contain enough protected-page placeholders")
    for page in formatted.pages[formatted_start:]:
        writer.add_page(page)
    if formatted.outline:
        offset = 0 if replace_leading_pages else len(records)
        _copy_outline(formatted.outline, writer, formatted, offset)
    target = Path(output_pdf)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        writer.write(stream)
    written = PdfReader(target)
    for index, record in enumerate(records):
        record["content_sha256"] = page_content_sha256(written.pages[index])
    return records


def _copy_outline(items: list[Any], writer: PdfWriter, source: PdfReader, offset: int, parent=None) -> None:
    current_parent = parent
    for item in items:
        if isinstance(item, list):
            _copy_outline(item, writer, source, offset, current_parent)
            continue
        try:
            page_number = source.get_destination_page_number(item)
        except Exception:
            continue
        current_parent = writer.add_outline_item(
            getattr(item, "title", str(item)), page_number + offset, parent=parent
        )


def verify_protected_pages(output_pdf: str | Path, records: list[dict[str, Any]]) -> None:
    output = PdfReader(output_pdf)
    for index, record in enumerate(records):
        actual = page_content_sha256(output.pages[index])
        if actual != record["content_sha256"]:
            raise ValueError(f"Protected source page {record['source_page']} content changed")

