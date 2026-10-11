from truelogger.grammar import validate_grammar


def test_duplicate_token_is_reported_conservatively():
    findings = validate_grammar("यह यह महत्वपूर्ण है।", protected_terms=set())
    assert findings[0].suggested_text == "यह महत्वपूर्ण है।"
    assert findings[0].rule_id == "duplicate-token"


def test_mantra_and_protected_text_are_not_grammar_corrected():
    assert validate_grammar("ॐ ॐ नमः शिवाय॥", protected_terms={"मंत्र"}) == []
    assert validate_grammar("राहु राहु का उल्लेख", protected_terms={"राहु"}) == []

