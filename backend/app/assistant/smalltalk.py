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
    r"how\s+do(es)?\s+(this|you)\s+work|what\s+data\s+(do\s+you\s+have|is\s+(there|available))|"
    r"show\s+me\s+what\s+you\s+can\s+do)[\s!.?,]*$",
    re.IGNORECASE,
)


def _capability_reply(datasets: list[str]) -> str:
    listed = ", ".join(sorted(datasets)) if datasets else "the loaded datasets"
    return (
        f"I answer questions about {listed}, and every figure is computed by SQL over "
        "those records rather than written by the model.\n\n"
        "Try:\n"
        "  • How much did we spend on vendor payouts last month?\n"
        "  • Which transactions are still unreconciled?\n"
        "  • Break down spend by vendor\n\n"
        "Open the evidence under any answer to see the rows it came from. If the data "
        "cannot answer something, I will say so rather than estimate."
    )


def conversational_reply(question: str, datasets: list[str]) -> str | None:
    """A canned reply for pure small talk, or None if this is a real question.

    Matches only when the whole message is small talk -- "hi, how much did we
    spend last month?" is a question with a greeting attached and must fall
    through to the planner.
    """
    text = (question or "").strip()
    if not text:
        return None

    if _GREETING.match(text):
        return (
            "Hello. Ask me anything about the finance data and I will compute the answer "
            "from the records.\n\n"
            "For example: \"How much did we spend on vendor payouts last month?\" or "
            "\"Which transactions are still unreconciled?\""
        )
    if _CAPABILITY.match(text):
        return _capability_reply(datasets)
    if _THANKS.match(text):
        return "Happy to help. Ask another question whenever you need one."
    if _GOODBYE.match(text):
        return "Goodbye."
    return None
