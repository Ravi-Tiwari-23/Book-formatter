from pypdf import PdfReader
from PIL import Image
import pymupdf

from truelogger.models import BlockKind, StructuredBlock
from truelogger.rendering import build_book_html, render_book
from truelogger.assets import prepend_protected_pages
from truelogger.verification import verify_pdf


def test_renderer_creates_numbered_pdf_with_outline(tmp_path):
    output = tmp_path / "book.pdf"
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "A Small Book", level=0),
        StructuredBlock(BlockKind.CHAPTER, "Chapter 1", level=1),
        StructuredBlock(BlockKind.BODY, "A sufficiently long paragraph for the generated book."),
    ]

    render_book(blocks, output)

    reader = PdfReader(output)
    assert len(reader.pages) >= 2
    assert reader.outline
    extracted = "".join(page.extract_text() or "" for page in reader.pages)
    assert "Contents" in extracted
    assert "Chapter 1" in extracted


def test_renderer_draws_devanagari_content_without_missing_glyph_markers(tmp_path):
    output = tmp_path / "hindi-book.pdf"
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "ज्योतिष परिचय", level=0),
        StructuredBlock(BlockKind.CHAPTER, "अध्याय 1: प्रारम्भ", level=1),
        StructuredBlock(BlockKind.HEADING, "ग्रहों का परिचय", level=2),
        StructuredBlock(
            BlockKind.BODY,
            "यह बहुत महत्वपूर्ण अध्याय है। इसमें हिन्दी और English दोनों पाठ सुरक्षित रहते हैं।",
        ),
        StructuredBlock(BlockKind.VERSE, "ॐ नमः शिवाय।\nॐ शान्तिः शान्तिः शान्तिः॥"),
    ]

    render_book(blocks, output)

    reader = PdfReader(output)
    extracted = "".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) == 3
    assert "English" in extracted
    assert "।" in extracted
    assert "\ufffd" not in extracted


def test_fallback_image_placement_preserves_aspect_ratio(tmp_path):
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (200, 100), "red").save(image_path)
    output = tmp_path / "image-book.pdf"
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "Image Book"),
        StructuredBlock(BlockKind.REMEDY, "01\nFirst Remedy", level=1),
        StructuredBlock(BlockKind.IMAGE, "Source image", image_path=str(image_path)),
    ]
    render_book(blocks, output)
    with pymupdf.open(output) as document:
        page = document[-1]
        image = page.get_images(full=True)[0]
        rect = page.get_image_rects(image[0])[0]
    assert abs((rect.width / rect.height) - 2.0) < 0.05


def test_short_remedies_flow_on_the_same_page_and_keep_openings_together(tmp_path):
    output = tmp_path / "remedy-flow.pdf"
    blocks = [StructuredBlock(BlockKind.BOOK_TITLE, "Remedy Flow")]
    for number in range(31, 34):
        blocks.extend(
            [
                StructuredBlock(BlockKind.REMEDY, f"{number}\nRemedy {number}", chapter_id=str(number)),
                StructuredBlock(
                    BlockKind.BODY,
                    f"Short opening paragraph for remedy {number} with practical Vastu guidance.",
                    chapter_id=str(number),
                ),
            ]
        )

    render_book(blocks, output)

    with pymupdf.open(output) as document:
        pages = {
            number: next(
                index
                for index, page in enumerate(document)
                if f"short opening paragraph for remedy {number}"
                in page.get_text("text").casefold()
            )
            for number in range(31, 34)
        }
        for number, page_index in pages.items():
            page_text = document[page_index].get_text("text").casefold()
            assert f"remedy {number}" in page_text
            assert f"short opening paragraph for remedy {number}" in page_text
    assert len(set(pages.values())) == 1


def test_actual_chapter_starts_on_a_fresh_page(tmp_path):
    output = tmp_path / "chapter-break.pdf"
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "Chapter Break"),
        StructuredBlock(BlockKind.BODY, "Previous section text " * 80),
        StructuredBlock(BlockKind.CHAPTER, "CHAPTER 4\nVASTU REMEDIES FOR HOME", level=1),
        StructuredBlock(BlockKind.BODY, "The chapter opening paragraph."),
    ]

    render_book(blocks, output)

    with pymupdf.open(output) as document:
        previous_page = next(i for i, page in enumerate(document) if "Previous section" in page.get_text("text"))
        chapter_page = next(
            i
            for i, page in enumerate(document)
            if "the chapter opening paragraph" in page.get_text("text").casefold()
        )
    assert chapter_page > previous_page


def test_toc_uses_real_columns_and_remedy_body_is_semantically_grouped():
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "Professional Book"),
        StructuredBlock(
            BlockKind.REMEDY,
            "33\nLord Kubera - God of Wealth, Lord of Wealth and Guardian of the Northern Side",
            chapter_id="33",
        ),
        StructuredBlock(BlockKind.BODY, "Opening paragraph.", chapter_id="33"),
        StructuredBlock(BlockKind.BODY, "Second paragraph.", chapter_id="33"),
    ]

    markup = build_book_html(blocks)

    assert "toc-number" in markup
    assert "toc-title" in markup
    assert "toc-leader" in markup
    assert "target-counter" in markup
    assert "remedy-opening" in markup
    assert "short-remedy" in markup


def test_cover_replacement_keeps_toc_targets_and_final_page_numbers_aligned(tmp_path):
    source = tmp_path / "source-cover.pdf"
    formatted = tmp_path / "formatted.pdf"
    final = tmp_path / "final.pdf"
    cover = pymupdf.open()
    cover_page = cover.new_page(width=595, height=842)
    cover_page.insert_text((72, 72), "SOURCE COVER")
    cover.save(source)
    cover.close()
    blocks = [
        StructuredBlock(BlockKind.BOOK_TITLE, "Aligned Book"),
        StructuredBlock(BlockKind.REMEDY, "01\nFirst Remedy", chapter_id="1"),
        StructuredBlock(BlockKind.BODY, "First body paragraph.", chapter_id="1"),
    ]
    render_book(blocks, formatted, protected_placeholder_count=1, include_title_page=False)
    prepend_protected_pages(
        source,
        formatted,
        final,
        [1],
        target_page_size=pymupdf.paper_size("A5"),
        replace_leading_pages=True,
    )

    with pymupdf.open(final) as document:
        assert len(document) == len(pymupdf.open(formatted))
        assert len({(round(page.rect.width, 1), round(page.rect.height, 1)) for page in document}) == 1
        toc_target = next(
            item[2] - 1
            for item in document.get_toc(simple=True)
            if "First Remedy" in item[1]
        )
        body_page = next(i for i, page in enumerate(document) if "First body paragraph" in page.get_text("text"))
        contents_text = next(page.get_text("text") for page in document if "Contents" in page.get_text("text"))
    assert toc_target == body_page
    assert str(body_page + 1) in contents_text
    report = verify_pdf(final)
    assert report["toc_links_checked"] >= 1
    assert report["toc_page_number_mismatches"] == []


