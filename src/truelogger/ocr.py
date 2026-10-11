from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output


class OCRUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class OCRResult:
    text: str
    confidence: float
    blocks: list[dict] = field(default_factory=list)


def find_tesseract(configured_path: str | None = None) -> str | None:
    candidates = [
        configured_path,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    return next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)


def preprocess_image(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.filter(ImageFilter.SHARPEN)


def ocr_image(
    image: Image.Image,
    *,
    executable: str | None = None,
    languages: str = "hin+eng",
    config: str = "--psm 6",
) -> OCRResult:
    binary = find_tesseract(executable)
    if not binary:
        raise OCRUnavailableError(
            "Tesseract OCR 5 was not found. Install it with Hindi and English language data, "
            "then add its folder to PATH or configure its executable path in the app."
        )
    pytesseract.pytesseract.tesseract_cmd = binary
    prepared = preprocess_image(image)
    data = pytesseract.image_to_data(prepared, lang=languages, output_type=Output.DICT, config=config)
    words = [word.strip() for word in data["text"] if word.strip()]
    scores = [float(value) for value in data["conf"] if str(value) not in {"-1", ""}]
    grouped = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = tuple(data.get(name, [0] * len(data["text"]))[i] for name in ("block_num", "par_num", "line_num"))
        grouped.setdefault(key, []).append(i)
    blocks = []
    for indices in grouped.values():
        blocks.append({
            "text": " ".join(data["text"][i].strip() for i in indices),
            "bbox": (min(data["left"][i] for i in indices), min(data["top"][i] for i in indices),
                     max(data["left"][i] + data["width"][i] for i in indices),
                     max(data["top"][i] + data["height"][i] for i in indices)),
            "type": 0, "ocr": True,
        })
    return OCRResult("\n".join(block["text"] for block in blocks), sum(scores) / len(scores) if scores else 0.0, blocks)

