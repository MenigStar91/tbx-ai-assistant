"""Small durable conversation store.

Only compact user/assistant text and the last validated query plan are stored.
Evidence rows never enter conversational memory, keeping prompts bounded and
preventing financial records from being duplicated into a chat-history table.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from uuid import UUID

from app.schemas import ConversationState, Message, QueryPlan


class ConversationStore:
    def __init__(self, path: str, max_messages: int = 12):
        self.path = path
        self.max_messages = max_messages
        self._lock = Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS conversation_state (
                    session_id TEXT PRIMARY KEY,
                    history_json TEXT NOT NULL,
                    last_plan_json TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def load(self, session_id: UUID) -> ConversationState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT history_json, last_plan_json FROM conversation_state WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        return ConversationState(
            session_id=session_id,
            history=[Message.model_validate(item) for item in json.loads(row[0])],
            last_plan=QueryPlan.model_validate_json(row[1]) if row[1] else None,
        )

    def append_turn(
        self,
        session_id: UUID,
        question: str,
        answer: str,
        plan: QueryPlan | None,
    ) -> ConversationState:
        current = self.load(session_id)
        history = list(current.history if current else [])
        history.extend([Message(role="user", content=question), Message(role="assistant", content=answer)])
        history = history[-self.max_messages :]
        last_plan = plan or (current.last_plan if current else None)
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO conversation_state(session_id, history_json, last_plan_json, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(session_id) DO UPDATE SET
                     history_json=excluded.history_json,
                     last_plan_json=excluded.last_plan_json,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    str(session_id),
                    json.dumps([message.model_dump() for message in history]),
                    last_plan.model_dump_json() if last_plan else None,
                ),
            )
        return ConversationState(session_id=session_id, history=history, last_plan=last_plan)
