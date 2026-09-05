from app.assistant.service import AssistantService
from app.data.catalog import DatasetCatalog
from app.data.query_engine import GroundedQueryEngine
from app.providers.mock import MockProvider
from app.schemas import QueryPlan
from app.tools.registry import ToolRegistry


class CountingConnection:
    def __init__(self, wrapped, statements):
        self.wrapped = wrapped
        self.statements = statements

    def execute(self, sql, parameters=None):
        self.statements.append(sql)
        return self.wrapped.execute(sql, parameters or [])

    def close(self):
        self.wrapped.close()


class CountingCatalog:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.statements = []
        self.max_result_rows = 200

    def describe(self):
        return self.wrapped.describe()

    def connection(self):
        return CountingConnection(self.wrapped.connection(), self.statements)


def test_single_aggregate_uses_one_data_scan(tmp_path):
    (tmp_path / "payments.csv").write_text("amount\n10\n20\n")
    catalog = CountingCatalog(DatasetCatalog(str(tmp_path)))

    result = GroundedQueryEngine(catalog).execute(
        QueryPlan(dataset="payments", operation="sum", measure="amount")
    )

    assert result.evidence.rows == [{"result": 30}]
    assert result.evidence.total_rows == 2
    assert len(catalog.statements) == 1
    assert "__total_matching" in catalog.statements[0]


def test_list_reads_only_requested_columns(tmp_path):
    (tmp_path / "payments.csv").write_text(
        "payment_id,amount,description\np1,10,first\np2,20,second\n"
    )
    result = GroundedQueryEngine(DatasetCatalog(str(tmp_path))).execute(
        QueryPlan(
            dataset="payments",
            operation="list",
            select=["payment_id", "amount"],
            limit=2,
        )
    )

    assert result.evidence.columns == ["payment_id", "amount"]
    assert all("description" not in row for row in result.evidence.rows)


class MetadataOnlyCatalog:
    def describe(self):
        return {
            "latency_probe": [
                {"name": "probe_status", "type": "VARCHAR", "description": "Probe state"}
            ]
        }

    def schema_vocabulary(self):
        return {"latency", "probe", "status", "state"}

    def entity_values(self):
        return []

    def column_values(self):
        return {}

    def connection(self):
        raise AssertionError("metadata cache helpers must not scan production rows")


def test_mysql_metadata_helpers_do_not_open_a_data_connection():
    catalog = MetadataOnlyCatalog()
    service = AssistantService(MockProvider(), ToolRegistry(), catalog)
    described = catalog.describe()

    assert "status" in service._vocabulary(described)
    assert service._values(described) == []
    assert service._column_values(described) == {}
