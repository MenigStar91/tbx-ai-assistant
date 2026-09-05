import pytest

from app.assistant.guards import missing_capability, sensitive_request
from app.data.catalog import DatasetCatalog
from app.data.query_engine import GroundedQueryEngine
from app.schemas import QueryFilter, QueryPlan


def _write_final_schema(directory):
    (directory / "bank.csv").write_text("bank_code,bank_name\nHDFC,HDFC Bank\n")
    (directory / "account.csv").write_text(
        "account_id,entity_id,account_number,program_id,available_balance,bank_code\n"
        "A1,E1,5010010000012345,101,425000.00,HDFC\n"
    )
    (directory / "transaction.csv").write_text(
        "transaction_id,account_id,transaction_date,transaction_type,description,"
        "transaction_amount,transaction_reference_id,utr_number\n"
        "T1,A1,2026-08-12 11:10:00.000000,debit,Subscription,135000.00,REF-1,SECRET-UTR\n"
    )


def test_final_schema_exposes_only_safe_joined_views(tmp_path):
    _write_final_schema(tmp_path)
    catalog = DatasetCatalog(str(tmp_path)).describe()

    assert set(catalog) == {"bank", "account", "transaction"}
    account_columns = {column["name"] for column in catalog["account"]}
    transaction_columns = {column["name"] for column in catalog["transaction"]}
    assert "account_number" not in account_columns
    assert "utr_number" not in transaction_columns
    assert {"account_last4", "bank_name"} <= account_columns
    assert {"account_last4", "bank_name", "utr_available"} <= transaction_columns


def test_results_and_exports_cannot_contain_protected_values(tmp_path):
    _write_final_schema(tmp_path)
    engine = GroundedQueryEngine(DatasetCatalog(str(tmp_path)))
    result = engine.execute(QueryPlan(dataset="transaction", operation="list"))

    assert result.evidence.rows[0]["account_last4"] == "2345"
    assert result.evidence.rows[0]["bank_name"] == "HDFC Bank"
    assert "5010010000012345" not in result.csv_content
    assert "SECRET-UTR" not in result.csv_content


def test_joined_bank_filter_and_aggregate(tmp_path):
    _write_final_schema(tmp_path)
    result = GroundedQueryEngine(DatasetCatalog(str(tmp_path))).execute(
        QueryPlan(
            dataset="transaction",
            operation="sum",
            measure="transaction_amount",
            filters=[QueryFilter(column="bank_code", operator="eq", value="HDFC")],
        )
    )
    assert result.evidence.rows == [{"result": pytest.approx(135000)}]


@pytest.mark.parametrize("question", ["Show every UTR", "Find UTR number ABC123"])
def test_utr_requests_are_blocked_before_the_model(question):
    assert sensitive_request(question)[1] == "protected_utr"


def test_full_account_number_request_is_blocked_but_last4_is_allowed():
    assert sensitive_request("Show the full account number")[1] == "protected_account_number"
    assert sensitive_request("Show the account ending in last 4 digits 2345") is None


def test_missing_domain_data_names_the_required_contract():
    vendor_message, vendor_reason = missing_capability("Which vendor had the highest spend?")
    assert vendor_reason == "missing_vendor_mapping"
    assert "transaction-to-vendor mapping" in vendor_message

    ledger_message, ledger_reason = missing_capability("Does double entry reconciliation match?")
    assert ledger_reason == "missing_ledger_entries"
    assert "journal_id" in ledger_message


def test_discovered_domain_columns_are_not_rejected_as_missing():
    vendor_catalog = {"spend": [{"name": "vendor_id", "type": "varchar"}]}
    ledger_catalog = {"journal": [
        {"name": "debit_amount", "type": "decimal"},
        {"name": "credit_amount", "type": "decimal"},
    ]}
    assert missing_capability("Spend by vendor", vendor_catalog) is None
    assert missing_capability("Check ledger reconciliation", ledger_catalog) is None
