"""Relative periods must anchor to the data, not to the wall clock.

A finance dataset is historical. If it ends in June and today is September,
anchoring "last month" to today selects an empty window and the assistant
answers a confident zero -- for the brief's own headline demo question.
"""
from datetime import date

from app.assistant.service import AssistantService
from app.data.catalog import DatasetCatalog
from app.providers.mock import MockProvider
from app.tools.registry import ToolRegistry


def _service(tmp_path, last_date: str):
    (tmp_path / "vendor_payouts.csv").write_text(
        "payout_id,payout_date,vendor_name,amount,status\n"
        "PAY-1,2026-01-15,Acme,100,paid\n"
        f"PAY-2,{last_date},Acme,200,paid\n"
    )
    catalog = DatasetCatalog(str(tmp_path))
    service = AssistantService(MockProvider(), ToolRegistry(), catalog)
    service._bounds_cache.clear()
    return service, catalog


def test_bounds_come_from_the_data(tmp_path):
    _, catalog = _service(tmp_path, "2026-06-30")
    assert catalog.date_bounds() == ("2026-01-15", "2026-06-30")


def test_anchor_is_the_first_of_the_month_after_the_data(tmp_path):
    service, catalog = _service(tmp_path, "2026-06-30")
    anchor, data_min, data_max = service._anchor(catalog.describe())
    assert anchor == date(2026, 7, 1)
    assert (data_min, data_max) == ("2026-01-15", "2026-06-30")


def test_data_ending_mid_month_still_makes_that_month_last_month(tmp_path):
    """The regression: data ending 2026-08-30 anchored to 2026-08-31, which is
    still inside August, so "last month" resolved to July and skipped the data's
    most recent month entirely."""
    from datetime import timedelta
    service, catalog = _service(tmp_path, "2026-08-30")
    anchor, _, _ = service._anchor(catalog.describe())
    assert anchor == date(2026, 9, 1)
    last_month_end = anchor.replace(day=1) - timedelta(days=1)
    assert last_month_end.replace(day=1) == date(2026, 8, 1)


def test_last_month_lands_inside_stale_data(tmp_path):
    """The regression: with data ending June 2026 and a September wall clock,
    "last month" must mean June, not August."""
    service, catalog = _service(tmp_path, "2026-06-30")
    anchor, _, _ = service._anchor(catalog.describe())
    from datetime import timedelta
    last_month_end = anchor.replace(day=1) - timedelta(days=1)
    assert last_month_end == date(2026, 6, 30)
    assert last_month_end.replace(day=1) == date(2026, 6, 1)


def test_falls_back_to_the_wall_clock_without_dates(tmp_path):
    (tmp_path / "vendors.csv").write_text("vendor_id,vendor_name\nV1,Acme\n")
    catalog = DatasetCatalog(str(tmp_path))
    service = AssistantService(MockProvider(), ToolRegistry(), catalog)
    service._bounds_cache.clear()
    anchor, _, data_max = service._anchor(catalog.describe())
    assert data_max is None
    assert anchor == date.today()
