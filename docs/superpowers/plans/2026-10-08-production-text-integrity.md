# Production Text Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the false-positive production text check with structured canonical-to-renderer and post-render verification, automatic stale-input synchronization, actionable reports, and a traceback-free Streamlit review experience.

**Architecture:** Approved corrections become ordered canonical text units with stable IDs. The pipeline synchronizes renderer body blocks from those units before rendering, then verifies the final PDF after removing identified generated furniture; both gates produce one structured report and raise `ProductionIntegrityError` only for genuine unresolved differences. Streamlit stores a finalized-text hash, catches that domain error, and renders native review/download controls.

**Tech Stack:** Python 3.11+, dataclasses/enums, PyMuPDF, Streamlit 1.57+, pytest 8, `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-10-08-production-text-integrity-design.md`

## Global Constraints

- Expected production wording is canonical approved source-derived text, never raw OCR or direct reference-PDF text.
- Formatting-only differences must pass; missing, duplicated, unexpected, modified, or reordered content must fail.
- Generated page furniture, TOC text, numbering labels, image captions, watermarks, metadata, and protected/decorative pages are excluded from body comparison.
- Renderer synchronization happens before a production failure; no text is silently adopted into canonical content.
- The report is persisted before `ProductionIntegrityError` is raised, and normal UI never displays its traceback.
- Do not add dependencies or bypass production QA.
- This directory is not a Git repository, so commit steps are replaced by explicit green-suite checkpoints.

## Review Focus

- A body line containing a genuine standalone number must retain that number; only position-identified page furniture is removed (Task 2 test).
- Repeated legitimate short phrases inside different paragraphs must not be classified as duplicated units (Task 1 test).
- Empty approved paragraphs and image-only blocks must not create phantom integrity units (Task 1 test).
- A renderer override that splits or merges canonical paragraphs must regenerate safe default blocks rather than guessing (Task 3 test).
- A report from an earlier approved-text hash must not remain visible after review changes (Task 4 test).

---

### Task 1: Canonical units, semantic normalization, and structured comparison

**Files:**
- Create: `src/truelogger/integrity.py`
- Modify: `src/truelogger/models.py`
- Replace/extend: `tests/test_text_qa.py`

**Interfaces:**
- Produces `IntegrityDifferenceType`, `TextUnit`, `IntegrityIssue`, `IntegrityReport`, and `ProductionIntegrityError`.
- Produces `normalize_integrity_text(value: str) -> str` and `compare_text_units(expected: list[TextUnit], actual: list[TextUnit], *, stage: str) -> IntegrityReport`.
- Adds `source_id: str | None = None` and `chapter_id: str | None = None` to `StructuredBlock` without breaking existing constructors.

- [ ] **Step 1: Write failing unit tests for normalization and exact multilingual equivalence**

Add focused tests proving exact, whitespace, wrapping, NFC/NFD, smart-quote, non-breaking-space, soft-hyphen, zero-width, approved spelling, Hindi, English, and mixed Hindi/English behavior. Assert a real word replacement remains unequal.

- [ ] **Step 2: Run the normalization tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_text_qa.py -v --basetemp tmp\pytest-integrity-red`

Expected: import/behavior failures because `truelogger.integrity` does not exist.

- [ ] **Step 3: Implement the domain types and `normalize_integrity_text`**

Use NFC, quote translation, removal of soft/zero-width characters, non-breaking-space conversion, whitespace collapse, and layout-hyphen normalization. Preserve wording, case, ordinary punctuation, and meaningful hyphens.

- [ ] **Step 4: Run normalization tests and verify GREEN**

Run the command from Step 2; expected: the normalization group passes.

- [ ] **Step 5: Write failing structured comparison tests**

Add tests for exact/order-preserving success and each classification: `MISSING`, `DUPLICATED`, `UNEXPECTED`, `MODIFIED`, `ORDER_CHANGED`. Include stable IDs, chapter labels, hashes/lengths, repeated phrases in distinct units, and omission of empty/image-only units.

- [ ] **Step 6: Run structured comparison tests and verify RED**

Expected: failures because `compare_text_units` is not implemented.

- [ ] **Step 7: Implement `compare_text_units` and report serialization**

Match by stable unit ID first, use sequence/order checks second, and emit complete issue records without logging paths. `ProductionIntegrityError` stores the report plus optional report path and has a concise non-traceback user message.

- [ ] **Step 8: Run `tests/test_text_qa.py` and verify GREEN**

Expected: all Task 1 tests pass.

### Task 2: Page-aware post-render verification

**Files:**
- Modify: `src/truelogger/integrity.py`
- Modify: `src/truelogger/verification.py`
- Modify: `tests/test_text_qa.py`

**Interfaces:**
- Produces `extract_pdf_body_text(pdf_path: str | Path, *, excluded_leading_pages: int = 0, excluded_texts: Collection[str] = ()) -> str`.
- Produces `verify_rendered_pdf(pdf_path: str | Path, expected_units: list[TextUnit], *, excluded_leading_pages: int = 0, excluded_texts: Collection[str] = ()) -> IntegrityReport`.
- Keeps `verify_text_integrity(...) -> dict[str, Any]` as a backward-compatible wrapper while returning the richer fields.

- [ ] **Step 1: Write failing PDF tests for generated furniture and real corruption**

Create small PyMuPDF fixtures proving page numbers, TOC pages, repeated running headers/footers, line wrapping, and renderer hyphen spacing pass. Prove a genuine body number is preserved, while missing, duplicated, truncated, modified, and reordered body units fail.

- [ ] **Step 2: Run the PDF tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_text_qa.py -v --basetemp tmp\pytest-pdf-red`

Expected: the existing substring verifier reports formatting artifacts or lacks the new API.

- [ ] **Step 3: Implement page-aware extraction and post-render alignment**

Inspect text blocks with coordinates; exclude explicitly leading decorative pages, numeric footer blocks at the page edge, repeated edge-position header/footer blocks, and explicitly supplied generated labels. Compare expected units in order against the cleaned semantic stream and create concise nearest-match excerpts for failures.

- [ ] **Step 4: Run PDF QA tests and verify GREEN**

Run the command from Step 2; expected: all furniture and corruption cases pass.

- [ ] **Step 5: Run the current production artifact through the new verifier**

Run a read-only script against `output/pdf/a753c073c62add4c/production/33-Quick-Vastu-Remedies-TRUELOGER-Final.pdf` and its approved-text JSON. Expected: 77 approved paragraphs verified with no false missing issues from page numbers or hyphen wrapping.

### Task 3: Pipeline canonicalization, synchronization, and persisted failure reports

**Files:**
- Modify: `src/truelogger/pipeline.py`
- Modify: `src/truelogger/rendering.py`
- Create: `tests/test_production_integrity.py`

**Interfaces:**
- Produces `canonical_text_units(project: ValidationProject, section_numbers: set[int] | None) -> list[TextUnit]`.
- Produces `synchronize_renderer_blocks(project: ValidationProject, canonical_units: list[TextUnit], profile: BookProfile | None, section_numbers: set[int] | None) -> tuple[list[StructuredBlock], bool]`.
- `ProjectPipeline.build(...)` writes `verification-report.json` before raising `ProductionIntegrityError` and records synchronization plus pre/post-render reports.

- [ ] **Step 1: Write failing pipeline tests for canonical provenance and stale renderer state**

Prove approved edits, not raw OCR/reference text, create canonical units. Prove stale same-shape override wording is replaced while block formatting survives; a split/merged or unidentified old override regenerates safe default blocks; exact current overrides remain unchanged.

- [ ] **Step 2: Run focused pipeline tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_production_integrity.py -v --basetemp tmp\pytest-pipeline-red`

Expected: missing canonical/synchronization APIs.

- [ ] **Step 3: Implement canonical assembly and automatic synchronization**

Attach correction IDs and section metadata to renderer body blocks. Synchronize body/list/verse/quote units only; exclude generated headings, remedy labels, book title, TOC, images, and captions. Preserve structure metadata when one-to-one mapping is safe; otherwise regenerate canonical default blocks.

- [ ] **Step 4: Run synchronization tests and verify GREEN**

Expected: all synchronization tests pass.

- [ ] **Step 5: Write failing production-build tests for reports and domain errors**

Assert pre-render and post-render summaries are present on success. Force genuine corruption and assert `verification-report.json` exists before `ProductionIntegrityError`, with chapter/unit/type/hash/length details and no sensitive path in the exception string.

- [ ] **Step 6: Run the new build tests and verify RED**

Expected: current generic `ValueError` and late report write fail the assertions.

- [ ] **Step 7: Integrate both gates into `ProjectPipeline.build`**

Build canonical units before the cache lookup, synchronize renderer blocks, include synchronized structure in the build key, run pre-render QA, render, run page-aware post-render QA, write the report, and raise the domain error only after persistence. Cache only successful artifacts.

- [ ] **Step 8: Run pipeline and legacy suites and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_production_integrity.py tests\test_pipeline.py tests\test_phase2_pipeline.py -v --basetemp tmp\pytest-pipeline-green`

Expected: all selected tests pass.

### Task 4: Streamlit finalized-hash state and integrity review UI

**Files:**
- Create: `src/truelogger/integrity_ui.py`
- Modify: `src/truelogger/ui_helpers.py`
- Modify: `app.py`
- Create: `tests/test_integrity_ui.py`

**Interfaces:**
- Produces `render_integrity_summary(report: IntegrityReport) -> None` and `render_integrity_failure(error: ProductionIntegrityError) -> None` using native Streamlit elements.
- Produces `approved_text_sha256(corrections: list[Correction]) -> str` and `invalidate_approved_state(state: MutableMapping[str, Any], project: ValidationProject, *, clear_structure: bool) -> None` in `ui_helpers.py`.
- Session state keys: `finalized_text_sha256`, `integrity_report`, and `integrity_report_key`.

- [ ] **Step 1: Write failing AppTest coverage for the failure panel**

Use `AppTest.from_string` to call `render_integrity_failure` with two issues. Assert `FINAL BUILD BLOCKED`, the issue count and chapter/type summaries, expected/renderer detail expanders, and a QA-report download button are present, with no uncaught exception or traceback text.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_integrity_ui.py -v --basetemp tmp\pytest-ui-red`

Expected: import failure because `integrity_ui` does not exist.

- [ ] **Step 3: Implement the native Streamlit summary/failure renderer**

Use `st.error`, bordered containers, `st.expander`, responsive horizontal button groups, and `st.download_button`; do not use custom HTML/CSS. Keep full developer details out of normal text.

- [ ] **Step 4: Run UI tests and verify GREEN**

Expected: AppTest reports no exception and all UI assertions pass.

- [ ] **Step 5: Write failing state invalidation tests**

Prove the build button is valid only when `finalized_text_sha256` equals the current approved hash. Prove saving a decision or adopting/editing renderer wording clears finalized hash, artifacts, integrity report state, and stale structure. Prove an older report key is ignored after wording changes.

- [ ] **Step 6: Run state tests and verify RED**

Expected: current boolean-only `text_finalized` behavior fails.

- [ ] **Step 7: Integrate hash finalization, error catch, and review actions in `app.py`**

Catch `ProductionIntegrityError` before the generic Streamlit exception boundary, keep the build status panel concise, store the report by content hash, and render review/download controls. “Use approved text” clears stale renderer structure; “Keep current renderer text” and “Edit” explicitly update the mapped correction, invalidate finalization, and require approval/finalization again; “Mark resolved” enables only when the unit compares equal.

- [ ] **Step 8: Run UI/state tests and verify GREEN**

Run the commands from Steps 2 and 6; expected: all pass with no uncaught exception.

### Task 5: Full regression and same-book production build

**Files:**
- Modify if needed based on evidence only: files changed in Tasks 1–4
- Verify: current `work/uploads`, `output/pdf/a753c073c62add4c`, and complete test suite

**Interfaces:**
- Consumes all prior task interfaces.
- Produces verified production artifacts and the final implementation report.

- [ ] **Step 1: Run the full automated suite**

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-final`

Expected: all existing and new tests pass with no warnings or errors.

- [ ] **Step 2: Reconstruct the current project from the matching uploaded source/reference PDFs and saved approved decisions**

Match inputs by hashes, reapply decisions from the saved corrections JSON, restore only the selected protected source pages recorded by the existing artifact, and build to a new verification directory so the old failure evidence remains intact.

- [ ] **Step 3: Generate the final production PDF with the same test book**

Expected: build completes, final PDF and `verification-report.json` exist, both integrity stages pass, and the report records zero missing/duplicated/unexpected/modified/order issues.

- [ ] **Step 4: Inspect the final report and PDF text evidence**

Confirm 33 expected sections, the canonical paragraph count, protected pages, chapter order, and the formerly false-positive page-boundary paragraphs. Record exact output paths and counts.

- [ ] **Step 5: Check for a running Streamlit app**

Use PowerShell `Get-NetTCPConnection` for ports 8500–8599 and identify the owning Python process. If running, rely on hot reload and tell the user to refresh; do not launch another server without asking.

- [ ] **Step 6: Run verification-before-completion and report evidence**

Report exact root cause, failed rule, files changed, stale-state contribution, synchronization behavior, tests added, full-suite result, and same-book production-build result. Do not claim completion if the final book build did not succeed.
