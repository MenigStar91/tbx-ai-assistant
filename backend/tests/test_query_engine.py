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

