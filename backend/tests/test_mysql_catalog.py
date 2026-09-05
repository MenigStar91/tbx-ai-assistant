from app.data.mysql_catalog import MySQLDatasetCatalog


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
