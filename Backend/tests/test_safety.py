import pytest

from app.agent.safety import check_message


@pytest.mark.parametrize("text", [
    "Actually I've had crushing chest pain for 20 minutes",
    "my left arm feels numb and I can't breathe properly",
    "I think I'm having a stroke",
    "the bleeding won't stop",
])
def test_emergencies_detected(text):
    hit = check_message(text)
    assert hit and hit.category == "emergency"
    assert "911" in hit.reply


def test_crisis_detected():
    hit = check_message("honestly I just want to die")
    assert hit and hit.category == "crisis"
    assert "988" in hit.reply


@pytest.mark.parametrize("text", [
    "I'd like to book a check-up next Friday",
    "no chest pain, just a routine visit",
    "I don't have chest pain anymore, the cardiologist wants a follow-up",
])
def test_routine_or_negated_messages_pass(text):
    assert check_message(text) is None
