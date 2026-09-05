"""Greetings, thanks, and "what can you do?".

The unsupported-subject guard is right that "hii" contains no word this dataset
knows -- but answering a greeting with "this dataset has nothing about 'hii'"
is a terrible first impression, and a greeting is the first thing anyone types.

Handled deterministically, before the guards and before any model call, so it
costs nothing and cannot be got wrong. A greeting is also the natural moment to
tell someone what they *can* ask, so these replies orient rather than deflect.
"""

from __future__ import annotations

import re

_GREETING = re.compile(
    r"^(hi+|hey+|hello+|yo|hola|namaste|namaskar|greetings|good\s+(morning|afternoon|evening)|"
    r"sup|what'?s\s+up|howdy)[\s!.?,]*$",
    re.IGNORECASE,
)

_THANKS = re.compile(r"^(thanks?|thank\s+you|ty|thx|cheers|great|nice|cool|awesome|perfect|ok(ay)?)[\s!.?,]*$", re.IGNORECASE)

_GOODBYE = re.compile(r"^(bye+|goodbye|see\s+you|later|exit|quit)[\s!.?,]*$", re.IGNORECASE)

_CAPABILITY = re.compile(
    r"^(help|what\s+can\s+you\s+do|what\s+do\s+you\s+do|who\s+are\s+you|what\s+is\s+this|"
    r"how\s+do(es)?\s+(this|you)\s+work|show\s+me\s+what\s+you\s+can\s+do|"
    r"what\s+(can|should)\s+i\s+ask)[\s!.?,]*$",
    re.IGNORECASE,
)

# "what data do we have?" is a question about the dataset, not a query over it.
# Answering it with a grand total of every transaction is a non sequitur.
_DESCRIBE_DATA = re.compile(
    r"^(what|which)\s+(all\s+)?(data|tables?|datasets?|columns?|fields?|files?)\s+"
    r"(do\s+(we|you|i)\s+have|are\s+(there|available)|is\s+(there|available)|"
    r"can\s+i\s+(query|ask\s+about)|exist)?[\s!.?,]*$",
    re.IGNORECASE,
)

# leading filler should not stop any of the above from matching
_FILLER = re.compile(
    r"^(damn|wow|oh|ok|okay|hmm+|huh|well|hey|so|and|but|umm+|uh|bruh|lol|yo|alright|"
    r"anyway|actually|btw|please)\b[\s,.!?]*",
    re.IGNORECASE,
)


def _describe_reply(datasets: list[str], columns: dict[str, list[str]] | None) -> str:
    if not datasets:
        return "No data is loaded yet. Upload the CSV files and I will discover their columns."
    lines = ["Here is what is loaded:", ""]
    for name in sorted(datasets):
        cols = (columns or {}).get(name) or []
        shown = ", ".join(cols[:8]) + ("…" if len(cols) > 8 else "")
        lines.append(f"  • {name}" + (f" — {shown}" if shown else ""))
    lines += ["", "Ask about any of it and I will compute the answer from those records."]
    return "\n".join(lines)


def _capability_reply(datasets: list[str], columns: dict[str, list[str]] | None) -> str:
    listed = ", ".join(sorted(datasets)) if datasets else "the loaded datasets"
    available = {column for values in (columns or {}).values() for column in values}
    if {"transaction_amount", "transaction_type", "transaction_date"} <= available or "transaction" in datasets:
        examples = ["How much was debited last month?"]
    else:
        examples = [f"How many records are in {datasets[0]}?" if datasets else "What data is available?"]
    if "bank_code" in available or "transaction" in datasets:
        examples.append("Show transactions for bank code HDFC")
    if {"available_balance", "bank_name"} <= available or "account" in datasets:
        examples.append("Break down available balance by bank")
    return (
        f"I answer questions about {listed}, and every figure is computed by SQL over "
        "those records rather than written by the model.\n\n"
        "Try:\n  • " + "\n  • ".join(examples) + "\n\n"
        "Open the evidence under any answer to see the rows it came from. If the data "
        "cannot answer something, I will say so rather than estimate."
    )


_METRIC_WORDS = re.compile(
    r"\b(total|sum|count|how|many|much|average|avg|largest|smallest|list|show|break|"
    r"spend|spent|paid|pay|receiv\w*|balance|unreconciled|reconciled|transactions?|payouts?)\b",
    re.IGNORECASE,
)


def too_vague(question: str) -> str | None:
    """A fragment the planner cannot ground, e.g. a half-typed question.

    Guessing at "What i" produced a confident grand total of everything. Asking
    costs nothing and is the honest response to an incomplete question.
    """
    words = re.findall(r"[a-zA-Z]{2,}", question or "")
    if len(words) >= 3 or _METRIC_WORDS.search(question or ""):
        return None
    return (
        "I did not catch what you are asking. Try naming what you want and over what "
        "period — for example \"total spend last month\" or \"unreconciled transactions\"."
    )


def conversational_reply(
    question: str,
    datasets: list[str],
    columns: dict[str, list[str]] | None = None,
) -> str | None:
    """A canned reply for pure small talk, or None if this is a real question.

    Matches only when the whole message is small talk -- "hi, how much did we
    spend last month?" is a question with a greeting attached and must fall
    through to the planner.
    """
    text = (question or "").strip()
    if not text:
        return None
    # strip leading filler so "Damn, so what data do we have?" still matches
    stripped = _FILLER.sub("", text).strip()
    while stripped != text:
        text, stripped = stripped, _FILLER.sub("", stripped).strip()
    if not text:
        return "Hello. Ask me anything about the finance data."

    if _DESCRIBE_DATA.match(text):
        return _describe_reply(datasets, columns)

    if _GREETING.match(text):
        return (
            "Hello. Ask me anything about the finance data and I will compute the answer "
            "from the records.\n\n"
            "For example: \"How much was debited last month?\" or "
            "\"Break down available balance by bank.\""
        )
    if _CAPABILITY.match(text):
        return _capability_reply(datasets, columns)
    if _THANKS.match(text):
        return "Happy to help. Ask another question whenever you need one."
    if _GOODBYE.match(text):
        return "Goodbye."
    return None
