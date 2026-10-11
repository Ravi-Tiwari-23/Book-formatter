from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_protected_terms(path: Path | None = None) -> set[str]:
    source = path or PROJECT_ROOT / "config" / "protected_terms.txt"
    return {
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def load_book_style(path: Path | None = None) -> dict[str, Any]:
    source = path or PROJECT_ROOT / "config" / "book_style.json"
    return json.loads(source.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class BookProfile:
    title: str
    slug: str
    expected_sections: tuple[int, ...]
    protected_pages: tuple[int, ...] = ()
    style_path: str = "config/book_style.json"

    def output_name(self, production: bool) -> str:
        suffix = "Final" if production else "Test"
        return f"{self.slug}-TRUELOGER-{suffix}.pdf"


def load_book_profile(path: Path | None = None) -> BookProfile:
    source = path or PROJECT_ROOT / "config" / "books" / "33-quick-vastu-remedies.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    return BookProfile(
        title=data["title"],
        slug=data["slug"],
        expected_sections=tuple(data["expected_sections"]),
        protected_pages=tuple(data.get("protected_pages", [])),
        style_path=data.get("style_path", "config/book_style.json"),
    )

