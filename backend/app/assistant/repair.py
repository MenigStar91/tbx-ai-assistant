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
from difflib import SequenceMatcher
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
SPEND_WORDS = {"spend", "spent", "spending", "paid", "pay", "pays", "payment",
               "payments", "outflow", "outflows", "debit", "debits", "outgoing"}
RECEIVE_WORDS = {"receive", "received", "receiving", "receipt", "receipts", "credit",
                 "credits", "inflow", "inflows", "incoming", "deposit", "deposits"}

SPEND_RE = re.compile(r"\b(" + "|".join(sorted(SPEND_WORDS)) + r")\b", re.IGNORECASE)
RECEIVED_RE = re.compile(r"\b(" + "|".join(sorted(RECEIVE_WORDS)) + r")\b", re.IGNORECASE)


def _mentions(question: str, words: set[str]) -> bool:
    """Does the question ask about this direction, allowing for a typo?

    Direction is the difference between money out and money in. Detecting it by
    exact spelling meant "how much did we spned" quietly dropped the debit
    filter and returned debits plus credits - a larger, wrong number, stated
    with full confidence.
    """
    from app.assistant.guards import looks_like_typo

    for token in re.findall(r"[a-zA-Z]{3,}", question.lower()):
        if token in words or looks_like_typo(token, words):
            return True
    return False

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

    # every month named in the question, in the order they appear. "may" only
    # counts as a month when the surrounding words make it one, so the modal
    # verb ("we may spend") is not read as a date.
    named: list[tuple[int, int]] = []
    for name, index in MONTHS.items():
        if len(name) <= 3 and name != "may":
            continue
        for match in re.finditer(rf"\b{name}\b", q):
            if name == "may":
                before = q[max(0, match.start() - 12):match.start()]
                after = q[match.end():match.end() + 8]
                if not re.search(r"\b(in|of|during|for|and|since|from|until|to)\s*$", before) \
                        and not re.search(r"^\s*(\d{4}|and|to|-)", after):
                    continue
            named.append((match.start(), index))
    if named:
        named.sort()
        year_match = re.search(r"\b((?:19|20)\d{2})\b", q)
        year = int(year_match.group(1)) if year_match else anchor.year
        first_month, last_month = named[0][1], named[-1][1]
        start, _ = _month_window(year, first_month)
        _, end = _month_window(year, last_month)
        if start > end:                       # "December and January" wraps
            start, _ = _month_window(year, last_month)
            _, end = _month_window(year, first_month)
        label = (f"{calendar.month_name[first_month]} {year}" if first_month == last_month
                 else f"{calendar.month_name[first_month]}-{calendar.month_name[last_month]} {year}")
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
    column_values: dict[str, set[str]] | None = None,
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

    # ---- 0b. resolve a table name that does not exist -------------------------
    # The planner says "transactions"; the table is "transaction_full". A near
    # miss on a table name is recoverable and should not fail the whole query.
    if plan.get("dataset") not in catalog and catalog:
        wanted = str(plan.get("dataset") or "").lower().rstrip("s")
        best, best_score = None, 0.0
        for name in catalog:
            base = name.lower()
            if base.startswith(wanted) or base.rstrip("s").startswith(wanted) or wanted in base:
                score = 0.95
            else:
                score = SequenceMatcher(None, wanted, base).ratio()
            if score > best_score:
                best, best_score = name, score
        if best and best_score >= 0.6:
            repairs.append(f'resolved table {plan.get("dataset")} -> {best}')
            plan["dataset"] = best

    # ---- 0c. the chosen table cannot answer this plan -------------------------
    # observed: "how much did we spend at HDFC BANK LIMITED" planned against
    # account_full with measure credit_amount, a column only transaction_full has.
    chosen = catalog.get(plan.get("dataset")) or []
    if chosen:
        chosen_columns = {c["name"] for c in chosen}
        needed = {f.get("column") for f in (plan.get("filters") or []) if f.get("column")}
        needed |= {g for g in (plan.get("group_by") or []) if g}
        if plan.get("operation") not in {"count", "list"} and plan.get("measure"):
            needed.add(plan["measure"])
        if needed - chosen_columns:
            fits = [name for name, cols in catalog.items()
                    if needed <= {c["name"] for c in cols}]
            if len(fits) == 1 and fits[0] != plan.get("dataset"):
                repairs.append(
                    f'moved to {fits[0]}: {plan.get("dataset")} has no '
                    f'{", ".join(sorted(needed - chosen_columns))}'
                )
                plan["dataset"] = fits[0]

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
            (name for name in ("transaction_amount", "available_balance", "amount",
                               "amount_paise", "value", "total") if name in numeric),
            numeric[0] if len(numeric) == 1 else None,
        )
        if preferred:
            repairs.append(f"set measure={preferred} (required by {plan['operation']})")
            plan["measure"] = preferred

    # ---- 4a. repair column names the planner invented -----------------------
    # observed: a sub-1B planner emits "dataset.date" instead of
    # "transaction_date". A qualified prefix or a near-miss name is recoverable;
    # anything else is left alone so validation refuses rather than guessing.
    real_columns = [c["name"] for c in catalog.get(plan.get("dataset")) or []]
    if real_columns:
        def fix_column(name: str) -> str | None:
            if not name or name in real_columns:
                return None
            bare = name.split(".")[-1]
            if bare in real_columns:
                return bare
            scored = sorted(
                ((SequenceMatcher(None, bare.lower(), c.lower()).ratio(), c) for c in real_columns),
                reverse=True,
            )
            best_score, best = scored[0]
            # a suffix match ("date" -> "transaction_date") is a strong signal
            if best_score >= 0.62 or any(
                c.lower().endswith("_" + bare.lower()) or c.lower().startswith(bare.lower() + "_")
                for c in real_columns
            ):
                exact = next(
                    (c for c in real_columns
                     if c.lower().endswith("_" + bare.lower()) or c.lower().startswith(bare.lower() + "_")),
                    None,
                )
                return exact or best
            return None

        for item in plan.get("filters") or []:
            if fixed := fix_column(item.get("column", "")):
                repairs.append(f'corrected column {item["column"]} -> {fixed}')
                item["column"] = fixed
        plan["group_by"] = [fix_column(g) or g for g in (plan.get("group_by") or [])]
        if plan.get("measure") and (fixed := fix_column(plan["measure"])):
            repairs.append(f'corrected measure {plan["measure"]} -> {fixed}')
            plan["measure"] = fixed

        # a measure that still is not a real column: fall back to the obvious
        # numeric column rather than failing the whole query
        if plan.get("operation") in {"sum", "average", "minimum", "maximum"} and plan.get("measure") not in real_columns:
            numeric = [
                c["name"] for c in catalog[plan["dataset"]]
                if any(t in c["type"].upper() for t in ("INT", "DOUBLE", "DECIMAL", "FLOAT"))
            ]
            preferred = next(
                    (n for n in ("transaction_amount", "available_balance", "amount",
                                 "amount_paise", "value", "total") if n in numeric),
                    None,
                )
            if preferred:
                repairs.append(f'measure {plan.get("measure")!r} is not a column here; used {preferred}')
                plan["measure"] = preferred

    # ---- 4a2. ledger direction ------------------------------------------------
    # "how much did we spend" over a bank ledger means debits. The schema has no
    # debit/credit split column and we do not add one, so the direction is
    # expressed as a filter on the real transaction_type column.
    if real_columns and "transaction_type" in real_columns:
        wants_spend = _mentions(question, SPEND_WORDS)
        wants_received = _mentions(question, RECEIVE_WORDS)
        already = any(f.get("column") == "transaction_type" for f in (plan.get("filters") or []))
        if not already and wants_spend != wants_received:
            direction = "debit" if wants_spend else "credit"
            plan["filters"] = (plan.get("filters") or []) + [
                {"column": "transaction_type", "operator": "eq", "value": direction}
            ]
            repairs.append(
                f"filtered to {direction}s "
                f"(the question asks about money going {'out' if wants_spend else 'in'})"
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
    if values or column_values:
        from app.assistant.guards import resolve_entity

        fixed = []
        for item in plan.get("filters") or []:
            value = item.get("value")
            if isinstance(value, str) and len(value) > 2 and item.get("operator") == "eq":
                # resolve against THIS column's values, not every value in the
                # database: "HDFC" is an exact bank_code but only a prefix of the
                # bank_name "HDFC BANK LIMITED", and the filter is on bank_name
                key = f"{plan.get('dataset')}.{item.get('column')}"
                scope = sorted(column_values.get(key, set())) if column_values else []
                verdict, best, _, _ = resolve_entity(value, scope or (values or []))
                if verdict in {"exact", "confident"} and best and best.lower() != value.lower():
                    repairs.append(f'resolved "{value}" to "{best}"')
                    item = {**item, "value": best}
            fixed.append(item)
        plan["filters"] = fixed

    # ---- 6. an eq filter on a value the column does not contain ---------------
    # (runs after canonicalisation, so a resolvable near-miss is already fixed)
    # "whcih all?" planned account_number eq 'all'; "which bank?" planned
    # bank_code eq '12345'. Both return zero rows, and a confident empty result
    # is indistinguishable from an answer. Flag them so the caller can refuse.
    if column_values:
        unresolved = []
        for item in plan.get("filters") or []:
            if item.get("operator") != "eq":
                continue
            key = f"{plan.get('dataset')}.{item.get('column')}"
            known = column_values.get(key)
            if not known:
                continue
            lowered = {str(k).strip().lower() for k in known}
            raw_value = str(item.get("value", "")).strip()
            if raw_value.lower() not in lowered:
                # the value may simply be on a sibling column: "Kotak" is not a
                # bank_code but it is a bank_name. Move the filter instead of
                # refusing a question the data can answer.
                from app.assistant.guards import resolve_entity

                moved = False
                for key, candidates in column_values.items():
                    table, _, other = key.partition(".")
                    if table != plan.get("dataset") or other == item.get("column"):
                        continue
                    verdict, best, _, _ = resolve_entity(raw_value, sorted(candidates))
                    if verdict in {"exact", "confident"} and best:
                        repairs.append(
                            f'moved filter {item["column"]}="{raw_value}" to {other}="{best}"'
                        )
                        item["column"], item["value"] = other, best
                        moved = True
                        break
                if moved:
                    continue
            if raw_value.lower() not in lowered:
                unresolved.append((item.get("column"), item.get("value"), sorted(known)[:5]))
        if unresolved:
            plan["_unresolved"] = unresolved

    return plan, repairs
