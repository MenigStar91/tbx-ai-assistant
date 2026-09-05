from app.assistant.semantic import relevant_catalog, resolve_plan_fields


CATALOG = {
    "account": [
        {"name": "available_balance", "type": "decimal", "description": "Funds available"},
        {"name": "ledger_balance", "type": "decimal", "description": "Book balance"},
        {"name": "bank_name", "type": "varchar"},
    ],
    "transaction": [
        {"name": "transaction_reference_id", "type": "varchar"},
    ],
}


def test_clear_alias_resolves_to_physical_field():
    plan, mappings, ambiguity = resolve_plan_fields(
        {"dataset": "account", "operation": "sum", "measure": "available funds",
         "group_by": ["bank name"], "select": [], "filters": []},
        CATALOG,
    )
    assert plan["measure"] == "available_balance"
    assert plan["group_by"] == ["bank_name"]
    assert mappings
    assert ambiguity is None


def test_directional_amount_alias_maps_to_transaction_amount():
    catalog = {"transaction": [
        {"name": "transaction_amount", "type": "decimal"},
        {"name": "transaction_type", "type": "varchar"},
    ]}
    plan, _, ambiguity = resolve_plan_fields(
        {"dataset": "transaction", "operation": "sum", "measure": "credit amount",
         "group_by": [], "select": [], "filters": []},
        catalog,
    )
    assert plan["measure"] == "transaction_amount"
    assert ambiguity is None


def test_ambiguous_balance_is_not_guessed():
    _, _, ambiguity = resolve_plan_fields(
        {"dataset": "account", "operation": "sum", "measure": "balance",
         "group_by": [], "select": [], "filters": []},
        CATALOG,
    )
    assert ambiguity is not None
    assert {item["value"] for item in ambiguity.options} == {
        "available_balance", "ledger_balance"
    }


def test_utr_is_never_substituted_for_plain_reference():
    _, _, ambiguity = resolve_plan_fields(
        {"dataset": "transaction", "operation": "count", "measure": None,
         "group_by": [], "select": [],
         "filters": [{"column": "utr number", "operator": "eq", "value": "X"}]},
        CATALOG,
    )
    assert ambiguity is not None
    assert not ambiguity.options


def test_planner_catalog_is_bounded_and_keeps_relevant_fields():
    catalog = {
        f"table_{index}": [
            {"name": f"field_{column}", "type": "varchar"} for column in range(30)
        ] for index in range(6)
    }
    catalog["account"] = CATALOG["account"]
    selected = relevant_catalog("available balance by bank", catalog)
    assert "account" in selected
    assert len(selected) <= 3
    assert all(len(columns) <= 20 for columns in selected.values())
    assert {"available_balance", "bank_name"} <= {
        column["name"] for column in selected["account"]
    }
