from truelogger.models import BlockKind
from truelogger.structure import detect_structure


def test_structure_detects_title_chapter_heading_verse_and_body():
    text = """ज्योतिष परिचय

अध्याय 1: प्रारम्भ

ग्रहों का परिचय

यह सामान्य गद्य का अनुच्छेद है जिसमें पर्याप्त शब्द हैं और यह पुस्तक की सामग्री समझाता है।

ॐ नमः शिवाय।
ॐ शान्तिः शान्तिः शान्तिः॥"""
    kinds = [block.kind for block in detect_structure(text)]
    assert kinds[0] == BlockKind.BOOK_TITLE
    assert BlockKind.CHAPTER in kinds
    assert BlockKind.HEADING in kinds
    assert BlockKind.BODY in kinds
    assert BlockKind.VERSE in kinds


def test_numbered_remedy_is_not_misclassified_as_a_chapter():
    blocks = detect_structure("""A Vastu Book

33 LORD KUBERA - GOD OF WEALTH

Kubera is considered the guardian of wealth.""")

    assert blocks[1].kind == BlockKind.NUMBERED_ITEM
    assert blocks[1].level == 3

