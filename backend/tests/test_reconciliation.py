"""The breakdown must add up to the headline, or we do not show the number."""
import pytest

from app.data.catalog import DatasetCatalog
from app.data.query_engine import GroundedQueryEngine
from app.schemas import QueryPlan


@pytest.fixture()
def engine(tmp_path):
    rows = "\n".join(
        f"TXN-{i},Vendor {i % 3},{i * 100},2026-0{(i % 6) + 1}-01" for i in range(1, 13)
    )
    (tmp_path / "transactions.csv").write_text(f"transaction_id,vendor_name,amount,txn_date\n{rows}\n")
    return GroundedQueryEngine(DatasetCatalog(str(tmp_path)))


def test_grouped_sum_reconciles_against_the_ungrouped_total(engine):
    result = engine.execute(QueryPlan(dataset="transactions", operation="sum",
                                      measure="amount", group_by=["vendor_name"]))
    assert result.evidence.reconciles is True
    assert result.evidence.reconcile_note
    assert sum(row["result"] for row in result.evidence.rows) == pytest.approx(7800)


def test_grouped_count_reconciles(engine):
    result = engine.execute(QueryPlan(dataset="transactions", operation="count",
                                      group_by=["vendor_name"]))
    assert result.evidence.reconciles is True


def test_a_complete_listing_reconciles(engine):
    result = engine.execute(QueryPlan(
        dataset="transactions", operation="list",
        select=["transaction_id", "vendor_name", "amount"], limit=200
    ))
    assert result.evidence.reconciles is True
    assert "All 12" in result.evidence.reconcile_note


def test_a_truncated_listing_is_marked_unverified_not_failed(engine):
    result = engine.execute(QueryPlan(
        dataset="transactions", operation="list",
        select=["transaction_id", "vendor_name", "amount"], limit=5
    ))
    assert result.evidence.reconciles is None
    assert "5 of 12" in result.evidence.reconcile_note


def test_average_is_excluded_because_it_does_not_compose(engine):
    # the mean of group means is not the overall mean, so claiming a check here
    # would be worse than admitting one does not apply
    result = engine.execute(QueryPlan(dataset="transactions", operation="average",
                                      measure="amount", group_by=["vendor_name"]))
    assert result.evidence.reconciles is None


def test_a_single_aggregate_has_nothing_to_reconcile(engine):
    result = engine.execute(QueryPlan(dataset="transactions", operation="sum", measure="amount"))
    assert result.evidence.reconciles is None
