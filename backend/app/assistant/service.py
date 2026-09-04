import json
import re

from pydantic import ValidationError

from app.data.catalog import DatasetCatalog
from app.data.exports import export_store
from app.data.query_engine import GroundedQueryEngine
from app.providers.base import LLMProvider
from app.schemas import ChatRequest, ChatResponse, Message, QueryPlan
from app.tools.registry import ToolRegistry


PLANNER_PROMPT = """QUERY_PLANNER
You translate finance questions into exactly one safe JSON query plan.
Use only datasets and columns in the supplied catalog. Never calculate an answer.
Resolve follow-ups using conversation history. If information is missing or ambiguous,
return {"clarification":"specific question"}. Otherwise return only JSON matching:
{"dataset":str,"operation":"list|count|sum|average|minimum|maximum","measure":str|null,
"group_by":[str],"filters":[{"column":str,"operator":"eq|neq|contains|gte|lte|gt|lt","value":any}],"limit":int}
AVAILABLE_DATASETS_JSON=__CATALOG__
"""

EXPLAINER_PROMPT = """GROUNDED_EXPLAINER
Explain only the supplied computed evidence. Do not add or recalculate numbers.
Mention filters or grouping that materially affect the answer. If the rows are empty,
say the uploaded data does not contain a matching answer. Be concise."""


class AssistantService:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry, catalog: DatasetCatalog):
        self.provider = provider
        self.tools = tools
        self.catalog = catalog

    @staticmethod
    def _json_object(content: str) -> dict:
        cleaned = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
        return json.loads(cleaned)

    async def respond(self, request: ChatRequest) -> ChatResponse:
        catalog = self.catalog.describe()
        if not catalog:
            return ChatResponse(
                session_id=request.session_id,
                answer="The TBX starter dataset has not been provided yet. Upload its CSV files when available; I will discover their schemas automatically.",
                confidence="low",
                clarification_needed=True,
            )
        planner_messages = [Message(role="system", content=PLANNER_PROMPT.replace("__CATALOG__", json.dumps(catalog)))]
        planner_messages.extend(request.history[-12:])
        planner_messages.append(Message(role="user", content=request.message))
        planned = await self.provider.generate(planner_messages)
        try:
            raw_plan = self._json_object(planned.content)
        except (json.JSONDecodeError, IndexError):
            return ChatResponse(session_id=request.session_id, answer="I could not map that question to the available data safely. Please specify the metric, time range, or status.", confidence="low", clarification_needed=True)
        if clarification := raw_plan.get("clarification"):
            return ChatResponse(session_id=request.session_id, answer=clarification, confidence="low", clarification_needed=True)
        try:
            plan = QueryPlan.model_validate(raw_plan)
            result = GroundedQueryEngine(self.catalog).execute(plan)
        except (ValidationError, ValueError) as exc:
            return ChatResponse(session_id=request.session_id, answer=f"I cannot verify that request against the available dataset: {exc}", confidence="low", clarification_needed=True)
        export_store.put(result.evidence.export_id or "", result.csv_content)
        evidence_json = result.evidence.model_dump_json()
        explanation = await self.provider.generate([
            Message(role="system", content=EXPLAINER_PROMPT),
            Message(role="user", content=f"Question: {request.message}\nComputed evidence: {evidence_json}"),
        ])
        return ChatResponse(
            session_id=request.session_id,
            answer=explanation.content,
            confidence="high" if result.evidence.rows else "low",
            evidence=result.evidence,
        )
