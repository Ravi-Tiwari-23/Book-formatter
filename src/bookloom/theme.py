from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import load_book_style


@dataclass(frozen=True, slots=True)
class BookTheme:
    version: str
    page_size: str
    page_dimensions_pt: tuple[float, float]
    margin_top_mm: float
    margin_right_mm: float
    margin_bottom_mm: float
    margin_left_mm: float
    chapter_padding_top_mm: float
    body_font: str
    heading_font: str
    devanagari_font: str
    body_size_pt: float
    line_height: float
    paragraph_spacing_pt: float
    book_title_size_pt: float
    chapter_size_pt: float
    heading_size_pt: float
    subheading_size_pt: float
    remedy_title_size_pt: float
    caption_size_pt: float
    toc_size_pt: float
    image_max_width_percent: float
    image_max_height_mm: float
    short_remedy_max_characters: int
    text_color: str
    accent_color: str
    cover_color: str
    cover_text_color: str
    muted_color: str
    rule_color: str
    page_number_position: str
    publisher_brand: str

    @classmethod
    def load(cls, path: Path | None = None) -> "BookTheme":
        data = load_book_style(path)
        data["page_dimensions_pt"] = tuple(data["page_dimensions_pt"])
        theme = cls(**data)
        if theme.page_size.upper() != "A4":
            raise ValueError("Bookloom Reading Edition must use fixed A4 pages")
        physical_top = theme.margin_top_mm + theme.chapter_padding_top_mm
        if not 22 <= physical_top <= 28:
            raise ValueError("Chapter heading top must be between 22 and 28 mm")
        return theme

    def to_style(self, **overrides: Any) -> dict[str, Any]:
        result = asdict(self)
        result.update(overrides)
        return result
