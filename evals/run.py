"""Accuracy and efficiency harness.

Produces the two numbers the pitch is argued from:

    "X% correct on N held-out questions, averaging T tokens per query."

Truth comes from independent SQL executed directly against the datasets, never
from the engine under test.

    python evals/run.py                       # in-process, default provider
    python evals/run.py --provider sarvam
    python evals/run.py --data data/sample
    python evals/run.py --md > EVAL.md        # paste into the README
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_questions() -> list[dict]:
    return json.loads((Path(__file__).parent / "questions.json").read_text())["questions"]


def _expectation_sql(sql: str, catalog) -> str:
    """Point the ground-truth query at the same surface the app queries.

    On a database we own the datasets are views; on a read-only one they are
    inlined projections. The expectation has to read the same thing, or it is
    measuring a different table.
    """
    if not getattr(catalog, "inline_sources", False):
        return sql
    from app.data.projections import PROJECTIONS, projection_sql

    prefix = getattr(catalog, "source_prefix", "")
    for dataset in PROJECTIONS:
        source = f'( {projection_sql(dataset, prefix)} ) AS "{dataset}"'
        sql = re.sub(rf'FROM\s+"?{dataset}"?\b', f"FROM {source}", sql, flags=re.IGNORECASE)
    return sql


def computed_value(response) -> float | None:
    """The single figure the assistant is asserting, whatever its shape."""
    evidence = response.evidence
    if evidence is None:
        return None
    if evidence.rows and "result" in evidence.rows[0]:
        # an aggregate over zero rows returns NULL, which is a legitimate 0
        return float(evidence.rows[0]["result"] or 0)
    return float(evidence.total_rows)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "mock"))
    parser.add_argument("--data", default=os.environ.get("DATA_DIRECTORY", "data/sample"))
    parser.add_argument("--md", action="store_true")
    args = parser.parse_args()

    os.environ["LLM_PROVIDER"] = args.provider
    os.environ["DATA_DIRECTORY"] = args.data

    from app.assistant.service import AssistantService
    from app.config import get_settings
    from app.data.catalog import DatasetCatalog
    from app.data.source_factory import create_catalog
    from app.data.metrics import metrics_store
    from app.providers.factory import create_provider
    from app.schemas import ChatRequest
    from app.tools.registry import ToolRegistry

    data_dir = str((ROOT / args.data).resolve())
    # honour DATA_BACKEND so the same questions can be scored against files or MySQL
    from app.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    catalog = create_catalog(settings) if settings.data_backend.lower() == "mysql" else DatasetCatalog(data_dir)
    connection = catalog.connection()
    service = AssistantService(create_provider(get_settings()), ToolRegistry(), catalog)

    metrics_store.reset()
    results: list[dict] = []

    for item in load_questions():
        response = await service.respond(ChatRequest(message=item["q"]))
        refused = response.clarification_needed

        if item.get("expect_conversational"):
            conversational = not refused and response.evidence is None and bool(response.answer)
            results.append({
                "q": item["q"], "kind": "conversational", "category": item.get("category", "other"),
                "pass": conversational,
                "detail": "greeted" if conversational else f"treated as a query ({response.refusal_reason or 'answered'})",
            })
            continue

        if item.get("expect_refusal"):
            results.append({
                "q": item["q"], "kind": "refusal", "category": item.get("category", "other"), "pass": refused,
                "detail": (response.refusal_reason or "refused") if refused
                          else f"ANSWERED when it should have refused ({computed_value(response)})",
            })
            continue

        if refused:
            results.append({"q": item["q"], "kind": "value", "category": item.get("category", "other"), "pass": False,
                            "detail": f"refused, but the data supports an answer: {response.refusal_reason}"})
            continue

        sql = item.get("expect_sql") or item["expect_groups_sql"]
        expected = float(connection.execute(_expectation_sql(sql, catalog)).fetchone()[0])
        actual = (float(response.evidence.total_groups)
                  if item.get("expect_groups_sql") and response.evidence.total_groups is not None
                  else computed_value(response))
        ok = actual is not None and abs(actual - expected) <= max(1e-6, abs(expected) * 1e-6)
        results.append({"q": item["q"], "kind": "value", "category": item.get("category", "other"), "pass": ok,
                        "detail": f"{actual:g}" if ok else f"got {actual}, expected {expected:g}"})

    connection.close()
    summary = metrics_store.summary()
    passed = sum(1 for r in results if r["pass"])
    pct = passed / len(results) * 100
    values = [r for r in results if r["kind"] == "value"]
    refusals = [r for r in results if r["kind"] == "refusal"]

    categories: dict[str, list[dict]] = {}
    for row in results:
        categories.setdefault(row.get("category", "other"), []).append(row)
    ordered = sorted(categories.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    if args.md:
        print("## Evaluation\n")
        print(f"Provider: `{args.provider}` · dataset: `{args.data}`\n")
        print("| Metric | Result |\n|---|---|")
        print(f"| Accuracy | **{pct:.1f}%** ({passed}/{len(results)}) |")
        print(f"| Grounded-value questions | {sum(r['pass'] for r in values)}/{len(values)} |")
        print(f"| Correct refusals | {sum(r['pass'] for r in refusals)}/{len(refusals)} |")
        print(f"| Avg tokens / query | {summary['avg_tokens_total']} |")
        print(f"| Avg latency | {summary['avg_latency_ms']} ms |")
        print(f"| P95 latency | {summary['p95_latency_ms']} ms |")
        print(f"| P95 tokens / query | {summary['p95_tokens_total']} |")
        print(f"| Model calls per answer | 1 |\n")
        print("### Accuracy by capability\n")
        print("| Capability | Score | Passed |\n|---|---|---|")
        for name, rows in ordered:
            hit = sum(r["pass"] for r in rows)
            print(f"| {name} | {hit / len(rows) * 100:.0f}% | {hit}/{len(rows)} |")
        print()
        print("| # | Question | Result |\n|---|---|---|")
        for i, r in enumerate(results, 1):
            print(f"| {i} | {r['q']} | {'pass' if r['pass'] else 'FAIL'} — {r['detail']} |")
    else:
        print()
        for i, r in enumerate(results, 1):
            print(f"  {'PASS' if r['pass'] else 'FAIL'}  {i:2}. {r['q']}")
            if not r["pass"]:
                print(f"         {r['detail']}")
        print(f"\n  {'-' * 56}")
        print("  BY CAPABILITY")
        for name, rows in ordered:
            hit = sum(r["pass"] for r in rows)
            bar = "#" * round(hit / len(rows) * 20)
            print(f"    {name:26} {hit / len(rows) * 100:5.0f}%  {hit}/{len(rows):<3} {bar}")
        print(f"  {'-' * 56}")
        print(f"  accuracy        {pct:.1f}%  ({passed}/{len(results)})")
        print(f"  value questions {sum(r['pass'] for r in values)}/{len(values)}")
        print(f"  refusals        {sum(r['pass'] for r in refusals)}/{len(refusals)}")
        print(f"  avg tokens      {summary['avg_tokens_total']} per query")
        print(f"  avg latency     {summary['avg_latency_ms']} ms")
        print(f"  p95 latency     {summary['p95_latency_ms']} ms")
        print(f"  p95 tokens      {summary['p95_tokens_total']} per query")
        print(f"  {'-' * 56}\n")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
