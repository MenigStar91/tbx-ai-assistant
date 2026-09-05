from app.assistant.followups import merge_follow_up
from app.schemas import QueryFilter, QueryPlan


def plan(**updates) -> QueryPlan:
    values = {
        "dataset": "transaction",
        "operation": "sum",
        "measure": "transaction_amount",
        "group_by": [],
        "filters": [QueryFilter(column="transaction_type", operator="eq", value="debit")],
    }
    values.update(updates)
    return QueryPlan(**values)


def test_standalone_question_does_not_leak_previous_filters():
    current = plan(filters=[])
    merged, repairs = merge_follow_up(current, plan(), "What is the total transaction amount?")
    assert merged.filters == []
    assert repairs == []


def test_follow_up_inherits_and_replaces_filters_by_column():
    previous = plan(filters=[
        QueryFilter(column="transaction_type", operator="eq", value="debit"),
        QueryFilter(column="bank_code", operator="eq", value="ICICI"),
    ])
    current = plan(
        operation="list",
        measure=None,
        filters=[QueryFilter(column="bank_code", operator="eq", value="HDFC")],
    )
    merged, _ = merge_follow_up(current, previous, "Now show only bank code HDFC")
    assert [(item.column, item.value) for item in merged.filters] == [
        ("transaction_type", "debit"), ("bank_code", "HDFC")
    ]


def test_follow_up_can_remove_a_named_filter():
    previous = plan(filters=[QueryFilter(column="bank_code", operator="eq", value="HDFC")])
    current = plan(filters=[])
    merged, repairs = merge_follow_up(current, previous, "Now without bank code")
    assert merged.filters == []
    assert any("removed" in item for item in repairs)
