from pathlib import Path

import pymupdf

from bookloom.cache import DiskCache
from bookloom.extraction import extract_pdf
from bookloom.matching import match_paragraphs
from bookloom.preview import render_page_preview
from bookloom.ui_helpers import correction_counts, paginate
from bookloom.pipeline import ProjectPipeline
from bookloom.models import Decision, ReviewStatus
from bookloom.matching import MatchCategory, PassageMatch
from bookloom.validation import build_corrections


def _text_pdf(path: Path, text: str = "Usable native text with enough characters for extraction."):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)


def test_native_text_page_never_invokes_ocr(tmp_path, monkeypatch):
    path = tmp_path / "native.pdf"
    _text_pdf(path)
    monkeypatch.setattr("bookloom.extraction.ocr_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR invoked")))
    result = extract_pdf(path, ocr_cache=DiskCache(tmp_path / "cache", namespace="ocr"))
    assert result.pages[0].method == "NATIVE"
    assert result.metrics["ocr_pages"] == 0


def test_cached_ocr_page_does_not_rerun_ocr(tmp_path, monkeypatch):
    path = tmp_path / "scan.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    calls = {"count": 0}

    class Result:
        text = "Recovered OCR text"
        confidence = 91.0

    def fake_ocr(*args, **kwargs):
        calls["count"] += 1
        return Result()

    monkeypatch.setattr("bookloom.extraction.ocr_image", fake_ocr)
    cache = DiskCache(tmp_path / "cache", namespace="ocr", version="ocr-v1")
    first = extract_pdf(path, ocr_cache=cache)
    second = extract_pdf(path, ocr_cache=cache)
    assert calls["count"] == 1
    assert first.metrics["ocr_cache_hits"] == 0
    assert second.metrics["ocr_cache_hits"] == 1


def test_exact_matches_bypass_rapidfuzz(tmp_path, monkeypatch):
    calls = {"count": 0}

    def counted(*args, **kwargs):
        calls["count"] += 1
        return 100

    monkeypatch.setattr("bookloom.matching.fuzz.WRatio", counted)
    result = match_paragraphs([(1, "Exact text")], [(9, "Exact   text")])
    assert result[0].category.value == "EXACT_MATCH"
    assert calls["count"] == 0


def test_preview_is_generated_lazily_and_then_cached(tmp_path):
    path = tmp_path / "book.pdf"
    _text_pdf(path)
    cache = DiskCache(tmp_path / "cache", namespace="previews", version="preview-v1")
    assert list((tmp_path / "cache").rglob("*.png")) == []
    first = render_page_preview(path, 1, cache=cache, dpi=120)
    second = render_page_preview(path, 1, cache=cache, dpi=120)
    assert first.path == second.path
    assert second.cache_hit is True


def test_review_pagination_limits_widgets_to_requested_page():
    values = list(range(73))
    page, total_pages = paginate(values, page_number=2, page_size=25)
    assert page == list(range(25, 50))
    assert total_pages == 3


def test_review_counters_exclude_auto_approved_exact_and_safe_matches():
    class Item:
        def __init__(self, category, status):
            self.category = category
            self.status = status

    items = [
        Item("EXACT_MATCH", ReviewStatus.APPROVED),
        Item("SAFE_MATCH", ReviewStatus.APPROVED),
        Item("SPELLING_DIFFERENCE", ReviewStatus.PENDING),
        Item("GRAMMAR_DIFFERENCE", ReviewStatus.PENDING),
    ]

    counts = correction_counts(items)

    assert counts == {
        "exact": 1,
        "safe_auto_approved": 1,
        "spelling": 1,
        "grammar": 1,
        "meaningful": 2,
        "needs_manual_review": 2,
    }


def test_cache_version_change_invalidates_only_that_namespace(tmp_path):
    old = DiskCache(tmp_path, namespace="comparison", version="v1")
    old.set("same-input", {"value": 1})
    assert DiskCache(tmp_path, namespace="comparison", version="v1").get("same-input") == {"value": 1}
    assert DiskCache(tmp_path, namespace="comparison", version="v2").get("same-input") is None


def test_pipeline_reuses_extraction_and_comparison_cache(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    text = "1. First Remedy\nThe text is identical and sufficiently long."
    _text_pdf(source, text)
    _text_pdf(reference, text)
    pipeline = ProjectPipeline(tmp_path / "cache")
    first = pipeline.analyze(source, reference)
    second = pipeline.analyze(source, reference)
    assert first.performance["comparison_cache_hits"] == 0
    assert second.performance["extraction_cache_hits"] == 2
    assert second.performance["comparison_cache_hits"] == 1
    assert second.performance["fuzzy_comparisons"] == 0


def test_exact_match_is_auto_resolved_out_of_review_queue(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    text = "1. First Remedy\nThe text is identical and sufficiently long."
    _text_pdf(source, text)
    _text_pdf(reference, text)
    project = ProjectPipeline(tmp_path / "cache").analyze(source, reference)
    assert project.corrections[0].status == ReviewStatus.APPROVED
    assert project.corrections[0].final_text == project.corrections[0].source_text


def test_progress_callback_receives_real_pipeline_stages(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(source, "1. Remedy\nSource content with enough native text.")
    _text_pdf(reference, "1. Remedy\nReference content with enough native text.")
    events = []
    ProjectPipeline(tmp_path / "cache").analyze(
        source,
        reference,
        progress=lambda stage, current, total: events.append((stage, current, total)),
    )
    assert ("source_extraction", 1, 1) in events
    assert ("reference_extraction", 1, 1) in events
    assert any(stage == "section_matching" for stage, _, _ in events)


def test_identical_build_reuses_verified_artifacts(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(source, "1. Remedy\nIdentical source content with enough native text.")
    _text_pdf(reference, "1. Remedy\nIdentical source content with enough native text.")
    pipeline = ProjectPipeline(tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    first = pipeline.build(project, tmp_path / "output")

    monkeypatch.setattr(
        "bookloom.pipeline.render_book",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("build reran")),
    )
    second = pipeline.build(project, tmp_path / "output")
    assert second.pdf == first.pdf
    assert project.performance["build_cache_hits"] == 1
    assert second.performance_report.exists()


def test_scoped_cache_clear_preserves_other_namespaces(tmp_path):
    pipeline = ProjectPipeline(tmp_path / "cache")
    pipeline.preview_cache.set("preview", {"ok": True})
    pipeline.comparison_cache.set("comparison", {"ok": True})
    removed = pipeline.clear_cache("previews")
    assert removed == 1
    assert pipeline.preview_cache.get("preview") is None
    assert pipeline.comparison_cache.get("comparison") == {"ok": True}


def test_changed_source_hash_invalidates_only_source_extraction(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(source, "1. Remedy\nOriginal source text with enough characters.")
    _text_pdf(reference, "1. Remedy\nReference text with enough characters.")
    pipeline = ProjectPipeline(tmp_path / "cache")
    pipeline.analyze(source, reference)
    source.unlink()
    _text_pdf(source, "1. Remedy\nChanged source text with enough characters.")
    changed = pipeline.analyze(source, reference)
    assert changed.performance["extraction_cache_hits"] == 1
    assert changed.performance["comparison_cache_hits"] == 0


def test_sequence_window_prevents_full_cartesian_fuzzy_search():
    source = [(1, f"source passage {index}") for index in range(100)]
    reference = [(1, f"unrelated reference passage {index}") for index in range(100)]
    metrics = {}
    match_paragraphs(source, reference, sequence_window=5, metrics=metrics)
    assert metrics["fuzzy_comparisons"] <= 100 * 7
    assert metrics["fuzzy_comparisons"] < 100 * 100


def test_comparison_ids_are_unique_and_stable(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    text = "1. First Remedy\nRepeated paragraph with enough characters.\nRepeated paragraph with enough characters."
    _text_pdf(source, text)
    _text_pdf(reference, text)
    pipeline = ProjectPipeline(tmp_path / "cache")
    first = pipeline.analyze(source, reference)
    second = pipeline.analyze(source, reference)
    first_ids = [item.id for item in first.corrections]
    assert len(first_ids) == len(set(first_ids))
    assert first_ids == [item.id for item in second.corrections]


def test_review_decision_does_not_restart_analysis(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(source, "1. Remedy\nSource text with enough native characters.")
    _text_pdf(reference, "1. Remedy\nReference text with enough native characters.")
    pipeline = ProjectPipeline(tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    monkeypatch.setattr(
        pipeline,
        "_extract",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("analysis restarted")),
    )
    project.decide(project.corrections[0].id, Decision.KEEP_SOURCE)


def test_final_build_does_not_restart_extraction(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    text = "1. Remedy\nIdentical text with enough native characters."
    _text_pdf(source, text)
    _text_pdf(reference, text)
    pipeline = ProjectPipeline(tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    monkeypatch.setattr(
        pipeline,
        "_extract",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("extraction restarted")),
    )
    pipeline.build(project, tmp_path / "output")


def test_preview_build_can_use_source_for_unresolved_passages(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(source, "1. Remedy\nSource wording with enough native characters.")
    _text_pdf(reference, "1. Remedy\nDifferent reference wording with enough characters.")
    pipeline = ProjectPipeline(tmp_path / "cache")
    project = pipeline.analyze(source, reference)
    assert any(item.status == ReviewStatus.PENDING for item in project.corrections)

    artifacts = pipeline.build(
        project,
        tmp_path / "preview",
        allow_unresolved_source=True,
    )

    manifest = __import__("json").loads(artifacts.manifest.read_text(encoding="utf-8"))
    assert artifacts.pdf.exists()
    assert manifest["preview_only"] is True
    assert "Source wording" in artifacts.approved_text.read_text(encoding="utf-8")


def test_exact_match_skips_independent_grammar_analysis(monkeypatch):
    monkeypatch.setattr(
        "bookloom.validation.validate_grammar",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("grammar ran")),
    )
    match = PassageMatch("same text", "same text", 1, 1, 100, MatchCategory.EXACT_MATCH)
    corrections = build_corrections([match], set())
    assert corrections[0].category == "EXACT_MATCH"


def test_reference_only_paragraph_enters_manual_review_once(tmp_path):
    source = tmp_path / "source.pdf"
    reference = tmp_path / "reference.pdf"
    _text_pdf(
        source,
        "1. Remedy\nShared paragraph with enough native characters.\n\nSource paragraph remains.",
    )
    _text_pdf(
        reference,
        "1. Remedy\nShared paragraph with enough native characters.\n\nSource paragraph remains.\n\nReference-only important sentence.",
    )

    project = ProjectPipeline(tmp_path / "cache").analyze(source, reference)
    missing = [
        item for item in project.corrections if item.category == "POSSIBLE_MISSING_CONTENT"
    ]

    assert len(missing) == 1
    assert missing[0].status == ReviewStatus.PENDING
    assert missing[0].source_text == ""
    assert missing[0].reference_text == "Reference-only important sentence."

