"""Per-query token and latency accounting.

"Model efficiency" is 20% of the score and the submission asks for a note on
model choice. Both need measured numbers, and a number you did not record
during the run cannot be reconstructed afterwards -- so every request is logged,
including the ones refused before the model was called.

sqlite3 is in the standard library; this adds no dependency.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

_LOCK = Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS query_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  asked_at   TEXT DEFAULT (datetime('now')),
  question   TEXT,
  model      TEXT,
  tokens_in  INTEGER DEFAULT 0,
  tokens_out INTEGER DEFAULT 0,
  latency_ms INTEGER DEFAULT 0,
  refused    INTEGER DEFAULT 0,
  reason     TEXT
);
"""


class MetricsStore:
    def __init__(self, path: str = "data/runtime/metrics.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def record(
        self,
        question: str,
        model: str = "pre-model-guard",
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        refused: bool = False,
        reason: str | None = None,
    ) -> None:
        # logging must never be the reason an answer fails
        try:
            with _LOCK, self._connect() as connection:
                connection.execute(
                    "INSERT INTO query_log (question, model, tokens_in, tokens_out, latency_ms, refused, reason)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (question, model, tokens_in, tokens_out, latency_ms, int(refused), reason),
                )
        except sqlite3.Error:
            pass

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) queries, COALESCE(SUM(refused),0) refusals,
                          COALESCE(AVG(tokens_in),0) avg_tokens_in,
                          COALESCE(AVG(tokens_out),0) avg_tokens_out,
                          COALESCE(AVG(tokens_in + tokens_out),0) avg_tokens_total,
                          COALESCE(AVG(latency_ms),0) avg_latency_ms
                     FROM query_log"""
            ).fetchone()
            by_model = connection.execute(
                """SELECT model, COUNT(*) n,
                          ROUND(AVG(tokens_in + tokens_out), 1) avg_tokens,
                          ROUND(AVG(latency_ms)) avg_latency_ms
                     FROM query_log GROUP BY model ORDER BY n DESC"""
            ).fetchall()
            samples = connection.execute(
                "SELECT tokens_in + tokens_out total_tokens, latency_ms FROM query_log ORDER BY id"
            ).fetchall()

        def percentile(values: list[int], fraction: float) -> float:
            if not values:
                return 0.0
            ordered = sorted(values)
            index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
            return float(ordered[index])

        token_samples = [int(item["total_tokens"]) for item in samples]
        latency_samples = [int(item["latency_ms"]) for item in samples]
        return {
            "queries": row["queries"],
            "refusals": row["refusals"],
            "avg_tokens_in": round(row["avg_tokens_in"], 1),
            "avg_tokens_out": round(row["avg_tokens_out"], 1),
            "avg_tokens_total": round(row["avg_tokens_total"], 1),
            "avg_latency_ms": round(row["avg_latency_ms"], 1),
            "p50_tokens_total": percentile(token_samples, 0.50),
            "p95_tokens_total": percentile(token_samples, 0.95),
            "p50_latency_ms": percentile(latency_samples, 0.50),
            "p95_latency_ms": percentile(latency_samples, 0.95),
            "by_model": [dict(item) for item in by_model],
        }

    def reset(self) -> None:
        with _LOCK, self._connect() as connection:
            connection.execute("DELETE FROM query_log")


metrics_store = MetricsStore()
