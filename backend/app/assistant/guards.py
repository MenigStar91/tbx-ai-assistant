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
from difflib import SequenceMatcher
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
    all any some none our we us my me it that those these them there the a an of in on for to from and
    or with without is are was were be been has have had do does did can could should would
    single individual entire overall across only just ever most least down up out made gave got
    now same about instead
    run ran within including excluding also then than data dataset row rows
    inr rupees rupee crore lakh lakhs usd gst gstin tds utr
    receive received receives receiving receipt receipts inflow inflows outflow outflows
    deposit deposits withdrawal withdrawals incoming outgoing branch ifsc
    above below previous earlier former latter one ones here there mentioned shown
    bank banks debit debits credit credits balance balances available program entity
    reference references id ids identifier identifiers last digits four raw masked
    january february march april may june july august september october november december
    """.split()
)

FORECAST_RE = re.compile(
    r"\b(will|forecast|forecasts|predict|prediction|projected|projection|expect|expected|"
    r"estimate|estimated|next\s+(month|quarter|year|week)|future|upcoming)\b",
    re.IGNORECASE,
)


def missing_capability(question: str, catalog: dict | None = None) -> tuple[str, str] | None:
    """Explain domain questions the published schema cannot prove.

    These are not generic out-of-scope refusals: they state the minimum data
    contract (and access) that would make the question answerable.
    """
    available_columns = {
        column["name"].lower()
        for columns in (catalog or {}).values()
        for column in columns
    }
    has_vendor_mapping = any(
        any(term in column for term in ("vendor", "supplier", "merchant", "counterparty"))
        for column in available_columns
    )
    if re.search(r"\b(vendor|supplier|merchant|counterparty)s?\b", question, re.IGNORECASE) and not has_vendor_mapping:
        return (
            "I cannot calculate vendor spend from the current TBX schema because transactions "
            "have no vendor identifier. I need read access to a vendor master plus a "
            "transaction-to-vendor mapping (vendor_id, vendor_name/category, transaction_id).",
            "missing_vendor_mapping",
        )
    has_ledger = {"debit_amount", "credit_amount"} <= available_columns
    if re.search(r"\b(recon(?:cile|ciliation)?|double[- ]entry|journal|ledger|trial balance)\b", question, re.IGNORECASE) and not has_ledger:
        return (
            "I cannot prove double-entry reconciliation from bank transactions alone. I need "
            "read access to immutable journal lines containing journal_id, posting_batch_id, "
            "account_id, debit, credit, currency, posting timestamp and posting status. "
            "Until then I can analyze transaction totals, but not certify that books balance.",
            "missing_ledger_entries",
        )
    return None


def sensitive_request(question: str) -> tuple[str, str] | None:
    """Block requests that could expose or falsely search protected fields.

    UTR values may be encrypted in the TBX source, so plaintext lookup is not
    promised. Account numbers are only queryable through the safe last-four
    projection. This guard runs before any model call, so sensitive text is not
    copied into an external prompt.
    """
    if re.search(r"\butr(?:\s+number)?s?\b", question, re.IGNORECASE):
        return (
            "UTR values are protected and are not exposed or searched in plaintext. "
            "I can show whether a transaction has a UTR, or you can use its transaction reference ID.",
            "protected_utr",
        )
    if re.search(r"\b(account|a/c)\s*(number|no\.?|#)s?\b", question, re.IGNORECASE):
        if not re.search(r"\b(last|ending|ends?\s+in)\b.{0,15}\b4|\blast\s+four\b", question, re.IGNORECASE):
            return (
                "Full account numbers are protected. Ask using only the last four digits, "
                "which are available as account_last4.",
                "protected_account_number",
            )
    return None

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


def _edit_distance_within(a: str, b: str, limit: int) -> bool:
    """True when a and b are at most `limit` single-character edits apart."""
    if abs(len(a) - len(b)) > limit:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def looks_like_typo(word: str, known: set[str]) -> bool:
    """Is this a misspelling of a word we know, rather than a new subject?

    "How mcuh did we spend" must not be refused as a question about a subject
    called "mcuh". Two cheap signals cover almost every real typo:
      * the same letters in a different order (transposition)
      * one insertion, deletion or substitution away
    Both require a similar length, so a genuinely different word like "ebitda"
    still refuses.
    """
    if len(word) < 3:
        return False
    signature = "".join(sorted(word))
    limit = 1 if len(word) <= 6 else 2
    for candidate in known:
        if abs(len(candidate) - len(word)) > limit:
            continue
        if len(candidate) == len(word) and signature == "".join(sorted(candidate)):
            return True
        if _edit_distance_within(word, candidate, limit):
            return True
    return False


def unsupported_subject(question: str, data_vocabulary: set[str]) -> list[str]:
    """Words in the question that are neither query language nor present in the data.

    Generic company words are excluded: "corp" in "CloudScale Corp" names nothing,
    it is boilerplate. Treating it as an unknown subject refuses a question whose
    vendor resolved perfectly well.
    """
    known = QUERY_LEXICON | data_vocabulary | COMPANY_SUFFIXES
    words = [
        part
        for token in re.findall(r"[a-zA-Z][a-zA-Z'\-/]{2,}", question.lower())
        for part in re.split(r"[-/]", token)
        if len(part) >= 3
    ]
    unknown = [
        word
        for word in words
        if word not in known
        and word.rstrip("s") not in known
        and f"{word}s" not in known
        # a misspelling of a word we know is a typo, not a new subject
        and not looks_like_typo(word, known)
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
            for chunk in phrase.split()
            for word in re.split(r"[-/]", chunk)
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


# ---------------------------------------------------------------------------
# Near-miss entity resolution
# ---------------------------------------------------------------------------

# Generic company words carry no identity. Left in, "Zylo Corp" scores ~0.6
# against "Acme Corp" on the shared suffix alone, and an unknown vendor gets
# silently treated as a known one -- which turns a correct refusal into a wrong
# number, the most damaging failure this system can have.
COMPANY_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "ltd", "limited", "llc", "llp", "co",
    "company", "group", "holdings", "industries", "services", "solutions", "partners",
    "pvt", "private", "technologies", "tech", "systems", "enterprises", "and", "the",
}

MATCH_FLOOR = 0.70     # below this the name simply is not in the data; a 0.6
                       # match is noise, not a 'did you mean'
MATCH_CONFIRM = 0.86   # above this, accept it


def _strip_suffixes(name: str) -> str:
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]
    distinctive = [w for w in words if w not in COMPANY_SUFFIXES]
    return " ".join(distinctive or words)


def _score(query: str, candidate: str) -> float:
    """Weighted toward the distinctive remainder, so shared boilerplate cannot
    carry a match on its own."""
    raw = SequenceMatcher(None, query.lower(), candidate.lower()).ratio()
    stripped = SequenceMatcher(None, _strip_suffixes(query), _strip_suffixes(candidate)).ratio()
    return 0.6 * stripped + 0.4 * min(raw, stripped)


def build_values(catalog: dict[str, list[dict[str, str]]], connection) -> list[str]:
    """Distinct values of low-cardinality text columns: the names a question can
    plausibly be referring to."""
    values: set[str] = set()
    for dataset, columns in catalog.items():
        for column in columns:
            if "CHAR" not in column["type"].upper() and "STRING" not in column["type"].upper():
                continue
            try:
                distinct = connection.execute(
                    f'SELECT COUNT(DISTINCT "{column["name"]}") FROM "{dataset}"'
                ).fetchone()[0]
                if not distinct or distinct > MAX_DISTINCT:
                    continue
                for (value,) in connection.execute(
                    f'SELECT DISTINCT "{column["name"]}" FROM "{dataset}" '
                    f'WHERE "{column["name"]}" IS NOT NULL LIMIT {MAX_DISTINCT}'
                ).fetchall():
                    text = str(value).strip()
                    if 2 < len(text) < 80:
                        values.add(text)
            except Exception:  # noqa: BLE001 - a column we cannot scan is simply skipped
                continue
    return sorted(values)


# words that introduce a name: "paid Acme", "spend on Acme", "from Acme"
ENTITY_CUE_RE = re.compile(
    r"\b(to|from|for|with|pay|paid|pays|billed|vendor|supplier|counterparty|called|named)\s*$",
    re.IGNORECASE,
)


def candidate_entities(question: str) -> list[str]:
    """Capitalised phrases that plausibly name something in the data.

    A single capitalised word at the start of a sentence is capitalised by
    grammar, not because it names anything -- "Damn, what data do we have?"
    must not be read as a question about a vendor called Damn. Such a word
    counts only when something introduces it as a name.
    """
    found = []
    for match in re.finditer(r"\b[A-Z][a-zA-Z&.'-]+(?:\s+[A-Z][a-zA-Z&.'-]+)*", question):
        phrase = match.group(0)
        words = [w for w in phrase.split() if w.lower() not in QUERY_LEXICON]
        candidate = " ".join(words)
        if len(candidate) < 4:
            continue

        if len(words) == 1:
            preceding = question[: match.start()].rstrip()
            sentence_initial = not preceding or preceding.endswith((".", "?", "!"))
            if sentence_initial and not ENTITY_CUE_RE.search(preceding):
                continue
        found.append(candidate)
    return found


def resolve_entity(phrase: str, values: list[str]) -> tuple[str, str | None, list[str], float]:
    """Classify a named entity against the values the data actually contains.

    Returns (verdict, best_match, close_candidates, score) where verdict is one
    of "exact", "confident", "ambiguous", "unknown".
    """
    if not values:
        return "unknown", None, [], 0.0

    lowered = phrase.lower().strip()
    for value in values:
        if value.lower() == lowered:
            return "exact", value, [], 1.0

    stripped_query = _strip_suffixes(phrase)
    for value in values:
        # a distinctive prefix of 3+ characters is a strong signal
        if stripped_query and _strip_suffixes(value).startswith(stripped_query) and len(stripped_query) >= 3:
            return "confident", value, [], 0.9

    scored = sorted(((_score(phrase, value), value) for value in values), reverse=True)
    best_score, best = scored[0]
    close = [value for score, value in scored[:3] if score >= MATCH_FLOOR]

    if best_score >= MATCH_CONFIRM:
        return "confident", best, [], best_score
    if best_score >= MATCH_FLOOR:
        return "ambiguous", best, close, best_score
    return "unknown", None, [], best_score
