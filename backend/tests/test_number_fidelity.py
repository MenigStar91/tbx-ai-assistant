from app.assistant.narrate import verify_numbers


def test_a_clean_template_answer_passes():
    ok, orphans = verify_numbers("The total is 958,750 across 7 records.", {"958,750", "7"})
    assert ok and orphans == []


def test_an_invented_figure_is_caught():
    ok, orphans = verify_numbers("The total is 958,750 and also 999.99", {"958,750"})
    assert not ok and "999.99" in orphans


def test_text_with_no_numbers_passes():
    assert verify_numbers("No rows matched that request.", set()) == (True, [])


def test_a_trailing_sentence_comma_is_not_part_of_the_numeral():
    # "...is 958,750, computed over 7 records" must not read as the number "958,750,"
    ok, orphans = verify_numbers(
        "The total is 958,750, computed over 7 records.", {"958,750", "7"}
    )
    assert ok, orphans


def test_thousands_separators_are_kept_together():
    from app.assistant.narrate import NUMERAL_RE
    assert NUMERAL_RE.findall("1,440,750.00 and 7") == ["1,440,750.00", "7"]
