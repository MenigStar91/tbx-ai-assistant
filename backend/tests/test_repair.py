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
