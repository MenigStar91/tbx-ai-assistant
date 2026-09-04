import json
import re
import time
from datetime import date, timedelta

from pydantic import ValidationError

from app.assistant import guards
from app.assistant.narrate import narrate
from app.assistant.repair import repair_plan
from app.assistant.smalltalk import conversational_reply
from app.data.catalog import DatasetCatalog
from app.data.exports import export_store
from app.data.metrics import metrics_store
from app.data.query_engine import GroundedQueryEngine
from app.providers.base import LLMProvider
from app.schemas import ChatRequest, ChatResponse, Message, QueryPlan
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
        names = ", ".join(column["name"] for column in columns)
        lines.append(f"{dataset}: {names}")
    return "\n".join(lines)


PLANNER_PROMPT = """You convert a finance question into ONE JSON query plan. Output JSON only.

TABLES (use columns ONLY from the table you pick):
__CATALOG__

FORMAT:
{"dataset":"<table>","operation":"list|count|sum|average|minimum|maximum",
 "measure":"<numeric column or null>","group_by":["<column>"],
 "filters":[{"column":"<column>","operator":"eq|neq|contains|gte|lte|gt|lt","value":<value>}],
 "limit":50}

RULES:
- Every column you name must exist in the dataset you chose. Never mix tables.
- "how much"/"total"/"spend" -> sum. "how many"/"count" -> count. Otherwise list.
- measure is null for list and count.
- group_by only when the question asks for a breakdown ("by vendor", "per category").
- A date range is TWO filters: gte the first day, lte the last day.
- Never invent a column or a value. If the question cannot be answered from these
  tables, return {"clarification":"<what is missing>"}.

TODAY=__TODAY__

EXAMPLES:
Q: How much did we spend on vendor payouts last month?
{"dataset":"vendor_payouts","operation":"sum","measure":"amount","group_by":[],"filters":[{"column":"payout_date","operator":"gte","value":"__LAST_MONTH_START__"},{"column":"payout_date","operator":"lte","value":"__LAST_MONTH_END__"}],"limit":50}

Q: Which transactions are still unreconciled?
{"dataset":"transactions","operation":"list","measure":null,"group_by":[],"filters":[{"column":"reconciliation_status","operator":"eq","value":"unreconciled"}],"limit":50}

Q: Break down spend by vendor
{"dataset":"transactions","operation":"sum","measure":"amount","group_by":["vendor_name"],"filters":[],"limit":50}
"""


class AssistantService:
    """Question -> guards -> planner -> validate -> compute -> templated answer.

    One model call per question. The answer sentence is generated from the
    computed evidence by app.assistant.narrate, not by a second model call:
    cheaper, and it removes the last place a figure could be garbled.
    """

    _vocabulary_cache: dict[str, set[str]] = {}

    def __init__(self, provider: LLMProvider, tools: ToolRegistry, catalog: DatasetCatalog):
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
        """Words the dataset itself contains. Cached per catalog shape, since
        rebuilding it means a DISTINCT scan of every text column."""
        signature = json.dumps(catalog, sort_keys=True)
        cached = self._vocabulary_cache.get(signature)
        if cached is None:
            connection = self.catalog.connection()
            try:
                cached = guards.build_vocabulary(catalog, connection)
            finally:
                connection.close()
            self._vocabulary_cache[signature] = cached
        return cached

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

        # ---- small talk, before the guards ------------------------------------
        # a greeting is not a question about missing data, and answering "hi" with
        # a refusal is the worst possible first impression
        if (greeting := conversational_reply(request.message, list(catalog))) is not None:
            metrics_store.record(question=request.message, model="pre-model-smalltalk", refused=False)
            return ChatResponse(
                session_id=request.session_id,
                answer=greeting,
                confidence="high",
                language=language,
                suggested_actions=[
                    "How much did we spend on vendor payouts last month?",
                    "Which transactions are still unreconciled?",
                    "Break down spend by vendor",
                ],
            )

        # ---- deterministic guards, before any model call (zero tokens) --------
        # English-only by construction, so Indic input skips them and relies on
        # plan validation instead, which is language-agnostic.
        if not guards.is_indic(language):
            if guards.FORECAST_RE.search(request.message):
                return self._refuse(
                    request,
                    "I can only report what is already in the dataset. Forecasting future "
                    "figures is outside what this data supports.",
                    language,
                    "forecast_request",
                )

            vocabulary = self._vocabulary(catalog)

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

            ghost = guards.unresolved_entity(request.message, vocabulary)
            if ghost:
                return self._refuse(
                    request,
                    f'"{ghost}" does not appear anywhere in the loaded data, so I cannot '
                    "answer that. Returning a total that ignores it would be misleading.",
                    language,
                    f"unresolved_entity:{ghost}",
                )

        # ---- one model call: question -> query plan --------------------------
        today = date.today()
        last_month_end = today.replace(day=1) - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        planner_prompt = (
            PLANNER_PROMPT.replace("__CATALOG__", format_catalog(catalog))
            .replace("__TODAY__", today.isoformat())
            .replace("__LAST_MONTH_START__", last_month_start.isoformat())
            .replace("__LAST_MONTH_END__", last_month_end.isoformat())
        )
        planner_messages = [Message(role="system", content=planner_prompt)]
        planner_messages.extend(request.history[-12:])
        planner_messages.append(Message(role="user", content=request.message))
        planned = await self.provider.generate(planner_messages)

        try:
            raw_plan = self._json_object(planned.content)
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
        raw_plan, repairs = repair_plan(raw_plan, request.message, catalog)

        try:
            plan = QueryPlan.model_validate(raw_plan)
            result = GroundedQueryEngine(self.catalog).execute(plan)
        except (ValidationError, ValueError) as exc:
            return self._refuse(
                request,
                f"I cannot verify that request against the available dataset: {exc}",
                language,
                "plan_validation_failed",
                planned,
            )

        export_store.put(result.evidence.export_id or "", result.csv_content)

        # ---- narration: templated from the computed result, no model call ----
        answer = narrate(plan, result.evidence, result.total_matching, language)

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
            usage={
                "model": planned.model,
                "tokens_in": planned.tokens_in,
                "tokens_out": planned.tokens_out,
                "latency_ms": planned.latency_ms,
                "total_ms": int((time.monotonic() - started) * 1000),
                "model_calls": 1,
            },
        )
