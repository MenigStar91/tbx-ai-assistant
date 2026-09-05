"""Conservative, deterministic merging for contextual finance questions."""

from __future__ import annotations

import re

from app.schemas import QueryPlan

FOLLOW_UP_RE = re.compile(
    r"\b(now|same|that|those|them|only|instead|previous|prior|month before|"
    r"what about|how about|do the same|remove|without)\b",
    re.IGNORECASE,
)
OPERATION_RE = re.compile(
    r"\b(total|sum|average|avg|mean|count|how many|how much|show|list|"
    r"minimum|maximum|highest|lowest)\b",
    re.IGNORECASE,
)
BREAKDOWN_RE = re.compile(r"\b(by|per|break\s*down|group)\b", re.IGNORECASE)


def merge_follow_up(current: QueryPlan, previous: QueryPlan | None, question: str) -> tuple[QueryPlan, list[str]]:
    """Merge a new validated plan with trusted prior state.

    Filters are inherited by default for an explicit follow-up and replaced by
    column, preventing duplicate date/bank filters. Standalone questions never
    inherit state, which prevents stale-filter leakage.
    """
    if previous is None or not FOLLOW_UP_RE.search(question):
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
    if not BREAKDOWN_RE.search(question):
        updates["group_by"] = previous.group_by

    current_filters = list(current.filters)
    remove_columns: set[str] = set()
    lowered = question.lower()
    for item in previous.filters:
        label = item.column.replace("_", " ")
        if re.search(rf"\b(?:remove|without)\s+(?:the\s+)?{re.escape(label)}\b", lowered):
            remove_columns.add(item.column)
    replacement_columns = {item.column for item in current_filters} | remove_columns
    inherited = [item for item in previous.filters if item.column not in replacement_columns]
    updates["filters"] = inherited + current_filters
    if inherited:
        repairs.append(f"inherited {len(inherited)} prior filter(s)")
    if remove_columns:
        repairs.append("removed prior filter(s): " + ", ".join(sorted(remove_columns)))

    return current.model_copy(update=updates), repairs
