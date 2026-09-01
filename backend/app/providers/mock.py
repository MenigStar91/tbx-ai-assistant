from app.schemas import Message, ProviderResponse


class MockProvider:
    async def generate(self, messages: list[Message]) -> ProviderResponse:
        user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        return ProviderResponse(
            content=(
                "Mock assistant is working. I received: "
                f"\"{user_message}\". Replace the mock provider or add TBX tools "
                "after the problem statement is released."
            )
        )

