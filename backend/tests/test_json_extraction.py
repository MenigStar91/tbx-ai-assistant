"""Small models wrap their JSON in prose. These are the shapes they actually emit."""
import pytest

from app.assistant.service import AssistantService

extract = AssistantService._json_object


def test_plain_json():
    assert extract('{"dataset":"transactions","operation":"count"}')["operation"] == "count"


def test_fenced_json():
    assert extract('```json\n{"dataset":"transactions"}\n```')["dataset"] == "transactions"


def test_json_with_a_chatty_preamble():
    text = 'Sure! Here is the query plan:\n{"dataset":"vendor_payouts","operation":"sum"}\nHope that helps.'
    assert extract(text)["dataset"] == "vendor_payouts"


def test_nested_objects_are_matched_to_the_right_brace():
    text = 'Plan: {"dataset":"t","filters":[{"column":"status","operator":"eq","value":"open"}]} done'
    assert extract(text)["filters"][0]["value"] == "open"


def test_braces_inside_strings_do_not_confuse_the_matcher():
    assert extract('{"dataset":"t","measure":"a}b"}')["measure"] == "a}b"


def test_no_json_at_all_raises():
    with pytest.raises(Exception):
        extract("I am not sure what you mean.")
