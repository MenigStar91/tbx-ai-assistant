from app.tools.registry import ToolRegistry


def test_percentage_change_is_deterministic():
    result = ToolRegistry().execute(
        "percentage_change", {"old_value": 100, "new_value": 125}
    )
    assert result == {"percentage_change": 25.0}

