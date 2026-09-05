"""Deterministic semantic resolution between model plans and physical columns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


ALIASES = {
    "available_balance": {"available balance", "available funds", "funds available", "balance"},
    "ledger_balance": {"ledger balance", "book balance"},
    "transaction_amount": {"transaction amount", "amount", "spend", "spent", "paid"},
    "bank_name": {"bank", "bank name"},
    "bank_code": {"bank code"},
    "vendor_name": {"vendor", "vendor name", "supplier", "merchant"},
    "transaction_reference_id": {"reference", "reference number", "reference id", "ref no", "ref id"},
    "account_last4": {"account last four", "account last 4", "account ending"},
}


def normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def aliases(column: dict[str, str]) -> set[str]:
    name = column["name"]
    result = {normalise(name), *ALIASES.get(name, set())}
    if description := column.get("description"):
        result.add(normalise(description))
    return result


def score(term: str, column: dict[str, str]) -> float:
    wanted = normalise(term)
    candidates = aliases(column)
    if wanted in candidates:
        return 1.0
    return max((SequenceMatcher(None, wanted, item).ratio() for item in candidates), default=0.0)


def relevant_catalog(question: str, catalog: dict, max_tables: int = 3, max_columns: int = 20) -> dict:
    """Return the smallest safe schema slice likely to answer the question."""
    words = set(normalise(question).split())
    ranked_tables = []
    for table, columns in catalog.items():
        ranked_columns = []
        for position, column in enumerate(columns):
            terms = set().union(*(set(alias.split()) for alias in aliases(column)))
            relevance = len(words & terms) * 10 + max((score(token, column) for token in words), default=0)
            ranked_columns.append((relevance, -position, column))
        ranked_columns.sort(key=lambda item: (item[0], item[1]), reverse=True)
        table_score = max((item[0] for item in ranked_columns), default=0)
        if set(normalise(table).split()) & words:
            table_score += 20
        selected = [item[2] for item in ranked_columns[:max_columns]]
        ranked_tables.append((table_score, table, selected))
    ranked_tables.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return {table: columns for _, table, columns in ranked_tables[:max_tables]}


@dataclass
class FieldAmbiguity:
    slot: str
    prompt: str
    options: list[dict[str, str]]


def resolve_plan_fields(plan: dict, catalog: dict) -> tuple[dict, list[str], FieldAmbiguity | None]:
    """Repair unknown fields only when one candidate is unambiguous.

    The resolver never crosses datasets and never resolves UTR aliases. Close
    candidates are returned to the user instead of being guessed.
    """
    plan = dict(plan)
    dataset = plan.get("dataset")
    columns = catalog.get(dataset, [])
    names = {item["name"] for item in columns}
    mappings: list[str] = []

    def resolve(term: str | None, slot: str) -> str | FieldAmbiguity | None:
        if not term or term in names:
            return term
        if "utr" in normalise(term):
            return FieldAmbiguity(slot, "UTR is protected and cannot be substituted with another reference field.", [])
        if normalise(term) == "balance":
            balance_columns = [item for item in columns if item["name"].endswith("balance")]
            if len(balance_columns) > 1:
                return FieldAmbiguity(
                    slot, "Which balance do you mean?",
                    [{"label": item["name"].replace("_", " ").title(),
                      "value": item["name"], "description": item.get("description", "")}
                     for item in balance_columns[:8]],
                )
        ranked = sorted(((score(term, item), item) for item in columns), key=lambda item: item[0], reverse=True)
        plausible = [(value, item) for value, item in ranked if value >= 0.72]
        if not plausible:
            return FieldAmbiguity(slot, f'Which field should "{term}" use?', [])
        best_score, best = plausible[0]
        if best_score >= 0.92 and (len(plausible) == 1 or best_score - plausible[1][0] >= 0.08):
            mappings.append(f"{slot}: {term} -> {best['name']} ({best_score:.2f})")
            return best["name"]
        options = [
            {"label": item["name"].replace("_", " ").title(), "value": item["name"],
             "description": item.get("description", "")}
            for _, item in plausible[:8]
        ]
        return FieldAmbiguity(slot, f'Which field did you mean by "{term}"?', options)

    for key in ("measure",):
        result = resolve(plan.get(key), key)
        if isinstance(result, FieldAmbiguity):
            return plan, mappings, result
        plan[key] = result

    for key in ("group_by", "select"):
        resolved = []
        for index, term in enumerate(plan.get(key) or []):
            result = resolve(term, f"{key}:{index}")
            if isinstance(result, FieldAmbiguity):
                return plan, mappings, result
            resolved.append(result)
        plan[key] = resolved

    filters = []
    for index, item in enumerate(plan.get("filters") or []):
        item = dict(item)
        result = resolve(item.get("column"), f"filters:{index}:column")
        if isinstance(result, FieldAmbiguity):
            return plan, mappings, result
        item["column"] = result
        filters.append(item)
    plan["filters"] = filters
    return plan, mappings, None
