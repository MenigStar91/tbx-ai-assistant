import pytest

from app.assistant import guards
from app.data.catalog import DatasetCatalog


@pytest.fixture()
def vocabulary(tmp_path):
    (tmp_path / "transactions.csv").write_text(
        "transaction_id,vendor_name,category,amount,reconciliation_status\n"
        "TXN-1,CloudScale Systems,Cloud Infrastructure,100,reconciled\n"
        "TXN-2,PeopleBridge Services,Payroll,200,unreconciled\n"
    )
    catalog = DatasetCatalog(str(tmp_path))
    connection = catalog.connection()
    try:
        return guards.build_vocabulary(catalog.describe(), connection)
    finally:
        connection.close()


def test_vocabulary_is_derived_from_the_data(vocabulary):
    assert "cloudscale" in vocabulary
    assert "unreconciled" in vocabulary
    assert "payroll" in vocabulary          # a real category here, so NOT a refusal trigger
    assert "ebitda" not in vocabulary


def test_subject_absent_from_the_data_is_refused(vocabulary):
    assert guards.unsupported_subject("What is our EBITDA?", vocabulary) == ["ebitda"]


def test_ordinary_question_is_not_refused(vocabulary):
    assert guards.unsupported_subject("Total spend by vendor last month", vocabulary) == []


def test_unknown_named_entity_is_refused(vocabulary):
    # the failure this guard exists for: without it the unknown vendor is dropped
    # and an unfiltered total is returned as though it answered the question
    assert guards.unresolved_entity("How much did we pay Globex Corporation?", vocabulary) == "Globex Corporation"


def test_known_vendor_passes(vocabulary):
    assert guards.unresolved_entity("How much did we pay CloudScale Systems?", vocabulary) is None


def test_capitalised_query_words_are_not_treated_as_entities(vocabulary):
    assert guards.unresolved_entity("Break down spend by vendor", vocabulary) is None


def test_forecasting_is_refused():
    assert guards.FORECAST_RE.search("What will our spend be next quarter?")
    assert not guards.FORECAST_RE.search("What was our spend last quarter?")


def test_indic_input_is_detected_and_skips_english_guards():
    assert guards.detect_language("पिछले महीने वेंडर पेआउट कितना था?") == "hi"
    assert guards.is_indic("hi") is True
    assert guards.detect_language("How much did we spend?") == "en"
