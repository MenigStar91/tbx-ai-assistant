from collections.abc import Callable
from decimal import Decimal
from typing import Any


Tool = Callable[..., dict[str, Any]]


def percentage_change(old_value: float, new_value: float) -> dict[str, Any]:
    old = Decimal(str(old_value))
    new = Decimal(str(new_value))
    if old == 0:
        raise ValueError("old_value must not be zero")
    result = ((new - old) / old) * Decimal("100")
    return {"percentage_change": float(result.quantize(Decimal("0.01")))}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {"percentage_change": percentage_change}

    def register(self, name: str, tool: Tool) -> None:
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return self._tools[name](**arguments)

