from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
import time

import pymupdf

from .assets import classify_source_image, prepend_protected_pages
from .blockers import validate_production_readiness
from .cache import DiskCache
from .config import BookProfile, load_book_style, load_protected_terms
from .differences import Difference, DifferenceType, compare_sections
from .extraction import extract_pdf, file_sha256
from .filenames import allocate_output_path
from .matching import match_paragraphs, normalize_text
from .metadata import (
    DocumentMetadata,
    MetadataFinding,
    ReferenceMetadata,
    extract_document_metadata,
    merge_metadata,
)
from .document_analysis import DocumentProfile, analyze_document
from .integrity import (
    IntegrityReport,
    ProductionIntegrityError,
    TextUnit,
    compare_text_units,
    pdf_body_start_page_index,
    verify_rendered_pdf,
)
from .models import BookSection, BlockKind, Confidence, Correction, Decision, DocumentApproval, DocumentModel, ExtractedDocument, StructuredBlock
from .provenance import pdf_image_fingerprints, verify_image_firewall
from .rendering import render_book, weasyprint_available
from .review import apply_decision, default_decision_for, effective_decision, effective_text, finalize_text
from .sections import SectionMatch, align_sections, detect_document_sections, normalize_title
from .semantic import build_document_model, document_model_from_structured_blocks
from .structure import detect_structure
from .validation import build_corrections
from .verification import verify_pdf, write_verification_report


INTEGRITY_QA_VERSION = 13


@dataclass
class ValidationProject:
    source: ExtractedDocument
    reference: ExtractedDocument
    corrections: list[Correction]
    protected_pages: list[int] = field(default_factory=list)
    structure_override: list[StructuredBlock] | None = None
    source_sections: list[BookSection] = field(default_factory=list)
    reference_sections: list[BookSection] = field(default_factory=list)
    source_front_matter: list[BookSection] = field(default_factory=list)
    reference_front_matter: list[BookSection] = field(default_factory=list)
    section_matches: list[SectionMatch] = field(default_factory=list)
    differences: list[Difference] = field(default_factory=list)
    source_image_fingerprints: set[str] = field(default_factory=set)
    reference_image_fingerprints: set[str] = field(default_factory=set)
    performance: dict = field(default_factory=dict)
    reference_metadata: ReferenceMetadata = field(default_factory=ReferenceMetadata)
    source_metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    metadata_findings: tuple[MetadataFinding, ...] = ()
    document_model: DocumentModel | None = None
    document_profile: DocumentProfile | None = None
    job_id: str | None = None
    source_upload_name: str | None = None
    reference_upload_name: str | None = None
    approval: DocumentApproval | None = None

    def decide(self, correction_id: str, decision: Decision, manual_text: str | None = None) -> None:
        for index, correction in enumerate(self.corrections):
            if correction.id == correction_id:
                self.corrections[index] = apply_decision(
                    correction, decision, manual_text=manual_text
                )
                return
        raise KeyError(f"Unknown correction id: {correction_id}")


@dataclass(slots=True)
class BuildArtifacts:
    pdf: Path
    validation_report: Path
    corrections: Path
    approved_text: Path
    approved_text_json: Path
    reference_text_json: Path
    source_structure_json: Path
    manifest: Path
    verification_report: Path
    performance_report: Path


def canonical_text_units(
    project: ValidationProject,
    section_numbers: set[int] | None,
) -> list[TextUnit]:
    """Build ordered production units exclusively from approved source-derived text."""
    corrections_by_section: dict[int | None, list[Correction]] = {}
    for correction in project.corrections:
        corrections_by_section.setdefault(correction.source_section, []).append(correction)

    units: list[TextUnit] = []
    order = 0
    if project.source_sections:
        for section in project.source_sections:
            if section_numbers is not None and section.number not in section_numbers:
                continue
            chapter_id = str(section.number) if section.number is not None else "front-matter"
            items = corrections_by_section.get(section.number, [])
            if items:
                entries = [
                    (
                        item.id,
                        effective_text(item),
                        item.source_text,
                        item.source_page,
                    )
                    for item in items
                ]
            else:
                entries = [
                    (
                        f"section:{chapter_id}:paragraph:{index}",
                        paragraph,
                        paragraph,
                        section.page_start,
                    )
                    for index, paragraph in enumerate(section.paragraphs)
                ]
            for identity, text, original_text, source_page in entries:
                if not text or not text.strip():
                    continue
                units.append(
                    TextUnit(
                        id=identity,
                        chapter_id=chapter_id,
                        chapter_title=section.title,
                        order=order,
                        text=text,
                        source_page=source_page,
                        original_text=original_text,
                    )
                )
                order += 1
        return units

    for correction in project.corrections:
        if section_numbers is not None and correction.source_section not in section_numbers:
            continue
        text = effective_text(correction)
        if not text or not text.strip():
            continue
        chapter_id = (
            str(correction.source_section)
            if correction.source_section is not None
            else "book"
        )
        units.append(
            TextUnit(
                id=correction.id,
                chapter_id=chapter_id,
                chapter_title="Book",
                order=order,
                text=text,
                source_page=correction.source_page,
                original_text=correction.source_text,
            )
        )
        order += 1
    return units


def _canonical_blocks(
    project: ValidationProject,
    canonical_units: list[TextUnit],
    profile: BookProfile | None,
    section_numbers: set[int] | None,
) -> list[StructuredBlock]:
    if not project.source_sections:
        blocks = detect_structure("\n\n".join(unit.text for unit in canonical_units))
        if len(blocks) == len(canonical_units):
            result = [
                replace(
                    block,
                    text=unit.text,
                    source_id=unit.id,
                    chapter_id=unit.chapter_id,
                )
                for block, unit in zip(blocks, canonical_units)
            ]
        else:
            result = [
                StructuredBlock(
                    BlockKind.BODY,
                    unit.text,
                    source_id=unit.id,
                    chapter_id=unit.chapter_id,
                )
                for unit in canonical_units
            ]
        return result

    title = project.document_profile.title if project.document_profile else profile.title if profile else project.source.path.stem
    blocks = [StructuredBlock(BlockKind.BOOK_TITLE, title)]
    units_by_chapter: dict[str, list[TextUnit]] = {}
    for unit in canonical_units:
        units_by_chapter.setdefault(unit.chapter_id, []).append(unit)
    for section in project.source_sections:
        if section_numbers is not None and section.number not in section_numbers:
            continue
        chapter_id = str(section.number) if section.number is not None else "front-matter"
        number = f"{section.number:02d}" if section.number is not None else ""
        semantic = project.document_profile is not None
        heading_kind = BlockKind(section.kind) if semantic else BlockKind.REMEDY
        if section.title:
            blocks.append(
            StructuredBlock(
                heading_kind,
                section.title if semantic else f"{number}\n{section.title}",
                level=section.level if semantic else 2,
                chapter_id=chapter_id,
                confidence=section.confidence,
                start_new_page=section.start_new_page,
                include_in_toc=section.include_in_toc,
                page_number=section.page_start,
            )
        )
        blocks.extend(
            StructuredBlock(
                BlockKind.BODY,
                unit.text,
                source_id=unit.id,
                chapter_id=unit.chapter_id,
            )
            for unit in units_by_chapter.get(chapter_id, [])
        )
    if project.document_profile:
        for block in blocks:
            if block.kind == BlockKind.BODY:
                table = next((table for table in project.document_profile.tables if normalize_text(table["text"]) == normalize_text(block.text)), None)
                if table:
                    block.kind = BlockKind.TABLE
                    block.table_rows = table["rows"]
                elif re.match(r"^[-*•]\s", block.text):
                    block.kind = BlockKind.BULLET_LIST
    return blocks


def _renderer_content_indices(
    project: ValidationProject,
    blocks: list[StructuredBlock],
) -> list[int]:
    generated = {BlockKind.IMAGE, BlockKind.REFERENCE_INFO}
    if project.source_sections:
        generated |= {BlockKind.BOOK_TITLE, BlockKind.REMEDY, BlockKind.CHAPTER, BlockKind.MAJOR_SECTION, BlockKind.SECTION, BlockKind.SUBSECTION, BlockKind.NUMBERED_ITEM}
    return [index for index, block in enumerate(blocks) if block.kind not in generated]


def synchronize_renderer_blocks(
    project: ValidationProject,
    canonical_units: list[TextUnit],
    profile: BookProfile | None,
    section_numbers: set[int] | None,
) -> tuple[list[StructuredBlock], bool]:
    """Repair stale renderer wording from canonical units before QA/rendering."""
    raw_defaults = _canonical_blocks(project, canonical_units, profile, section_numbers)
    project.document_model = document_model_from_structured_blocks(
        project.source.sha256,
        raw_defaults,
        page_types=project.document_model.page_types if project.document_model else {},
        metadata=project.metadata,
        language=project.document_profile.language if project.document_profile else "english",
    )
    defaults = project.document_model.to_structured_blocks()
    if project.structure_override is None:
        return defaults, False

    blocks = project.structure_override
    content_indices = _renderer_content_indices(project, blocks)
    if len(content_indices) != len(canonical_units):
        project.structure_override = defaults
        return defaults, True

    synchronized = list(blocks)
    changed = False
    for block_index, unit in zip(content_indices, canonical_units):
        block = synchronized[block_index]
        if (
            normalize_text(block.text) != normalize_text(unit.text)
            or getattr(block, "source_id", None) != unit.id
            or getattr(block, "chapter_id", None) != unit.chapter_id
        ):
            synchronized[block_index] = StructuredBlock(
                kind=block.kind,
                text=unit.text,
                level=block.level,
                page_number=block.page_number,
                image_path=block.image_path,
                source_id=unit.id,
                chapter_id=unit.chapter_id,
            )
            changed = True
    if changed:
        project.structure_override = synchronized
        return synchronized, True
    return blocks, False


def proposed_structure(
    project: ValidationProject,
    profile: BookProfile | None = None,
    section_numbers: set[int] | None = None,
) -> list[StructuredBlock]:
    """Return the semantic renderer structure shown in the editable UI."""
    return _canonical_blocks(
        project,
        canonical_text_units(project, section_numbers),
        profile,
        section_numbers,
    )


def renderer_text_units(
    project: ValidationProject,
    blocks: list[StructuredBlock],
    canonical_units: list[TextUnit],
) -> list[TextUnit]:
    expected_by_id = {unit.id: unit for unit in canonical_units}
    result: list[TextUnit] = []
    for index in _renderer_content_indices(project, blocks):
        block = blocks[index]
        block_source_id = getattr(block, "source_id", None)
        expected = expected_by_id.get(block_source_id or "")
        result.append(
            TextUnit(
                id=block_source_id or f"renderer:{index}",
                chapter_id=getattr(block, "chapter_id", None)
                or (expected.chapter_id if expected else ""),
                chapter_title=expected.chapter_title if expected else "Renderer input",
                order=len(result),
                text=block.text,
                kind=block.kind.value,
                source_page=expected.source_page if expected else block.page_number,
                original_text=expected.original_text if expected else block.text,
            )
        )
    return result


def _integrity_payload(
    pre_render: IntegrityReport,
    post_render: IntegrityReport | None,
) -> dict:
    passed = pre_render.passed and (post_render is None or post_render.passed)
    active = post_render if post_render and not post_render.passed else pre_render
    return {
        "status": "PASSED" if passed else "FAILED",
        "passed": passed,
        "chapters_checked": pre_render.chapters_checked,
        "checked_units": pre_render.checked_units,
        "resynchronized": pre_render.resynchronized,
        "summary": active.summary,
        "issues": [issue.to_dict() for issue in active.issues],
        "pre_render": pre_render.to_dict(),
        "post_render": post_render.to_dict() if post_render else None,
    }


class ProjectPipeline:
    def __init__(self, cache_dir: str | Path = ".cache/bookloom"):
        self.cache_dir = Path(cache_dir)
        self.extraction_cache = DiskCache(
            self.cache_dir, namespace="extraction", version="extraction-v4"
        )
        self.ocr_cache = DiskCache(self.cache_dir, namespace="ocr", version="ocr-v2")
        self.comparison_cache = DiskCache(
            self.cache_dir, namespace="comparison", version="comparison-v10"
        )
        self.provenance_cache = DiskCache(
            self.cache_dir, namespace="provenance", version="provenance-v1"
        )
        self.preview_cache = DiskCache(
            self.cache_dir, namespace="previews", version="preview-v1"
        )
        self.build_cache = DiskCache(
            self.cache_dir, namespace="builds", version="build-v14"
        )
        self.cache = self.extraction_cache

    def clear_cache(
        self,
        scope: str,
        *,
        project: ValidationProject | None = None,
        tesseract_path: str | None = None,
    ) -> int:
        caches = {
            "previews": [self.preview_cache],
            "comparison": [self.comparison_cache],
            "builds": [self.build_cache],
            "all": [
                self.extraction_cache,
                self.ocr_cache,
                self.comparison_cache,
                self.provenance_cache,
                self.preview_cache,
                self.build_cache,
            ],
        }
        if scope in caches:
            return sum(cache.clear() for cache in caches[scope])
        if scope != "current_book" or project is None:
            raise ValueError(f"Unsupported cache scope: {scope}")
        removed = 0
        for document, text_only in ((project.source, False), (project.reference, True)):
            extraction_key = (
                f"extract-v2:{document.sha256}:{tesseract_path or ''}:text-only={text_only}"
            )
            removed += int(self.extraction_cache.delete(extraction_key))
            removed += int(self.provenance_cache.delete(document.sha256))
        removed += int(
            self.comparison_cache.delete(
                f"{project.source.sha256}:{project.reference.sha256}:adaptive-v10"
            )
        )
        removed += self.build_cache.clear()
        return removed

    def _extract(
        self,
        path: Path,
        tesseract_path: str | None = None,
        *,
        text_only: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> ExtractedDocument:
        key = f"extract-v2:{file_sha256(path)}:{tesseract_path or ''}:text-only={text_only}"
        cached = self.extraction_cache.get(key)
        if cached is not None:
            cached.path = path
            cached.metrics = dict(cached.metrics)
            for metric in (
                "pdf_open_seconds",
                "native_extraction_seconds",
                "page_classification_seconds",
                "image_extraction_seconds",
                "ocr_render_seconds",
                "ocr_seconds",
                "total_extraction_seconds",
            ):
                cached.metrics[metric] = 0.0
            cached.metrics["extraction_cache_hit"] = 1
            if progress:
                progress(cached.page_count, cached.page_count)
            return cached
        result = extract_pdf(
            path,
            tesseract_path=tesseract_path,
            text_only=text_only,
            ocr_cache=self.ocr_cache,
            progress=progress,
        )
        result.metrics["extraction_cache_hit"] = 0
        self.extraction_cache.set(key, result)
        return result

    def analyze(
        self,
        source_pdf: str | Path,
        reference_pdf: str | Path,
        *,
        tesseract_path: str | None = None,
        job_id: str | None = None,
        source_upload_name: str | None = None,
        reference_upload_name: str | None = None,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> ValidationProject:
        total_started = time.perf_counter()
        emit = progress or (lambda stage, current, total: None)
        source_path = Path(source_pdf)
        reference_path = Path(reference_pdf)
        stage_started = time.perf_counter()
        source = self._extract(
            source_path,
            tesseract_path,
            text_only=False,
            progress=lambda current, total: emit("source_extraction", current, total),
        )
        source_seconds = time.perf_counter() - stage_started
        stage_started = time.perf_counter()
        reference = self._extract(
            reference_path,
            tesseract_path,
            text_only=True,
            progress=lambda current, total: emit("reference_extraction", current, total),
        )
        reference_seconds = time.perf_counter() - stage_started
        emit("source_ocr_required", int(source.metrics.get("ocr_pages", 0)), source.page_count)
        emit(
            "reference_ocr_required",
            int(reference.metrics.get("ocr_pages", 0)),
            reference.page_count,
        )

        source_analysis = analyze_document(source)
        reference_analysis = analyze_document(reference)
        emit("document_analysis", len(source_analysis.sections), len(source_analysis.sections))
        comparison_key = f"{source.sha256}:{reference.sha256}:adaptive-v10"
        cached_comparison = self.comparison_cache.get(comparison_key)
        comparison_cache_hit = int(cached_comparison is not None)
        match_metrics: dict[str, int] = {}
        if cached_comparison is not None:
            source_sections = cached_comparison["source_sections"]
            reference_sections = cached_comparison["reference_sections"]
            source_front_matter = cached_comparison["source_front_matter"]
            reference_front_matter = cached_comparison["reference_front_matter"]
            section_matches = cached_comparison["section_matches"]
            corrections = cached_comparison["corrections"]
            differences = cached_comparison["differences"]
            match_metrics = cached_comparison["match_metrics"]
            emit("section_matching", len(section_matches), len(source_sections))
            source_structure_seconds = reference_structure_seconds = 0.0
            section_matching_seconds = passage_matching_seconds = correction_seconds = 0.0
        else:
            stage_started = time.perf_counter()
            source_sections = source_analysis.sections
            source_front_matter = []
            source_structure_seconds = time.perf_counter() - stage_started
            stage_started = time.perf_counter()
            reference_sections = reference_analysis.sections
            reference_front_matter = []
            reference_structure_seconds = time.perf_counter() - stage_started
            stage_started = time.perf_counter()
            section_matches = align_sections(source_sections, reference_sections, match_numbers=False)
            emit("section_matching", len(section_matches), len(source_sections))
            section_matching_seconds = time.perf_counter() - stage_started
            protected_terms = load_protected_terms()
            corrections = []
            differences = []
            passage_matching_seconds = 0.0
            correction_seconds = 0.0
            if source_sections:
                for match_index, section_match in enumerate(section_matches, start=1):
                    source_section = section_match.source
                    reference_section = section_match.reference
                    source_paragraphs = [(source_section.page_start, text) for text in source_section.paragraphs]
                    reference_paragraphs = (
                        [(reference_section.page_start, text) for text in reference_section.paragraphs]
                        if reference_section else []
                    )
                    stage_started = time.perf_counter()
                    passage_matches = match_paragraphs(
                        source_paragraphs, reference_paragraphs, metrics=match_metrics
                    )
                    passage_matching_seconds += time.perf_counter() - stage_started
                    stage_started = time.perf_counter()
                    section_corrections = build_corrections(passage_matches, protected_terms)
                    for correction_index, correction in enumerate(section_corrections):
                        correction.source_section = source_section.number
                        correction.reference_section = reference_section.number if reference_section else None
                        correction.id = _comparison_id(
                            correction,
                            source_section.number,
                            reference_section.number if reference_section else None,
                            correction_index,
                        )
                    corrections.extend(section_corrections)
                    if reference_section:
                        section_differences = compare_sections(source_section, reference_section)
                        differences.extend(section_differences)
                        corrections.extend(
                            _missing_content_corrections(
                                section_differences,
                                section_corrections,
                                source_section.number,
                                reference_section.number,
                            )
                        )
                    correction_seconds += time.perf_counter() - stage_started
                    emit("passage_comparison", match_index, len(section_matches))
            else:
                stage_started = time.perf_counter()
                matches = match_paragraphs(
                    source.paragraphs, reference.paragraphs, metrics=match_metrics
                )
                passage_matching_seconds += time.perf_counter() - stage_started
                stage_started = time.perf_counter()
                corrections = build_corrections(matches, protected_terms)
                correction_seconds += time.perf_counter() - stage_started
            corrections = _dedupe_corrections(corrections)
            self.comparison_cache.set(
                comparison_key,
                {
                    "source_sections": source_sections,
                    "reference_sections": reference_sections,
                    "source_front_matter": source_front_matter,
                    "reference_front_matter": reference_front_matter,
                    "section_matches": section_matches,
                    "corrections": corrections,
                    "differences": differences,
                    "match_metrics": match_metrics,
                },
            )
        stage_started = time.perf_counter()
        source_fingerprints = self._fingerprints(source_path)
        source_provenance_seconds = time.perf_counter() - stage_started
        stage_started = time.perf_counter()
        reference_fingerprints = self._fingerprints(reference_path)
        reference_provenance_seconds = time.perf_counter() - stage_started
        source_metadata = extract_document_metadata(source)
        reference_metadata = extract_document_metadata(reference)
        metadata_merge = merge_metadata(source_metadata, reference_metadata)
        emit("preparing_review", len(corrections), len(corrections))
        performance = {
            "document_analysis_version": 10,
            "source_pages": source.page_count,
            "reference_pages": reference.page_count,
            "source_extraction_seconds": source_seconds,
            "reference_extraction_seconds": reference_seconds,
            "source_pdf_open_seconds": source.metrics.get("pdf_open_seconds", 0.0),
            "reference_pdf_open_seconds": reference.metrics.get("pdf_open_seconds", 0.0),
            "source_native_extraction_seconds": source.metrics.get("native_extraction_seconds", 0.0),
            "reference_native_extraction_seconds": reference.metrics.get("native_extraction_seconds", 0.0),
            "source_page_classification_seconds": source.metrics.get("page_classification_seconds", 0.0),
            "reference_page_classification_seconds": reference.metrics.get("page_classification_seconds", 0.0),
            "source_image_extraction_seconds": source.metrics.get("image_extraction_seconds", 0.0),
            "ocr_render_seconds": source.metrics.get("ocr_render_seconds", 0.0) + reference.metrics.get("ocr_render_seconds", 0.0),
            "ocr_seconds": source.metrics.get("ocr_seconds", 0.0) + reference.metrics.get("ocr_seconds", 0.0),
            "source_structure_detection_seconds": source_structure_seconds,
            "reference_structure_detection_seconds": reference_structure_seconds,
            "section_matching_seconds": section_matching_seconds,
            "passage_matching_seconds": passage_matching_seconds,
            "matching_seconds": section_matching_seconds + passage_matching_seconds,
            "correction_analysis_seconds": correction_seconds,
            "source_provenance_seconds": source_provenance_seconds,
            "reference_provenance_seconds": reference_provenance_seconds,
            "total_seconds": time.perf_counter() - total_started,
            "source_native_pages": int(source.metrics.get("native_pages", 0)),
            "source_ocr_pages": int(source.metrics.get("ocr_pages", 0)),
            "reference_native_pages": int(reference.metrics.get("native_pages", 0)),
            "reference_ocr_pages": int(reference.metrics.get("ocr_pages", 0)),
            "ocr_cache_hits": int(source.metrics.get("ocr_cache_hits", 0)) + int(reference.metrics.get("ocr_cache_hits", 0)),
            "extraction_cache_hits": int(source.metrics.get("extraction_cache_hit", 0)) + int(reference.metrics.get("extraction_cache_hit", 0)),
            "comparison_cache_hits": comparison_cache_hit,
            "exact_matches": sum(item.category == "EXACT_MATCH" for item in corrections),
            "exact_fast_paths": match_metrics.get("exact_fast_paths", 0),
            "safe_fast_paths": match_metrics.get("safe_fast_paths", 0),
            "fuzzy_comparisons": match_metrics.get("fuzzy_comparisons", 0),
            "preview_render_seconds": 0.0,
            "preview_cache_hits": 0,
            "build_cache_hits": 0,
        }
        return ValidationProject(
            source=source,
            reference=reference,
            corrections=corrections,
            source_sections=source_sections,
            reference_sections=reference_sections,
            source_front_matter=source_front_matter,
            reference_front_matter=reference_front_matter,
            section_matches=section_matches,
            differences=differences,
            source_image_fingerprints=source_fingerprints,
            reference_image_fingerprints=reference_fingerprints,
            performance=performance,
            reference_metadata=reference_metadata,
            source_metadata=source_metadata,
            metadata=metadata_merge.metadata,
            metadata_findings=metadata_merge.findings,
            document_model=build_document_model(
                source,
                metadata=metadata_merge.metadata,
                language=source_analysis.language,
            ),
            protected_pages=source_analysis.cover_pages,
            document_profile=source_analysis,
            job_id=job_id,
            source_upload_name=source_upload_name or source_path.name,
            reference_upload_name=reference_upload_name or reference_path.name,
        )

    def _fingerprints(self, path: Path) -> set[str]:
        key = file_sha256(path)
        cached = self.provenance_cache.get(key)
        if cached is not None:
            return cached
        result = pdf_image_fingerprints(path)
        self.provenance_cache.set(key, result)
        return result

    def build(
        self,
        project: ValidationProject,
        output_dir: str | Path,
        *,
        profile: BookProfile | None = None,
        production: bool = False,
        section_numbers: set[int] | None = None,
        allow_unresolved_source: bool = False,
    ) -> BuildArtifacts:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        if production and allow_unresolved_source:
            raise ValueError("A production build cannot include unresolved source fallbacks")
        approved = (
            "\n\n".join(item.final_text or item.source_text for item in project.corrections)
            if allow_unresolved_source
            else finalize_text(project.corrections)
        )
        canonical_units = canonical_text_units(project, section_numbers)
        base_blocks, renderer_resynchronized = synchronize_renderer_blocks(
            project, canonical_units, profile, section_numbers
        )
        build_key = self._build_key(
            project,
            output,
            approved,
            profile,
            production,
            section_numbers,
            allow_unresolved_source,
        )
        cached_artifacts = self.build_cache.get(build_key)
        if cached_artifacts is not None and _artifacts_exist(cached_artifacts):
            project.performance["build_cache_hits"] = int(
                project.performance.get("build_cache_hits", 0)
            ) + 1
            cached_artifacts.performance_report.write_text(
                json.dumps(project.performance, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return cached_artifacts
        build_started = time.perf_counter()
        project.performance.setdefault("build_cache_hits", 0)
        if production:
            validate_production_readiness(
                sections=project.source_sections,
                corrections=project.corrections,
                expected_section_numbers=set(),
                protected_assets_present=True,
                reference_images_included=0,
                fonts_ok=True,
            )
        pre_render = compare_text_units(
            canonical_units,
            renderer_text_units(project, base_blocks, canonical_units),
            stage="PRE_RENDER",
        )
        pre_render.resynchronized = renderer_resynchronized
        verification_path_target = output / "verification-report.json"
        if production and not pre_render.passed:
            failure_payload = _integrity_payload(pre_render, None)
            write_verification_report(
                {"text_integrity": failure_payload}, verification_path_target
            )
            raise ProductionIntegrityError(pre_render, verification_path_target)
        blocks, image_records = self._append_images(base_blocks, project, output)
        formatted = output / "_formatted-book.pdf"
        final_pdf = allocate_output_path(
            output,
            project.source_upload_name or project.source.path.name,
            build_key,
            preview=allow_unresolved_source,
        )
        style = project.document_profile.style(load_book_style()) if project.document_profile else load_book_style()
        render_book(
            blocks,
            formatted if project.protected_pages else final_pdf,
            style=style,
            include_title_page=not project.protected_pages,
            protected_placeholder_count=len(project.protected_pages),
        )
        protected_records: list[dict] = []
        if project.protected_pages:
            protected_records = prepend_protected_pages(
                project.source.path,
                formatted,
                final_pdf,
                project.protected_pages,
                target_page_size=style.get("page_dimensions_pt", (595.28, 841.89)),
                replace_leading_pages=True,
            )
            formatted.unlink(missing_ok=True)

        prefix = profile.slug if profile else ""
        approved_name = f"{prefix}-Final-Text.md" if prefix else "final-approved-text.md"
        approved_json_name = f"{prefix}-Final-Text.json" if prefix else "final-approved-text.json"
        corrections_name = f"{prefix}-Corrections.json" if prefix else "corrections.json"
        validation_name = f"{prefix}-Validation-Report.md" if prefix else "validation-report.md"
        manifest_name = f"{prefix}-Build-Manifest.json" if prefix else "build-manifest.json"
        approved_path = output / approved_name
        approved_path.write_text(approved, encoding="utf-8")
        approved_json_path = output / approved_json_name
        approved_json_path.write_text(
            json.dumps(_approved_text_json(project), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reference_text_path = output / "reference_text.json"
        reference_text_path.write_text(
            json.dumps(_sections_json(project.reference_sections), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        source_structure_path = output / "source_structure.json"
        source_structure_path.write_text(
            json.dumps(_sections_json(project.source_sections), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        corrections_path = output / corrections_name
        corrections_path.write_text(
            json.dumps([_correction_json(item) for item in project.corrections], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        validation_path = output / validation_name
        validation_path.write_text(_validation_report(project), encoding="utf-8")

        qa_dir = output / "qa-pages"
        verification = verify_pdf(final_pdf, protected_records=protected_records, render_directory=qa_dir)
        provenance = verify_image_firewall(
            output_fingerprints=pdf_image_fingerprints(final_pdf),
            source_fingerprints=project.source_image_fingerprints,
            reference_fingerprints=project.reference_image_fingerprints,
        )
        verification["image_provenance"] = provenance
        post_render = verify_rendered_pdf(
            final_pdf,
            canonical_units,
            excluded_leading_pages=pdf_body_start_page_index(final_pdf),
        )
        verification["text_integrity"] = _integrity_payload(pre_render, post_render)
        if production and not post_render.passed:
            write_verification_report(verification, verification_path_target)
            raise ProductionIntegrityError(post_render, verification_path_target)
        if production and not verification["valid"]:
            write_verification_report(verification, verification_path_target)
            layout_reasons = []
            for key, label in (
                ("blank_pages", "blank pages"),
                ("page_size_mismatches", "inconsistent page sizes"),
                ("image_caption_issues", "image/caption separation"),
                ("overflow_pages", "page overflow"),
                ("orphan_heading_pages", "orphan headings"),
                ("toc_invalid_targets", "invalid TOC targets"),
                ("toc_page_number_mismatches", "incorrect printed TOC page numbers"),
            ):
                if verification.get(key):
                    layout_reasons.append(f"{label}: {verification[key]}")
            raise BuildBlockedError(layout_reasons or ["layout QA failed"])
        verification_path = write_verification_report(
            verification, verification_path_target
        )
        weasy_ok, weasy_error = weasyprint_available()
        manifest_data = {
            "source_pdf_sha256": project.source.sha256,
            "reference_pdf_sha256": project.reference.sha256,
            "job_id": project.job_id,
            "source_filename": project.source_upload_name or project.source.path.name,
            "reference_filename": project.reference_upload_name or project.reference.path.name,
            "output_filename": final_pdf.name,
            "output_version": _output_version(final_pdf),
            "final_text_sha256": hashlib.sha256(approved.encode("utf-8")).hexdigest(),
            "output_pdf_sha256": file_sha256(final_pdf),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "page_count": verification["page_count"],
            "font_configuration": {
                "body": style["body_font"],
                "heading": style["heading_font"],
                "embedded_fonts": verification["fonts"],
            },
            "style_version": style["version"],
            "renderer": "WeasyPrint" if weasy_ok else "PyMuPDF fallback",
            "weasyprint_diagnostic": weasy_error,
            "protected_assets": protected_records,
            "embedded_source_images": image_records,
            "reference_images_imported": provenance["reference_images_included"],
            "detected_source_sections": len(project.source_sections),
            "detected_reference_sections": len(project.reference_sections),
            "matched_sections": sum(match.reference is not None for match in project.section_matches),
            "correction_version": "2.0",
            "preview_only": allow_unresolved_source,
            "document_approval": asdict(project.approval) if project.approval else None,
            "metadata": project.metadata.to_dict(),
            "source_metadata": project.source_metadata.to_dict(),
            "reference_metadata": project.reference_metadata.to_dict(),
            "metadata_conflicts": [asdict(item) for item in project.metadata_findings],
            "document_profile": project.document_profile.to_dict() if project.document_profile else None,
        }
        if project.document_profile:
            (output / "document-analysis.json").write_text(
                json.dumps({
                    **project.document_profile.to_dict(),
                    "metadata": project.metadata.to_dict(),
                    "source_metadata": project.source_metadata.to_dict(),
                    "reference_metadata": project.reference_metadata.to_dict(),
                    "page_types": {
                        str(page): page_type.value
                        for page, page_type in (project.document_model.page_types if project.document_model else {}).items()
                    },
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_path = output / manifest_name
        manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        project.performance["build_seconds"] = time.perf_counter() - build_started
        performance_path = output / "performance-report.json"
        performance_path.write_text(
            json.dumps(project.performance, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        artifacts = BuildArtifacts(
            pdf=final_pdf,
            validation_report=validation_path,
            corrections=corrections_path,
            approved_text=approved_path,
            approved_text_json=approved_json_path,
            reference_text_json=reference_text_path,
            source_structure_json=source_structure_path,
            manifest=manifest_path,
            verification_report=verification_path,
            performance_report=performance_path,
        )
        self.build_cache.set(build_key, artifacts)
        return artifacts

    def _build_key(
        self,
        project: ValidationProject,
        output: Path,
        approved: str,
        profile: BookProfile | None,
        production: bool,
        section_numbers: set[int] | None,
        allow_unresolved_source: bool,
    ) -> str:
        structure = [
            {
                "kind": block.kind.value,
                "text": block.text,
                "level": block.level,
                "page": block.page_number,
                "image": block.image_path,
            }
            for block in (project.structure_override or [])
        ]
        payload = {
            "source": project.source.sha256,
            "reference": project.reference.sha256,
            "source_upload_name": project.source_upload_name or project.source.path.name,
            "approved_sha256": hashlib.sha256(approved.encode("utf-8")).hexdigest(),
            "protected_pages": sorted(project.protected_pages),
            "structure": structure,
            "style": project.document_profile.style(load_book_style()) if project.document_profile else load_book_style(),
            "profile": repr(profile),
            "production": production,
            "sections": sorted(section_numbers) if section_numbers is not None else None,
            "allow_unresolved_source": allow_unresolved_source,
            "output": str(output.resolve()),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _approved_blocks(
        self,
        project: ValidationProject,
        approved: str,
        profile: BookProfile | None,
        section_numbers: set[int] | None,
    ) -> list[StructuredBlock]:
        return _canonical_blocks(
            project, canonical_text_units(project, section_numbers), profile, section_numbers
        )

    def _append_images(
        self,
        base_blocks: list[StructuredBlock],
        project: ValidationProject,
        output: Path,
    ) -> tuple[list[StructuredBlock], list[dict]]:
        images_by_chapter: dict[str, list[StructuredBlock]] = {}
        unmapped_images: list[StructuredBlock] = []
        asset_dir = output / "assets"
        seen: set[str] = set()
        records: list[dict] = []
        for page in project.source.pages:
            for image in page.images:
                occurrence = (image.digest, page.page_number, image.bbox)
                if occurrence in seen:
                    continue
                seen.add(occurrence)
                classification = classify_source_image(
                    page.page_number,
                    image.bbox,
                    page.width or 0,
                    page.height or 0,
                )
                if page.page_number in project.protected_pages or (project.document_profile is None and classification.value in {
                    "DECORATIVE",
                    "PROTECTED_BRANDING",
                }):
                    continue
                association = next((a for a in project.document_profile.image_associations if a["digest"] == image.digest and a["source_page"] == page.page_number and tuple(a["bbox"] or ()) == tuple(image.bbox or ())), None) if project.document_profile else None
                if association and association["classification"] != "content_image":
                    continue
                chapter_id = association["parent_section_id"] if association else _image_chapter_id(project, page, image.bbox)
                if project.source_sections and not chapter_id:
                    # An unmatched image from title/front matter is usually a
                    # logo or decorative asset. Never attach it to the final
                    # remedy merely because it is last in document order.
                    continue
                asset_dir.mkdir(parents=True, exist_ok=True)
                path = asset_dir / f"{image.digest}.{image.extension}"
                path.write_bytes(image.data)
                records.append(
                    {
                        "source_page": page.page_number,
                        "sha256": image.digest,
                        "output_file": str(path.relative_to(output)),
                        "extension": image.extension,
                        "classification": association["classification"] if association else classification.value,
                        "association": association,
                    }
                )
                image_block = StructuredBlock(
                    BlockKind.IMAGE,
                    f"Source image - page {page.page_number}",
                    page_number=page.page_number,
                    image_path=str(path),
                    chapter_id=chapter_id,
                )
                if chapter_id:
                    images_by_chapter.setdefault(chapter_id, []).append(image_block)
                else:
                    unmapped_images.append(image_block)

        blocks: list[StructuredBlock] = []
        active_chapter: str | None = None
        for block in base_blocks:
            if block.chapter_id != active_chapter and block.chapter_id is not None:
                if active_chapter:
                    blocks.extend(images_by_chapter.pop(active_chapter, []))
                active_chapter = block.chapter_id
            blocks.append(block)
        if active_chapter:
            blocks.extend(images_by_chapter.pop(active_chapter, []))
        for chapter_id in sorted(images_by_chapter, key=lambda value: int(value) if value.isdigit() else 10**9):
            blocks.extend(images_by_chapter[chapter_id])
        blocks.extend(unmapped_images)
        return blocks, records


def _image_chapter_id(
    project: ValidationProject,
    page,
    bbox: tuple[float, float, float, float] | None,
) -> str | None:
    candidates = [
        section
        for section in project.source_sections
        if section.page_start <= page.page_number <= section.page_end
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return str(candidates[0].number) if candidates[0].number is not None else None

    image_y = ((bbox[1] + bbox[3]) / 2) if bbox else 0.0
    located: list[tuple[float, object]] = []
    for section in candidates:
        title = normalize_title(section.title)
        number_pattern = re.compile(rf"\b{section.number}\s*[.)\-:]?") if section.number else None
        for block in page.blocks:
            text = normalize_text(str(block.get("text", "")))
            if title and title in normalize_title(text) or (number_pattern and number_pattern.search(text)):
                y0 = float(block.get("bbox", (0, 0, 0, 0))[1])
                located.append((abs(y0 - image_y), section))
                break
    selected = min(located, default=(0, candidates[0]), key=lambda item: item[0])[1]
    return str(selected.number) if selected.number is not None else None


def _correction_json(item: Correction) -> dict:
    return {
        "correction_state": item.correction_state,
        "id": item.id,
        "source_text": item.source_text,
        "reference_text": item.reference_text,
        "suggestion": item.suggested_text,
        "final_approved_text": effective_text(item),
        "source_page": item.source_page,
        "reference_page": item.reference_page,
        "confidence": item.confidence.value,
        "reason": item.reason,
        "category": item.category,
        "status": item.status.value,
        "default_decision": (item.default_decision or default_decision_for(item)).value,
        "user_decision": item.user_decision.value if item.user_decision else None,
        "decision": effective_decision(item).value,
        "review_required": item.review_required,
        "source_section": item.source_section,
        "reference_section": item.reference_section,
    }


def _dedupe_corrections(items: list[Correction]) -> list[Correction]:
    """Keep the first stable occurrence of a correction within its section pair."""
    unique: dict[tuple[str, int | None, int | None], Correction] = {}
    for item in items:
        key = (item.id, item.source_section, item.reference_section)
        unique.setdefault(key, item)
    return list(unique.values())


def _missing_content_corrections(
    differences: list[Difference],
    existing: list[Correction],
    source_section: int | None,
    reference_section: int | None,
) -> list[Correction]:
    represented_reference = [
        normalize_text(item.reference_text or "") for item in existing if item.reference_text
    ]
    result: list[Correction] = []
    for difference in differences:
        if difference.type != DifferenceType.POSSIBLE_MISSING_CONTENT:
            continue
        normalized = normalize_text(difference.reference_text)
        if any(normalized and normalized in represented for represented in represented_reference):
            continue
        identity = (
            source_section,
            difference.source_page,
            reference_section,
            difference.reference_page,
            normalized,
        )
        result.append(
            Correction(
                id=hashlib.sha1(repr(identity).encode("utf-8")).hexdigest()[:16],
                source_text="",
                reference_text=difference.reference_text,
                suggested_text="",
                final_text=None,
                source_page=difference.source_page,
                reference_page=difference.reference_page,
                confidence=Confidence.LOW,
                reason=difference.reason,
                category=DifferenceType.POSSIBLE_MISSING_CONTENT.value,
                review_required=True,
                source_section=source_section,
                reference_section=reference_section,
                default_decision=Decision.KEEP_SOURCE,
            )
        )
    return result


def _comparison_id(
    correction: Correction,
    source_section: int | None,
    reference_section: int | None,
    source_block_index: int,
) -> str:
    identity = (
        source_section,
        correction.source_page,
        source_block_index,
        reference_section,
        correction.reference_page,
        normalize_for_id(correction.source_text),
        normalize_for_id(correction.reference_text or ""),
    )
    return hashlib.sha1(repr(identity).encode("utf-8")).hexdigest()[:16]


def normalize_for_id(value: str) -> str:
    return " ".join(value.split())


def _artifacts_exist(artifacts: BuildArtifacts) -> bool:
    return all(
        path.exists()
        for path in (
            artifacts.pdf,
            artifacts.validation_report,
            artifacts.corrections,
            artifacts.approved_text,
            artifacts.approved_text_json,
            artifacts.reference_text_json,
            artifacts.source_structure_json,
            artifacts.manifest,
            artifacts.verification_report,
            artifacts.performance_report,
        )
    )


def _output_version(path: Path) -> int | None:
    match = re.search(r" (\d+)\.pdf$", path.name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _approved_text_json(project: ValidationProject) -> dict:
    sections: list[dict] = []
    for section in project.source_sections:
        approved = [
            effective_text(item)
            for item in project.corrections
            if item.source_section == section.number
        ]
        sections.append(
            {
                "number": section.number,
                "title": section.title,
                "source_page_start": section.page_start,
                "source_page_end": section.page_end,
                "paragraphs": approved or section.paragraphs,
            }
        )
    return {
        "source_sha256": project.source.sha256,
        "reference_sha256": project.reference.sha256,
        "locked": all(item.status.value != "PENDING" for item in project.corrections),
        "sections": sections,
    }


def _sections_json(sections: list[BookSection]) -> list[dict]:
    return [
        {
            "number": section.number,
            "title": section.title,
            "paragraphs": section.paragraphs,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "raw_text": section.raw_text,
            "normalized_text": section.normalized_text,
        }
        for section in sections
    ]


def _validation_report(project: ValidationProject) -> str:
    exact = sum(item.category == "EXACT_MATCH" for item in project.corrections)
    safe = sum(item.category == "SAFE_MATCH" for item in project.corrections)
    needs_review = sum(item.status.value == "PENDING" for item in project.corrections)
    lines = [
        "# Validation Report",
        "",
        f"Source: {project.source.path.name}",
        f"Reference: {project.reference.path.name}",
        f"Total paragraphs: {len(project.corrections)}",
        f"Exact matches: {exact}",
        f"Safe auto-approved: {safe}",
        f"Corrections reviewed: {len(project.corrections)}",
        f"Needs manual review: {needs_review}",
        f"Source sections detected: {len(project.source_sections)}",
        f"Reference sections detected: {len(project.reference_sections)}",
        f"Sections matched: {sum(match.reference is not None for match in project.section_matches)}",
        f"Possible missing content: {sum(item.type.value == 'POSSIBLE_MISSING_CONTENT' for item in project.differences)}",
        "Reference images imported: 0",
    ]
    for item in project.corrections:
        lines.extend(
            [
                "",
                f"## Source page {item.source_page}",
                "",
                f"- Source: {item.source_text}",
                f"- Reference: {item.reference_text or '(no reliable match)'}",
                f"- Final: {effective_text(item)}",
                f"- Reason: {item.reason}",
                f"- Confidence: {item.confidence.value}",
                f"- Decision: {effective_decision(item).value}",
            ]
        )
    return "\n".join(lines) + "\n"
