import fitz

from truelogger.extraction import extract_pdf


def test_text_pdf_is_extracted_without_ocr(tmp_path):
    path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Reference based validation")
    document.save(path)

    result = extract_pdf(path)

    assert result.page_count == 1
    assert result.pages[0].used_ocr is False
    assert "Reference based validation" in result.pages[0].text

