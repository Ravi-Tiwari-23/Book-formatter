from truelogger.matching import MatchCategory, match_paragraphs, normalize_text


def test_normalize_text_preserves_devanagari_but_normalizes_spacing():
    assert normalize_text("  यह  बहुत\nमहत्वपूर्ण है। ") == "यह बहुत महत्वपूर्ण है।"


def test_matching_finds_reference_correction_without_using_page_numbers():
    source = [(9, "यह बहोत महत्वपूर्ण अध्याय है।")]
    reference = [(2, "यह बहुत महत्वपूर्ण अध्याय है।")]

    result = match_paragraphs(source, reference)

    assert result[0].reference_page == 2
    assert result[0].category in {
        MatchCategory.SPELLING_DIFFERENCE,
        MatchCategory.MINOR_DIFFERENCE,
    }
    assert result[0].score >= 80


def test_matching_marks_unrelated_source_as_source_only():
    result = match_paragraphs([(1, "पूरी तरह अलग सामग्री")], [(4, "Completely unrelated text")])
    assert result[0].category == MatchCategory.SOURCE_ONLY

