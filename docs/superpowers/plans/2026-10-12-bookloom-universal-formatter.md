# Bookloom Universal Formatter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the application to Bookloom and deliver a polished one-approval Streamlit workflow that reliably converts heterogeneous source PDFs into standardized, image-aware, A4 Trueloger Reading Edition books.

**Architecture:** Preserve the existing extraction, comparison, correction, provenance, and integrity systems while introducing an isolated job model and a canonical semantic document model between content processing and rendering. The Bookloom UI operates on job/review services, and the production renderer consumes only the approved semantic model through a centralized theme.

**Tech Stack:** Python 3.11+, Streamlit 1.57+, PyMuPDF, Tesseract/pytesseract, WeasyPrint, pypdf, Pillow, RapidFuzz, pytest, Streamlit AppTest.

**Spec:** `docs/superpowers/specs/2026-10-08-universal-book-formatter-one-approval-design.md`

## Global Constraints

- Bookloom is the software/project/package identity; Trueloger is company/publisher branding only.
- Preserve the existing technology stack, upload flow, OCR, comparison, image extraction, provenance, caches, and integrity checks.
- Source content is authoritative; uncertain reference content defaults to keeping source.
- Every production page is A4; generated collection cover is the default.
- Chapter headings begin 22–28 mm from the physical top; compact items do not force page breaks.
- Production uses WeasyPrint; the PyMuPDF renderer is a labeled degraded preview only.
- Final filenames preserve the source base and add non-overwriting numeric versions.
- New behavior follows red-green-refactor and every milestone ends in a focused Git commit.
- Never commit `.venv/`, `work/`, `output/`, `tmp/`, caches, or secrets.

## Review Focus

- A repeated watermark or logo embedded on many pages must not become dozens of content figures; Task 5 adds a recurrence fixture and assertion.
- A low-confidence reference conflict involving a number, author, or DOI must preserve source unless explicitly overridden; Task 3 pins this policy.
- A scanned Hindi page with a full-page raster must be OCR input, not a content image; Tasks 4 and 5 cover the boundary.
- A long source name containing spaces, Unicode, and Windows-invalid characters must produce a safe recognizable numbered filename without overwrite; Task 2 covers it.
- A source with uppercase fragments and numbered prose must not produce a polluted multi-page TOC; Tasks 6 and 7 cover hierarchy validation and final pagination.

---

### Task 1: Repository Baseline and Bookloom Identity

**Files:**
- Modify: `pyproject.toml`
- Rename: `src/truelogger/` -> `src/bookloom/`
- Modify: `app.py`
- Modify: `tests/*.py`
- Modify: `run.ps1`
- Modify: `setup.ps1`
- Create: `.streamlit/config.toml`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: current `truelogger` package and the full green baseline.
- Produces: importable `bookloom` package, Bookloom UI identity, and a Git history suitable for milestone commits.

- [ ] **Step 1: Verify and record the pre-change baseline**

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-baseline`

Expected: 102 or more tests pass with zero failures.

- [ ] **Step 2: Initialize Git and create the baseline commit**

Run: `git init`, verify `git status --short` excludes ignored runtime artifacts, then commit the existing source as `chore: capture Bookloom migration baseline`.

- [ ] **Step 3: Write identity tests that fail before the rename**

Add assertions that `import bookloom` succeeds, project metadata names Bookloom, the Streamlit title is Bookloom, and README distinguishes Bookloom software from Trueloger publisher branding.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bookloom_identity.py -v`

Expected: FAIL because the `bookloom` package and identity do not yet exist.

- [ ] **Step 4: Rename the package and application identity**

Move the source namespace to `src/bookloom`, update imports/tests/package metadata/launchers, keep a temporary compatibility import only if serialized-state migration needs it, and replace software-facing names without removing intentional publisher branding.

- [ ] **Step 5: Add the native Bookloom Streamlit theme**

Create `.streamlit/config.toml` with deep teal primary color, warm-white background, green-grey secondary background, dark accessible text, medium radii, borders, and local/system-safe typography. Remove the existing global unsafe CSS from `app.py`.

- [ ] **Step 6: Verify identity and regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bookloom_identity.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-identity`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Commit: `chore: rename application to Bookloom`

### Task 2: Isolated Jobs, Original Filenames, and Numbered Outputs

**Files:**
- Modify: `src/bookloom/models.py`
- Create: `src/bookloom/jobs.py`
- Create: `src/bookloom/filenames.py`
- Modify: `src/bookloom/pipeline.py`
- Modify: `app.py`
- Create: `tests/test_jobs.py`
- Create: `tests/test_filenames.py`

**Interfaces:**
- Consumes: `ExtractedDocument`, `ValidationProject`, current content-hash storage.
- Produces: `ProcessingJob`, `create_job(...)`, `sanitize_source_stem(...)`, and `allocate_output_path(...)`.

- [ ] **Step 1: Write failing filename and isolation tests**

Test `Complete House Vastu.pdf` -> `Complete House Vastu 1.pdf`, a changed approved build -> `Complete House Vastu 2.pdf`, cached reuse -> the existing filename, preview -> `Complete House Vastu Preview 1.pdf`, Unicode preservation, Windows-invalid character sanitation, and A/B/C jobs with no state leakage.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_filenames.py -v`

Expected: FAIL because job/original-name/version interfaces do not exist.

- [ ] **Step 2: Implement job and filename interfaces**

Define `ProcessingJob` with job identity, original names, paths, options, review/approval/artifact state, and warnings. Define `create_job(source_upload_name: str, source_path: Path, reference_upload_name: str, reference_path: Path, options: ProcessingOptions) -> ProcessingJob`. Define deterministic, collision-safe filename allocation keyed by source identity and build fingerprint.

- [ ] **Step 3: Route uploads and builds through `ProcessingJob`**

Preserve client filenames in `_save_upload`, clear document-specific Streamlit state on job changes, write chosen filename/version to manifest, and ensure cached artifacts reuse their assigned version.

- [ ] **Step 4: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_filenames.py tests/test_cache.py tests/test_pipeline.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-jobs`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit: `feat: isolate Bookloom jobs and version output names`

### Task 3: Safe Defaults and One Document Approval

**Files:**
- Modify: `src/bookloom/models.py`
- Modify: `src/bookloom/review.py`
- Modify: `src/bookloom/ui_helpers.py`
- Modify: `src/bookloom/pipeline.py`
- Modify: `app.py`
- Create: `tests/test_document_approval.py`
- Modify: `tests/test_validation_review.py`
- Modify: `tests/test_integrity_ui.py`

**Interfaces:**
- Consumes: `Correction`, `Decision`, `ReviewStatus`, `ProcessingJob`.
- Produces: `default_decision_for(finding)`, `effective_decision(finding)`, `apply_override(...)`, `approve_document(...) -> DocumentApproval`, and grouped review summaries.

- [ ] **Step 1: Write failing decision-policy tests**

Cover safe OCR/spelling/punctuation/high-confidence accept defaults; low-confidence, semantic, missing-content, conflicting-number/author/DOI keep-source defaults; override precedence; empty manual edit as the only local blocker; and untouched findings finalizing successfully.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_document_approval.py -v`

Expected: FAIL on missing default/effective approval interfaces.

- [ ] **Step 2: Implement review policy and audit model**

Extend findings with `default_decision`, `user_decision`, computed `effective_decision`, `requires_manual_action`, and friendly severity. Add immutable `DocumentApproval` with approval timestamp, policy version, finding/default/override/edit counts, and effective-text hash.

- [ ] **Step 3: Replace pending-record finalization with effective decisions**

Update canonical text and production blockers to use effective decisions. Explicit override wins, then safe default. Approval fails only for an invalid manual edit or a true extraction/build blocker.

- [ ] **Step 4: Add grouped review helpers and invalidation**

Group by semantic section/page, compute All/Needs attention/Low confidence/Changed/Reviewed views, map backend categories to sentence-case labels, and invalidate approval/artifacts when any override changes.

- [ ] **Step 5: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_document_approval.py tests/test_validation_review.py tests/test_integrity_ui.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-approval`

Expected: all tests pass.

- [ ] **Step 6: Commit**

Commit: `feat: add safe defaults and one document approval`

### Task 4: Canonical Semantic Document and Source-First Metadata

**Files:**
- Modify: `src/bookloom/models.py`
- Create: `src/bookloom/semantic.py`
- Modify: `src/bookloom/extraction.py`
- Modify: `src/bookloom/document_analysis.py`
- Modify: `src/bookloom/metadata.py`
- Modify: `src/bookloom/pipeline.py`
- Create: `tests/test_semantic_model.py`
- Modify: `tests/test_extraction.py`
- Modify: `tests/test_metadata.py`

**Interfaces:**
- Consumes: extracted pages/blocks/tables/images and approved finding text.
- Produces: `DocumentModel`, `SemanticBlock`, `DocumentMetadata`, `PageType`, `build_document_model(...)`, and `merge_metadata(...)`.

- [ ] **Step 1: Write failing semantic/page/metadata tests**

Cover native/scanned/mixed classification; stable block IDs and reading order; first-class abstract, keywords, lists, table, figure, conclusion, references; source-first metadata; reference fallback; author/DOI conflict findings; and missing DOI omission.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_semantic_model.py tests/test_extraction.py tests/test_metadata.py -v`

Expected: FAIL because canonical semantic interfaces and mixed page type are missing.

- [ ] **Step 2: Implement semantic dataclasses and adapters**

Add the model types and compatibility adapters from existing `BookSection`/`StructuredBlock` so current integrity paths remain functional during migration.

- [ ] **Step 3: Implement page classification and semantic construction**

Retain native text where reliable, identify full-page scan rasters, classify mixed pages, carry tables/assets directly, and construct ordered semantic blocks from source layout.

- [ ] **Step 4: Implement source-first metadata merge**

Extract source and reference metadata independently, normalize DOI variants, record provenance/confidence, create findings for material conflicts, and never invent missing fields.

- [ ] **Step 5: Make approved `DocumentModel` the renderer input boundary**

Update pipeline assembly so renderer blocks are generated from the approved semantic model rather than raw correction order or renderer heuristics.

- [ ] **Step 6: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_semantic_model.py tests/test_extraction.py tests/test_metadata.py tests/test_production_integrity.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-semantic`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Commit: `feat: build source-first semantic documents`

### Task 5: Document-Wide Image Intelligence

**Files:**
- Modify: `src/bookloom/models.py`
- Modify: `src/bookloom/assets.py`
- Create: `src/bookloom/image_analysis.py`
- Modify: `src/bookloom/document_analysis.py`
- Modify: `src/bookloom/pipeline.py`
- Modify: `src/bookloom/verification.py`
- Modify: `tests/test_assets.py`
- Create: `tests/test_image_analysis.py`

**Interfaces:**
- Consumes: extracted image occurrences, page geometry/text blocks, semantic blocks.
- Produces: `analyze_images(document, model) -> list[SemanticImage]` with classification, logical occurrence, insertion anchor, caption association, and confidence.

- [ ] **Step 1: Write failing recurrence and placement tests**

Create fixtures for a repeated watermark/logo, a full-page scan, two unique meaningful figures, the same meaningful digest used intentionally in different contexts, a captioned diagram, and a low-confidence large image. Assert no repeated decoration emission, scan exclusion, logical deduplication, correct before/after block anchors, and preserved aspect ratio.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_analysis.py tests/test_assets.py -v`

Expected: FAIL because document-wide classification and insertion anchors are absent.

- [ ] **Step 2: Implement document-wide visual inventory**

Compute digest/perceptual identity, recurrence/position patterns, size/coverage, transparency/entropy, text overlap, nearby caption signals, page role, and scan-raster status.

- [ ] **Step 3: Implement classification and logical occurrence rules**

Classify photo/illustration, diagram/chart, raster table/textual figure, cover art, logo, furniture, watermark/background, scan, and artifact. Deduplicate repeated decoration while preserving genuinely distinct content occurrences.

- [ ] **Step 4: Implement reading-order association**

Assign `insert_before_block_id` or `insert_after_block_id`, semantic parent, caption, source location, and confidence using neighboring blocks and column geometry.

- [ ] **Step 5: Extend image QA**

Compare expected meaningful logical occurrences with rendered figures, report missing/duplicate/misordered assets, and keep reference-image firewall checks.

- [ ] **Step 6: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_analysis.py tests/test_assets.py tests/test_adaptive_documents.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-images`

Expected: all tests pass.

- [ ] **Step 7: Commit**

Commit: `fix: classify and anchor source images reliably`

### Task 6: Reliable Heading Hierarchy and Contents Selection

**Files:**
- Modify: `src/bookloom/document_analysis.py`
- Modify: `src/bookloom/semantic.py`
- Modify: `src/bookloom/sections.py`
- Modify: `src/bookloom/structure.py`
- Create: `tests/test_heading_hierarchy.py`
- Modify: `tests/test_structure.py`
- Modify: `tests/test_adaptive_documents.py`

**Interfaces:**
- Consumes: layout/style signatures, source TOC evidence, semantic blocks.
- Produces: `infer_hierarchy(...)` and `validate_hierarchy(...)` with level, confidence, page-break, and TOC decisions.

- [ ] **Step 1: Write failing hierarchy tests**

Cover explicit chapters, unnumbered major sections, compact remedies, numbered prose, all-caps fragments, repeated furniture, table cells, verse fragments, no-following-content headings, source-TOC support, and implausibly dense generated TOCs.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_heading_hierarchy.py tests/test_structure.py -v`

Expected: FAIL on false headings and missing hierarchy validation.

- [ ] **Step 2: Implement combined evidence and negative evidence**

Use style recurrence, font hierarchy, gaps, position, numbering depth, text form, following-content extent, source TOC relationships, and negative evidence. Do not treat uppercase, bold, or numbering alone as sufficient.

- [ ] **Step 3: Implement hierarchy validation**

Demote candidates with no body range, duplicated fragments, table/list membership, furniture recurrence, or implausible TOC density. Keep low-confidence content as paragraphs/lists unless explicitly overridden.

- [ ] **Step 4: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_heading_hierarchy.py tests/test_structure.py tests/test_adaptive_documents.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-headings`

Expected: all tests pass.

- [ ] **Step 5: Commit**

Commit: `fix: infer stable headings and contents entries`

### Task 7: A4 Reading Edition Renderer and Pagination

**Files:**
- Modify: `config/book_style.json`
- Create: `src/bookloom/theme.py`
- Modify: `src/bookloom/rendering.py`
- Modify: `src/bookloom/pipeline.py`
- Modify: `src/bookloom/verification.py`
- Modify: `tests/test_rendering.py`
- Create: `tests/test_reading_edition.py`

**Interfaces:**
- Consumes: approved `DocumentModel`, semantic images, centralized `BookTheme`.
- Produces: generated cover, publication block, semantic body HTML, reconciled TOC, and production PDF.

- [ ] **Step 1: Write failing theme/layout tests**

Assert fixed A4 pages, generated teal cover, source title/metadata, omitted missing DOI, 15–16 mm normal top margin, chapter heading physical top between 22 and 28 mm, compact items sharing pages, heading-plus-three-lines cohesion, styled tables/lists/figures, thin footer rule, centered page number, and no cover number.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reading_edition.py tests/test_rendering.py -v`

Expected: FAIL on current adaptive dimensions, cover, and 24 mm chapter padding.

- [ ] **Step 2: Implement centralized `BookTheme`**

Load fixed A4 tokens, teal/green palette, Source Serif 4 or bundled equivalent, Noto Serif Devanagari, compact top-spacing tokens, table/list/figure tokens, and footer geometry without document-profile color/size overrides.

- [ ] **Step 3: Render semantic front matter and body**

Generate the collection cover by default, support explicit original-cover mode, render publication metadata/abstract/keywords only when present, and dispatch each semantic block through reusable renderers.

- [ ] **Step 4: Implement anchor-based image placement and pagination rules**

Insert figures at semantic anchors, preserve proportions/captions, start only real chapters/major sections on new pages, and enforce orphan/widow controls.

- [ ] **Step 5: Implement TOC reconciliation**

Render provisionally, read anchor destinations, regenerate right-aligned leader rows, rerender when TOC length changes pagination, and validate displayed numbers against links.

- [ ] **Step 6: Enforce renderer support policy**

Allow PyMuPDF only for clearly labeled degraded preview. Block production with an actionable message when WeasyPrint/GTK or required fonts are unavailable.

- [ ] **Step 7: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reading_edition.py tests/test_rendering.py tests/test_phase2_pipeline.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-renderer`

Expected: all tests pass.

- [ ] **Step 8: Render and visually inspect representative fixtures**

Render cover, contents, first body, chapter, compact-item, table, image, references, and final pages to PNG. Verify no excess top whitespace, clipping, stretched images, false figure pages, broken Hindi, or footer collisions.

- [ ] **Step 9: Commit**

Commit: `feat: render the A4 Reading Edition`

### Task 8: Polished Bookloom Streamlit Workflow

**Files:**
- Modify: `app.py`
- Create: `src/bookloom/app_state.py`
- Create: `src/bookloom/review_ui.py`
- Create: `src/bookloom/workflow_ui.py`
- Modify: `src/bookloom/integrity_ui.py`
- Modify: `.streamlit/config.toml`
- Create: `tests/test_bookloom_ui.py`
- Modify: `tests/test_integrity_ui.py`

**Interfaces:**
- Consumes: `ProcessingJob`, grouped review data, `DocumentApproval`, build artifacts.
- Produces: staged native Streamlit workflow and testable state transitions.

- [ ] **Step 1: Write failing Streamlit AppTest coverage**

Assert Bookloom identity; upload/options form; disabled process action without both PDFs; summary metrics; collapsed section groups; friendly badges; filters; lazy preview buttons; decision autosave; conditional manual wording; persistent approve action; confirmation summary; approval/build transition; meaningful errors; PDF preview; and numbered download label.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bookloom_ui.py -v`

Expected: FAIL on the current basic, per-item-save workflow.

- [ ] **Step 2: Extract state and workflow helpers from `app.py`**

Centralize initialization/migration/invalidation in `app_state.py`, processing/upload/download presentation in `workflow_ui.py`, and grouped optional review in `review_ui.py`. Keep business logic in services rather than widget callbacks.

- [ ] **Step 3: Build the staged native UI**

Use page config, themed containers, Material Symbols, upload form, responsive metrics, status stages, segmented/pill filters, dynamic collapsed expanders, lazy previews, native bottom actions, and a native approval dialog. Remove per-item Save and the second mandatory finalize action.

- [ ] **Step 4: Improve errors, diagnostics, and downloads**

Map domain exceptions to actionable messages, hide raw tracebacks, guard expensive closed diagnostics, make final PDF the primary download, and place audit artifacts in a secondary expander.

- [ ] **Step 5: Verify task and full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_bookloom_ui.py tests/test_integrity_ui.py -v`

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-ui`

Expected: all tests pass.

- [ ] **Step 6: Run the app for browser-level smoke testing**

Start Bookloom locally, verify upload, grouped review, approval, preview, downloads, responsive wrapping, and no stale state across sequential PDFs. Stop the test server after inspection.

- [ ] **Step 7: Commit**

Commit: `feat: deliver the polished Bookloom workflow`

### Task 9: Expanded QA and Multi-Document Regression

**Files:**
- Modify: `src/bookloom/verification.py`
- Modify: `src/bookloom/pipeline.py`
- Create: `tests/test_visual_qa.py`
- Modify: `tests/test_adaptive_documents.py`
- Modify: `tests/test_production_integrity.py`

**Interfaces:**
- Consumes: production PDF, approved semantic model, expected image inventory, pagination metadata.
- Produces: expanded verification report and representative QA page set.

- [ ] **Step 1: Write failing QA tests**

Cover inconsistent size, blank/near-empty page, duplicate page, overflow, table/footer collision, missing/duplicate/misordered image, orphan heading, TOC mismatch, cover numbering, missing glyph marker, suspicious image-only page, and representative-page selection by semantic role.

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_visual_qa.py -v`

Expected: FAIL on newly required checks.

- [ ] **Step 2: Implement expanded verification**

Add structured issue records and selection of cover, contents, first body, chapter, table, image, compact-item, references, and final pages when present.

- [ ] **Step 3: Exercise the regression matrix in one process**

Run design-reference, compact-item, chapter, scanned, Hindi, mixed-language, image-heavy, text-only, table, and TOC fixtures sequentially. Assert one A4 theme, correct content isolation, safe review defaults, and valid outputs.

- [ ] **Step 4: Verify full suite and visual artifacts**

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-final`

Inspect the latest representative PNGs and verification reports. Expected: zero failures and no visual defects.

- [ ] **Step 5: Commit**

Commit: `test: expand Bookloom publication QA`

### Task 10: README, Setup Validation, and Release Check

**Files:**
- Modify: `README.md`
- Modify: `setup.ps1`
- Modify: `run.ps1`
- Modify: `pyproject.toml`
- Modify: `docs/superpowers/specs/2026-10-08-universal-book-formatter-one-approval-design.md`
- Modify: `docs/superpowers/plans/2026-10-12-bookloom-universal-formatter.md`

**Interfaces:**
- Consumes: completed Bookloom workflow and verified commands.
- Produces: accurate onboarding and a final requirements/commit audit.

- [ ] **Step 1: Rewrite README around the final product**

Document Bookloom purpose, Trueloger publisher relationship, workflow, supported PDF types/languages, architecture, requirements, Windows setup, OCR/WeasyPrint configuration, usage, review defaults, output naming, artifacts, QA, troubleshooting, tests, privacy/local processing, and known production requirements.

- [ ] **Step 2: Verify documented setup and commands**

Run the exact installation/status/test/start commands that can be safely exercised in the existing environment. Correct any stale command, package name, path, or screenshot-free description.

- [ ] **Step 3: Run final verification**

Run: `.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom-release`

Run focused representative builds and inspect their verification JSON and rendered PNGs.

Expected: full suite passes, production renderer/fonts are reported accurately, and artifacts satisfy the spec.

- [ ] **Step 4: Audit repository naming and forbidden hacks**

Use `rg` to confirm old software-facing Trueloger names remain only where intentionally denoting publisher branding or migration compatibility; confirm no filename/title/heading-specific renderer logic; inspect `git status` and `git diff --check`.

- [ ] **Step 5: Commit**

Commit: `docs: complete Bookloom documentation and release checks`

- [ ] **Step 6: Report the ordered commit history**

List each milestone commit, test evidence, visual-QA evidence, any unavailable external regression PDFs, and any remaining environmental requirements without claiming unverified behavior.
