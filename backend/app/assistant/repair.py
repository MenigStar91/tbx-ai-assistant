"""Deterministic repair of a model-produced query plan.

Section 7 asks us to get the *smallest* model to perform, not to reach for a
bigger one. Sub-1B planners make a small number of highly repeatable mistakes,
and every one of them is cheaper to correct in code than to prompt away:

  * spurious group_by -- "what is the total transaction amount?" comes back
    grouped by transaction_date, which turns a total into a per-day breakdown
    and reports the first day as the answer
  * wrong table -- "how many vendor payouts are there?" plans against `vendors`
    even though the question names the dataset outright

Repairs are conservative: each one fires only on an unambiguous signal, and
never invents a filter or a value. Anything it cannot fix safely is left for
plan validation to refuse.
"""

from __future__ import annotations

import re

# words that mean the user actually asked for a breakdown
BREAKDOWN_RE = re.compile(
    r"\b(by|per|each|breakdown|break down|split|grouped?|top|which\s+\w+|across)\b",
    re.IGNORECASE,
)


def _phrase_in(question: str, dataset: str) -> bool:
    """True when the question names the dataset outright: "vendor payouts"
    matches vendor_payouts, "transactions" matches transactions."""
    words = [word for word in dataset.split("_") if word]
    pattern = r"\b" + r"[\s_]+".join(re.escape(word) + "s?" for word in words) + r"\b"
    return re.search(pattern, question, re.IGNORECASE) is not None


def repair_plan(
    plan: dict,
    question: str,
    catalog: dict[str, list[dict[str, str]]],
) -> tuple[dict, list[str]]:
    """Return the corrected plan and a list of the repairs applied.

    The repair list is surfaced in the response, so a corrected plan is visible
    rather than silently different from what the model produced.
    """
    repairs: list[str] = []
    plan = dict(plan)

    # ---- 1. drop a grouping the question never asked for --------------------
    if plan.get("group_by") and not BREAKDOWN_RE.search(question):
        repairs.append(f"dropped group_by={plan['group_by']} (question asks for a single figure)")
        plan["group_by"] = []

    # ---- 2. honour a dataset the question names outright --------------------
    named = [name for name in catalog if _phrase_in(question, name)]
    # prefer the most specific match: "vendor payouts" over "vendors"
    named.sort(key=len, reverse=True)
    if named and plan.get("dataset") != named[0]:
        target = named[0]
        target_columns = {column["name"] for column in catalog[target]}
        referenced = {item.get("column") for item in plan.get("filters") or []}
        referenced |= set(plan.get("group_by") or [])
        if plan.get("operation") not in {"count", "list"} and plan.get("measure"):
            referenced.add(plan["measure"])
        if referenced <= target_columns:
            repairs.append(f"switched dataset {plan.get('dataset')} -> {target} (named in the question)")
            plan["dataset"] = target

    # ---- 3. a measure is meaningless for count/list -------------------------
    if plan.get("operation") in {"count", "list"} and plan.get("measure"):
        repairs.append(f"cleared measure={plan['measure']} (not used by {plan['operation']})")
        plan["measure"] = None

    # ---- 4. an aggregate with no measure cannot run; pick the obvious one ----
    if plan.get("operation") in {"sum", "average", "minimum", "maximum"} and not plan.get("measure"):
        columns = catalog.get(plan.get("dataset"), [])
        numeric = [
            column["name"]
            for column in columns
            if any(token in column["type"].upper() for token in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "BIGINT"))
        ]
        preferred = next(
            (name for name in ("amount", "amount_paise", "value", "total") if name in numeric),
            numeric[0] if len(numeric) == 1 else None,
        )
        if preferred:
            repairs.append(f"set measure={preferred} (required by {plan['operation']})")
            plan["measure"] = preferred

    return plan, repairs
