import json
import re
import time
from datetime import date, timedelta

from app.schemas import Message, ProviderResponse


def _parse_catalog(system: str) -> dict[str, list[dict[str, str]]]:
    """Read the table listing back out of the planner prompt.

    Supports the compact "table: col, col" format and the older
    AVAILABLE_DATASETS_JSON= line, so the mock keeps working as the offline
    planner and the demo fallback whatever the prompt looks like.
    """
    marker = "AVAILABLE_DATASETS_JSON="
    if marker in system:
        try:
            return json.loads(system.split(marker, 1)[1].split("\n", 1)[0])
        except json.JSONDecodeError:
            return {}

    catalog: dict[str, list[dict[str, str]]] = {}
    for line in system.splitlines():
        match = re.match(r"^([a-z0-9_]+):\s*(.+)$", line.strip())
        if not match:
            continue
        name, columns = match.group(1), match.group(2)
        if "," not in columns and " " in columns:
            continue
        catalog[name] = [{"name": c.strip(), "type": "VARCHAR"} for c in columns.split(",") if c.strip()]
    return catalog


def _estimate_tokens(text: str) -> int:
    """~4 characters per token. Only used by the mock provider; real providers
    report their own usage."""
    return max(1, len(text) // 4)


class MockProvider:
    async def generate(self, messages: list[Message]) -> ProviderResponse:
        started = time.monotonic()
        user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        system = messages[0].content if messages else ""
        if "TABLES" in system or "QUERY_PLANNER" in system:
            catalog = _parse_catalog(system)
            if not catalog:
                return ProviderResponse(content='{"clarification":"Upload the TBX starter CSV files first."}')
            question = user_message.lower()
            dataset = "vendor_payouts" if "payout" in question and "vendor_payouts" in catalog else "transactions"
            if dataset not in catalog:
                dataset = next(iter(catalog))
            column_names = {item["name"] for item in catalog[dataset]}
            measure_column = next((name for name in ("amount", "amount_paise", "value") if name in column_names), None)
            if any(term in question for term in ("average", "avg", "mean")) and measure_column:
                operation = "average"
            elif any(term in question for term in ("largest", "biggest", "highest", "maximum")) and measure_column:
                operation = "maximum"
            elif any(term in question for term in ("smallest", "lowest", "minimum")) and measure_column:
                operation = "minimum"
            elif any(term in question for term in ("how many", "count", "number of")):
                operation = "count"
            elif any(term in question for term in ("how much", "total", "spend")) and measure_column:
                operation = "sum"
            else:
                operation = "list"
            group_by = ["vendor_name"] if "by vendor" in question and "vendor_name" in column_names else []
            filters = []
            status_column = "reconciliation_status" if "reconciliation_status" in column_names else "status"
            for status in ("unreconciled", "pending", "reconciled", "completed", "failed", "processing", "scheduled"):
                if status in question and status_column in column_names:
                    filters.append({"column": status_column, "operator": "eq", "value": status})
                    break
            if "last month" in question:
                match = re.search(r"TODAY=(\d{4}-\d{2}-\d{2})", system)
                date_column = "payout_date" if "payout_date" in column_names else "transaction_date"
                if match and date_column in column_names:
                    today = date.fromisoformat(match.group(1))
                    first_this_month = today.replace(day=1)
                    last_previous_month = first_this_month - timedelta(days=1)
                    first_previous_month = last_previous_month.replace(day=1)
                    filters.extend([
                        {"column": date_column, "operator": "gte", "value": first_previous_month.isoformat()},
                        {"column": date_column, "operator": "lte", "value": last_previous_month.isoformat()},
                    ])
            content = json.dumps({
                "dataset": dataset,
                "operation": operation,
                "measure": measure_column if operation in {"sum", "average", "minimum", "maximum"} else None,
                "group_by": group_by,
                "filters": filters,
                "limit": 50,
            })
            return ProviderResponse(
                content=content,
                tokens_in=_estimate_tokens(system) + _estimate_tokens(user_message),
                tokens_out=_estimate_tokens(content),
                latency_ms=int((time.monotonic() - started) * 1000),
                model="keyword-baseline",
            )
        if "GROUNDED_EXPLAINER" in system:
            marker = "Computed evidence: "
            evidence = json.loads(user_message.split(marker, 1)[1]) if marker in user_message else {}
            rows = evidence.get("rows", [])
            if not rows:
                answer = "The uploaded data contains no matching records."
            elif len(rows) == 1 and "result" in rows[0]:
                answer = f"The computed result is {rows[0]['result']}."
            else:
                answer = f"I found {len(rows)} matching breakdown row(s). Review the evidence table below for the exact records."
            return ProviderResponse(content=answer + " This answer was computed directly from the dataset in mock mode.")
        return ProviderResponse(
            content=(
                "Mock assistant is working. I received: "
                f"\"{user_message}\". Replace the mock provider or add TBX tools "
                "after the problem statement is released."
            )
        )
