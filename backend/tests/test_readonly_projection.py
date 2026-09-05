"""TBX grants SELECT only, so the safe surface must travel with the query.

No CREATE VIEW, no CREATE INDEX, no writes of any kind against their database.
These tests assert the generated SQL carries its own joins and masking and stays
portable to MySQL.
"""
import pytest

from app.data.catalog import DatasetCatalog
from app.data.dialect import portability_problems
from app.data.projections import from_clause, projection_sql
from app.data.query_engine import GroundedQueryEngine
from app.schemas import QueryFilter, QueryPlan


def test_inlined_clause_carries_the_joins_and_the_masking():
    clause = from_clause("transaction", "", inline=True)
    assert clause.startswith("( SELECT")
    assert 'AS "transaction"' in clause
    assert "LEFT JOIN" in clause
    assert "account_last4" in clause and "utr_available" in clause


def test_the_projection_never_exposes_the_protected_columns():
    for dataset in ("bank", "account", "transaction"):
        sql = projection_sql(dataset, "")
        assert "AS account_number" not in sql
        assert "AS utr_number" not in sql


def test_projections_stay_mysql_portable():
    for dataset in ("bank", "account", "transaction"):
        assert portability_problems(projection_sql(dataset, "")) == [], dataset


def test_inlined_sql_needs_no_ddl():
    """Nothing in the generated SQL creates, drops or writes anything."""
    for dataset in ("bank", "account", "transaction"):
        sql = from_clause(dataset, "", inline=True).upper()
        for forbidden in ("CREATE ", "DROP ", "INSERT ", "UPDATE ", "DELETE ", "ALTER "):
            assert forbidden not in sql, (dataset, forbidden)


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


def test_the_owned_path_still_works(engine):
    result = engine.execute(QueryPlan(
        dataset="transaction", operation="sum", measure="transaction_amount",
        filters=[QueryFilter(column="transaction_type", operator="eq", value="debit")]))
    assert float(result.evidence.rows[0]["result"]) == pytest.approx(100.0)
    assert portability_problems(result.evidence.sql) == []
