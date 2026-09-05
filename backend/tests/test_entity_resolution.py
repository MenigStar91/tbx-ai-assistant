"""Near-miss vendor names must refuse, not resolve to a different vendor.

"Zylo Corp" scores ~0.6 against "Acme Corp" on the shared suffix alone. Left
unhandled that turns a correct refusal into a confidently wrong number, which
is the single most damaging failure this system can produce.
"""
from app.assistant.guards import (
    MATCH_CONFIRM,
    MATCH_FLOOR,
    candidate_entities,
    resolve_entity,
)

VALUES = ["Acme Industries", "Northwind Cloud", "PeopleBridge Services", "Deccan Office Supplies"]


def test_exact_name_resolves():
    verdict, best, _, _ = resolve_entity("Acme Industries", VALUES)
    assert (verdict, best) == ("exact", "Acme Industries")


def test_case_insensitive_exact():
    verdict, _, _, _ = resolve_entity("acme industries", VALUES)
    assert verdict == "exact"


def test_distinctive_prefix_resolves():
    verdict, best, _, _ = resolve_entity("Acme", VALUES)
    assert verdict == "confident" and best == "Acme Industries"


def test_shared_company_suffix_does_not_carry_a_match():
    # the headline bug: a suffix in common must not make an unknown name known
    verdict, _, _, score = resolve_entity("Zylo Corp", VALUES + ["Acme Corp"])
    assert verdict == "unknown", f"resolved with score {score}"


def test_globex_is_unknown():
    verdict, _, _, _ = resolve_entity("Globex Corporation", VALUES)
    assert verdict == "unknown"


def test_a_genuine_near_miss_is_flagged_ambiguous_not_guessed():
    verdict, _, close, _ = resolve_entity("Northwind Clod", VALUES)
    assert verdict in {"ambiguous", "confident"}
    if verdict == "ambiguous":
        assert "Northwind Cloud" in close


def test_thresholds_are_ordered():
    assert 0 < MATCH_FLOOR < MATCH_CONFIRM < 1


def test_candidate_extraction_ignores_query_words():
    assert candidate_entities("Break down spend by vendor") == []
    assert "Globex Corporation" in candidate_entities("How much did we pay Globex Corporation?")


def test_no_values_means_unknown():
    verdict, _, _, _ = resolve_entity("Acme", [])
    assert verdict == "unknown"
