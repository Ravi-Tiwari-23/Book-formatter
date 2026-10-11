import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from truelogger.pipeline import ProjectPipeline
from truelogger.models import Decision
from truelogger.document_analysis import analyze_document
from truelogger.extraction import extract_pdf


def make_document(path, pattern):
    document = pymupdf.open()
    if pattern == "chapters":
        for index in range(3):
            page = document.new_page(width=612, height=792)
            page.insert_text((55, 65), f"{index + 1}. Topic {index + 1}", fontsize=22, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(55, 100, 540, 700),
                                (f"This chapter explains topic {index + 1} through detailed observations and careful examples. " * 18), fontsize=11)
    elif pattern == "items":
        page = document.new_page(width=420, height=595)
        for index in range(4):
            y = 65 + index * 100
            page.insert_text((40, y), f"{index + 1}. Practical tip {index + 1}", fontsize=13, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(40, y + 14, 380, y + 80),
                                f"Use this short practical suggestion {index + 1} to organize the room and keep the space comfortable.", fontsize=10)
    elif pattern == "plain":
        page = document.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(50, 55, 550, 720),
                            "This unnumbered document has ordinary paragraphs with enough text to preserve their meaning.\n\nAnother paragraph contains names, numbers 1234 and a citation (Smith, 2020).", fontsize=11)
    elif pattern == "headings":
        page = document.new_page(width=612, height=792)
        for index, title in enumerate(("Introduction", "Observations", "Conclusions")):
            y = 65 + index * 170
            page.insert_text((55, y), title, fontsize=17, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(55, y + 20, 540, y + 140),
                                f"The {title.lower()} section provides useful context for readers. " * 5, fontsize=11)
    elif pattern == "images":
        page = document.new_page(width=612, height=792)
        for index, title in enumerate(("First observation", "Second observation")):
            y = 60 + index * 310
            page.insert_text((55, y), title, fontsize=17, fontname="hebo")
            page.insert_text((55, y + 30), f"The photograph documents observation {index + 1}.", fontsize=11)
            image = Image.new("RGB", (200, 100), "#895524" if index == 0 else "#246789")
            import io
            payload = io.BytesIO(); image.save(payload, format="PNG")
            page.insert_image(pymupdf.Rect(55, y + 55, 255, y + 155), stream=payload.getvalue())
    elif pattern == "toc":
        page = document.new_page()
        page.insert_text((55, 65), "Contents", fontsize=22)
        page.insert_text((55, 100), "1. Introduction ........ 2\n2. Observations ........ 3", fontsize=11)
        for index, title in enumerate(("Introduction", "Observations")):
            page = document.new_page()
            page.insert_text((55, 65), f"{index + 1}. {title}", fontsize=18, fontname="hebo")
            page.insert_textbox(pymupdf.Rect(55, 100, 540, 700), (f"{title} material includes examples and explanations. " * 30), fontsize=11)
    elif pattern == "table":
        page = document.new_page()
        page.insert_text((55, 65), "Measurements", fontsize=18, fontname="hebo")
        page.insert_text((55, 95), "The following table records the measured observations.", fontsize=11)
        for x in (55, 220, 420):
            page.draw_line((x, 130), (x, 250))
        for y in (130, 170, 210, 250):
            page.draw_line((55, y), (420, y))
        for y, row in zip((155, 195, 235), (("Region", "Value"), ("North", "15"), ("South", "25"))):
            page.insert_text((65, y), row[0], fontsize=11)
            page.insert_text((230, y), row[1], fontsize=11)
    elif pattern == "mixed_hindi":
        from truelogger.ocr import find_tesseract
        assert find_tesseract(), "This acceptance fixture requires local Hindi + English OCR"
        native = pymupdf.open(); page = native.new_page()
        page.insert_htmlbox(pymupdf.Rect(50, 50, 545, 750),
                            '<p>यह हिन्दी पुस्तक का पहला अनुच्छेद है। इसमें सामान्य जानकारी और उपयोगी विचार दिए गए हैं।</p><p>अगला अनुच्छेद पाठक को विषय समझने में सहायता करता है।</p>',
                            css='p {font-family: "Nirmala UI"; font-size: 18pt; line-height:1.7;}')
        scan = page.get_pixmap(dpi=200).tobytes("png")
        document.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=scan)
        page = document.new_page()
        page.insert_text((55, 80), "A native English page keeps its original text layer for extraction.", fontsize=11)
        native.close()
    else:
        raise ValueError(pattern)
    document.save(path)
    document.close()


def test_contrasting_documents_use_same_pipeline_without_configuration_changes(tmp_path):
    pipeline = ProjectPipeline(tmp_path / "cache")
    reports = {}
    for pattern in ("items", "chapters", "plain", "headings", "images", "toc", "table", "mixed_hindi"):
        source = tmp_path / f"{pattern}.pdf"
        make_document(source, pattern)
        project = pipeline.analyze(source, source)
        for item in list(project.corrections):
            project.decide(item.id, Decision.KEEP_SOURCE)
        artifacts = pipeline.build(project, tmp_path / pattern, production=True)
        qa = json.loads(artifacts.verification_report.read_text())
        assert qa["valid"], (pattern, qa)
        assert qa["text_integrity"]["passed"], (pattern, qa["text_integrity"])
        assert not qa["page_size_mismatches"]
        reports[pattern] = (project, artifacts)
    assert reports["items"][0].document_profile.numbered_items_compact
    assert not reports["items"][0].document_profile.major_heading_new_page
    assert sum(s.kind == "chapter" for s in reports["chapters"][0].source_sections) == 3
    assert reports["plain"][0].document_profile.cover_pages == []
    assert reports["plain"][0].document_profile.image_associations == []
    assert sum(s.kind == "section" for s in reports["headings"][0].source_sections) == 3
    assert reports["toc"][0].document_profile.toc_pages == [1]
    assert len(reports["table"][0].document_profile.tables) == 1
    assert reports["mixed_hindi"][0].document_profile.ocr_pages == [1]
    assert reports["mixed_hindi"][0].document_profile.language == "mixed"
    associations = reports["images"][0].document_profile.image_associations
    assert len({a["parent_section_id"] for a in associations}) == 2
    with pymupdf.open(reports["items"][1].pdf) as pdf:
        pages = [i for i, p in enumerate(pdf) if "Use this short" in p.get_text()]
        assert len(pages) == 1
    with pymupdf.open(reports["chapters"][1].pdf) as pdf:
        starts = [entry[2] for entry in pdf.get_toc() if "Topic" in entry[1]]
        assert len(set(starts)) == 3


def test_numbered_body_sentences_and_capitals_do_not_force_headings(tmp_path):
    pdf = pymupdf.open(); page = pdf.new_page()
    page.insert_text((60, 70), "IMPORTANT NOTICE\n1. This is an ordinary list sentence.\n2. This sentence is also ordinary.\nThe body continues after the list.", fontsize=11)
    path = tmp_path / "ordinary.pdf"; pdf.save(path); pdf.close()
    profile = analyze_document(extract_pdf(path))
    assert not profile.major_heading_new_page
    assert all(s.kind == "body_paragraph" for s in profile.sections)
    assert profile.low_confidence_blocks


def test_reference_layout_does_not_change_source_profile(tmp_path):
    source = tmp_path / "source.pdf"; reference = tmp_path / "reference.pdf"
    make_document(source, "items"); make_document(reference, "chapters")
    pipeline = ProjectPipeline(tmp_path / "cache")
    a = pipeline.analyze(source, source)
    b = pipeline.analyze(source, reference)
    assert a.document_profile.to_dict() == b.document_profile.to_dict()
    assert all(item.final_text in (None, item.source_text) for item in b.corrections)


def test_internal_section_ids_are_not_reference_matching_evidence():
    from truelogger.models import BookSection
    from truelogger.sections import align_sections
    source = [BookSection(1, 'Astronomy', ['Stars and galaxies'], 1, 1)]
    reference = [BookSection(1, 'Cooking', ['Soup recipes'], 1, 1)]
    assert align_sections(source, reference, match_numbers=False)[0].reference is None


def test_mixed_index_page_does_not_discard_body_or_metadata(tmp_path):
    pdf = pymupdf.open(); page = pdf.new_page()
    page.insert_text((50, 65), 'Published by Example Press\nAuthor: A Writer\nEdition 2020\nISBN 123456\nSome introduction\nIndex\n1. First topic\nThis page also has essential body content.', fontsize=11)
    path = tmp_path / 'mixed-index.pdf'; pdf.save(path); pdf.close()
    profile = analyze_document(extract_pdf(path))
    assert profile.toc_pages == []
    assert 'essential body content' in ' '.join(s.raw_text for s in profile.sections)


def test_hindi_rendered_text_qa_still_detects_changed_words(tmp_path):
    from truelogger.integrity import TextUnit, verify_rendered_pdf
    from truelogger.models import BlockKind, StructuredBlock
    from truelogger.rendering import render_book
    text = 'हिन्दी विचार दिए गए हैं। विषय और विज्ञान सुरक्षित हैं।'
    output = render_book([StructuredBlock(BlockKind.BODY, text)], tmp_path / 'unicode.pdf', include_title_page=False)
    assert verify_rendered_pdf(output, [TextUnit('1', '1', '', 0, text)]).passed
    assert not verify_rendered_pdf(output, [TextUnit('1', '1', '', 0, text.replace('विज्ञान', 'गणित'))]).passed
