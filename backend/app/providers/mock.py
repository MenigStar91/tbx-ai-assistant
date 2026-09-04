import json
import re
from datetime import date, timedelta

from app.schemas import Message, ProviderResponse


class MockProvider:
    async def generate(self, messages: list[Message]) -> ProviderResponse:
        user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        system = messages[0].content if messages else ""
        if "QUERY_PLANNER" in system:
            marker = "AVAILABLE_DATASETS_JSON="
            raw = system.split(marker, 1)[1].split("\n", 1)[0]
            catalog = json.loads(raw)
            if not catalog:
                return ProviderResponse(content='{"clarification":"Upload the TBX starter CSV files first."}')
            question = user_message.lower()
            dataset = "vendor_payouts" if "payout" in question and "vendor_payouts" in catalog else "transactions"
            if dataset not in catalog:
                dataset = next(iter(catalog))
            column_names = {item["name"] for item in catalog[dataset]}
            operation = "sum" if any(term in question for term in ("how much", "total", "spend")) and "amount" in column_names else "list"
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
            return ProviderResponse(content=json.dumps({
                "dataset": dataset,
                "operation": operation,
                "measure": "amount" if operation == "sum" else None,
                "group_by": group_by,
                "filters": filters,
                "limit": 50,
            }))
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
