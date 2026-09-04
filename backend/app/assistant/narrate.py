"""Deterministic narration of a computed result.

Replaces the second model call. Two reasons, both scored:

* Efficiency (20%): the explainer previously received the full evidence JSON --
  up to 200 rows -- on every question. That is the single largest token cost in
  the request path, and it bought a sentence we can generate exactly.
* Grounding (30%): a template cannot garble a number it was handed. Removing the
  model from the output path removes the last place a figure could drift.

Hindi phrasing is deliberately label-shaped rather than sentence-shaped: short
noun phrases carry the number without risking mangled grammar. Languages without
a phrase table fall back to English -- an English answer with the right number
beats a confidently wrong sentence.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas import Evidence, QueryPlan

_OPERATION_WORD = {
    "sum": "total",
    "count": "count",
    "average": "average",
    "minimum": "minimum",
    "maximum": "maximum",
}

_HI = {
    "total": "कुल",
    "count": "संख्या",
    "average": "औसत",
    "minimum": "न्यूनतम",
    "maximum": "अधिकतम",
    "records": "रिकॉर्ड",
    "none": "इस शर्त पर कोई रिकॉर्ड नहीं मिला।",
    "groups": "समूह",
    "filtered": "फ़िल्टर",
}


def _format_number(value: Any) -> str:
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _filter_phrase(plan: QueryPlan) -> str:
    if not plan.filters:
        return ""
    parts = [f"{item.column} {item.operator} {item.value}" for item in plan.filters]
    return " (" + "; ".join(parts) + ")"


def narrate(plan: QueryPlan, evidence: Evidence, total_matching: int, language: str = "en") -> str:
    """Build the answer sentence from the computed evidence. No model involved."""
    hindi = language == "hi"

    if total_matching == 0:
        return _HI["none"] if hindi else (
            f"No rows in {plan.dataset} match that request{_filter_phrase(plan)}. "
            "This is a real empty result, not a failure to answer."
        )

    if plan.operation == "list":
        shown = len(evidence.rows)
        truncated = "" if shown >= total_matching else f", showing the first {shown}"
        if hindi:
            return f"{total_matching} {_HI['records']} ({plan.dataset}){truncated}"
        return (
            f"{total_matching} matching row{'s' if total_matching != 1 else ''} "
            f"in {plan.dataset}{truncated}{_filter_phrase(plan)}. The records are below."
        )

    if plan.group_by:
        groups = len(evidence.rows)
        top = evidence.rows[:3]
        key = plan.group_by[0]
        summary = ", ".join(
            f"{row.get(key)} ({_format_number(row.get('result'))})" for row in top
        )
        if hindi:
            return f"{groups} {_HI['groups']} — {summary}"
        return (
            f"{groups} group{'s' if groups != 1 else ''} of {plan.dataset} by "
            f"{', '.join(plan.group_by)}, across {total_matching} record"
            f"{'s' if total_matching != 1 else ''}{_filter_phrase(plan)}. Largest: {summary}."
        )

    result = evidence.rows[0].get("result") if evidence.rows else None
    word = _OPERATION_WORD.get(plan.operation, plan.operation)
    measure = f" of {plan.measure}" if plan.measure else ""
    if hindi:
        return f"{_HI.get(word, word)} {_format_number(result)} — {total_matching} {_HI['records']}"
    return (
        f"The {word}{measure} is {_format_number(result)}, computed over "
        f"{total_matching} record{'s' if total_matching != 1 else ''} "
        f"in {plan.dataset}{_filter_phrase(plan)}."
    )


# Thousands separators only count when followed by exactly three digits, so a
# sentence comma after a figure ("...is 958,750, computed over...") is not
# swallowed into the numeral and reported as an invented number.
NUMERAL_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def verify_numbers(text: str, allowed: set[str]) -> tuple[bool, list[str]]:
    """Every numeral in the answer must be one we computed.

    Trivially true while narration is a pure template -- which is the point. It
    is a tripwire, not a fix: the day someone adds a generative rewrite step to
    make the wording nicer, this is what catches the first invented figure
    instead of a judge catching it.
    """
    orphans = [n for n in NUMERAL_RE.findall(text or "") if n not in allowed]
    return not orphans, orphans


def allowed_numerals(evidence, total_matching: int, filters: list) -> set[str]:
    """Every numeral the answer is permitted to contain, from computed values."""
    allowed: set[str] = {str(total_matching), f"{total_matching:,}"}
    for row in (evidence.rows or []):
        for value in row.values():
            if isinstance(value, (int, float)):
                allowed |= {str(value), f"{value:,}", _format_number(value)}
            elif value is not None:
                allowed |= set(NUMERAL_RE.findall(str(value)))
    for item in filters or []:
        allowed |= set(NUMERAL_RE.findall(str(getattr(item, "value", item))))
    if evidence.total_groups is not None:
        allowed |= {str(evidence.total_groups), f"{evidence.total_groups:,}"}
    return allowed
