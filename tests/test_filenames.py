from pathlib import Path

from bookloom.filenames import allocate_output_path, sanitize_source_stem


def test_output_names_follow_uploaded_filename_and_increment_per_changed_build(
    tmp_path: Path,
) -> None:
    first = allocate_output_path(
        tmp_path, "Complete House Vastu.pdf", "approved-build-a"
    )
    cached = allocate_output_path(
        tmp_path, "Complete House Vastu.pdf", "approved-build-a"
    )
    changed = allocate_output_path(
        tmp_path, "Complete House Vastu.pdf", "approved-build-b"
    )

    assert first.name == "Complete House Vastu 1.pdf"
    assert cached == first
    assert changed.name == "Complete House Vastu 2.pdf"


def test_preview_has_its_own_clear_numbered_name(tmp_path: Path) -> None:
    path = allocate_output_path(
        tmp_path, "Complete House Vastu.pdf", "preview-build-a", preview=True
    )

    assert path.name == "Complete House Vastu Preview 1.pdf"


def test_source_stem_preserves_unicode_and_removes_windows_invalid_characters() -> None:
    assert sanitize_source_stem("वास्तु: घर? <2026>.pdf") == "वास्तु घर 2026"
    assert sanitize_source_stem("CON.pdf") == "CON Book"
