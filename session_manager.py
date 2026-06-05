import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CallState(str, Enum):
    GREETING = "GREETING"
    IDENTIFY_SERVICE = "IDENTIFY_SERVICE"
    COLLECT_INFO = "COLLECT_INFO"
    CONFIRM = "CONFIRM"
    BOOKED = "BOOKED"
    EMERGENCY = "EMERGENCY"
    ENDED = "ENDED"


EMERGENCY_KEYWORDS = [
    "flooding", "flood", "no heat", "no hot water", "freezing", "burst pipe",
    "gas leak", "no power", "sparks", "fire", "emergency", "urgent", "dangerous",
]

SERVICE_KEYWORDS = {
    "hvac": ["hvac", "heating", "cooling", "ac", "air condition", "furnace", "heat pump"],
    "plumbing": ["plumbing", "pipe", "drain", "toilet", "faucet", "water", "leak", "sewage"],
    "electrical": ["electrical", "electric", "wiring", "outlet", "breaker", "panel", "light"],
}


@dataclass
class Session:
    session_id: str
    state: CallState = CallState.GREETING
    history: list[dict] = field(default_factory=list)
    collected: dict = field(default_factory=dict)
    is_emergency: bool = False

    def add_turn(self, role: str, text: str) -> None:
        self.history.append({"role": role, "content": text})

    def to_claude_messages(self) -> list[dict]:
        return self.history.copy()


_sessions: dict[str, Session] = {}


def create_session() -> Session:
    sid = str(uuid.uuid4())[:12]
    session = Session(session_id=sid)
    _sessions[sid] = session
    logger.info("Session created: %s", sid)
    return session


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def end_session(session_id: str) -> None:
    if session_id in _sessions:
        _sessions[session_id].state = CallState.ENDED
        logger.info("Session ended: %s", session_id)


def detect_emergency(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in EMERGENCY_KEYWORDS)


def detect_service_type(text: str) -> str | None:
    lower = text.lower()
    for service, keywords in SERVICE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return service
    return None


def extract_info(text: str, session: Session) -> None:
    import re
    # Extract phone
    phone = re.search(r"\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b", text)
    if phone and not session.collected.get("phone"):
        session.collected["phone"] = phone.group(1)

    # Extract time preference
    time_patterns = ["morning", "afternoon", "evening", "monday", "tuesday", "wednesday",
                     "thursday", "friday", "saturday", "sunday", "today", "tomorrow",
                     "am", "pm", "o'clock"]
    for pattern in time_patterns:
        if pattern in text.lower() and not session.collected.get("preferred_time"):
            session.collected["preferred_time"] = text.strip()
            break

    # Detect service
    service = detect_service_type(text)
    if service and not session.collected.get("service_type"):
        session.collected["service_type"] = service


def advance_state(session: Session, user_text: str) -> None:
    if detect_emergency(user_text):
        session.is_emergency = True
        session.state = CallState.EMERGENCY
        return

    extract_info(user_text, session)

    if session.state == CallState.GREETING:
        session.state = CallState.IDENTIFY_SERVICE
    elif session.state == CallState.IDENTIFY_SERVICE:
        session.state = CallState.COLLECT_INFO
    elif session.state == CallState.COLLECT_INFO:
        has_name = bool(session.collected.get("name") or len(session.history) > 4)
        has_service = bool(session.collected.get("service_type") or detect_service_type(user_text))
        if has_name and has_service:
            session.state = CallState.CONFIRM
    elif session.state == CallState.CONFIRM:
        if any(w in user_text.lower() for w in ["yes", "correct", "right", "confirm", "sounds good", "perfect"]):
            session.state = CallState.BOOKED
