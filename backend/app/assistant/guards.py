"""Deterministic guardrails that run BEFORE the language model.

The brief scores accuracy and grounding at 30% and says a fabricated figure is
"a liability". Relying on the model to volunteer {"clarification": ...} is not a
guarantee -- especially under the lightweight-model constraint, where the
planner is small and eager to produce *something*.

These guards refuse structurally instead, and because they run before the model
call an unanswerable question costs zero tokens (which also helps the 20%
efficiency criterion).

Vocabulary is derived from the live catalog, never hardcoded, so this keeps
working when the TBX starter dataset replaces the sample files.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import duckdb

# Ordinary query language. A word outside this set AND outside the dataset's own
# vocabulary means we are being asked about a subject we hold no data on.
QUERY_LEXICON: set[str] = set(
    """
    what how which show list give tell who when where whose why total sum spend spent spending
    pay paid pays payment payments payout payouts transaction transactions txn record records
    count number many much average avg mean largest biggest highest maximum max smallest lowest
    minimum min top bottom break breakdown group grouped by per each split compare comparison
    versus vs against trend over time still yet outstanding open closed export download
    vendor vendors supplier suppliers customer category categories account accounts code ledger
    amount amounts value values status statuses reconcile reconciled unreconciled reconciliation
    partially exception exceptions currency description narration method
    month months monthly year years annual quarter quarterly week weeks day days date dates period
    last this previous prior preceding before after between during since until earlier ago recent
    all any some none our we us my me it that those these there the a an of in on for to from and
    or with without is are was were be been has have had do does did can could should would
    single individual entire overall across only just ever most least down up out made gave got
    run ran within including excluding also then than data dataset row rows
    inr rupees rupee crore lakh lakhs usd gst gstin tds utr
    january february march april may june july august september october november december
    """.split()
)

FORECAST_RE = re.compile(
    r"\b(will|forecast|forecasts|predict|prediction|projected|projection|expect|expected|"
    r"estimate|estimated|next\s+(month|quarter|year|week)|future|upcoming)\b",
    re.IGNORECASE,
)

# Indic scripts. The lexicon guards are English-only by construction; running
# them on Devanagari or Tamil would refuse every valid question, so non-Latin
# input skips them and relies on plan validation, which is language-agnostic.
_SCRIPTS = [
    ("hi", re.compile(r"[ऀ-ॿ]")),
    ("bn", re.compile(r"[ঀ-৿]")),
    ("pa", re.compile(r"[਀-੿]")),
    ("gu", re.compile(r"[઀-૿]")),
    ("or", re.compile(r"[଀-୿]")),
    ("ta", re.compile(r"[஀-௿]")),
    ("te", re.compile(r"[ఀ-౿]")),
    ("kn", re.compile(r"[ಀ-೿]")),
    ("ml", re.compile(r"[ഀ-ൿ]")),
]

MAX_DISTINCT = 400  # a column with more distinct values than this is not a vocabulary


def detect_language(text: str) -> str:
    for code, pattern in _SCRIPTS:
        if pattern.search(text or ""):
            return code
    return "en"


def is_indic(language: str) -> bool:
    return language != "en"


def _tokenise(value: Any) -> list[str]:
    return [word for word in re.split(r"[^a-zA-Z]+", str(value)) if len(word) > 1]


def build_vocabulary(catalog: dict[str, list[dict[str, str]]], connection: duckdb.DuckDBPyConnection) -> set[str]:
    """Every word the dataset itself contains: column names plus the distinct
    values of low-cardinality text columns (statuses, categories, vendor names).
    """
    vocabulary: set[str] = set()
    for dataset, columns in catalog.items():
        vocabulary.update(_tokenise(dataset))
        for column in columns:
            vocabulary.update(_tokenise(column["name"]))
            if "CHAR" not in column["type"].upper() and "STRING" not in column["type"].upper():
                continue
            try:
                distinct = connection.execute(
                    f'SELECT COUNT(DISTINCT "{column["name"]}") FROM "{dataset}"'
                ).fetchone()[0]
                if distinct and distinct <= MAX_DISTINCT:
                    for (value,) in connection.execute(
                        f'SELECT DISTINCT "{column["name"]}" FROM "{dataset}" '
                        f'WHERE "{column["name"]}" IS NOT NULL LIMIT {MAX_DISTINCT}'
                    ).fetchall():
                        vocabulary.update(_tokenise(value))
            except duckdb.Error:
                continue
    return {word.lower() for word in vocabulary}


def unsupported_subject(question: str, data_vocabulary: set[str]) -> list[str]:
    """Words in the question that are neither query language nor present in the data."""
    known = QUERY_LEXICON | data_vocabulary
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", question.lower())
    unknown = [
        word
        for word in words
        if word not in known and word.rstrip("s") not in known and f"{word}s" not in known
    ]
    # de-duplicate, keep order
    seen: set[str] = set()
    return [word for word in unknown if not (word in seen or seen.add(word))]


def unresolved_entity(question: str, data_vocabulary: set[str]) -> str | None:
    """A capitalised phrase that appears nowhere in the data.

    Catches "How much did we pay Globex Corporation last month?" -- which would
    otherwise silently drop the unknown vendor and return the total for every
    vendor, a confidently wrong number.
    """
    for phrase in re.findall(r"\b[A-Z][a-zA-Z&.'-]+(?:\s+[A-Z][a-zA-Z&.'-]+)*", question):
        words = [
            word
            for word in phrase.split()
            # a capitalised word that is ordinary query language ("Break down...",
            # "Show me...") is capitalised by grammar, not because it names a thing
            if word.lower() not in QUERY_LEXICON
        ]
        if not words:
            continue
        if any(word.lower() in data_vocabulary for word in words):
            continue
        candidate = " ".join(words)
        if len(candidate) >= 4:
            return candidate
    return None


@lru_cache(maxsize=8)
def _cached_lexicon_size() -> int:  # pragma: no cover - introspection helper
    return len(QUERY_LEXICON)
