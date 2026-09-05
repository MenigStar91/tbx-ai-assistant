"""The generated SQL must run on MySQL, not just DuckDB.

The prototype reads files through DuckDB; the real dataset is MySQL. These
tests fail the moment a DuckDB-only construct reaches the query builder, so the
switch is a configuration change rather than a debugging session.
"""
import pytest

from app.data.catalog import DatasetCatalog
from app.data.dialect import portability_problems, to_driver_params
from app.data.query_engine import GroundedQueryEngine
from app.schemas import QueryFilter, QueryPlan


@pytest.fixture()
def engine(tmp_path):
    (tmp_path / "bank.csv").write_text("bank_code,bank_name\nHDFC,HDFC BANK LIMITED\n")
    (tmp_path / "account.csv").write_text(
        "account_id,entity_id,account_number,program_id,available_balance,bank_code\n"
        "a1,e1,50200013729069,21,100.00,HDFC\n")
    (tmp_path / "transaction.csv").write_text(
        "transaction_id,account_id,transaction_date,transaction_type,description,"
        "transaction_amount,transaction_reference_id,utr_number\n"
        "t1,a1,2026-06-01 10:00:00,debit,NEFT - X,100.00,REF1,UTR1\n")
    return GroundedQueryEngine(DatasetCatalog(str(tmp_path)))


def _sql(engine, plan):
    return engine.execute(plan).evidence.sql


def test_aggregate_sql_is_portable(engine):
    sql = _sql(engine, QueryPlan(dataset="transaction", operation="sum",
                                 measure="transaction_amount"))
    assert portability_problems(sql) == [], sql


def test_grouped_sql_avoids_nulls_last(engine):
    sql = _sql(engine, QueryPlan(dataset="transaction", operation="sum",
                                 measure="transaction_amount", group_by=["bank_name"]))
    assert "NULLS LAST" not in sql.upper()
    assert "(result IS NULL)" in sql
    assert portability_problems(sql) == []


def test_filtered_sql_is_portable(engine):
    sql = _sql(engine, QueryPlan(
        dataset="transaction", operation="count",
        filters=[QueryFilter(column="bank_code", operator="eq", value="HDFC"),
                 QueryFilter(column="description", operator="contains", value="NEFT")]))
    assert portability_problems(sql) == [], sql


def test_listing_sql_is_portable(engine):
    sql = _sql(engine, QueryPlan(dataset="transaction", operation="list", limit=5))
    assert portability_problems(sql) == [], sql


def test_placeholder_rewrite_leaves_quoted_text_alone():
    assert to_driver_params('SELECT ? FROM "t" WHERE c = ?') == 'SELECT %s FROM "t" WHERE c = %s'
    assert to_driver_params("SELECT '?' , ?") == "SELECT '?' , %s"


def test_detector_actually_catches_duckdb_isms():
    assert portability_problems("SELECT CAST(x AS VARCHAR)")
    assert portability_problems("SELECT 1 ORDER BY a DESC NULLS LAST")
    assert portability_problems("SELECT `x`")
    assert portability_problems("SELECT * FROM read_csv_auto('a.csv')")
