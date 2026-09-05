from app.assistant.smalltalk import conversational_reply

DATASETS = ["bank", "account", "transaction"]


def test_a_greeting_is_greeted_not_refused():
    for greeting in [
        "hi",
        "hii",
        "hiii",
        "hey",
        "helloo",
        "yo",
        "Namaste",
        "Good morning",
    ]:
        assert conversational_reply(greeting, DATASETS) is not None, greeting


def test_capability_questions_get_final_schema_examples():
    reply = conversational_reply("what can you do", DATASETS)

    assert reply is not None
    assert "debited last month" in reply.lower()
    assert "available balance by bank" in reply.lower()
    assert "vendor payouts" not in reply.lower()


def test_thanks_and_goodbye():
    assert conversational_reply("thanks!", DATASETS)
    assert conversational_reply("bye", DATASETS)


def test_a_real_question_falls_through():
    assert conversational_reply(
        "How much was debited last month?",
        DATASETS,
    ) is None


def test_a_greeting_attached_to_a_question_falls_through():
    assert conversational_reply(
        "Hi, how much was debited last month?",
        DATASETS,
    ) is None


def test_empty_input_falls_through():
    assert conversational_reply("", DATASETS) is None
    assert conversational_reply("   ", DATASETS) is None