# Bookloom

Bookloom is a local PDF-to-book production workspace. It extracts a source PDF, uses a second PDF only as validation evidence, lets an editor review exceptions, and produces a source-faithful A4 reading edition after one final approval.

Bookloom is the software and project name. **TRUELOGER** appears only as the publisher identity in the current Reading Edition theme.

## What Bookloom does

- Reads native, scanned, and mixed PDFs; OCR runs only where a usable text layer is absent.
- Supports English, Hindi, and mixed Hindi/English documents when the matching Tesseract language packs are installed.
- Treats the source PDF as authoritative. Reference-only or low-confidence wording is never inserted automatically.
- Detects chapters, headings, paragraphs, lists, verses, tables, captions, figures, front matter, and bibliographic metadata.
- Suppresses cover art, scans, repeated logos, watermarks, and page furniture instead of treating them as body illustrations.
- Keeps meaningful source figures in reading order with their aspect ratio and source caption.
- Applies conservative defaults, autosaves optional overrides, and asks for one document-level approval.
- Produces a fixed A4 edition with a generated cover, linked contents page, compact chapter top spacing, bookmarks, footer rule, and page numbers.
- Blocks a production build when text, image, pagination, glyph, page-size, overflow, or contents checks fail.

The source and reference PDFs are copied into an isolated job directory. They are never overwritten.

## Workflow

1. Upload the **Source PDF** to be published.
2. Upload the **Reference PDF** used to check wording and metadata. Its layout and images are not copied into the book.
3. Open **Processing options** only when OCR needs a custom Tesseract path or the original source cover must be preserved.
4. Select **Analyze PDFs**.
5. Review the grouped findings if desired. Safe spelling/OCR corrections can default to the suggestion; semantic, numeric, missing-content, and low-confidence findings default to the source.
6. Select **Review and approve document**, confirm the complete decision set once, and build the A4 Reading Edition.
7. Download the numbered PDF. The PDF preview and audit files are available separately and are loaded only when requested.

Changing an override invalidates the previous approval, so stale decisions cannot silently reach production.

## Output names and artifacts

The PDF keeps the uploaded source name and adds a number:

```text
Complete House Vastu.pdf
→ Complete House Vastu 1.pdf
→ Complete House Vastu 2.pdf
```

An unchanged cached build reuses its existing number. Preview files use `Preview 1`, `Preview 2`, and so on, without consuming production numbers. Windows-invalid filename characters are removed safely while Unicode names are retained.

Each successful job can include:

- the numbered final PDF;
- `validation-report.md` and `corrections.json`;
- `final-approved-text.md` and `final-approved-text.json`;
- `source_structure.json` and `document-analysis.json`;
- `build-manifest.json` with source, reference, output, renderer, font, approval, and hash data;
- `verification-report.json` with text, image, layout, contents, page-size, and visual-QA results;
- `performance-report.json`; and
- `qa-pages/` renderings for visual inspection.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer
- Tesseract OCR 5 with `eng.traineddata` and `hin.traineddata` for scanned English/Hindi pages
- WeasyPrint's GTK/Pango runtime for the primary CSS production renderer

Native-text PDFs do not require Tesseract. Bookloom reports the availability of both Tesseract and WeasyPrint in the sidebar.

## Install and run on Windows

Open PowerShell in the repository directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run.ps1
```

`setup.ps1` creates `.venv`, upgrades packaging tools, and installs Bookloom with its development and image-processing dependencies. `run.ps1` starts Streamlit and discovers a compatible GTK runtime without modifying the global `PATH`.

To start the app directly:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### Tesseract

Install Tesseract 5 and ensure the English and Hindi language files are present in its `tessdata` directory. Put `tesseract.exe` on `PATH`, or enter its full path in Bookloom's Processing options.

### WeasyPrint and GTK

The launcher searches these locations in order:

1. `BOOKLOOM_GTK_BIN`
2. the legacy migration variable `TRUELOGGER_GTK_BIN`
3. `C:\msys64-truelogger\ucrt64\bin`
4. `C:\msys64\ucrt64\bin`

The selected folder must contain `libgobject-2.0-0.dll`. `BOOKLOOM_GTK_BIN` is the public configuration name; the older variable and directory are read only for compatibility with existing installations.

Example:

```powershell
$env:BOOKLOOM_GTK_BIN = "C:\msys64\ucrt64\bin"
.\run.ps1
```

## Quality and safety model

Bookloom verifies the approved semantic document before rendering and then extracts the finished PDF to verify it again. Production checks cover:

- missing, changed, duplicated, unexpected, or reordered approved text;
- missing, duplicated, unexpected, or misordered source-image occurrences;
- reference-image leakage;
- blank, near-empty, duplicate, inconsistent-size, overflowing, or suspicious image-only pages;
- orphan headings, table/footer collisions, missing-glyph markers, and numbered covers;
- invalid contents links or printed page-number mismatches; and
- chapter headings outside the 22–28 mm physical top band.

The generated cover is the default. Preserving selected original cover pages is opt-in, and their PDF content hashes are checked after assembly.

## Architecture

The code lives under `src/bookloom/`:

- extraction and OCR create page-level source records;
- document analysis and semantic modeling infer structure without using the reference layout;
- matching and review create conservative findings and effective decisions;
- rendering consumes only the approved semantic model and central A4 theme;
- integrity and verification enforce text, image, provenance, and layout gates; and
- Streamlit provides the upload → review → build → download workflow.

Processing caches live under `work/cache/`. Uploaded job files live under `work/uploads/`. Generated application output lives under `output/`. These local runtime directories are ignored by Git and can be cleared from the sidebar.

## Tests

Run the complete suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp tmp\pytest-bookloom
```

The suite includes native/scanned/mixed extraction, Hindi rendering, source/reference authority, one-approval behavior, image classification, heading inference, filename versioning, production integrity, visual QA, and Streamlit AppTest coverage.

## Troubleshooting

- **Analyze PDFs is disabled:** both PDF upload fields are required.
- **Scanned pages have no text:** install Tesseract, add `eng`/`hin` language data, and verify the executable path in Processing options.
- **WeasyPrint is unavailable:** install a GTK/Pango runtime and set `BOOKLOOM_GTK_BIN`; restart Bookloom afterward.
- **Final build is blocked:** open the reported integrity or layout details. Bookloom deliberately refuses to download an unverified production PDF.
- **A title or author is missing:** Bookloom omits uncertain metadata instead of inventing it. The source remains authoritative.
- **A repeated logo is missing from the body:** cover art, contents decoration, watermarks, and repeating furniture are intentionally suppressed. Meaningful body figures remain eligible.
- **A second build has `2` in its name:** numbered names prevent accidental overwrite. An identical cached build keeps its existing number.

## Privacy

Processing is local. Bookloom does not upload documents to a remote model or service. Anyone with filesystem access to this computer may still be able to read `work/`, `output/`, and cache artifacts, so clear them before sharing the machine or repository.

## Current production limits

- OCR quality depends on scan resolution, orientation, language data, and source print quality.
- Complex multi-column and heavily designed pages may require editorial review even when integrity checks pass.
- The fixed output is A4; source page dimensions do not change the Reading Edition size.
- WeasyPrint plus GTK/Pango is the supported high-fidelity production path. The PyMuPDF renderer is a compatibility fallback and can differ in advanced CSS pagination.
