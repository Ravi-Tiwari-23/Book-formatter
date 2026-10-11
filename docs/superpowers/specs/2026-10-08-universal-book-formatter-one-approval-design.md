# Bookloom Universal Book Formatter and One-Approval Review Design

## Purpose

Transform structurally different source PDFs into one professional Trueloger Reading Edition while keeping the source authoritative, using the reference PDF only for validation and bibliographic evidence, and requiring only one mandatory document-level approval before production.

The existing Python, Streamlit, PyMuPDF, Tesseract, WeasyPrint, comparison, correction, caching, provenance, and integrity systems remain in place. This design changes the boundary between document understanding, review, and rendering; it does not rebuild the application or replace its technology stack.

## Product Identity

The software product and repository are named **Bookloom**. The name describes the application weaving text, structure, images, metadata, and validation evidence into a consistent publication.

Bookloom replaces the old project/application identity across:

- Python distribution metadata and package namespace;
- Streamlit page title, headings, status copy, and help text;
- README, setup instructions, launcher messages, and generated audit metadata;
- cache namespaces and application-owned identifiers where migration is safe; and
- tests and documentation that refer to the software itself.

**Trueloger remains the company/publisher identity only.** It may appear in the selected Reading Edition theme, generated cover/footer branding, and company-specific publishing metadata. It is not the application, package, or project name. Legacy environment variables and serialized cache compatibility may be read during migration, but new public configuration uses the Bookloom name.

## Product Outcome

For every upload pair, the application will:

1. create an isolated processing job;
2. analyze the source independently;
3. extract native text, OCR only where needed, and classify pages as native, scanned, or mixed;
4. build a semantic document model from source layout and reading order;
5. compare source content with the reference conservatively;
6. assign every finding a safe default decision;
7. permit optional grouped review and autosaved overrides;
8. record one document-level approval;
9. render the approved semantic model with the fixed A4 Trueloger Reading Edition theme;
10. reconcile final pagination and the contents page;
11. run text, layout, asset, and visual QA; and
12. offer the final artifacts for download.

Different documents may contain chapters, compact numbered remedies, articles, tables, images, Hindi text, or mixed content. Their structures remain different, but their generated books share one visual system.

## Confirmed Current-State Gaps

The current repository already provides native extraction, OCR fallback, comparison, human decisions, image provenance, protected-page support, PDF rendering, contents links, integrity gates, disk caches, and 102 passing tests. The architectural gaps are:

- `DocumentProfile.style()` carries source dimensions and inferred accent variants into output, while the required collection is fixed A4 with one theme.
- A detected source cover becomes a protected leading page by default, while the required default is a generated collection cover.
- Metadata is extracted from the reference only and displayed as a separate reference-information page instead of a source-first publication block.
- Semantic meaning is divided between `BookSection`, `StructuredBlock`, corrections, and renderer heuristics. Abstracts, keywords, author blocks, numbered lists, captions, conclusions, and publication metadata are not first-class model elements.
- Page classification is effectively native or OCR, not explicit native/scanned/mixed.
- Table identity is reconstructed through text equality later in the pipeline, which is fragile.
- Images are associated with a section but generally appended at its boundary rather than inserted at their source reading-order position.
- Image classification considers each occurrence mostly in isolation. It does not use cross-page recurrence, visual similarity, overlap with text, or document-wide placement patterns, so a repeated watermark/logo can be classified as meaningful content and emitted many times. A reproduced build recorded 166 `content_image` occurrences, including the same JPEG digest repeated across consecutive pages.
- Chapter CSS currently adds 24 mm of internal top padding on top of the 18 mm page margin. This places some chapter headings roughly 41 mm from the physical top of the page and creates avoidable empty space.
- Weak heading candidates can enter the contents page when short uppercase fragments, numbered body lines, or fragmented source-layout text are mistaken for navigational sections.
- The current review requires unresolved findings to be individually saved before finalization.
- The current structure-lock and finalization sequence introduces extra mandatory actions.
- Job files are content-hash separated, but job lifecycle, approval, options, and artifacts are not represented by one first-class job object.
- The WeasyPrint and PyMuPDF renderers do not provide equivalent publication behavior; production-quality pagination and contents reconciliation require WeasyPrint.

## Architectural Boundary

The application is divided into two explicit layers.

### Content engine

The content engine owns:

- upload validation and job isolation;
- source/reference extraction;
- page-type and language detection;
- OCR selection;
- layout records and reading order;
- source structure detection;
- source-first metadata extraction;
- reference matching and correction suggestions;
- safe default review decisions;
- user overrides;
- document approval; and
- the approved semantic document model.

It does not choose typography, colors, cover decoration, footer geometry, or page breaks.

### Design and book-format engine

The design engine owns:

- the Trueloger Reading Edition theme;
- generated cover composition;
- publication block presentation;
- A4 page geometry;
- contents layout and final page numbers;
- semantic block rendering;
- heading pagination and orphan control;
- tables, lists, figures, and captions;
- running furniture and page numbers; and
- layout and visual QA.

It may never infer or rewrite content. It consumes the approved semantic model and produces publication pages.

## Processing Job Isolation

Each source/reference pair receives a `ProcessingJob` with:

- stable `job_id` derived from full source and reference hashes plus processing options;
- source and reference paths;
- original client filenames for source and reference, preserved separately from the internal hash-based storage names;
- a job-specific working directory;
- a job-specific output directory;
- extraction and OCR records;
- the source document profile;
- the semantic document model;
- correction findings and review overrides;
- the document approval record;
- selected theme and cover options;
- generated artifacts and QA reports; and
- current processing stage and recoverable warnings.

Streamlit session state stores the current `job_id` and current job object. Loading a new upload pair replaces the active job-facing state, including preview keys, filters, structure edits, approval hashes, and artifacts. Shared disk caches remain safe because their keys include content hashes, algorithm versions, OCR parameters, and relevant options.

No mutable module-level variable may hold current-document facts.

## Output Filename and Versioning

The downloadable PDF uses the original uploaded source filename as its base instead of the generic `final-book.pdf` name.

For example:

- uploaded source: `Complete House Vastu.pdf`;
- first approved generated book: `Complete House Vastu 1.pdf`;
- next newly generated approved version: `Complete House Vastu 2.pdf`;
- later version: `Complete House Vastu 3.pdf`.

The numeric suffix is inserted immediately before `.pdf`. The application sanitizes only characters that are invalid or unsafe in Windows filenames while preserving the recognizable source title, spaces, capitalization, and Unicode text. If the uploaded name is missing or unusable, the detected document title becomes the base; `Trueloger Book` is the final fallback.

Version allocation is scoped to the preserved source identity and output history. It never overwrites an existing generated PDF. Reopening or downloading an already cached build returns the same filename and does not consume a new version number. A newly generated build whose approved text, semantic structure, theme options, or cover choice differs receives the next available number. Preview builds use the same recognizable base with an explicit marker, such as `Complete House Vastu Preview 1.pdf`, so they cannot be mistaken for approved output.

The chosen filename and version are stored in the build manifest and document approval/build audit data. Internal working files may retain stable hash-based names, but those names are never presented as the user's download filename.

## Extraction and Page Classification

Extraction remains native-text-first.

Each page records:

- dimensions and orientation;
- native text quantity and quality;
- image coverage;
- native text blocks and span attributes;
- OCR requirement and OCR confidence;
- extracted tables and figures;
- language signals; and
- one of `NATIVE_TEXT`, `SCANNED`, or `MIXED`.

`NATIVE_TEXT` means the native layer is reliable for the page. `SCANNED` means the content is image-based and requires OCR. `MIXED` means reliable native content and significant image-based textual regions coexist. Mixed pages preserve native text and OCR only the regions that lack a reliable text layer where feasible; the first implementation may use page-level OCR for those regions only when reliable bounding boxes cannot be isolated.

Password-protected or unreadable PDFs fail before analysis with a specific user-facing error. OCR failures are recorded per page and do not erase successful extraction from other pages.

## Semantic Document Model

Rendering consumes a single `DocumentModel`, not raw OCR strings, correction arrays, or renderer-specific heuristics.

The model contains:

- `DocumentMetadata` with title, author, co-author, editor, publisher, edition, publication year, ISBN, DOI, category, language, and confidence/provenance per field;
- `DocumentProfile` with page counts, language, page types, source geometry, cover/TOC detection, table/image presence, hierarchy summary, compact-item behavior, and warnings;
- ordered semantic blocks with stable IDs, source page, bounding box, reading-order position, hierarchy, confidence, and children where appropriate; and
- source asset references with hashes, dimensions, classifications, captions, and semantic parent IDs.

Supported block types are:

- document title;
- publication block;
- abstract;
- keywords;
- chapter;
- major section;
- section;
- subsection;
- numbered item;
- paragraph;
- bullet list and bullet item;
- numbered list and numbered item;
- table;
- image;
- caption;
- quote;
- footnote;
- conclusion;
- reference entry; and
- references section.

Existing `BookSection` and `StructuredBlock` interfaces may remain as compatibility adapters during migration, but the canonical model is `DocumentModel`.

## Structure and Heading Inference

Heading classification uses combined evidence:

- relative font size and weight;
- position and whitespace;
- capitalization and punctuation;
- numbering depth;
- text length;
- repetition and page-edge furniture detection;
- source TOC relationships;
- whether substantial body content follows;
- recurrence of the same style signature; and
- whether similar headings consistently begin near the top of a page.

Heading candidates also pass negative-evidence checks. Repeated furniture, isolated table cells, running labels, OCR fragments, individual verse lines, sentences ending as ordinary prose, and short all-caps fragments without a stable style signature are excluded. A heading must have a meaningful body range or a verified relationship to the source TOC; being bold, uppercase, or numbered is not sufficient.

Explicit chapter/part labels are strong evidence but are not required. A numeric prefix alone is not sufficient.

Only high-confidence chapters and major book sections receive `start_new_page=True`. Compact numbered entries, remedies, tips, ordinary sections, and subsections flow naturally. The renderer keeps a heading with at least two to three following lines. Long sections continue normally across pages.

The original source TOC supplies hierarchy evidence but is excluded from body content and never supplies final page numbers.

Before rendering, a hierarchy validation pass rejects or demotes suspicious headings when they would create an implausibly dense TOC, have no following content, duplicate nearby fragments, or split a coherent paragraph/list. Low-confidence candidates remain body/list content unless the optional structure editor promotes them.

## Metadata Policy

Metadata extraction is source-first:

1. source PDF metadata and visible source content;
2. reference metadata and visible reference content as validation or fallback evidence;
3. an explicit user override when provided.

Every resolved field records its value, provenance, and confidence. A reference value does not silently replace a conflicting source value. Conflicting author, DOI, ISBN, title, or edition values become important findings with a default of preserving the source.

DOIs are normalized from labeled, bare, or `https://doi.org/` forms. A DOI is never invented. Missing DOI output is controlled by the theme option: omit by default, with an optional explicit “not available” line.

Abstracts, keywords, conclusions, and references are preserved only when detected in the source. The application does not synthesize them.

## Reference Validation and Findings

The reference remains text-only validation evidence. Its structure and images never determine source structure or enter the publication asset stream.

Every finding records:

- stable ID;
- source section and page;
- source, reference, and suggested wording;
- category and user-facing label;
- confidence;
- risk/severity;
- `default_decision`;
- optional `user_decision`;
- `effective_decision`;
- optional manual wording;
- whether it needs attention;
- reason and provenance; and
- audit timestamps where available.

`effective_decision` is always computed as `user_decision or default_decision`. An untouched finding is therefore actionable and never blocks approval merely because it was not opened.

### Default-decision policy

- Exact source/reference match: keep the identical source text.
- Safe OCR typo, spelling, punctuation, or broken-word correction: accept suggestion.
- High-confidence non-semantic reference match: accept suggestion.
- Medium-confidence suggestion that does not alter meaning, names, identifiers, or numbers: accept suggestion.
- Possible missing content: keep source.
- Semantic conflict: keep source.
- Low-confidence reference wording: keep source.
- Uncertain author, DOI, ISBN, edition, publisher, or numerical value: keep source or omit the uncertain addition.
- Unreadable OCR or large missing passage: keep recoverable source text and flag as needing attention.

“Needs attention” is reserved for materially risky cases such as unreadable OCR, large missing passages, conflicting numerical facts, conflicting identity metadata, and large semantic changes. Low confidence alone is not automatically blocking.

## One-Approval Review Experience

The review page begins with:

- source and reference names;
- sections processed;
- automatic corrections;
- content differences;
- possible missing content;
- findings that need attention;
- a “Review important issues” action when applicable; and
- the primary “Approve all and continue” action.

Review is optional. Findings are grouped first by semantic section and then by source page. Duplicate top-level rows are eliminated; a group label reports the number of contained issues. All groups are collapsed by default.

Filters use human-facing concepts: All, Needs attention, Low confidence, Changed, and Reviewed. Backend enum names are mapped to sentence-case labels and badges.

Inside a group, each issue displays source, reference, suggestion, confidence, reason, and decision. Source/reference page previews remain lazy and load only when requested.

Decision widgets autosave through Streamlit callbacks. Accept and keep-source choices hide the manual wording input. Selecting manual edit reveals the input and requires non-empty wording for that finding. Changing an override invalidates document approval, semantic structure derived from approved wording, generated artifacts, and related integrity state.

The main action remains visible in a native bottom action container on long pages. It opens one confirmation dialog summarizing:

- safe corrections to apply;
- uncertain findings that will preserve source text;
- user overrides;
- manual edits; and
- unresolved manual-edit validation errors, if any.

Confirmation creates one `DocumentApproval` record with document/job ID, approval timestamp, total findings, defaults used, user overrides, manual edits, effective-text hash, and policy version. Individual effective decisions remain in the audit artifacts.

There are no required per-finding save buttons and no second mandatory “Finalize approved text” action.

## Optional Structure Editing

Detected structure may remain inspectable in an advanced area for exceptional cases. It is not part of the normal mandatory path.

Structure editing may change block type, hierarchy, TOC inclusion, and page-break intent. It cannot silently change approved wording. A wording edit must become an explicit finding override/manual edit and invalidate the document approval. If no structure edits exist, approval immediately proceeds to generation.

## Trueloger Reading Edition Theme

The central theme file defines all publication tokens. No document profile may override page size or collection colors.

Required defaults:

- A4, 210 x 297 mm, for every generated page;
- deep teal cover and primary color near `#234F4B`;
- dark green headings near `#315D56`;
- white reading pages and dark charcoal body text;
- Source Serif 4 for Latin text when bundled;
- Noto Serif Devanagari for Hindi and Devanagari coverage;
- a normal-page top margin of approximately 15–16 mm and no decorative vertical centering of body headings;
- chapter openers positioned approximately 22–28 mm from the physical top of the page, including the page margin, unless an explicitly selected special part-opening design requires more space;
- no chapter-level 24 mm padding in addition to the page margin; chapter spacing is a small theme token, normally 6–10 mm below the content-box top;
- justified 10–10.5 pt body text with approximately 1.4 line height;
- centralized title, chapter, section, subheading, item, TOC, and caption scales;
- subtle green-grey rules and table fills;
- thin footer divider and centered page number; and
- no page number on the cover.

Fonts are bundled locally and embedded by the production renderer. Missing required production fonts block production with a precise diagnostic rather than silently substituting a font with incomplete Hindi coverage.

## Cover and Front Matter

Generated Collection Cover is the default. “Use Original Cover” is an explicit option.

The generated cover recreates the reference design language without copying its raster page:

- Trueloger collection branding;
- category label derived from metadata or a neutral collection label;
- large centered source title;
- “The Reading Edition” marker;
- restrained line geometry;
- wisdom/tradition supporting line; and
- Trueloger footer branding on a deep teal background.

If title confidence is inadequate, the UI exposes a title override. The filename is only the final fallback.

After the cover, the book may contain a restrained title/edition page, contents, and a publication block. The publication block shows source-authoritative author/co-author and DOI/ISBN values when reliably available. It does not create a reference-source page in the published book.

## Universal Rendering

The renderer dispatches exclusively by semantic block type, using reusable handlers such as `render_chapter`, `render_section`, `render_paragraph`, `render_list`, `render_table`, `render_image`, and `render_references`. It contains no filename-, title-, heading-, or book-specific branches.

### Contents and pagination

TOC inclusion defaults are:

- document title: excluded;
- chapter and major section: included;
- section: configurable and included for normal books;
- subsection: excluded unless source hierarchy/TOC supports inclusion;
- compact numbered item: included when the source treats the item sequence as navigational; and
- paragraph/list/table/image: excluded.

The primary renderer uses an explicit pagination reconciliation loop:

1. render with semantic anchors and provisional contents;
2. read anchor destinations from the rendered PDF;
3. generate contents rows with final displayed page numbers;
4. render again;
5. repeat once if contents length changed pagination; and
6. fail QA if displayed numbers and link destinations do not agree.

TOC rows use a grid with a right-aligned page-number column and CSS leaders, never hand-built period strings.

### Tables, lists, and figures

Tables retain extracted row/column data directly in the semantic block. Header rows are marked explicitly, repeated on continuation pages, and styled with a light green-grey fill, thin borders, and readable padding. The renderer may reduce table type modestly but may not clip or overlap the footer.

Bullet and numbered lists remain distinct semantic structures. Numbering is never converted to bullets.

Image handling begins with a document-wide visual inventory rather than classifying each extracted occurrence independently. Each image record includes its digest, perceptual similarity key, source page and bounding box, pixel dimensions, page-coverage ratio, color/entropy signals, transparency, overlap with text, recurrence count and positions, nearby caption/text, and whether it is the raster backing of a scanned page.

The classifier distinguishes:

- meaningful photo or illustration;
- diagram/chart;
- rasterized table or textual figure;
- source cover artwork;
- logo/brand mark;
- header/footer decoration;
- repeated watermark/background;
- page scan used for OCR; and
- tiny or extraction-only artifact.

Full-page scans are OCR inputs, not publication figures. Images or near-identical images repeated in a consistent position across many pages default to watermark/header/footer/background classification. Small repeated marks default to logos or decoration. A repeated digest is not emitted once per page merely because it appears in multiple PDF image rectangles.

Meaningful figures are deduplicated by logical occurrence and inserted according to source reading order. Every figure receives an explicit `insert_after_block_id` or `insert_before_block_id`, semantic parent, caption association, and confidence. Association uses the nearest preceding/following text blocks, column geometry, caption language, and source coordinates; it does not merely choose a section and append the image to that section's end.

Meaningful images preserve aspect ratio, use at most 75–85 percent of content width by default, and do not receive a dedicated page unless their size requires it. Captions stay with their images. Only known provenance produces a source-page caption. Low-confidence large or unique image classifications are surfaced in the optional review instead of being silently discarded or duplicated.

## Renderer Support Policy

WeasyPrint is the production renderer because the required CSS pagination, font shaping, TOC target resolution, table continuation, orphan control, and Hindi typography cannot be guaranteed by the current lightweight fallback.

The PyMuPDF renderer remains available for development preview or a clearly labeled degraded diagnostic output. It must not silently claim production parity. If WeasyPrint/GTK is unavailable, the UI explains how to configure it and prevents a falsely verified production build.

## QA and Failure Handling

Production retains the existing pre-render and post-render text-integrity gates and adds checks for:

- fixed A4 dimensions on every page;
- blank and near-empty accidental pages;
- duplicate pages;
- text and image overflow;
- table overflow and footer collision;
- missing expected source images;
- duplicate meaningful images and repeated watermark/logo emission;
- figure order or section-placement mismatches against semantic insertion anchors;
- forbidden reference images;
- image/caption separation;
- orphan headings and paragraph widows/orphans;
- cover page numbering;
- footer and page-number consistency;
- TOC alignment, links, and displayed page numbers;
- missing glyph markers and Devanagari font coverage;
- suspicious image-only output pages; and
- unexpected changes to approved text.

Representative visual QA pages are selected by semantic role: cover, contents, first body page, chapter opener, table page, image page, compact-item page, references page, and final page where those roles exist. They are rendered to PNG for inspection and recorded in the verification report.

User-facing failures identify the document stage and recoverable scope, for example a password-protected file, OCR failure on a specific page, missing production renderer, or an isolated table overflow. Raw Python tracebacks are not shown in normal UI.

## Streamlit State and Flow

The normal UI flow is:

`Upload -> Process -> Optional grouped review -> Approve -> Generate -> QA -> Download`

The upload area keeps source and reference inputs and adds simple options for theme, A4 size, OCR correction, reference validation, image preservation, generated contents, metadata extraction, professional formatting, and generated/original cover behavior. Options that are mandatory for the only supported theme may be displayed as fixed or disabled rather than introducing unused configuration branches.

Processing status reports real stages from the pipeline. Expensive previews remain lazy. Build execution starts after the approval dialog records approval; the same interaction may set a pending-build flag and the following Streamlit rerun performs the build safely.

## Frontend Design

Bookloom uses a polished, restrained editorial interface built primarily from native Streamlit elements. A `.streamlit/config.toml` theme provides a warm-white canvas, deep teal primary color, quiet green-grey surfaces, readable dark text, consistent borders, and professional typography. Fragile CSS targeting Streamlit internals is removed.

The page is organized into clear workflow stages:

1. **Create a book** — a compact introduction, source/reference upload containers, and essential output options in a form.
2. **Processing** — one live status component with named stages, progress, recoverable warnings, and no raw traceback.
3. **Document review** — summary metrics, important-issue action, grouped optional findings, and the persistent approval action.
4. **Book preview** — PDF preview, concise QA summary, and optional advanced diagnostics.
5. **Downloads** — a prominent final-PDF download followed by secondary audit artifacts.

The sidebar contains only system readiness, current document identity, theme/output settings that apply globally, and cache maintenance. Main review and output content stays in the main area.

UI conventions:

- sentence-case labels and headings;
- Material Symbols for actions and statuses instead of decorative emoji;
- bordered containers for upload, summary, review, QA, and download groups;
- no more than four summary metrics per row;
- segmented controls or pills for compact filters;
- collapsed expanders for optional details and diagnostics;
- accessible labels and `alt` text for every image/PDF preview;
- lazy preview rendering and no expensive work inside closed expanders;
- a native confirmation dialog for final approval;
- a native bottom action container for the primary approval control on long review pages; and
- clear empty, loading, recoverable-error, blocking-error, and completed states.

The frontend remains a single-page workflow unless testing demonstrates that page separation materially improves reliability. Business logic moves out of `app.py` into focused modules so UI tests can exercise state transitions without invoking expensive PDF operations.

## Compatibility and Migration

Existing cached objects and Streamlit hot-reload state may contain older `Correction`, `ValidationProject`, or structured-block instances. Migration code supplies default decisions and safely reconstructs current dataclasses. Cache namespaces and algorithm versions are incremented wherever serialized schemas or inference behavior changes.

Book-specific profiles remain supported only for genuinely external requirements such as filenames or legacy protected assets. They may not control content recognition, expected heading names, or renderer structure. Existing 33-remedy behavior is expressed by semantic inference and tests rather than filename checks.

## Files and Responsibilities

- `src/truelogger/models.py`: job, metadata, semantic document/block, finding-decision, and approval models.
- `src/truelogger/extraction.py`: page classification, richer layout records, mixed-page behavior, table/image extraction.
- `src/truelogger/ocr.py`: OCR-region/page results and recoverable diagnostics.
- `src/truelogger/document_analysis.py`: document profiling, hierarchy inference, reading order, semantic model construction, and asset association.
- `src/truelogger/metadata.py`: source-first extraction, reference validation, provenance, and conflicts.
- `src/truelogger/review.py`: decision policy, effective decisions, overrides, manual validation, and document approval.
- `src/truelogger/pipeline.py`: isolated job orchestration, approved semantic model assembly, artifact audit data, and staged generation.
- `src/truelogger/rendering.py`: theme-based semantic rendering, cover, publication block, contents reconciliation, body components, and footer.
- `src/truelogger/verification.py`: layout, TOC, duplicate-page, image, font, and representative-page QA.
- `src/truelogger/ui_helpers.py`: grouped review summaries, filters, labels, and state invalidation.
- `config/book_style.json`: fixed Trueloger Reading Edition design tokens.
- `app.py`: streamlined upload/options, staged status, grouped optional review, autosave callbacks, confirmation dialog, build trigger, and downloads.
- `.streamlit/config.toml`: Bookloom application theme and accessible component styling.
- `README.md`: product overview, workflow, architecture, setup, OCR/WeasyPrint requirements, usage, QA outputs, troubleshooting, tests, and project/company naming distinction.
- `tests/`: unit, pipeline, rendering, QA, sequential-job, regression, and Streamlit AppTest coverage.

## Test Strategy

Implementation follows test-driven development. Tests are added in dependency order.

### Review tests

1. Every finding receives a default decision.
2. Safe/high-confidence non-semantic fixes default to accept.
3. Low-confidence, semantic, missing-content, metadata-conflict, and risky findings default to keep source/omit uncertain additions.
4. Effective decision prefers the user override.
5. Untouched findings do not block document approval.
6. Manual edit with empty wording blocks only that finding.
7. One approval produces the expected final text and audit record.
8. Changing an override invalidates approval and artifacts.
9. Findings group by section/page without duplicate top-level rows.
10. Streamlit controls autosave and conditionally show manual wording.

### Semantic and rendering tests

1. Native, scanned, and mixed pages classify correctly.
2. English, Hindi, and mixed documents retain Unicode text.
3. Source metadata wins; reference fallback and conflicts behave conservatively.
4. DOI variants normalize and missing DOI is never fabricated.
5. Chapters start on new pages while compact numbered items flow together.
6. Chapter headings begin within the configured 22–28 mm physical-top band and ordinary headings do not create an unnecessarily blank upper page region.
7. Heading openings remain with two to three lines of body text.
8. Tables, bullet lists, numbered lists, images, captions, abstract, keywords, conclusion, and references retain semantics.
9. Repeated watermarks, logos, page scans, and extraction artifacts are not emitted as content figures.
10. Meaningful images occur at their reading-order anchors near related source content and are not duplicated.
11. Short uppercase/OCR fragments and ordinary numbered sentences do not pollute the contents page.
12. Every output page is A4, including original-cover mode.
13. Generated covers share the reference design language.
14. Contents numbers match final anchors after reconciliation.
15. Required fonts are embedded and Hindi has no missing glyph markers.
16. Download filenames preserve the uploaded source base name, allocate non-overwriting numeric versions, and reuse the same name for a cached build.
17. Streamlit AppTest verifies Bookloom identity, the upload form, grouped review defaults, autosaved overrides, approval dialog state, errors, and final download labels.

### Regression matrix

The same pipeline and running process exercise:

1. the Balancing Five Elements design-reference document;
2. Complete House Vastu when available;
3. a short-remedy-heavy document;
4. a long-chapter document;
5. a scanned document;
6. a Hindi document;
7. an English/Hindi mixed document;
8. an image-heavy document;
9. a text-only document; and
10. a document with tables.

Synthetic fixtures cover missing external samples without pretending to validate their exact content. Sequential A/B/C processing verifies that metadata, findings, previews, semantic blocks, images, approval records, and outputs never leak between jobs. The complete existing test suite remains green.

## Completion Criteria

The feature is complete only when:

- structurally different PDFs pass through one pipeline without code changes;
- source/reference pairs and job state remain isolated across sequential processing;
- source content remains authoritative and reference uncertainty cannot silently overwrite it;
- review is optional and one document-level approval can finalize untouched findings safely;
- per-finding overrides autosave and remain auditable;
- generated books use the fixed A4 Trueloger Reading Edition theme;
- the generated cover, contents, publication block, headings, body, tables, lists, images, references, footer, and page numbers form one coherent collection;
- only actual chapters/major sections force page breaks;
- compact entries flow naturally and headings are not orphaned;
- chapter headings use the compact top-spacing band and do not waste the upper page area;
- repeated decoration, watermarks, logos, and scanned page rasters are not mistaken for content images;
- meaningful images and captions remain deduplicated and anchored beside related content;
- contents entries contain genuine navigational headings rather than fragmented body text;
- final downloads use the recognizable uploaded source name plus a numeric version instead of `final-book.pdf`;
- the application and package use the Bookloom identity while Trueloger appears only as company/publisher branding;
- the frontend presents a coherent staged workflow with accessible native Streamlit controls and no fragile global CSS;
- Hindi and mixed-script output render correctly with embedded fonts;
- contents page numbers match final pagination;
- QA rejects inconsistent sizes, overflows, broken fonts, missing images, duplicates, and altered approved text;
- existing supported documents remain functional; and
- no filename-, title-, or heading-specific processing logic is introduced.
