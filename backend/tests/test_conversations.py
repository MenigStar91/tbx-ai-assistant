from uuid import uuid4

from app.data.conversations import ConversationStore
from app.schemas import ClarificationRequest, PendingClarification, QueryPlan


def test_conversation_store_is_durable_and_bounded(tmp_path):
    path = str(tmp_path / "conversations.db")
    session_id = uuid4()
    query_plan = QueryPlan(dataset="transaction", operation="count")
    store = ConversationStore(path, max_messages=4)

    for index in range(3):
        store.append_turn(session_id, f"question {index}", f"answer {index}", query_plan)

    reloaded = ConversationStore(path, max_messages=4).load(session_id)
    assert reloaded is not None
    assert [message.content for message in reloaded.history] == [
        "question 1", "answer 1", "question 2", "answer 2"
    ]
    assert reloaded.last_plan == query_plan


def test_refusal_does_not_erase_last_validated_plan(tmp_path):
    store = ConversationStore(str(tmp_path / "conversations.db"))
    session_id = uuid4()
    query_plan = QueryPlan(dataset="account", operation="count")
    store.append_turn(session_id, "first", "answer", query_plan)
    state = store.append_turn(session_id, "unsupported", "cannot answer", None)
    assert state.last_plan == query_plan


def test_pending_clarification_is_durable_and_can_be_cleared(tmp_path):
    store = ConversationStore(str(tmp_path / "conversations.db"))
    session_id = uuid4()
    pending = PendingClarification(
        request=ClarificationRequest(
            kind="field", slot="measure", prompt="Which balance?", options=[]
        ),
        original_question="total balance",
        partial_plan={"dataset": "account", "operation": "sum"},
    )
    store.append_turn(session_id, "total balance", "Which balance?", None, pending)
    assert ConversationStore(store.path).load(session_id).pending_clarification == pending
    cleared = store.append_turn(session_id, "available", "done", None, None)
    assert cleared.pending_clarification is None
