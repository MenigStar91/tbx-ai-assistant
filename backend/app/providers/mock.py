import json

from app.schemas import Message, ProviderResponse


class MockProvider:
    async def generate(self, messages: list[Message]) -> ProviderResponse:
        user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        system = messages[0].content if messages else ""
        if "QUERY_PLANNER" in system:
            marker = "AVAILABLE_DATASETS_JSON="
            raw = system.split(marker, 1)[1].split("\n", 1)[0]
            catalog = json.loads(raw)
            if not catalog:
                return ProviderResponse(content='{"clarification":"Upload the TBX starter CSV files first."}')
            dataset = next(iter(catalog))
            return ProviderResponse(content=json.dumps({
                "dataset": dataset,
                "operation": "count",
                "measure": None,
                "group_by": [],
                "filters": [],
                "limit": 50,
            }))
        if "GROUNDED_EXPLAINER" in system:
            return ProviderResponse(content="The result shown below was computed directly from the uploaded dataset. Mock mode only demonstrates the grounded pipeline; configure a lightweight model for natural-language interpretation.")
        return ProviderResponse(
            content=(
                "Mock assistant is working. I received: "
                f"\"{user_message}\". Replace the mock provider or add TBX tools "
                "after the problem statement is released."
            )
        )
