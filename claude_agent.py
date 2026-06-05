import os
import logging
from session_manager import Session, CallState

import anthropic

logger = logging.getLogger(__name__)
MODEL = "claude-haiku-20240307"

SYSTEM_PROMPT = """You are Alex, a friendly AI receptionist for HomeServ Pro, a home services company (HVAC, plumbing, electrical).

RULES:
- Keep every response under 35 words — you are speaking out loud
- Be warm, professional, and efficient
- Collect in order: customer name → service needed → address → preferred appointment time
- When you have all 4 pieces of info, say: "I have everything I need. Let me confirm your appointment."
- For emergencies (flooding, no heat, gas leak, no power): say "This sounds urgent. I'm flagging this for immediate dispatch."
- Never give pricing over the phone
- Do not mention you are an AI unless directly asked

CONVERSATION GOAL: Book a service appointment."""

GREETING = "Thank you for calling HomeServ Pro! This is Alex. Are you calling about HVAC, plumbing, or electrical service today?"

EMERGENCY_RESPONSE = "This sounds urgent. I'm flagging this for immediate dispatch. Can I get your name and address right now so we can send someone immediately?"

BOOKING_CONFIRMATION_KEYWORDS = [
    "i have everything",
    "let me confirm",
    "all set",
    "appointment confirmed",
    "we're all booked",
]


def _is_booking_complete(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in BOOKING_CONFIRMATION_KEYWORDS)


def get_greeting() -> str:
    return GREETING


def process_turn(session: Session, user_text: str) -> dict:
    if session.is_emergency:
        return {
            "text": EMERGENCY_RESPONSE,
            "state": CallState.EMERGENCY,
            "booking_triggered": False,
        }

    messages = session.to_claude_messages() + [{"role": "user", "content": user_text}]

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        reply = _fallback_reply(session, user_text)
    else:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=MODEL,
                max_tokens=120,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            reply = resp.content[0].text.strip()
        except Exception as exc:
            logger.error("Claude error: %s", exc)
            reply = _fallback_reply(session, user_text)

    booking_triggered = _is_booking_complete(reply) or session.state == CallState.CONFIRM

    return {
        "text": reply,
        "state": session.state,
        "booking_triggered": booking_triggered,
    }


def _fallback_reply(session: Session, user_text: str) -> str:
    state = session.state
    collected = session.collected

    if state == CallState.GREETING or state == CallState.IDENTIFY_SERVICE:
        return "I can help with that! May I start with your name and the address where you need service?"
    if state == CallState.COLLECT_INFO:
        if not collected.get("name"):
            return "Could I get your name please?"
        if not collected.get("service_type"):
            return "What type of service do you need — HVAC, plumbing, or electrical?"
        if not collected.get("address"):
            return "What's the service address?"
        return "What's your preferred appointment time — morning or afternoon, any day this week?"
    if state == CallState.CONFIRM:
        name = collected.get("name", "there")
        service = collected.get("service_type", "the service")
        time = collected.get("preferred_time", "at your preferred time")
        return f"I have everything I need. Let me confirm: {name}, {service} service, {time}. Is that correct?"
    return "I'm here to help! What service do you need today?"
