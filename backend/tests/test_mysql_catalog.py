import pytest

from app.data.mysql_catalog import (
    MySQLConnectionAdapter,
    MySQLDatasetCatalog,
    QueryPolicyError,
)
from app.schemas import QueryFilter, QueryPlan


def catalog(tmp_path) -> MySQLDatasetCatalog:
    return MySQLDatasetCatalog(
        host="unused",
        port=3306,
        database="test",
        user="test",
        password="test",
        upload_directory=str(tmp_path),
        data_max_date="2026-08-31",
    )


def test_csv_type_inference_keeps_identifiers_as_text():
    assert MySQLDatasetCatalog._column_type("account_id", ["001", "002"]) == "VARCHAR(255)"
    assert MySQLDatasetCatalog._column_type("transaction_amount", ["10.25", "20"]) == "DECIMAL(20,6)"
    assert MySQLDatasetCatalog._column_type("transaction_date", ["2026-08-01"]) == "DATETIME"


def test_date_anchor_is_metadata_configuration_not_a_table_scan(tmp_path):
    instance = catalog(tmp_path)
    assert instance.date_bounds() == (None, "2026-08-31")
    assert instance.column_date_bounds() == {}


def test_schema_vocabulary_uses_optional_descriptions_without_rows(tmp_path):
    instance = catalog(tmp_path)
    instance._catalog_cache = {
        "transaction": [
            {"name": "transaction_amount", "type": "decimal", "description": "Posted amount"}
        ]
    }
    assert {"transaction", "amount", "posted"} <= instance.schema_vocabulary()


def test_broad_transaction_queries_require_a_time_filter(tmp_path):
    instance = catalog(tmp_path)
    instance.require_time_filter_tables = {"transaction"}
    instance._catalog_cache = {
        "transaction": [
            {"name": "transaction_date", "type": "datetime"},
            {"name": "transaction_amount", "type": "decimal"},
        ]
    }
    with pytest.raises(QueryPolicyError, match="require a date/time filter"):
        instance.validate_plan(QueryPlan(
            dataset="transaction", operation="sum", measure="transaction_amount"
        ))


def test_time_scoped_and_point_lookup_transaction_queries_are_allowed(tmp_path):
    instance = catalog(tmp_path)
    instance.require_time_filter_tables = {"transaction"}
    instance._catalog_cache = {
        "transaction": [
            {"name": "transaction_date", "type": "datetime"},
            {"name": "transaction_reference_id", "type": "varchar"},
        ]
    }
    instance.validate_plan(QueryPlan(
        dataset="transaction", operation="count",
        filters=[QueryFilter(column="transaction_date", operator="gte", value="2026-08-01")],
    ))
    instance.validate_plan(QueryPlan(
        dataset="transaction", operation="count",
        filters=[QueryFilter(column="transaction_reference_id", operator="eq", value="REF-1")],
    ))


def test_explain_cost_is_read_from_nested_mysql_plan():
    payload = {"query_block": {"cost_info": {"query_cost": "42.75"}}}
    assert MySQLConnectionAdapter._query_cost(payload) == pytest.approx(42.75)


def test_database_identifier_is_validated_before_grant_sql(tmp_path):
    with pytest.raises(ValueError, match="database name"):
        MySQLDatasetCatalog(
            host="unused", port=3306, database="bad-name`; DROP DATABASE test",
            user="test", password="test", upload_directory=str(tmp_path),
        )
