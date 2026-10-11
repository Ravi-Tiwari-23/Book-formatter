from __future__ import annotations

import hashlib
import importlib
import time
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path

import streamlit as st

import bookloom.pipeline as _pipeline_module

if getattr(_pipeline_module, "INTEGRITY_QA_VERSION", 1) < 13:
    # Dataclasses and enums stored in Session State must keep one class
    # identity for the life of the process. Reload only the cache implementation
    # and its pipeline consumer; reloading models makes otherwise valid enum
    # instances impossible to pickle.
    import bookloom.cache as _cache_module
    import bookloom.integrity as _integrity_module
    import bookloom.integrity_ui as _integrity_ui_module

    importlib.reload(_cache_module)
    importlib.reload(_integrity_module)
    importlib.reload(_integrity_ui_module)
    importlib.reload(_pipeline_module)

from bookloom.blockers import BuildBlockedError
from bookloom.config import load_book_profile
from bookloom.integrity import ProductionIntegrityError
from bookloom.integrity_ui import render_integrity_failure, render_integrity_summary
from bookloom.models import (
    BlockKind,
    Confidence,
    Correction,
    Decision,
    ReviewStatus,
    StructuredBlock,
)
from bookloom.ocr import find_tesseract
from bookloom.pipeline import ProjectPipeline, ValidationProject, proposed_structure
from bookloom.preview import render_page_preview
from bookloom.rendering import weasyprint_available
from bookloom.review import finalize_text
from bookloom.structure import detect_structure
from bookloom.ui_helpers import (
    approved_text_sha256,
    correction_counts,
    current_integrity_report,
    finalization_is_current,
    invalidate_approved_state,
    paginate,
)


ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output" / "pdf"


def _save_upload(upload, role: str) -> Path:
    data = upload.getvalue()
    digest = hashlib.sha256(data).hexdigest()[:16]
    directory = WORK / "uploads" / digest
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{role}.pdf"
    if not path.exists():
        path.write_bytes(data)
    return path


def _init() -> None:
    existing_pipeline = st.session_state.get("pipeline")
    existing_build_cache = getattr(existing_pipeline, "build_cache", None)
    if existing_pipeline is None or getattr(existing_build_cache, "version", None) != "build-v13":
        st.session_state.pipeline = ProjectPipeline(WORK / "cache")
    st.session_state.setdefault("project", None)
    st.session_state.setdefault("artifacts", None)
    st.session_state.setdefault("text_finalized", False)
    st.session_state.setdefault("finalized_text_sha256", None)
    st.session_state.setdefault("integrity_report", None)
    st.session_state.setdefault("integrity_report_key", None)
    st.session_state.profile = None
    project = st.session_state.get("project")
    if project is not None and project.__class__ is not ValidationProject:
        corrections = []
        for item in project.corrections:
            values = {
                field.name: getattr(item, field.name)
                for field in fields(Correction)
                if hasattr(item, field.name)
            }
            values["confidence"] = Confidence(values["confidence"].value)
            values["status"] = ReviewStatus(values["status"].value)
            if values.get("decision") is not None:
                values["decision"] = Decision(values["decision"].value)
            corrections.append(Correction(**values))
        structure = None
        if project.structure_override is not None:
            structure = [
                StructuredBlock(
                    kind=BlockKind(block.kind.value),
                    text=block.text,
                    level=block.level,
                    page_number=block.page_number,
                    image_path=block.image_path,
                    source_id=getattr(block, "source_id", None),
                    chapter_id=getattr(block, "chapter_id", None),
                )
                for block in project.structure_override
            ]
        values = {
            field.name: getattr(project, field.name)
            for field in fields(ValidationProject)
            if hasattr(project, field.name)
        }
        values["corrections"] = corrections
        values["structure_override"] = structure
        project = ValidationProject(**values)
        st.session_state.project = project
    if project is not None and (project.document_profile is None or project.performance.get('document_analysis_version') != 10):
        counts = Counter(item.source_text for item in project.corrections)
        previous = {item.source_text: item for item in project.corrections if counts[item.source_text] == 1}
        migrated = st.session_state.pipeline.analyze(project.source.path, project.reference.path)
        for item in migrated.corrections:
            old = previous.get(item.source_text)
            if old is not None and old.decision is not None:
                migrated.decide(item.id, old.decision, old.final_text if old.decision == Decision.EDIT else None)
        project = migrated
        st.session_state.project = project
        invalidate_approved_state(st.session_state, project, clear_structure=True)
    if (
        project is not None
        and st.session_state.get("text_finalized")
        and not st.session_state.get("finalized_text_sha256")
    ):
        st.session_state.finalized_text_sha256 = approved_text_sha256(
            project.corrections
        )


def _system_status() -> None:
    tesseract = find_tesseract(st.session_state.get("tesseract_path") or None)
    weasy_ok, _ = weasyprint_available()
    with st.sidebar:
        st.subheader("System status")
        st.write("Tesseract OCR", "✅" if tesseract else "⚠️ not found")
        st.write("WeasyPrint", "✅" if weasy_ok else "⚠️ GTK/Pango missing")
        if not tesseract:
            st.caption("Text PDFs work now. Scanned PDFs require Tesseract 5 with hin+eng.")
        if not weasy_ok:
            st.caption("PDF creation uses the safe PyMuPDF fallback until GTK/Pango is installed.")
        with st.expander("Cache controls"):
            pipeline = st.session_state.pipeline
            if st.button("Clear preview cache", width="stretch"):
                st.toast(f"Removed {pipeline.clear_cache('previews')} preview cache files")
            if st.button("Clear comparison cache", width="stretch"):
                st.toast(f"Removed {pipeline.clear_cache('comparison')} comparison cache files")
            project = st.session_state.get("project")
            if st.button("Clear current book cache", disabled=project is None, width="stretch"):
                removed = pipeline.clear_cache(
                    "current_book",
                    project=project,
                    tesseract_path=st.session_state.get("tesseract_path") or None,
                )
                st.toast(f"Removed {removed} current-book cache files")
            if st.button("Clear all caches", width="stretch"):
                st.toast(f"Removed {pipeline.clear_cache('all')} cache files")


def _upload_and_analyze() -> None:
    st.header("Steps 1–3 · Upload and analyze")
    left, right = st.columns(2)
    with left:
        source_upload = st.file_uploader("Source PDF", type="pdf", key="source")
    with right:
        reference_upload = st.file_uploader("Reference book PDF", type="pdf", key="reference")
    st.text_input(
        "Optional Tesseract executable path",
        key="tesseract_path",
        placeholder=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
    if st.button("Start validation", type="primary", disabled=not (source_upload and reference_upload)):
        source_path = _save_upload(source_upload, "source")
        reference_path = _save_upload(reference_upload, "reference")
        with st.status("Extracting and comparing PDFs…", expanded=True) as status:
            progress_bar = st.progress(0.0)
            progress_text = st.empty()

            def update_progress(stage: str, current: int, total: int) -> None:
                labels = {
                    "source_extraction": "Extracting source",
                    "reference_extraction": "Extracting reference",
                    "source_ocr_required": "Source OCR pages required",
                    "reference_ocr_required": "Reference OCR pages required",
                    "section_matching": "Matching sections",
                    "passage_comparison": "Comparing passages",
                    "preparing_review": "Preparing review",
                }
                progress_text.write(f"{labels.get(stage, stage)}: {current}/{total}")
                progress_bar.progress(min(1.0, current / max(1, total)))

            project = st.session_state.pipeline.analyze(
                source_path,
                reference_path,
                tesseract_path=st.session_state.tesseract_path or None,
                progress=update_progress,
            )
            st.session_state.project = project
            invalidate_approved_state(
                st.session_state, project, clear_structure=True
            )
            status.update(label="Validation ready", state="complete")
        st.rerun()


def _summary(project) -> None:
    st.header("Step 4 · Compare")
    counts = correction_counts(project.corrections)
    values = [
        ("Source sections detected", len(project.source_sections)),
        ("Reference sections detected", len(project.reference_sections)),
        ("Sections matched", sum(match.reference is not None for match in project.section_matches)),
        ("Exact passages", counts["exact"]),
        ("Safe auto-approved", counts["safe_auto_approved"]),
        ("Spelling candidates", counts["spelling"]),
        ("Grammar candidates", counts["grammar"]),
        ("Meaningful differences", counts["meaningful"]),
        ("Needs manual review", counts["needs_manual_review"]),
    ]
    for start in range(0, len(values), 4):
        for column, (label, value) in zip(st.columns(4), values[start:start + 4]):
            column.metric(label, value)
    with st.expander("Performance diagnostics"):
        st.json(project.performance)
    with st.expander("Document analysis"):
        st.json(project.document_profile.to_dict() if project.document_profile else {})
    metadata = project.reference_metadata
    with st.expander("Reference metadata"):
        st.table(
            {
                "Field": ["Title", "Author", "DOI", "Publisher", "Edition", "ISBN"],
                "Detected value": [
                    metadata.title or "Not identified",
                    metadata.author or "Not identified in supplied reference",
                    metadata.doi or "Not available in supplied reference",
                    metadata.publisher or "Not identified",
                    metadata.edition or "Not identified",
                    metadata.isbn or "Not identified",
                ],
            }
        )


def _review(project) -> None:
    st.header("Step 5 · Review corrections")
    pending = sum(item.status == ReviewStatus.PENDING for item in project.corrections)
    st.progress((len(project.corrections) - pending) / max(1, len(project.corrections)))
    st.caption(f"{pending} passages still need a decision. No text is formatted before all decisions are locked.")
    filter_left, filter_right = st.columns(2)
    status_filter = filter_left.selectbox(
        "Status filter", ["All", *[status.value for status in ReviewStatus]], key="review-status-filter"
    )
    categories = sorted({item.category for item in project.corrections})
    category_filter = filter_right.selectbox(
        "Type filter", ["All", *categories], key="review-category-filter"
    )

    def filtered(items):
        return [
            item
            for item in items
            if (status_filter == "All" or item.status.value == status_filter)
            and (category_filter == "All" or item.category == category_filter)
        ]

    review_tab, safe_tab = st.tabs(["Needs review", "Resolved / safe"])

    def render_items(items, container, key_prefix):
        with container:
            items = filtered(items)
            if not items:
                st.info("No items in this category.")
                return
            _, total_pages = paginate(items, page_number=1, page_size=25)
            page_number = st.selectbox(
                "Review page",
                range(1, total_pages + 1),
                key=f"{key_prefix}-page",
                format_func=lambda value: f"Page {value} of {total_pages}",
            )
            visible, _ = paginate(items, page_number=page_number, page_size=25)
            st.caption(f"Showing {len(visible)} of {len(items)} passages (maximum 25 per page).")
            for index, item in enumerate(visible):
                section = f"Section {item.source_section}" if item.source_section else "Front matter"
                state = "✓ reviewed" if item.status != ReviewStatus.PENDING else item.confidence.value
                with st.expander(f"{section} · page {item.source_page} · {item.category} · {state}", expanded=index < 2 and pending > 0):
                    left, right = st.columns(2)
                    left.markdown("**Source**")
                    left.write(item.source_text)
                    right.markdown("**Reference (text only)**")
                    right.write(item.reference_text or "No reliable reference match")
                    st.markdown("**Suggestion**")
                    st.write(item.suggested_text)
                    st.caption(f"{item.reason} · confidence {item.confidence.value}")
                    preview_left, preview_right = st.columns(2)
                    source_preview_key = f"source-preview-{item.id}"
                    if preview_left.button("Load source page preview", key=f"load-{source_preview_key}"):
                        result = render_page_preview(
                            project.source.path,
                            item.source_page,
                            cache=st.session_state.pipeline.preview_cache,
                            dpi=120,
                        )
                        project.performance["preview_render_seconds"] = project.performance.get(
                            "preview_render_seconds", 0.0
                        ) + result.render_seconds
                        project.performance["preview_cache_hits"] = project.performance.get(
                            "preview_cache_hits", 0
                        ) + int(result.cache_hit)
                        st.session_state[source_preview_key] = str(result.path)
                    if source_preview_key in st.session_state:
                        preview_left.image(st.session_state[source_preview_key], caption=f"Source page {item.source_page}")
                    if item.reference_page:
                        reference_preview_key = f"reference-preview-{item.id}"
                        if preview_right.button("Load reference page preview", key=f"load-{reference_preview_key}"):
                            result = render_page_preview(
                                project.reference.path,
                                item.reference_page,
                                cache=st.session_state.pipeline.preview_cache,
                                dpi=120,
                            )
                            project.performance["preview_render_seconds"] = project.performance.get(
                                "preview_render_seconds", 0.0
                            ) + result.render_seconds
                            project.performance["preview_cache_hits"] = project.performance.get(
                                "preview_cache_hits", 0
                            ) + int(result.cache_hit)
                            st.session_state[reference_preview_key] = str(result.path)
                        if reference_preview_key in st.session_state:
                            preview_right.image(
                                st.session_state[reference_preview_key],
                                caption=f"Reference page {item.reference_page}",
                            )
                    if item.review_required:
                        st.warning("Manual review required; reference wording is not automatically trusted.")
                    options = list(Decision)
                    default = options.index(item.decision) if item.decision else 0
                    decision_value = st.selectbox(
                        "Decision",
                        options,
                        index=default,
                        key=f"decision-{item.id}",
                        format_func=lambda value: {
                            Decision.ACCEPT: "Accept suggestion",
                            Decision.REJECT: "Reject",
                            Decision.EDIT: "Edit",
                            Decision.KEEP_SOURCE: "Use Source",
                            Decision.USE_REFERENCE: "Use Reference",
                        }[value],
                    )
                    manual = st.text_area(
                        "Final wording (used only for Edit)",
                        value=item.final_text if item.decision == Decision.EDIT else item.suggested_text,
                        key=f"manual-{item.id}",
                    )
                    if st.button("Save decision", key=f"save-{item.id}"):
                        decision = decision_value
                        project.decide(item.id, decision, manual if decision == Decision.EDIT else None)
                        invalidate_approved_state(
                            st.session_state, project, clear_structure=True
                        )
                        st.rerun()

    render_items(
        [item for item in project.corrections if item.status == ReviewStatus.PENDING],
        review_tab,
        "needs-review",
    )
    render_items(
        [item for item in project.corrections if item.status != ReviewStatus.PENDING],
        safe_tab,
        "resolved",
    )


def _structure(project) -> None:
    pending = sum(item.status == ReviewStatus.PENDING for item in project.corrections)
    st.header("Steps 6–7 · Finalize text and review structure")
    if pending:
        st.info("Complete every meaningful correction decision to enable Finalize Approved Text.")
        return
    approved = finalize_text(project.corrections)
    finalized = finalization_is_current(st.session_state, project.corrections)
    st.session_state.text_finalized = finalized
    if not finalized:
        if st.button("Finalize Approved Text", type="primary"):
            st.session_state.text_finalized = True
            st.session_state.finalized_text_sha256 = approved_text_sha256(
                project.corrections
            )
            st.session_state.artifacts = None
            st.session_state.integrity_report = None
            st.session_state.integrity_report_key = None
            st.rerun()
        return
    st.success("Approved text finalized. Final book generation is enabled.")
    st.download_button("Download approved text", approved, "final-approved-text.md", "text/markdown")
    blocks = project.structure_override or proposed_structure(
        project, st.session_state.profile
    )
    rows = [
        {
            "type": block.kind.value,
            "text": block.text,
            "source_id": block.source_id,
            "chapter_id": block.chapter_id,
            "_original_index": index,
        }
        for index, block in enumerate(blocks)
    ]
    edited = st.data_editor(
        rows,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "type": st.column_config.SelectboxColumn(
                "Block type", options=[kind.value for kind in BlockKind], required=True
            ),
            "text": st.column_config.TextColumn("Approved wording", required=True, width="large"),
            "source_id": None,
            "chapter_id": None,
            "_original_index": None,
        },
        key="structure_editor",
    )
    if st.button("Lock book structure"):
        project.structure_override = [
            replace(
                blocks[int(row['_original_index'])] if row.get('_original_index') is not None else StructuredBlock(BlockKind.BODY, ''),
                kind=BlockKind(row["type"]),
                text=row["text"],
                level=_level(BlockKind(row["type"])),
                source_id=row.get("source_id"),
                chapter_id=row.get("chapter_id"),
            )
            for row in edited
            if row.get("text", "").strip()
        ]
        st.success("Structure locked. Formatting will not change the wording.")


def _level(kind: BlockKind) -> int:
    return {BlockKind.CHAPTER: 1, BlockKind.MAJOR_SECTION: 1, BlockKind.HEADING: 2,
            BlockKind.SECTION: 2, BlockKind.SUBHEADING: 3, BlockKind.SUBSECTION: 3,
            BlockKind.NUMBERED_ITEM: 3}.get(kind, 0)


def _build(project) -> None:
    st.header("Steps 8–9 · Preview and build")
    pages = list(range(1, project.source.page_count + 1))
    selected = st.multiselect(
        "Protected source pages to preserve intact at the start of the book",
        pages,
        default=project.protected_pages,
        help="Select approved opening/logo/art pages. They are fitted proportionally to the configured book size without stretching; a small centered crop may be used for full bleed.",
    )
    project.protected_pages = selected
    locked = project.structure_override is not None
    if not locked:
        st.caption("You may generate with detected structure, or lock edits in the previous section first.")
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        preview_clicked = st.button(
            "PREVIEW ONLY · Build using current source text",
            help="Development preview: unresolved passages use source wording and is never marked final.",
        )
        production_clicked = st.button(
            "Build Final Book",
            type="primary",
            disabled=not finalization_is_current(
                st.session_state, project.corrections
            )
            or bool(any(item.status == ReviewStatus.PENDING for item in project.corrections)),
        )
    if preview_clicked or production_clicked:
        build_dir = OUTPUT / hashlib.sha256(
            f"{project.source.sha256}:{project.reference.sha256}".encode()
        ).hexdigest()[:16] / ("production" if production_clicked else "test-build")
        with st.status("Building professional book PDF…", expanded=True) as status:
            try:
                st.write("Rendering TRUELOGER layout, TOC, page numbers, and bookmarks")
                artifacts = st.session_state.pipeline.build(
                    project,
                    build_dir,
                    profile=st.session_state.profile,
                    production=production_clicked,
                    section_numbers=None,
                    allow_unresolved_source=preview_clicked,
                )
                st.write("Running text, PDF, protected-page, and image-provenance QA")
                st.session_state.artifacts = artifacts
                verification = __import__("json").loads(
                    artifacts.verification_report.read_text(encoding="utf-8")
                )
                integrity = verification.get("text_integrity")
                st.session_state.integrity_report = integrity
                st.session_state.integrity_report_key = approved_text_sha256(
                    project.corrections
                )
                status.update(label="Build generated and verified", state="complete")
            except ProductionIntegrityError as error:
                status.update(label="Final build blocked", state="error")
                st.session_state.artifacts = None
                st.session_state.integrity_report = error.report.to_dict()
                st.session_state.integrity_report_key = approved_text_sha256(
                    project.corrections
                )
                action = render_integrity_failure(error)
                if action:
                    _apply_integrity_action(project, action)
                return
            except BuildBlockedError as error:
                status.update(label="Production build blocked", state="error")
                st.error(str(error))
                return
        st.rerun()

    report = current_integrity_report(
        st.session_state, approved_text_sha256(project.corrections)
    )
    if report and not report.get("passed", False):
        from bookloom.integrity import IntegrityDifferenceType, IntegrityIssue, IntegrityReport

        issues = [
            IntegrityIssue(
                canonical_id=item["canonical_id"],
                chapter_id=item.get("chapter_id", ""),
                chapter_title=item.get("chapter_title", ""),
                unit_order=item.get("unit_order", 0),
                difference_type=IntegrityDifferenceType(item["difference_type"]),
                expected_text=item.get("expected_text", ""),
                actual_text=item.get("actual_text", ""),
                expected_sha256=item.get("expected_sha256", ""),
                actual_sha256=item.get("actual_sha256", ""),
                expected_length=item.get("expected_length", 0),
                actual_length=item.get("actual_length", 0),
                difference_excerpt=item.get("difference_excerpt", ""),
                status=item.get("status", "NEEDS_REVIEW"),
            )
            for item in report.get("issues", [])
        ]
        saved_report = IntegrityReport(
            stage=report.get("stage", "POST_RENDER"),
            passed=False,
            checked_units=report.get("checked_units", 0),
            chapters_checked=report.get("chapters_checked", 0),
            issues=issues,
            resynchronized=report.get("resynchronized", False),
        )
        action = render_integrity_failure(ProductionIntegrityError(saved_report))
        if action:
            _apply_integrity_action(project, action)


def _apply_integrity_action(project, action: dict[str, str]) -> None:
    kind = action["action"]
    correction_id = action["canonical_id"]
    if kind == "USE_APPROVED":
        project.structure_override = None
        st.session_state.integrity_report = None
        st.session_state.integrity_report_key = None
        st.session_state.artifacts = None
        st.rerun()
    if kind in {"KEEP_RENDERER", "EDIT"}:
        project.decide(correction_id, Decision.EDIT, action["text"])
        invalidate_approved_state(st.session_state, project, clear_structure=True)
        st.rerun()


def _downloads(artifacts) -> None:
    manifest = __import__("json").loads(artifacts.manifest.read_text(encoding="utf-8"))
    preview_only = bool(manifest.get("preview_only"))
    st.header("Preview download" if preview_only else "Step 10 · Download final artifacts")
    if preview_only:
        st.warning("PREVIEW ONLY — unresolved passages use current source text. This is not a final book.")
    verification = __import__("json").loads(
        artifacts.verification_report.read_text(encoding="utf-8")
    )
    if verification.get("text_integrity"):
        render_integrity_summary(verification["text_integrity"])
    st.pdf(
        artifacts.pdf,
        height=720,
        alt="Preview of the generated professional book PDF",
    )
    for label, path, mime in [
        ("Preview PDF" if preview_only else "Final PDF", artifacts.pdf, "application/pdf"),
        ("Validation report", artifacts.validation_report, "text/markdown"),
        ("Corrections JSON", artifacts.corrections, "application/json"),
        ("Final approved text", artifacts.approved_text, "text/markdown"),
        ("Final approved text JSON", artifacts.approved_text_json, "application/json"),
        ("Reference text JSON", artifacts.reference_text_json, "application/json"),
        ("Source structure JSON", artifacts.source_structure_json, "application/json"),
        ("Build manifest", artifacts.manifest, "application/json"),
        ("Verification report", artifacts.verification_report, "application/json"),
        ("Performance report", artifacts.performance_report, "application/json"),
    ]:
        st.download_button(f"Download {label}", path.read_bytes(), path.name, mime)


def main() -> None:
    rerun_started = time.perf_counter()
    st.set_page_config(
        page_title="Bookloom",
        page_icon=":material/auto_stories:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init()
    st.title("Bookloom")
    st.caption("Source-faithful PDF review and professional book production")
    _system_status()
    _upload_and_analyze()
    project = st.session_state.project
    if project:
        _summary(project)
        _review(project)
        _structure(project)
        _build(project)
    if st.session_state.artifacts:
        _downloads(st.session_state.artifacts)
    st.session_state["streamlit_rerun_count"] = st.session_state.get(
        "streamlit_rerun_count", 0
    ) + 1
    st.session_state["streamlit_last_rerun_seconds"] = time.perf_counter() - rerun_started
    if project:
        project.performance["streamlit_rerun_count"] = st.session_state["streamlit_rerun_count"]
        project.performance["streamlit_last_rerun_seconds"] = st.session_state[
            "streamlit_last_rerun_seconds"
        ]


if __name__ == "__main__":
    main()
