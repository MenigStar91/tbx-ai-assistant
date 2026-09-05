"""Conservative, deterministic merging for contextual finance questions."""

from __future__ import annotations

import re

from app.data.display import equivalent_to
from app.schemas import QueryPlan

FOLLOW_UP_RE = re.compile(
    r"\b(now|same|that|those|them|only|instead|previous|prior|month before|"
    r"what about|how about|do the same|remove|without)\b"
    # a leading connective is the most common way people continue a question:
    # "And at HDFC?", "For June?", "In Q2?". Missing these silently drops the
    # previous filters and answers a different question with full confidence.
    r"|^\s*(and|also|but|or|then|for|in|at|on|by|from)\b",
    re.IGNORECASE,
)
LEADING_CONNECTIVE_RE = re.compile(
    r"^\s*(and|also|but|or|then|for|in|at|on|by|from)\b", re.IGNORECASE
)
OPERATION_RE = re.compile(
    r"\b(total|sum|average|avg|mean|count|how many|how much|show|list|"
    r"minimum|maximum|highest|lowest)\b",
    re.IGNORECASE,
)
BREAKDOWN_RE = re.compile(r"\b(by|per|break\s*down|group)\b", re.IGNORECASE)
BROADEN_RE = re.compile(
    r"\b(in\s+total|overall|altogether|combined|in\s+aggregate|as\s+a\s+whole|"
    r"across\s+all|all\s+banks|all\s+accounts|every\s+bank)\b",
    re.IGNORECASE,
)
BARE_TOTAL_RE = re.compile(r"\btotals?\b", re.IGNORECASE)

EQUIVALENT_COLUMNS = (
    {"bank_code", "bank_name"},
    {"account_id", "account_last4", "account_number"},
)


def _equivalent_columns(column: str) -> set[str]:
    return next((group for group in EQUIVALENT_COLUMNS if column in group), {column})


def _is_follow_up(question: str) -> bool:
    if FOLLOW_UP_RE.search(question):
        return True
    # A connective alone is weak evidence, so accept it only for a compact
    # refinement such as "And at HDFC?" or "For June?".
    return bool(LEADING_CONNECTIVE_RE.search(question)) and len(question.split()) <= 8


def _widens_scope(question: str) -> bool:
    return bool(BROADEN_RE.search(question)) or (
        bool(BARE_TOTAL_RE.search(question)) and len(question.split()) <= 4
    )

def merge_follow_up(current: QueryPlan, previous: QueryPlan | None, question: str) -> tuple[QueryPlan, list[str]]:
    """Merge a new validated plan with trusted prior state.

    Filters are inherited by default for an explicit follow-up and replaced by
    column, preventing duplicate date/bank filters. Standalone questions never
    inherit state, which prevents stale-filter leakage.
    """
    if previous is None or not _is_follow_up(question):
        return current, []

    updates: dict = {}
    repairs: list[str] = []
    if current.dataset != previous.dataset:
        updates["dataset"] = previous.dataset
        repairs.append(f"inherited dataset={previous.dataset} from the previous question")
    if not OPERATION_RE.search(question):
        updates["operation"] = previous.operation
        updates["measure"] = previous.measure
        repairs.append(f"inherited operation={previous.operation}")
    widening = _widens_scope(question)
    if not BREAKDOWN_RE.search(question) and not widening:
        updates["group_by"] = previous.group_by

    current_filters = list(current.filters)

    remove_columns: set[str] = set()
    lowered = question.lower()
    for item in previous.filters:
        label = item.column.replace("_", " ")
        if re.search(rf"\b(?:remove|without)\s+(?:the\s+)?{re.escape(label)}\b", lowered):
            remove_columns.add(item.column)
    replacement_columns = {item.column for item in current_filters} | remove_columns
    # a filter on bank_name replaces an inherited bank_code, and vice versa
    for item in current_filters:
        replacement_columns |= equivalent_to(item.column)

    if widening:
        # "overall" drops entity scope while retaining the period and cash-flow
        # direction, which are normally still part of the analytical question.
        for group in EQUIVALENT_COLUMNS:
            replacement_columns |= group
        updates["group_by"] = current.group_by
        repairs.append("widened scope beyond the previous bank/account filter")
    inherited = [item for item in previous.filters if item.column not in replacement_columns]
    updates["filters"] = inherited + current_filters
    if inherited:
        repairs.append(f"inherited {len(inherited)} prior filter(s)")
    if remove_columns:
        repairs.append("removed prior filter(s): " + ", ".join(sorted(remove_columns)))

    merged = current.model_copy(update=updates)
    if merged.operation != "list" and merged.select:
        merged = merged.model_copy(update={"select": []})
    elif merged.operation == "list" and not merged.select and previous.operation == "list":
        merged = merged.model_copy(update={"select": previous.select})
    return merged, repairs
