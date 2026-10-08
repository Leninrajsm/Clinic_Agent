"""Deterministic red-flag pre-check that runs BEFORE the LLM on every patient message.

Deliberately conservative: a false positive (escalating someone who mentions chest pain in
passing) is far cheaper than a miss. Simple negation ("no chest pain") is respected.
"""

import re
from dataclasses import dataclass

EMERGENCY_PATTERNS = [
    r"chest (pain|pressure|tightness|hurts)|crushing (pain|chest)|heart attack",
    r"(can'?t|cannot|can not|hard to|trouble|difficulty|struggling to) breath(e|ing)|short(ness)? of breath|not breathing",
    r"\bstroke\b|face (is )?droop|slurred speech",
    r"(left|right|one) (arm|side|leg)[^.]{0,20}\b(numb|weak)|numb(ness)? (in|on) (my )?(left|right|one)",
    r"(severe|heavy|uncontrolled|won'?t stop) bleeding|bleeding (heavily|a lot|won'?t stop)",
    r"unconscious|passed out|unresponsive|not responsive|seizure",
    r"anaphyla|throat (is )?(closing|swelling)",
    r"overdos|poison",
]
CRISIS_PATTERNS = [
    r"suicid|kill myself|end my life|want to die|hurt myself|self[- ]harm",
]
NEGATION = re.compile(r"\b(no|not|never|don'?t have|do not have|without|denies|haven'?t had)\b[^.,;]{0,15}$")

EMERGENCY_REPLY = (
    "This could be a medical emergency. Please call 911 right now or go to the nearest emergency room. "
    "Please don't wait for an appointment. I've also alerted our clinical staff."
)
CRISIS_REPLY = (
    "I'm really sorry you're going through this. If you are in immediate danger, please call 911. "
    "You can also call or text 988 (Suicide & Crisis Lifeline) any time to talk to someone right now. "
    "I've alerted our clinical staff so someone from the clinic can reach out to you."
)


@dataclass
class SafetyHit:
    category: str  # "emergency" | "crisis"
    matched: str
    reply: str


def _first_hit(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        for m in re.finditer(pat, text):
            if not NEGATION.search(text[: m.start()]):
                return m.group(0)
    return None


def check_message(text: str) -> SafetyHit | None:
    t = text.lower()
    if hit := _first_hit(t, CRISIS_PATTERNS):
        return SafetyHit("crisis", hit, CRISIS_REPLY)
    if hit := _first_hit(t, EMERGENCY_PATTERNS):
        return SafetyHit("emergency", hit, EMERGENCY_REPLY)
    return None
