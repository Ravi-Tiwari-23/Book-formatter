from bookloom.matching import MatchCategory, PassageMatch, match_paragraphs
from bookloom.models import Decision, ReviewStatus
from bookloom.review import apply_decision, finalize_text
from bookloom.validation import build_corrections


def _match(source: str, reference: str, score: float = 96) -> PassageMatch:
    return PassageMatch(
        source_text=source,
        reference_text=reference,
        source_page=1,
        reference_page=5,
        score=score,
        category=MatchCategory.SPELLING_DIFFERENCE,
    )


def test_exact_reference_evidence_produces_high_confidence_suggestion():
    corrections = build_corrections(
        [_match("यह बहोत महत्वपूर्ण है।", "यह बहुत महत्वपूर्ण है।")],
        protected_terms={"मंत्र"},
    )
    assert corrections[0].suggested_text == "यह बहुत महत्वपूर्ण है।"
    assert corrections[0].confidence.value == "HIGH"
    assert corrections[0].status == ReviewStatus.PENDING


def test_punctuation_spacing_difference_is_safely_auto_approved():
    match = match_paragraphs(
        [(1, "Place it in the north , then continue .")],
        [(2, "Place it in the north, then continue.")],
    )[0]

    correction = build_corrections([match], protected_terms=set())[0]

    assert match.category == MatchCategory.SAFE_MATCH
    assert correction.status == ReviewStatus.APPROVED
    assert correction.final_text == correction.source_text
    assert correction.review_required is False


def test_protected_term_difference_requires_manual_review():
    correction = build_corrections(
        [_match("यह मंत्र पवित्र है।", "यह मन्त्र पवित्र है।")],
        protected_terms={"मंत्र", "मन्त्र"},
    )[0]
    assert correction.review_required is True
    assert correction.confidence.value == "LOW"


def test_manual_edit_becomes_authoritative_final_text():
    correction = build_corrections([_match("गलत", "सही")], protected_terms=set())[0]
    edited = apply_decision(correction, Decision.EDIT, manual_text="मान्य पाठ")
    assert finalize_text([edited]) == "मान्य पाठ"


def test_untouched_review_uses_its_conservative_default():
    correction = build_corrections([_match("गलत", "सही")], protected_terms=set())[0]
    assert finalize_text([correction]) == correction.source_text

