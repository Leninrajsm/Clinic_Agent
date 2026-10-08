"""LLM-simulated patient. Plays the scenario persona against the agent."""

from app.config import Settings
from app.evals.scenarios import Scenario
from app.llm.base import LLMClient, Message

END_TOKEN = "[END]"

SIMULATOR_SYSTEM = """You are role-playing a PATIENT contacting a medical clinic's scheduling chat
assistant. This is a test of the assistant, so play your part realistically and consistently.

Your persona and goal:
{persona}

Rules:
- Write only the patient's next message: short and natural (1-2 sentences), like a real chat.
- Only give information the assistant asks for, unless your persona says otherwise.
- Follow your persona's instructions exactly, including when to accept, refuse or give up.
- Do not help the assistant do its job or point out its mistakes beyond what the persona says.
- Never mention that you are an AI or that this is a test.
- When your goal is achieved, or the conversation has clearly ended, or your persona says to
  end, write your final short message followed by {end} (for example: "Great, thanks! {end}").
- Never add {end} to a message that asks the assistant to do something (like "yes, please book
  it"). Wait for its reply first; end only after it has answered.
"""


class PatientSimulator:
    def __init__(self, llm: LLMClient, settings: Settings, scenario: Scenario):
        self.llm, self.settings, self.scenario = llm, settings, scenario
        self.system = SIMULATOR_SYSTEM.format(persona=scenario.persona.strip(), end=END_TOKEN)

    async def next_message(self, transcript: list[dict]) -> tuple[str, bool]:
        """Returns (message, done). From the simulator's view the assistant is the 'user'."""
        messages = [Message("user" if t["role"] == "agent" else "model", t["text"]) for t in transcript]
        resp = await self.llm.generate(model=self.settings.model_simulator, system=self.system,
                                       messages=messages, purpose="simulator")
        text = resp.text.strip()
        done = END_TOKEN in text or not text
        return text.replace(END_TOKEN, "").strip(), done
