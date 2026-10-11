from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import pymupdf

from .cache import DiskCache
from .extraction import file_sha256


@dataclass(frozen=True, slots=True)
class PreviewResult:
    path: Path
    cache_hit: bool
    render_seconds: float


def render_page_preview(
    pdf_path: str | Path,
    page_number: int,
    *,
    cache: DiskCache,
    dpi: int = 120,
) -> PreviewResult:
    started = time.perf_counter()
    source = Path(pdf_path)
    key = f"{file_sha256(source)}:{page_number}:{dpi}"
    target = cache.path_for(key, ".png")
    if target.exists():
        return PreviewResult(target, True, time.perf_counter() - started)
    with pymupdf.open(source) as document:
        if page_number < 1 or page_number > len(document):
            raise ValueError(f"Page {page_number} is outside the PDF")
        pixmap = document[page_number - 1].get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(target)
    return PreviewResult(target, False, time.perf_counter() - started)

