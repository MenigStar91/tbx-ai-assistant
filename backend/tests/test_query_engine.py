from app.data.catalog import DatasetCatalog
from app.data.query_engine import GroundedQueryEngine
from app.schemas import QueryFilter, QueryPlan


def test_grounded_sum_and_filter(tmp_path):
    (tmp_path / "vendor_payouts.csv").write_text(
        "vendor,amount,status\nAcme,100,reconciled\nAcme,50,pending\nOther,40,pending\n"
    )
    engine = GroundedQueryEngine(DatasetCatalog(str(tmp_path)))
    result = engine.execute(QueryPlan(
        dataset="vendor_payouts", operation="sum", measure="amount",
        filters=[QueryFilter(column="vendor", operator="eq", value="Acme")],
    ))
    assert result.evidence.rows == [{"result": 150}]



def test_row_count_is_the_true_match_count_not_the_page_size(tmp_path):
    """A LIMIT must not change the number the user is told.

    Reporting len(rows) here is how "which transactions are unreconciled?"
    confidently answers 5 when the real answer is 12.
    """
    from app.data.catalog import DatasetCatalog
    from app.data.query_engine import GroundedQueryEngine
    from app.schemas import QueryPlan

    rows = "\n".join(f"TXN-{i},{i * 100},unreconciled" for i in range(1, 13))
    (tmp_path / "transactions.csv").write_text(f"transaction_id,amount,reconciliation_status\n{rows}\n")

    engine = GroundedQueryEngine(DatasetCatalog(str(tmp_path)))
    result = engine.execute(QueryPlan(dataset="transactions", operation="list", limit=5))

    assert result.evidence.returned_rows == 5
    assert result.evidence.total_rows == 12
    assert result.total_matching == 12


def test_aggregates_are_never_truncated_by_the_limit(tmp_path):
    from app.data.catalog import DatasetCatalog
    from app.data.query_engine import GroundedQueryEngine
    from app.schemas import QueryPlan

    rows = "\n".join(f"TXN-{i},Vendor {i},{i * 100}" for i in range(1, 7))
    (tmp_path / "transactions.csv").write_text(f"transaction_id,vendor_name,amount\n{rows}\n")

    engine = GroundedQueryEngine(DatasetCatalog(str(tmp_path)))
    result = engine.execute(
        QueryPlan(dataset="transactions", operation="sum", measure="amount",
                  group_by=["vendor_name"], limit=2)
    )

    # every group is returned; a limit of 2 would silently change the breakdown
    assert result.evidence.total_groups == 6
    assert len(result.evidence.rows) == 6
