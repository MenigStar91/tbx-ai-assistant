import json

import pytest

from app.assistant.service import AssistantService
from app.assistant.followups import merge_follow_up
from app.data.catalog import DatasetCatalog
from app.schemas import ChatRequest, Message, ProviderResponse, QueryFilter, QueryPlan
from app.tools.registry import ToolRegistry


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


def test_short_leading_connective_is_a_follow_up():
    previous = plan(filters=[QueryFilter(column="transaction_type", operator="eq", value="debit")])
    current = plan(filters=[QueryFilter(column="bank_code", operator="eq", value="HDFC")])
    merged, repairs = merge_follow_up(current, previous, "And at HDFC?")
    assert [(item.column, item.value) for item in merged.filters] == [
        ("transaction_type", "debit"), ("bank_code", "HDFC")
    ]
    assert repairs


def test_bank_name_replaces_an_inherited_bank_code():
    previous = plan(filters=[
        QueryFilter(column="transaction_type", operator="eq", value="debit"),
        QueryFilter(column="bank_code", operator="eq", value="HDFC"),
    ])
    current = plan(filters=[QueryFilter(column="bank_name", operator="eq", value="ICICI BANK")])
    merged, _ = merge_follow_up(current, previous, "And at ICICI Bank?")
    assert [(item.column, item.value) for item in merged.filters] == [
        ("transaction_type", "debit"), ("bank_name", "ICICI BANK")
    ]


def test_overall_total_drops_entity_scope_but_keeps_period_and_direction():
    previous = plan(
        group_by=["bank_name"],
        filters=[
            QueryFilter(column="transaction_type", operator="eq", value="debit"),
            QueryFilter(column="bank_code", operator="eq", value="HDFC"),
            QueryFilter(column="transaction_date", operator="gte", value="2026-08-01"),
            QueryFilter(column="transaction_date", operator="lte", value="2026-08-31"),
        ],
    )
    current = plan(group_by=[], filters=[
        QueryFilter(column="transaction_type", operator="eq", value="debit")
    ])
    merged, repairs = merge_follow_up(current, previous, "And total spent?")
    assert merged.group_by == []
    assert not any(item.column in {"bank_code", "bank_name"} for item in merged.filters)
    assert {item.column for item in merged.filters} == {"transaction_type", "transaction_date"}
    assert any("widened" in item for item in repairs)


@pytest.mark.asyncio
async def test_planner_receives_previous_plan_without_replaying_transcript(tmp_path):
    (tmp_path / "transactions.csv").write_text(
        "transaction_date,transaction_type,transaction_amount\n"
        "2026-08-01,debit,100\n"
    )

    class RecordingProvider:
        messages = []

        async def generate(self, messages):
            self.messages = messages
            return ProviderResponse(content=json.dumps({
                "dataset": "transactions", "operation": "sum",
                "measure": "transaction_amount", "group_by": [], "select": [],
                "filters": [], "limit": 50,
            }))

    provider = RecordingProvider()
    service = AssistantService(provider, ToolRegistry(), DatasetCatalog(str(tmp_path)))
    previous = QueryPlan(
        dataset="transactions", operation="sum", measure="transaction_amount",
        filters=[QueryFilter(column="transaction_type", operator="eq", value="debit")],
    )
    await service.respond(ChatRequest(
        message="And total?", previous_plan=previous,
        history=[
            Message(role="user", content="STALE BANK FILTER"),
            Message(role="assistant", content="STALE ANSWER"),
        ],
    ))

    sent = "\n".join(message.content for message in provider.messages)
    assert "PREVIOUS_VALIDATED_PLAN=" in sent
    assert "STALE BANK FILTER" not in sent
    assert "STALE ANSWER" not in sent
