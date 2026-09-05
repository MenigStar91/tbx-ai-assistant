"""Score multi-turn context handling separately from single-turn accuracy."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> int:
    os.environ.setdefault("LLM_PROVIDER", "mock")
    from app.assistant.service import AssistantService
    from app.config import get_settings
    from app.data.factory import get_dataset_catalog
    from app.providers.factory import create_provider
    from app.schemas import ChatRequest, Message
    from app.tools.registry import ToolRegistry

    cases = json.loads((Path(__file__).parent / "follow_up_questions.json").read_text())["conversations"]
    settings = get_settings()
    catalog = get_dataset_catalog()
    service = AssistantService(create_provider(settings), ToolRegistry(), catalog)
    passed = total = 0

    for conversation in cases:
        history: list[Message] = []
        previous_plan = None
        session_id = uuid4()
        for turn in conversation["turns"]:
            response = await service.respond(ChatRequest(
                session_id=session_id,
                message=turn["q"],
                history=history[-12:],
                previous_plan=previous_plan,
            ))
            total += 1
            plan = response.query_plan
            expected = turn["expect"]
            actual_filters = {item.column: item.value for item in plan.filters} if plan else {}
            ok = bool(plan) and all(getattr(plan, key) == value for key, value in expected.items() if key != "filters")
            ok = ok and all(actual_filters.get(key) == value for key, value in expected.get("filters", {}).items())
            ok = ok and not (set(actual_filters) - set(expected.get("filters", {})) - {"transaction_date"})
            passed += int(ok)
            detail = "" if ok else f" -> {plan.model_dump() if plan else response.refusal_reason}"
            print(f"{'PASS' if ok else 'FAIL'} {conversation['name']}: {turn['q']}{detail}")
            history.extend([Message(role="user", content=turn["q"]), Message(role="assistant", content=response.answer)])
            previous_plan = plan or previous_plan

    score = passed / total * 100 if total else 0
    print(f"Follow-up plan accuracy: {score:.1f}% ({passed}/{total})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
