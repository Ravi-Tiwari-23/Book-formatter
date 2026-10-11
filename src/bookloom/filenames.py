from __future__ import annotations

import json
import re
from pathlib import Path


_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_REGISTRY_NAME = ".bookloom-output-versions.json"


def sanitize_source_stem(upload_name: str) -> str:
    """Return a readable, Unicode-preserving filename stem safe on Windows."""

    stem = Path(upload_name).stem
    stem = _INVALID_WINDOWS_CHARS.sub(" ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        stem = "Book"
    if stem.upper() in _RESERVED_WINDOWS_NAMES:
        stem = f"{stem} Book"
    return stem[:160].rstrip(" .") or "Book"


def allocate_output_path(
    output_dir: str | Path,
    source_upload_name: str,
    build_fingerprint: str,
    *,
    preview: bool = False,
) -> Path:
    """Allocate a stable numbered filename, reusing it for the same build."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    registry_path = directory / _REGISTRY_NAME
    registry = _load_registry(registry_path)
    stem = sanitize_source_stem(source_upload_name)
    mode = "preview" if preview else "production"
    key = f"{mode}:{stem}:{build_fingerprint}"
    existing = registry.get(key)
    if isinstance(existing, str):
        return directory / existing

    prefix = f"{stem} Preview" if preview else stem
    used_numbers = {
        int(match.group(1))
        for value in registry.values()
        if isinstance(value, str)
        and (match := re.fullmatch(rf"{re.escape(prefix)} (\d+)\.pdf", value))
    }
    for candidate in directory.glob(f"{prefix} *.pdf"):
        match = re.fullmatch(rf"{re.escape(prefix)} (\d+)\.pdf", candidate.name)
        if match:
            used_numbers.add(int(match.group(1)))
    version = max(used_numbers, default=0) + 1
    filename = f"{prefix} {version}.pdf"
    registry[key] = filename
    _write_registry(registry_path, registry)
    return directory / filename


def _load_registry(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_registry(path: Path, registry: dict[str, str]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
