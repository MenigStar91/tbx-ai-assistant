import json
import re
import time
from datetime import date, timedelta

import duckdb
from pydantic import ValidationError

from app.assistant import guards
from app.assistant.narrate import allowed_numerals, narrate, verify_numbers
from app.assistant.repair import repair_plan
from app.assistant.smalltalk import conversational_reply, too_vague
from app.assistant.semantic import normalise, relevant_catalog, resolve_plan_fields
from app.assistant.followups import merge_follow_up
from app.data.base import DatasetCatalogProtocol
from app.data.exports import export_store
from app.data.display import RECONCILIATION_UNAVAILABLE
from app.data.metrics import metrics_store
from app.data.projections import from_clause
from app.data.query_engine import GroundedQueryEngine
from app.providers.base import LLMProvider
from app.schemas import (
    ChatRequest, ChatResponse, ClarificationOption, ClarificationRequest, Message,
    PendingClarification, ProviderResponse, QueryPlan,
)
from app.tools.registry import ToolRegistry


def format_catalog(catalog: dict[str, list[dict[str, str]]]) -> str:
    """One line per dataset, columns comma-separated.

    json.dumps(catalog) was ~660 tokens of dense {"name":..,"type":..} objects,
    and a sub-1B planner could not navigate it -- it blended columns from one
    dataset into a query against another. Plain lines are both cheaper and far
    easier for a small model to read, which is the whole game under Section 7.
    """
    lines = []
    for dataset, columns in sorted(catalog.items()):
        names = ", ".join(
            column["name"] + (
                f" ({' '.join(column['description'].split())[:100]})"
                if column.get("description") else ""
            )
            for column in columns
        )
        lines.append(f"{dataset}: {names}")
    return "\n".join(lines)


PLANNER_PROMPT = """You convert a finance question into ONE JSON query plan. Output JSON only.

TABLES (use columns ONLY from the table you pick):
__CATALOG__

FORMAT:
{"dataset":"<table>","operation":"list|count|sum|average|minimum|maximum",
 "measure":"<numeric column or null>","group_by":["<column>"],
 "select":["<columns required for list output; empty for aggregates>"],
 "filters":[{"column":"<column>","operator":"eq|neq|contains|gte|lte|gt|lt","value":<value>}],
 "limit":50}

RULES:
- Every column you name must exist in the dataset you chose. Never mix tables.
- "how much"/"total"/"spend" -> sum. "how many"/"count" -> count. Otherwise list.
- "spend"/"paid"/"outflow" means transaction_type=debit; "received"/"inflow"
  means transaction_type=credit when that field exists. If both appear, do not guess.
- measure is null for list and count.
- select only the columns needed to answer a list question (maximum 12). Use [] for aggregates.
- group_by only when the question asks for a breakdown ("by vendor", "per category").
- A date range is TWO filters: gte the first day, lte the last day.
- Bare "reference", "ref no" or "reference id" maps to transaction_reference_id.
  UTR is protected and must never be substituted for the plaintext reference field.
- Never invent a column or a value. If the question cannot be answered from these
  tables, return {"clarification":"<what is missing>"}.

TODAY=__TODAY__   (anchored to the data, which spans __DATA_MIN__ to __DATA_MAX__)
A period outside that span has no rows. Do not shift it to one that does.

EXAMPLES:
Q: How much was debited last month?
{"dataset":"transaction","operation":"sum","measure":"transaction_amount","group_by":[],"select":[],"filters":[{"column":"transaction_type","operator":"eq","value":"debit"},{"column":"transaction_date","operator":"gte","value":"__LAST_MONTH_START__"},{"column":"transaction_date","operator":"lte","value":"__LAST_MONTH_END__"}],"limit":50}

Q: Show transactions for bank code HDFC
{"dataset":"transaction","operation":"list","measure":null,"group_by":[],"select":["transaction_date","transaction_type","transaction_amount","transaction_reference_id","bank_code"],"filters":[{"column":"bank_code","operator":"eq","value":"HDFC"}],"limit":50}

Q: Break down available balance by bank
{"dataset":"account","operation":"sum","measure":"available_balance","group_by":["bank_name"],"select":[],"filters":[],"limit":50}
"""


class AssistantService:
    """Question -> guards -> planner -> validate -> compute -> templated answer.

    One model call per question. The answer sentence is generated from the
    computed evidence by app.assistant.narrate, not by a second model call:
    cheaper, and it removes the last place a figure could be garbled.
    """

    _vocabulary_cache: dict[str, set[str]] = {}
    _column_values_cache: dict[str, dict[str, set[str]]] = {}
    _bounds_cache: dict[str, tuple[str | None, str | None]] = {}
    _values_cache: dict[str, list[str]] = {}
    _column_bounds_cache: dict[str, dict[str, tuple[str, str]]] = {}
    _value_search_cache: dict[tuple[str, str, str], tuple[list[str], bool]] = {}

    def __init__(self, provider: LLMProvider, tools: ToolRegistry, catalog: DatasetCatalogProtocol):
        self.provider = provider
        self.tools = tools
        self.catalog = catalog

    @staticmethod
    def _json_object(content: str) -> dict:
        """Extract the first complete JSON object from a model response.

        Small models are the point of this project, and small models wrap their
        JSON in prose, fences, or a chatty preamble. Brace-matching survives all
        three; json.loads on the raw string does not.
        """
        cleaned = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        start = cleaned.find("{")
        if start == -1:
            raise json.JSONDecodeError("no JSON object in model output", cleaned, 0)
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(cleaned[start : index + 1])
        raise json.JSONDecodeError("unterminated JSON object in model output", cleaned, start)

    def _vocabulary(self, catalog: dict) -> set[str]:
        """Planning vocabulary, cached per extracted catalog shape."""
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._vocabulary_cache.get(signature)
        if cached is None:
            connection = self.catalog.connection()
            try:
                cached = guards.build_vocabulary(catalog, connection, self._source_for())
            finally:
                connection.close()
            self._vocabulary_cache[signature] = cached
        return cached

    def _values(self, catalog: dict) -> list[str]:
        """The names the data actually contains, for near-miss resolution."""
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._values_cache.get(signature)
        if cached is None:
            connection = self.catalog.connection()
            try:
                cached = guards.build_values(catalog, connection, self._source_for())
            finally:
                connection.close()
            self._values_cache[signature] = cached
        return cached

    def _column_bounds(self, catalog: dict) -> dict[str, tuple[str, str]]:
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._column_bounds_cache.get(signature)
        if cached is None:
            cached = self.catalog.column_date_bounds()
            self._column_bounds_cache[signature] = cached
        return cached

    def _source_for(self):
        """How this catalog's datasets are reached in SQL.

        A database we own exposes views; a read-only one needs the projection
        inlined into every statement.
        """
        inline = bool(getattr(self.catalog, "inline_sources", False))
        prefix = getattr(self.catalog, "source_prefix", "")
        return lambda dataset: from_clause(dataset, prefix, inline)

    def _column_values(self, catalog: dict) -> dict[str, set[str]]:
        """Distinct values per column, for spotting an invented filter."""
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._column_values_cache.get(signature)
        if cached is None:
            connection = self.catalog.connection()
            try:
                cached = guards.build_column_values(catalog, connection, self._source_for())
            finally:
                connection.close()
            self._column_values_cache[signature] = cached
        return cached

    def _anchor(self, catalog: dict) -> tuple[date, str | None, str | None]:
        """The date the planner should treat as 'now'.

        The day after the data ends, so "last month" resolves to the last full
        month the data contains. Falls back to the wall clock only when nothing
        in the data looks like a date.
        """
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._bounds_cache.get(signature)
        if cached is None:
            cached = self.catalog.date_bounds()
            self._bounds_cache[signature] = cached
        data_min, data_max = cached
        if not data_max:
            return date.today(), data_min, data_max
        try:
            end = date.fromisoformat(data_max[:10])
        except ValueError:
            return date.today(), data_min, data_max
        # The first day of the month AFTER the data ends, so "last month" means the
        # data's final month. Anchoring to end+1 day leaves the anchor inside that
        # month whenever the data stops mid-month, and "last month" silently skips
        # the most recent month the data has.
        following = (end.replace(day=28) + timedelta(days=4)).replace(day=1)
        return following, data_min, data_max

    def _refuse(self, request: ChatRequest, message: str, language: str, reason: str, usage=None) -> ChatResponse:
        metrics_store.record(
            question=request.message,
            model=usage.model if usage else "pre-model-guard",
            tokens_in=usage.tokens_in if usage else 0,
            tokens_out=usage.tokens_out if usage else 0,
            latency_ms=usage.latency_ms if usage else 0,
            refused=True,
            reason=reason,
        )
        return ChatResponse(
            session_id=request.session_id,
            answer=message,
            confidence="low",
            clarification_needed=True,
            refusal_reason=reason,
            language=language,
            usage=usage.model_dump(exclude={"content"}) if usage else None,
        )

    async def respond(self, request: ChatRequest) -> ChatResponse:
        started = time.monotonic()
        language = guards.detect_language(request.message)
        catalog = self.catalog.describe()

        if not catalog:
            return self._refuse(
                request,
                "The TBX starter dataset has not been provided yet. Upload its CSV files when "
                "available; I will discover their schemas automatically.",
                language,
                "no_dataset",
            )

        # A selected clarification resumes the server-stored partial plan. The
        # browser cannot supply or alter that plan, and no second model call is
        # needed for an allowlisted selection.
        resumed_plan = None
        clarification_attempts = 0
        if request.selection:
            pending = request.pending_clarification
            if not pending or pending.request.id != request.selection.clarification_id:
                return self._refuse(
                    request, "That clarification has expired. Please ask the question again.",
                    language, "expired_clarification",
                )
            allowed = {option.value for option in pending.request.options}
            if request.selection.value not in allowed and pending.request.allow_search:
                slot = pending.request.slot.split(":")
                if slot[0] == "filters" and slot[2] == "value":
                    item = pending.partial_plan["filters"][int(slot[1])]
                    matches, _ = self.catalog.search_values(
                        pending.partial_plan["dataset"], item["column"],
                        request.selection.value, 8,
                    )
                    exact = next(
                        (value for value in matches if normalise(value) == normalise(request.selection.value)),
                        None,
                    )
                    if exact:
                        request.selection.value = exact
                        allowed.add(exact)
            if request.selection.value not in allowed:
                return self._refuse(
                    request, "Please choose one of the fields shown for this question.",
                    language, "invalid_clarification_selection",
                )
            resumed_plan = dict(pending.partial_plan)
            clarification_attempts = pending.attempts + 1
            slot = pending.request.slot.split(":")
            if slot[0] in {"measure"}:
                resumed_plan[slot[0]] = request.selection.value
            elif slot[0] in {"group_by", "select"}:
                resumed_plan[slot[0]][int(slot[1])] = request.selection.value
            elif slot[0] == "filters":
                resumed_plan["filters"][int(slot[1])][slot[2]] = request.selection.value
            request = request.model_copy(update={"message": pending.original_question})

        # ---- small talk, before the guards ------------------------------------
        # a greeting is not a question about missing data, and answering "hi" with
        # a refusal is the worst possible first impression
        if (greeting := conversational_reply(
            request.message,
            list(catalog),
            {name: [c["name"] for c in cols] for name, cols in catalog.items()},
        )) is not None:
            metrics_store.record(question=request.message, model="pre-model-smalltalk", refused=False)
            return ChatResponse(
                session_id=request.session_id,
                answer=greeting,
                confidence="high",
                language=language,
                suggested_actions=[
                    "How much was debited last month?",
                    "Show transactions for bank code HDFC",
                    "Break down available balance by bank",
                ],
            )

        # with a previous plan in hand a two-word message is a refinement
        # ("For HDFC?"), not an unanswerable fragment
        if request.previous_plan is None and (vague := too_vague(request.message)) is not None:
            metrics_store.record(question=request.message, model="pre-model-guard",
                                 refused=True, reason="too_vague")
            return ChatResponse(
                session_id=request.session_id, answer=vague, confidence="low",
                clarification_needed=True, refusal_reason="too_vague", language=language,
            )

        # ---- deterministic guards, before any model call (zero tokens) --------
        # English-only by construction, so Indic input skips them and relies on
        # plan validation instead, which is language-agnostic.
        if not guards.is_indic(language):
            sensitive = guards.sensitive_request(request.message)
            if sensitive:
                message, reason = sensitive
                return self._refuse(request, message, language, reason)

            capability = guards.missing_capability(request.message, catalog)
            if capability:
                message, reason = capability
                return self._refuse(request, message, language, reason)

            if guards.RECONCILIATION_RE.search(request.message):
                return self._refuse(
                    request, RECONCILIATION_UNAVAILABLE, language, "no_reconciliation_data"
                )

            if guards.FORECAST_RE.search(request.message):
                return self._refuse(
                    request,
                    "I can only report what is already in the dataset. Forecasting future "
                    "figures is outside what this data supports.",
                    language,
                    "forecast_request",
                )

            vocabulary = self._vocabulary(catalog)

            # Near-miss resolution. The word-level check above lets "Zylo Corp"
            # through whenever some other vendor is a "Corp", so every named
            # entity is also scored against the real values with generic company
            # words stripped out first. A wrong vendor is a wrong number.
            known_values = self._values(catalog)
            for phrase in guards.candidate_entities(request.message) if known_values else []:
                verdict, best, close, score = guards.resolve_entity(phrase, known_values)
                if verdict == "unknown":
                    return self._refuse(
                        request,
                        f'"{phrase}" does not appear anywhere in the loaded data, so I cannot '
                        "answer that. Returning a figure that ignores it would be misleading.",
                        language,
                        f"unknown_entity:{phrase}",
                    )
                if verdict == "ambiguous":
                    return self._refuse(
                        request,
                        f'I am not confident which one "{phrase}" refers to (closest match '
                        f'scored {score:.2f}). Did you mean: {", ".join(close)}?',
                        language,
                        f"ambiguous_entity:{phrase}",
                    )


            missing = guards.unsupported_subject(request.message, vocabulary)
            if missing:
                available = ", ".join(sorted(catalog))
                return self._refuse(
                    request,
                    f'This dataset covers {available}. It has nothing about '
                    f'"{", ".join(missing)}", so I cannot answer that.',
                    language,
                    f"unsupported_subject:{','.join(missing)}",
                )

            ghost = guards.unresolved_entity(request.message, vocabulary) if known_values else None
            if ghost:
                return self._refuse(
                    request,
                    f'"{ghost}" does not appear anywhere in the loaded data, so I cannot '
                    "answer that. Returning a total that ignores it would be misleading.",
                    language,
                    f"unresolved_entity:{ghost}",
                )

        # ---- one model call: question -> query plan --------------------------
        anchor, data_min, data_max = self._anchor(catalog)
        last_month_end = anchor.replace(day=1) - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        planner_prompt = (
            PLANNER_PROMPT.replace(
                "__CATALOG__", format_catalog(relevant_catalog(request.message, catalog))
            )
            .replace("__TODAY__", anchor.isoformat())
            .replace("__DATA_MIN__", data_min or "unknown")
            .replace("__DATA_MAX__", data_max or "unknown")
            .replace("__LAST_MONTH_START__", last_month_start.isoformat())
            .replace("__LAST_MONTH_END__", last_month_end.isoformat())
        )
        planner_messages = [Message(role="system", content=planner_prompt)]
        if request.previous_plan:
            planner_messages.append(Message(
                role="system",
                content="PREVIOUS_VALIDATED_PLAN=" + request.previous_plan.model_dump_json(),
            ))
        # The transcript is deliberately NOT sent. Context is carried by merging
        # the previous QueryPlan in Python (app/assistant/followups.py), so the
        # model never has to resolve what "that" referred to and cannot get it
        # wrong. Replaying history also made the planner sticky: asked to widen
        # ("and total spent?") it copied the previous bank filter straight back.
        planner_messages.append(Message(role="user", content=request.message))
        planned = (
            ProviderResponse(content=json.dumps(resumed_plan), model="clarification-selection")
            if resumed_plan is not None
            else await self.provider.generate(planner_messages)
        )

        try:
            raw_plan = resumed_plan or self._json_object(planned.content)
        except (json.JSONDecodeError, IndexError):
            return self._refuse(
                request,
                "I could not map that question to the available data safely. Please specify "
                "the metric, time range, or status.",
                language,
                "unparseable_plan",
                planned,
            )

        if clarification := raw_plan.get("clarification"):
            return self._refuse(request, clarification, language, "model_clarification", planned)

        # deterministic repair before validation: small planners make a small set
        # of repeatable mistakes that are cheaper to correct than to prompt away
        raw_plan, repairs = repair_plan(
            raw_plan, request.message, catalog, self._values(catalog), anchor,
            self._column_bounds(catalog), self._column_values(catalog),
        )
        raw_plan, mappings, ambiguity = resolve_plan_fields(raw_plan, catalog)
        repairs.extend(mappings)
        if ambiguity:
            if clarification_attempts >= 2:
                return self._refuse(
                    request,
                    "I still cannot resolve the requested field safely. Please name the exact field.",
                    language, "clarification_limit_reached", planned,
                )
            clarification = ClarificationRequest(
                kind="field", slot=ambiguity.slot, prompt=ambiguity.prompt,
                options=[ClarificationOption(**option) for option in ambiguity.options],
            )
            pending = PendingClarification(
                request=clarification, original_question=request.message,
                partial_plan=raw_plan, attempts=clarification_attempts,
            )
            return ChatResponse(
                session_id=request.session_id,
                answer=ambiguity.prompt,
                confidence="low",
                clarification_needed=True,
                refusal_reason="ambiguous_field",
                language=language,
                clarification=clarification,
                pending_clarification=pending,
                usage=planned.model_dump(exclude={"content"}),
            )

        # A filter on a value the column does not contain is an invented filter.
        # Answering "no rows match" would present a bad plan as a real finding.
        if unresolved := raw_plan.pop("_unresolved", None):
            column, value, examples = unresolved[0]
            return self._refuse(
                request,
                f'There is no {column} of "{value}" in this data, so I cannot answer that. '
                f'Values I do have include: {", ".join(examples)}.',
                language,
                f"invented_filter:{column}={value}",
                planned,
            )

        # Resolve low-cardinality values from MySQL, not from model memory. Only
        # indexed dimension-like fields participate, and only exact equality
        # filters need confirmation.
        for index, item in enumerate(raw_plan.get("filters") or []):
            column = item.get("column", "")
            value = item.get("value")
            if item.get("operator") != "eq" or not isinstance(value, str):
                continue
            if not re.search(r"(^|_)(name|code|status|type)$", column, re.IGNORECASE):
                continue
            key = (raw_plan.get("dataset", ""), column, normalise(value))
            try:
                candidates, has_more = self._value_search_cache.get(key) or self.catalog.search_values(
                    raw_plan["dataset"], column, value, 8
                )
                self._value_search_cache[key] = (candidates, has_more)
            except (AttributeError, ValueError):
                continue
            exact = next((candidate for candidate in candidates if normalise(candidate) == normalise(value)), None)
            if exact:
                item["value"] = exact
                continue
            if len(candidates) == 1:
                item["value"] = candidates[0]
                repairs.append(f"filter:{column}: {value} -> {candidates[0]} (unique database match)")
                continue
            clarification = ClarificationRequest(
                kind="value", slot=f"filters:{index}:value",
                prompt=f'Which {column.replace("_", " ")} did you mean by "{value}"?',
                options=[ClarificationOption(label=candidate, value=candidate) for candidate in candidates],
                allow_search=True,
                search_url=(
                    f"/api/v1/datasets/{raw_plan['dataset']}/values?column={column}&q="
                ),
            )
            if clarification_attempts >= 2:
                return self._refuse(
                    request,
                    f'I still cannot identify "{value}" safely. Please provide its exact database value.',
                    language, "clarification_limit_reached", planned,
                )
            pending = PendingClarification(
                request=clarification, original_question=request.message,
                partial_plan=raw_plan, attempts=clarification_attempts,
            )
            return ChatResponse(
                session_id=request.session_id, answer=clarification.prompt,
                confidence="low", clarification_needed=True,
                refusal_reason="ambiguous_value", language=language,
                clarification=clarification, pending_clarification=pending,
                usage=planned.model_dump(exclude={"content"}),
            )
        try:
            plan = QueryPlan.model_validate(raw_plan)
            plan, follow_up_repairs = merge_follow_up(plan, request.previous_plan, request.message)
            repairs.extend(follow_up_repairs)
            result = GroundedQueryEngine(self.catalog).execute(plan)
        except (ValidationError, ValueError, duckdb.Error) as exc:
            # a raw pydantic traceback is not an answer; say what went wrong plainly
            detail = str(exc).split("\n")[0]
            if isinstance(exc, duckdb.Error):
                # a type mismatch means the plan asked something the columns
                # cannot answer - that is a refusal, never a stack trace
                detail = "the filters did not match the column types in that table"
            elif isinstance(exc, ValidationError):
                fields = ", ".join(str(e.get("loc", ["?"])[0]) for e in exc.errors()[:3])
                detail = f"the plan it produced was incomplete ({fields})"
            return self._refuse(
                request,
                f"I could not build a query I trust for that: {detail}. "
                "Try naming the metric, the table, or a date range explicitly.",
                language,
                "plan_validation_failed",
                planned,
            )

        # a receipt that does not add up is worse than no receipt
        if result.evidence.reconciles is False:
            return self._refuse(
                request,
                "I computed a total but the supporting records do not add up to it, so I will "
                "not show you a number I cannot stand behind. "
                + result.evidence.reconcile_note,
                language,
                "reconciliation_failed",
                planned,
            )

        export_store.put(result.evidence.export_id or "", result.csv_content)

        # ---- narration: templated from the computed result, no model call ----
        answer = narrate(plan, result.evidence, result.total_matching, language)
        # tripwire: no numeral may appear in the answer that we did not compute
        verified, orphans = verify_numbers(
            answer, allowed_numerals(result.evidence, result.total_matching, plan.filters)
        )

        metrics_store.record(
            question=request.message,
            model=planned.model,
            tokens_in=planned.tokens_in,
            tokens_out=planned.tokens_out,
            latency_ms=planned.latency_ms,
            refused=False,
        )

        return ChatResponse(
            session_id=request.session_id,
            answer=answer,
            confidence="high" if result.total_matching else "low",
            evidence=result.evidence,
            language=language,
            plan_repairs=repairs,
            numbers_verified=verified,
            orphan_numbers=orphans,
            usage={
                "model": planned.model,
                "tokens_in": planned.tokens_in,
                "tokens_out": planned.tokens_out,
                "latency_ms": planned.latency_ms,
                "total_ms": int((time.monotonic() - started) * 1000),
                "model_calls": 1,
            },
            query_plan=plan,
        )
