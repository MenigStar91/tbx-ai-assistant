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

import calendar
import re
from datetime import date, timedelta

SPEND_WORDS = {
    "spend", "spent", "spending", "paid", "pay", "pays", "payment", "payments",
    "outflow", "outflows", "debit", "debits", "outgoing", "withdrawal", "withdrawals",
}
RECEIVE_WORDS = {
    "receive", "received", "receiving", "receipt", "receipts", "credit", "credits",
    "inflow", "inflows", "incoming", "deposit", "deposits",
}


def _mentions(question: str, words: set[str]) -> bool:
    """Recognise a financial direction while tolerating a small typo."""
    from app.assistant.guards import looks_like_typo

    return any(
        token in words or looks_like_typo(token, words)
        for token in re.findall(r"[a-zA-Z]{3,}", question.lower())
    )


# words that mean the user actually asked for a breakdown
NEGATION_RE = re.compile(
    r"\b(not|isn'?t|aren'?t|wasn'?t|weren'?t|except|excluding|other\s+than|apart\s+from|"
    r"besides|non|without|didn'?t|no\s+longer|unmatched|outstanding)\b",
    re.IGNORECASE,
)

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


MONTHS = {
    name.lower(): index
    for index, name in enumerate(calendar.month_name)
    if name
} | {
    name.lower(): index
    for index, name in enumerate(calendar.month_abbr)
    if name
}


def _month_window(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(anchor: date, months: int) -> tuple[date, date]:
    total = (anchor.year * 12 + anchor.month - 1) + months
    return _month_window(total // 12, total % 12 + 1)


def resolve_period(question: str, anchor: date) -> tuple[date, date, str] | None:
    """Compute the date window ourselves instead of letting the model do it.

    Date arithmetic is arithmetic. The planner emitted September for "last month"
    against a September anchor, producing an empty result stated as an answer.
    The same rule that keeps the model away from sums keeps it away from calendars.
    """
    q = question.lower()

    if re.search(r"\blast\s+month\b|\bprevious\s+month\b|\bprior\s+month\b", q):
        start, end = _shift_month(anchor, -1)
        return start, end, "last month"
    if re.search(r"\bthis\s+month\b|\bcurrent\s+month\b", q):
        start, end = _shift_month(anchor, 0)
        return start, end, "this month"
    if re.search(r"\bmonth\s+before\b", q):
        start, end = _shift_month(anchor, -2)
        return start, end, "the month before"

    if match := re.search(r"\blast\s+(\d{1,2})\s+months?\b", q):
        count = int(match.group(1))
        start, _ = _shift_month(anchor, -count)
        _, end = _shift_month(anchor, -1)
        return start, end, f"last {count} months"

    if re.search(r"\blast\s+year\b", q):
        year = anchor.year - 1
        return date(year, 1, 1), date(year, 12, 31), "last year"
    if re.search(r"\bthis\s+year\b|\bytd\b|\byear\s+to\s+date\b", q):
        return date(anchor.year, 1, 1), anchor, "this year"

    if match := re.search(r"\bq([1-4])\b(?:\s+((?:19|20)\d{2}))?", q):
        quarter = int(match.group(1))
        year = int(match.group(2)) if match.group(2) else anchor.year
        first = (quarter - 1) * 3 + 1
        start, _ = _month_window(year, first)
        _, end = _month_window(year, first + 2)
        return start, end, f"Q{quarter} {year}"

    # Resolve every named month so "May-June 2026" means the whole range.
    # "May" is treated as a month only when its surrounding text is temporal.
    named: list[tuple[int, int]] = []
    for name, index in MONTHS.items():
        if len(name) <= 3 and name != "may":
            continue
        for month_match in re.finditer(rf"\b{name}\b", q):
            if name == "may":
                before = q[max(0, month_match.start() - 12):month_match.start()]
                after = q[month_match.end():month_match.end() + 8]
                if not re.search(r"\b(in|of|during|for|and|since|from|until|to)\s*$", before) \
                        and not re.search(r"^\s*(\d{4}|and|to|-)", after):
                    continue
            named.append((month_match.start(), index))
    if named:
        named.sort()
        year_match = re.search(r"\b((?:19|20)\d{2})\b", q)
        year = int(year_match.group(1)) if year_match else anchor.year
        first_month, last_month = named[0][1], named[-1][1]
        start_year = year - 1 if first_month > last_month else year
        start, _ = _month_window(start_year, first_month)
        _, end = _month_window(year, last_month)
        label = (
            f"{calendar.month_name[first_month]} {year}"
            if first_month == last_month
            else f"{calendar.month_name[first_month]}-{calendar.month_name[last_month]} {year}"
        )
        return start, end, label

    if match := re.search(r"\b((?:19|20)\d{2})\b", q):
        year = int(match.group(1))
        return date(year, 1, 1), date(year, 12, 31), str(year)

    return None


def repair_plan(
    plan: dict,
    question: str,
    catalog: dict[str, list[dict[str, str]]],
    values: list[str] | None = None,
    anchor: date | None = None,
    column_bounds: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict, list[str]]:
    """Return the corrected plan and a list of the repairs applied.

    The repair list is surfaced in the response, so a corrected plan is visible
    rather than silently different from what the model produced.
    """
    repairs: list[str] = []
    plan = dict(plan)
    wants_spend = _mentions(question, SPEND_WORDS)
    wants_received = _mentions(question, RECEIVE_WORDS)

    # ---- 0. a missing operation is inferable from the question ---------------
    if not plan.get("operation"):
        q = question.lower()
        if any(w in q for w in ("how many", "count", "number of")):
            inferred = "count"
        elif any(w in q for w in ("average", "avg", "mean")):
            inferred = "average"
        elif any(w in q for w in ("largest", "biggest", "highest", "maximum")):
            inferred = "maximum"
        elif any(w in q for w in ("smallest", "lowest", "minimum")):
            inferred = "minimum"
        elif any(w in q for w in ("how much", "total", "spend", "spent", "paid", "sum")):
            inferred = "sum"
        else:
            inferred = "list"
        repairs.append(f"inferred operation={inferred} (the planner omitted it)")
        plan["operation"] = inferred

    # Correct only deterministic table mistakes. Pluralisation is safe; fuzzy
    # table guessing is left to the clarification flow.
    selected_dataset = plan.get("dataset")
    if selected_dataset not in catalog and selected_dataset:
        wanted = re.sub(r"[^a-z0-9]", "", str(selected_dataset).lower()).rstrip("s")
        exact = [
            name for name in catalog
            if re.sub(r"[^a-z0-9]", "", name.lower()).rstrip("s") == wanted
        ]
        if len(exact) == 1:
            repairs.append(f"resolved dataset {selected_dataset} -> {exact[0]}")
            plan["dataset"] = exact[0]

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

    # Cash-flow questions belong to the one table that actually publishes a
    # transaction direction. This is discovered from the live catalog, not from
    # a fixed table name.
    if wants_spend != wants_received:
        directional_tables = [
            name for name, columns in catalog.items()
            if "transaction_type" in {column["name"] for column in columns}
        ]
        if len(directional_tables) == 1 and plan.get("dataset") != directional_tables[0]:
            repairs.append(
                f"moved dataset {plan.get('dataset')} -> {directional_tables[0]} "
                "because the question requires transaction direction"
            )
            plan["dataset"] = directional_tables[0]

    # If the planner picked a real but unsuitable table, move only when exactly
    # one live table contains every physical field requested by the plan.
    chosen_columns = {
        column["name"] for column in catalog.get(plan.get("dataset"), [])
    }
    referenced = {
        item.get("column") for item in plan.get("filters") or [] if item.get("column")
    }
    referenced |= set(plan.get("group_by") or [])
    referenced |= set(plan.get("select") or [])
    if plan.get("operation") not in {"count", "list"} and plan.get("measure"):
        referenced.add(plan["measure"])
    if referenced - chosen_columns:
        fitting = [
            name for name, columns in catalog.items()
            if referenced <= {column["name"] for column in columns}
        ]
        if len(fitting) == 1 and fitting[0] != plan.get("dataset"):
            repairs.append(
                f"moved dataset {plan.get('dataset')} -> {fitting[0]} "
                "because it is the only table containing the requested fields"
            )
            plan["dataset"] = fitting[0]

    # ---- 3. a measure is meaningless for count/list -------------------------
    if plan.get("operation") in {"count", "list"} and plan.get("measure"):
        repairs.append(f"cleared measure={plan['measure']} (not used by {plan['operation']})")
        plan["measure"] = None

    # A list must have an explicit, bounded projection. Small planners sometimes
    # omit it, so select only columns named by the question plus a compact set of
    # finance evidence columns. This never expands beyond the live catalog.
    if plan.get("operation") == "list" and not plan.get("select"):
        columns = [column["name"] for column in catalog.get(plan.get("dataset"), [])]
        lowered = question.lower().replace(" ", "_")
        mentioned = [name for name in columns if name.lower() in lowered]
        evidence = [
            name for name in (
                "transaction_date", "transaction_type", "transaction_amount",
                "transaction_reference_id", "bank_code", "bank_name",
                "account_last4", "available_balance",
            ) if name in columns
        ]
        selected = list(dict.fromkeys(mentioned + evidence))[:8]
        if not selected:
            selected = columns[:8]
        plan["select"] = selected
        repairs.append(f"set explicit list projection ({len(selected)} columns)")
    elif plan.get("operation") != "list" and plan.get("select"):
        plan["select"] = []
        repairs.append("cleared list projection for aggregate query")

    # ---- 4. an aggregate with no measure cannot run; pick the obvious one ----
    if plan.get("operation") in {"sum", "average", "minimum", "maximum"} and not plan.get("measure"):
        columns = catalog.get(plan.get("dataset"), [])
        numeric = [
            column["name"]
            for column in columns
            if any(token in column["type"].upper() for token in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "BIGINT"))
        ]
        preferred = next(
            (name for name in ("transaction_amount", "available_balance", "amount", "amount_paise", "value", "total") if name in numeric),
            numeric[0] if len(numeric) == 1 else None,
        )
        if preferred:
            repairs.append(f"set measure={preferred} (required by {plan['operation']})")
            plan["measure"] = preferred

    # Enforce cash-flow direction from the user's wording. This corrects an
    # omitted or opposite model filter without asking the model to do arithmetic.
    real_columns = {column["name"] for column in catalog.get(plan.get("dataset"), [])}
    if "transaction_type" in real_columns:
        if wants_spend != wants_received:
            direction = "debit" if wants_spend else "credit"
            existing = next(
                (item.get("value") for item in (plan.get("filters") or [])
                 if item.get("column") == "transaction_type"),
                None,
            )
            plan["filters"] = [
                item for item in (plan.get("filters") or [])
                if item.get("column") != "transaction_type"
            ] + [{"column": "transaction_type", "operator": "eq", "value": direction}]
            if existing != direction:
                repairs.append(
                    f"set transaction_type={direction} from the requested cash-flow direction"
                )

    # ---- 4b. a negated filter needs a negation in the question ---------------
    # observed: "how many vendor payouts failed" planned status neq failed, which
    # counts everything that did NOT fail and states it confidently
    if not NEGATION_RE.search(question):
        flipped = []
        for item in plan.get("filters") or []:
            if item.get("operator") == "neq":
                repairs.append(
                    f'changed {item.get("column")} neq -> eq (the question contains no negation)'
                )
                item = {**item, "operator": "eq"}
            flipped.append(item)
        plan["filters"] = flipped

    # ---- 4c. compute the date window ourselves --------------------------------
    if anchor and (period := resolve_period(question, anchor)):
        start, end, label = period
        columns = catalog.get(plan.get("dataset")) or []
        date_column = next(
            (c["name"] for c in columns if "DATE" in c["type"].upper() or "TIMESTAMP" in c["type"].upper()),
            None,
        )
        # anchor to the column actually being filtered, not to the dataset with the
        # furthest-reaching timestamp
        if date_column and column_bounds:
            key = f"{plan.get('dataset')}.{date_column}"
            if key in column_bounds:
                try:
                    column_max = date.fromisoformat(column_bounds[key][1])
                    local = (column_max.replace(day=28) + timedelta(days=4)).replace(day=1)
                    if local != anchor:
                        recomputed = resolve_period(question, local)
                        if recomputed:
                            start, end, label = recomputed
                except ValueError:
                    pass

        if date_column:
            others = [
                item for item in (plan.get("filters") or [])
                if item.get("column") != date_column
            ]
            had_dates = len(others) != len(plan.get("filters") or [])
            plan["filters"] = others + [
                {"column": date_column, "operator": "gte", "value": start.isoformat()},
                {"column": date_column, "operator": "lte", "value": end.isoformat()},
            ]
            verb = "replaced" if had_dates else "set"
            repairs.append(f'{verb} the date range for "{label}": {start} to {end}')

    # ---- 5. canonicalise filter values against the real data ----------------
    # The guards may have resolved "CloudScale Corp" to "CloudScale Systems", but
    # the model still emits the user's literal phrase. Filtering on it matches
    # nothing and produces a confident empty result, which reads as an answer.
    if values:
        from app.assistant.guards import resolve_entity

        fixed = []
        for item in plan.get("filters") or []:
            value = item.get("value")
            if isinstance(value, str) and len(value) > 2 and item.get("operator") == "eq":
                verdict, best, _, _ = resolve_entity(value, values)
                if verdict in {"exact", "confident"} and best and best != value:
                    repairs.append(f'resolved "{value}" to "{best}"')
                    item = {**item, "value": best}
            fixed.append(item)
        plan["filters"] = fixed

    return plan, repairs
