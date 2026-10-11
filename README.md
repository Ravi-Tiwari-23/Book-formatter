# Bookloom

Bookloom is the PDF review and production application. Trueloger is retained
only as the publisher identity used by the current house style and source
materials; it is not the software name.

A local Windows application for reference-led Hindi/English PDF validation,
human correction approval, and professional book production. The source and
reference PDFs are never overwritten.

## Capabilities

- Per-page direct extraction with PyMuPDF and OCR fallback for scanned pages.
- Tesseract 5 OCR at 300 DPI with `hin+eng`, word confidence, and preprocessing.
- Monotonic fuzzy paragraph matching with RapidFuzz, independent of page numbers.
- Conservative reference/rule-based suggestions with protected terminology.
- Explicit Accept, Reject, Edit, Keep Source, and Use Reference decisions.
- Locked final text before structure detection or formatting.
- Editable title/chapter/heading/body/verse/list structure.
- A5 HTML/CSS book template with TOC, page numbers, and PDF bookmarks.
- Exact cloning of selected Trulogger opening/logo/art pages.
- Original embedded-image byte extraction and hash recording.
- Validation report, corrections JSON, approved text, manifest, QA renderings,
  verification report, and final PDF.
- Number/title/sequence-based remedy section alignment, including recognition
  and production gating for remedies 1-33.
- Strict reference text-only mode: reference images are fingerprinted for QA
  but never enter the publication asset pipeline.
- Output-image provenance firewall and production blockers for missing sections,
  unresolved reviews, missing protected assets, fonts, and reference imagery.
- Book-specific profiles under `config/books/` without hardcoding titles into
  the processing engine.
- Native-text-first extraction with versioned, persistent extraction, per-page
  OCR, comparison, lazy-preview, provenance, and verified-build caches.
- Section-scoped matching with exact-text fast paths before bounded RapidFuzz
  candidate searches; exact matches are resolved automatically.
- Real stage timings and cache counters in the UI and in each build's
  `performance-report.json`.
- Review-first pagination (25 records per page), pre-render filters, and 120 DPI
  page previews generated only when requested.
- Canonical remedy detection selects the ordered 1–33 heading sequence and
  keeps cover, contents, publication, disclaimer, and introduction material
  outside the remedy count. Repeated headers, footers, nested numbered lists,
  and doubled extraction artifacts are suppressed.
- Exact and safe non-semantic matches are auto-approved. Final book generation
  remains locked until meaningful differences are reviewed and the approved
  text is explicitly finalized.

## Windows setup

From PowerShell in VS Code:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

Streamlit opens the local application in the default browser. Alternatively:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### Tesseract OCR

Install Tesseract OCR 5 and ensure both `eng.traineddata` and
`hin.traineddata` are present in its `tessdata` directory. Add the installation
directory to `PATH`, or paste the full `tesseract.exe` path into the UI. Text
PDFs do not require Tesseract.

### WeasyPrint on Windows

WeasyPrint is the primary HTML/CSS renderer and needs its GTK/Pango native
runtime on Windows. If those DLLs are not available, the application reports
that status and uses its bundled PyMuPDF renderer fallback. This keeps local
generation operational; install GTK/Pango before production typesetting to use
the exact WeasyPrint CSS layout.

The launcher automatically discovers the official MSYS2 UCRT64 runtime at
`C:\msys64-truelogger\ucrt64\bin` or `C:\msys64\ucrt64\bin`. A custom runtime
can be selected with `BOOKLOOM_GTK_BIN` (or the legacy
`TRUELOGGER_GTK_BIN`); no global `PATH` modification is
required.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest
```

## Output safety

Uploaded inputs are copied into `work/uploads/` under a content hash. Generated
artifacts are written under `output/`. Protected pages are copied as PDF page
objects without rasterization; their content-stream hashes are verified after
the final PDF is written.

Processing caches live under `work/cache/` and persist across application
restarts. The sidebar can clear previews, comparisons, the current book, or all
caches independently. Changing a review decision or building a PDF does not
restart extraction or comparison.

The development preview button is explicitly marked **PREVIEW ONLY**. It uses
the current source wording for unresolved passages and cannot create a
production build or silently apply unresolved reference text.

For **33 Quick Vastu Remedies**, upload the TRUELOGER source as the Source PDF
and `33 Quick Vastu Remedies(1).pdf` as the Reference PDF. The UI first permits
a remedies 1-3 preview. The production button remains blocked until remedies
1-33 are present, every correction is resolved, and protected pages are
selected. Production artifacts are written beneath `output/pdf/` with the
book-specific filenames defined in the Phase 2 profile.

