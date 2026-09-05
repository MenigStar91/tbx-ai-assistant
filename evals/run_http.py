"""Black-box model evaluation through the deployed chat API.

Every assistant response is obtained by invoking curl. The evaluator does not
import the API, assistant service, provider, or query engine.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def curl_json(url: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], float]:
    command = ["curl", "--silent", "--show-error", "--fail-with-body"]
    if payload is not None:
        command += ["-X", "POST", "-H", "content-type: application/json", "--data-binary", "@-"]
    command.append(url)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout), elapsed_ms


def subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(subset(item, candidate) for candidate in actual) for item in expected)
    return expected == actual


def asserted_value(body: dict[str, Any], groups: bool = False) -> float | None:
    evidence = body.get("evidence")
    if not evidence:
        return None
    if groups:
        value = evidence.get("total_groups")
    elif evidence.get("rows") and "result" in evidence["rows"][0]:
        value = evidence["rows"][0]["result"] or 0
    else:
        value = evidence.get("total_rows")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_case(item: dict[str, Any], body: dict[str, Any]) -> tuple[bool, str]:
    expected = item.get("expected")
    refused = bool(body.get("clarification_needed"))
    if expected == "refusal":
        ok = refused and bool(body.get("refusal_reason"))
        return ok, body.get("refusal_reason") or "answered instead of refusing"
    if expected == "conversational":
        ok = not refused and body.get("evidence") is None and bool(body.get("answer"))
        return ok, "conversational" if ok else "treated as a data query"
    if refused:
        return False, f"refused: {body.get('refusal_reason') or 'unspecified'}"
    expected_plan = item.get("plan", {})
    if not subset(expected_plan, body.get("query_plan")):
        return False, "query plan does not match the expected semantic fields"
    groups = "expected_groups" in item
    expected_value = float(item.get("expected_groups") if groups else item["expected_value"])
    actual = asserted_value(body, groups)
    value_ok = actual is not None and math.isclose(actual, expected_value, rel_tol=1e-6, abs_tol=1e-6)
    verified = body.get("numbers_verified") is True and body.get("evidence") is not None
    return value_ok and verified, f"got {actual}, expected {expected_value:g}"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# HTTP model evaluation",
        "",
        f"Model label: `{report['model_label']}`  ",
        f"Dataset: `{report['dataset']}`  ",
        f"Timestamp: `{report['timestamp']}`  ",
        f"API: `{report['base_url']}`",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Accuracy | **{report['accuracy_pct']:.1f}%** ({report['passed']}/{report['total']}) |",
        f"| Grounded-value questions | {report['grounded_passed']}/{report['grounded_total']} |",
        f"| Correct refusals | {report['refusal_passed']}/{report['refusal_total']} |",
        f"| Real provider observed | {'yes' if report['provider_valid'] else 'no'} ({', '.join(report['observed_models']) or 'not reported'}) |",
        f"| Average tokens | {report['avg_tokens']:.1f} |",
        f"| P95 HTTP latency | {report['p95_latency_ms']:.0f} ms |",
        "",
        "| # | Question | Result |",
        "|---:|---|---|",
    ]
    for index, row in enumerate(report["results"], 1):
        detail = str(row["detail"]).replace("|", "\\|")
        lines.append(f"| {index} | {row['question']} | {'PASS' if row['pass'] else 'FAIL'} — {detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--model-label", required=True)
    parser.add_argument("--cases", type=Path, default=HERE / "http_questions.json")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--md-output", type=Path)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    curl_json(f"{base_url}/api/v1/health")
    fixture = json.loads(args.cases.read_text())
    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    tokens: list[int] = []
    observed_models: set[str] = set()

    for item in fixture["questions"]:
        try:
            body, latency_ms = curl_json(
                f"{base_url}/api/v1/chat",
                {"session_id": str(uuid.uuid4()), "message": item["q"]},
            )
            passed, detail = score_case(item, body)
            usage = body.get("usage") or {}
            token_count = int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0))
            if usage.get("model"):
                observed_models.add(str(usage["model"]))
            tokens.append(token_count)
            latencies.append(latency_ms)
        except Exception as exc:  # keep the full run useful after one HTTP failure
            passed, detail, latency_ms = False, f"HTTP error: {exc}", 0.0
        results.append({
            "question": item["q"], "category": item["category"],
            "kind": item.get("expected", "grounded"), "pass": passed,
            "detail": detail, "latency_ms": round(latency_ms, 1),
        })

    passed = sum(row["pass"] for row in results)
    grounded = [row for row in results if row["kind"] == "grounded"]
    refusals = [row for row in results if row["kind"] == "refusal"]
    report = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "dataset": fixture["dataset"],
        "model_label": args.model_label,
        "observed_models": sorted(observed_models),
        "provider_valid": bool(observed_models) and not any(
            "fallback" in model.lower() or "keyword-baseline" in model.lower()
            for model in observed_models
        ),
        "passed": passed,
        "total": len(results),
        "accuracy_pct": passed / len(results) * 100,
        "grounded_passed": sum(row["pass"] for row in grounded),
        "grounded_total": len(grounded),
        "refusal_passed": sum(row["pass"] for row in refusals),
        "refusal_total": len(refusals),
        "avg_tokens": statistics.mean(tokens) if tokens else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "results": results,
    }
    markdown = render_markdown(report)
    print(markdown, end="")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2) + "\n")
    if args.md_output:
        args.md_output.parent.mkdir(parents=True, exist_ok=True)
        args.md_output.write_text(markdown)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
