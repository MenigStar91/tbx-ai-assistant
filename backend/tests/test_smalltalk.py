from app.assistant.smalltalk import conversational_reply

DATASETS = ["transactions", "vendor_payouts"]


def test_a_greeting_is_greeted_not_refused():
    # the reported bug: "hii" was answered with "this dataset has nothing about 'hii'"
    for greeting in ["hi", "hii", "hiii", "hey", "helloo", "yo", "Namaste", "Good morning"]:
        assert conversational_reply(greeting, DATASETS) is not None, greeting


def test_capability_questions_get_examples():
    reply = conversational_reply("what can you do", DATASETS)
    assert "vendor payouts" in reply


def test_thanks_and_goodbye():
    assert conversational_reply("thanks!", DATASETS)
    assert conversational_reply("bye", DATASETS)


def test_a_real_question_falls_through():
    assert conversational_reply("How much did we spend last month?", DATASETS) is None


def test_a_greeting_attached_to_a_question_falls_through():
    assert conversational_reply("hi, how much did we spend last month?", DATASETS) is None


def test_empty_input_falls_through():
    assert conversational_reply("", DATASETS) is None
    assert conversational_reply("   ", DATASETS) is None
