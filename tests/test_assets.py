import hashlib

import pymupdf
from pypdf import PdfReader, PdfWriter

from bookloom.assets import AssetClass, classify_source_image, prepend_protected_pages


def _content_hash(page) -> str:
    content = page.get_contents()
    data = content.get_data() if content else b""
    return hashlib.sha256(data).hexdigest()


def test_protected_page_content_is_cloned_without_rewriting(tmp_path):
    source = tmp_path / "source.pdf"
    book = tmp_path / "book.pdf"
    output = tmp_path / "final.pdf"
    for path, text in [(source, "TRULOGGER ORIGINAL"), (book, "FORMATTED BOOK")]:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(path)
    original_hash = _content_hash(PdfReader(source).pages[0])

    records = prepend_protected_pages(source, book, output, [1])

    final_reader = PdfReader(output)
    assert _content_hash(final_reader.pages[0]) == original_hash
    assert records[0]["source_page"] == 1
    assert records[0]["content_sha256"] == original_hash


def test_source_images_receive_conservative_asset_classification():
    assert classify_source_image(1, (0, 0, 400, 600), 400, 600) == AssetClass.PROTECTED_BRANDING
    assert classify_source_image(4, (40, 100, 360, 500), 400, 600) == AssetClass.PROTECTED_PHOTO
    assert classify_source_image(4, None, 400, 600) == AssetClass.UNKNOWN


def test_protected_cover_is_fitted_to_the_book_page_size(tmp_path):
    source_path = tmp_path / "source.pdf"
    formatted_path = tmp_path / "formatted.pdf"
    output_path = tmp_path / "book.pdf"

    source = PdfWriter()
    source.add_blank_page(width=595, height=842)
    with source_path.open("wb") as stream:
        source.write(stream)

    formatted = PdfWriter()
    formatted.add_blank_page(width=420, height=595)
    formatted.add_blank_page(width=420, height=595)
    with formatted_path.open("wb") as stream:
        formatted.write(stream)

    records = prepend_protected_pages(
        source_path,
        formatted_path,
        output_path,
        [1],
        target_page_size=(420, 595),
    )

    pages = PdfReader(output_path).pages
    assert {(round(float(page.mediabox.width)), round(float(page.mediabox.height))) for page in pages} == {(420, 595)}
    assert records[0]["fit_mode"] == "cover"


