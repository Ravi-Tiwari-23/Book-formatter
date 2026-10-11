from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

from .models import ExtractedDocument, ExtractedImage, ExtractedPage
from .cache import DiskCache
from .ocr import ocr_image


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_images(document: pymupdf.Document, page: pymupdf.Page, page_number: int) -> list[ExtractedImage]:
    result: list[ExtractedImage] = []
    for image in page.get_images(full=True):
        xref = image[0]
        payload = document.extract_image(xref)
        boxes = page.get_image_rects(xref)
        for bbox in (list(map(tuple, boxes)) or [None]):
            result.append(
            ExtractedImage(
                page_number=page_number,
                xref=xref,
                extension=payload.get("ext", "bin"),
                data=payload["image"],
                digest=hashlib.sha256(payload["image"]).hexdigest(),
                bbox=bbox,
            )
        )
    return result


def extract_pdf(
    path: str | Path,
    *,
    min_direct_characters: int = 24,
    ocr_dpi: int = 300,
    tesseract_path: str | None = None,
    text_only: bool = False,
    ocr_cache: DiskCache | None = None,
    ocr_languages: str = "hin+eng",
    ocr_config: str = "--psm 6",
    ocr_workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractedDocument:
    source = Path(path)
    started = time.perf_counter()
    pdf_hash = file_sha256(source)
    pages: list[ExtractedPage] = []
    ocr_jobs: list[tuple[int, bytes, str]] = []
    metrics: dict[str, float | int] = {
        "pdf_open_seconds": 0.0,
        "native_pages": 0,
        "ocr_pages": 0,
        "ocr_cache_hits": 0,
        "native_extraction_seconds": 0.0,
        "page_classification_seconds": 0.0,
        "image_extraction_seconds": 0.0,
        "ocr_render_seconds": 0.0,
        "ocr_seconds": 0.0,
    }
    open_started = time.perf_counter()
    document = pymupdf.open(source)
    metrics["pdf_open_seconds"] = time.perf_counter() - open_started
    try:
        total_pages = len(document)
        for index, page in enumerate(document):
            native_started = time.perf_counter()
            raw_text = page.get_text("text", sort=True).strip()
            blocks = []
            for native_block in page.get_text("dict", sort=True)["blocks"]:
                for line in native_block.get("lines", []):
                    spans = line.get("spans", [])
                    blocks.append({
                        "bbox": tuple(line["bbox"]),
                        "text": "".join(span["text"] for span in spans),
                        "type": 0,
                        "font_size": max((span["size"] for span in spans), default=0),
                        "bold": any(span["flags"] & 16 for span in spans),
                        "font": spans[0]["font"] if spans else "",
                    })
            metrics["native_extraction_seconds"] += time.perf_counter() - native_started
            classification_started = time.perf_counter()
            used_ocr = not _usable_native_text(raw_text, min_direct_characters)
            metrics["page_classification_seconds"] += (
                time.perf_counter() - classification_started
            )
            confidence = None
            cache_hit = False
            if used_ocr:
                key = f"{pdf_hash}:{index + 1}:{ocr_languages}:{ocr_dpi}:{ocr_config}"
                cached = ocr_cache.get(key) if ocr_cache else None
                if cached is not None:
                    raw_text = cached["text"]
                    blocks = cached.get("blocks", [])
                    confidence = cached["confidence"]
                    cache_hit = True
                    metrics["ocr_cache_hits"] += 1
                else:
                    render_started = time.perf_counter()
                    pixmap = page.get_pixmap(dpi=ocr_dpi, alpha=False)
                    ocr_jobs.append((index, pixmap.tobytes("png"), key))
                    metrics["ocr_render_seconds"] += time.perf_counter() - render_started
                metrics["ocr_pages"] += 1
            else:
                metrics["native_pages"] += 1
                tables = page.find_tables().tables
                for table in tables:
                    rows = [[cell or "" for cell in row] for row in table.extract()]
                    if len(rows) < 2 or max(map(len, rows), default=0) < 2:
                        continue
                    rect = pymupdf.Rect(table.bbox)
                    blocks = [b for b in blocks if not rect.contains(pymupdf.Rect(b["bbox"]))]
                    blocks.append({"type": 0, "text": " ".join(cell for row in rows for cell in row),
                                   "bbox": tuple(rect), "table_rows": rows, "font_size": 0})
                blocks.sort(key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))
            image_started = time.perf_counter()
            images = [] if text_only else _extract_images(document, page, index + 1)
            metrics["image_extraction_seconds"] += time.perf_counter() - image_started
            pages.append(
                ExtractedPage(
                    page_number=index + 1,
                    text=raw_text,
                    used_ocr=used_ocr,
                    ocr_confidence=confidence,
                    blocks=blocks,
                    images=images,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    method="OCR" if used_ocr else "NATIVE",
                    ocr_cache_hit=cache_hit,
                )
            )
            if progress:
                progress(index + 1, total_pages)
    finally:
        document.close()

    if ocr_jobs:
        ocr_started = time.perf_counter()
        workers = ocr_workers or max(1, min(4, (os.cpu_count() or 2) - 1))

        def run(job: tuple[int, bytes, str]):
            page_index, png, key = job
            image = Image.open(BytesIO(png))
            result = ocr_image(
                image,
                executable=tesseract_path,
                languages=ocr_languages,
                config=ocr_config,
            )
            return page_index, key, result

        with ThreadPoolExecutor(max_workers=min(workers, len(ocr_jobs))) as executor:
            for page_index, key, result in executor.map(run, ocr_jobs):
                pages[page_index].text = result.text
                pages[page_index].ocr_confidence = result.confidence
                scale = 72 / ocr_dpi
                pages[page_index].blocks = [
                    {**block, "bbox": tuple(v * scale for v in block["bbox"])}
                    for block in getattr(result, "blocks", [])
                ]
                if ocr_cache:
                    ocr_cache.set(key, {"text": result.text, "confidence": result.confidence, "blocks": pages[page_index].blocks})
        metrics["ocr_seconds"] = time.perf_counter() - ocr_started
    metrics["total_extraction_seconds"] = time.perf_counter() - started
    return ExtractedDocument(source, pages, pdf_hash, metrics=metrics)


def _usable_native_text(text: str, minimum_characters: int) -> bool:
    compact = "".join(text.split())
    if len(compact) < minimum_characters:
        return False
    replacement_ratio = compact.count("\ufffd") / max(1, len(compact))
    readable = sum(character.isalnum() for character in compact) / max(1, len(compact))
    return replacement_ratio < 0.02 and readable >= 0.45

