"""The repeatable mistakes a sub-1B planner makes, and the repairs for them."""
from app.assistant.repair import repair_plan

CATALOG = {
    "transactions": [
        {"name": "transaction_id", "type": "VARCHAR"},
        {"name": "transaction_date", "type": "DATE"},
        {"name": "vendor_name", "type": "VARCHAR"},
        {"name": "amount", "type": "BIGINT"},
        {"name": "reconciliation_status", "type": "VARCHAR"},
    ],
    "vendors": [{"name": "vendor_id", "type": "VARCHAR"}, {"name": "vendor_name", "type": "VARCHAR"}],
    "vendor_payouts": [
        {"name": "payout_id", "type": "VARCHAR"},
        {"name": "payout_date", "type": "DATE"},
        {"name": "amount", "type": "BIGINT"},
        {"name": "status", "type": "VARCHAR"},
    ],
}


def test_spurious_grouping_is_dropped():
    # observed: "total transaction amount" came back grouped by transaction_date,
    # which reports the first day instead of the total
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": "amount", "group_by": ["transaction_date"]},
        "What is the total transaction amount?", CATALOG)
    assert plan["group_by"] == []
    assert repairs


def test_a_real_breakdown_keeps_its_grouping():
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": "amount", "group_by": ["vendor_name"]},
        "Break down spend by vendor", CATALOG)
    assert plan["group_by"] == ["vendor_name"]
    assert repairs == []


def test_dataset_named_in_the_question_wins():
    # observed: "how many vendor payouts" planned against `vendors`
    plan, repairs = repair_plan(
        {"dataset": "vendors", "operation": "count", "measure": "vendor_name", "group_by": [], "filters": []},
        "How many vendor payouts are there?", CATALOG)
    assert plan["dataset"] == "vendor_payouts"


def test_the_more_specific_dataset_name_wins():
    plan, _ = repair_plan(
        {"dataset": "transactions", "operation": "count", "group_by": [], "filters": []},
        "How many vendor payouts are there?", CATALOG)
    assert plan["dataset"] == "vendor_payouts"


def test_dataset_is_not_switched_when_columns_would_break():
    # reconciliation_status does not exist on vendor_payouts, so leave it alone
    # and let plan validation refuse rather than silently querying the wrong thing
    plan, _ = repair_plan(
        {"dataset": "transactions", "operation": "list", "group_by": [],
         "filters": [{"column": "reconciliation_status", "operator": "eq", "value": "unreconciled"}]},
        "Which vendor payouts are unreconciled?", CATALOG)
    assert plan["dataset"] == "transactions"


def test_measure_is_cleared_for_count():
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "count", "measure": "vendor_name", "group_by": []},
        "How many transactions are there?", CATALOG)
    assert plan["measure"] is None


def test_missing_measure_is_filled_for_an_aggregate():
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": None, "group_by": []},
        "What is the total?", CATALOG)
    assert plan["measure"] == "amount"


def test_repair_never_invents_a_filter():
    plan, _ = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": "amount", "group_by": [], "filters": []},
        "What is the total transaction amount?", CATALOG)
    assert plan["filters"] == []


def test_filter_values_are_canonicalised_to_real_names():
    # "CloudScale Corp" filtered literally matches nothing and returns a
    # confident empty result, which reads as an answer
    values = ["CloudScale Systems", "Northwind Cloud"]
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": "amount", "group_by": [],
         "filters": [{"column": "vendor_name", "operator": "eq", "value": "CloudScale Corp"}]},
        "How much did we pay CloudScale Corp?", CATALOG, values)
    assert plan["filters"][0]["value"] == "CloudScale Systems"
    assert any("resolved" in r for r in repairs)


def test_an_exact_value_is_left_alone():
    values = ["CloudScale Systems"]
    plan, repairs = repair_plan(
        {"dataset": "transactions", "operation": "sum", "measure": "amount", "group_by": [],
         "filters": [{"column": "vendor_name", "operator": "eq", "value": "CloudScale Systems"}]},
        "spend for CloudScale Systems", CATALOG, values)
    assert plan["filters"][0]["value"] == "CloudScale Systems"
    assert not any("resolved" in r for r in repairs)


def test_a_negated_filter_without_a_negation_is_flipped():
    # "how many vendor payouts failed" -> status neq failed counts the successes
    plan, repairs = repair_plan(
        {"dataset": "vendor_payouts", "operation": "count", "group_by": [],
         "filters": [{"column": "status", "operator": "neq", "value": "failed"}]},
        "How many vendor payouts failed?", CATALOG)
    assert plan["filters"][0]["operator"] == "eq"
    assert any("neq -> eq" in r for r in repairs)


def test_a_real_negation_keeps_neq():
    plan, repairs = repair_plan(
        {"dataset": "vendor_payouts", "operation": "count", "group_by": [],
         "filters": [{"column": "status", "operator": "neq", "value": "paid"}]},
        "How many payouts are not paid?", CATALOG)
    assert plan["filters"][0]["operator"] == "neq"


def test_unreconciled_style_wording_keeps_neq():
    plan, _ = repair_plan(
        {"dataset": "transactions", "operation": "list", "group_by": [],
         "filters": [{"column": "reconciliation_status", "operator": "neq", "value": "reconciled"}]},
        "Which transactions are still outstanding?", CATALOG)
    assert plan["filters"][0]["operator"] == "neq"
