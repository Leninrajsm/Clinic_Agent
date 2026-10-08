"""Builds the system prompt in a fixed, inspectable order:
safety core (locked) -> policy vN (what the loop improves) -> clinic context -> live state."""

from app.agent.state import SessionState
from app.clinic.dates import Clock
from app.db.seed import clinic_info, load_fixture


def build_system_prompt(
    safety_core: str, policy_text: str, policy_version: str, state: SessionState, clock: Clock, max_attempts: int
) -> str:
    info = clinic_info()
    now = clock.now()
    specialties = ", ".join(sorted({p["specialty"] for p in load_fixture()["providers"]}))
    return "\n\n".join([
        safety_core.replace("{clinic_name}", info["name"]).strip(),
        f"# Clinic policy ({policy_version})\n\n{policy_text.strip()}",
        "# Clinic context\n"
        f"- Clinic: {info['name']}. Hours: {info['hours']}\n"
        f"- Today is {now:%A, %B %d, %Y}; current time {now:%I:%M %p} ({clock.tz.key}).\n"
        f"- Specialties offered: {specialties}.",
        "# Conversation state (maintained by the system)\n" + state.summary(max_attempts),
    ])
