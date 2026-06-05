import os
import json
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import session_manager
import claude_agent
import tts_handler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    tts_handler.AUDIO_CACHE_DIR.mkdir(exist_ok=True)
    logger.info("VoiceAgent AI ready. ElevenLabs: %s", tts_handler.has_elevenlabs())
    yield


app = FastAPI(
    title="VoiceAgent AI",
    description="Real-time AI voice agent — WebSocket + Claude + ElevenLabs",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# WebSocket voice session
# ---------------------------------------------------------------------------

@app.websocket("/ws/voice-session")
async def voice_session(websocket: WebSocket):
    await websocket.accept()
    session = session_manager.create_session()
    database.create_session(session.session_id)
    logger.info("WS connected: %s", session.session_id)

    greeting_text = claude_agent.get_greeting()
    greeting_audio = await tts_handler.synthesize(greeting_text)
    session.add_turn("assistant", greeting_text)
    database.log_turn(session.session_id, "assistant", greeting_text)

    await websocket.send_json({
        "type": "session_start",
        "session_id": session.session_id,
        "greeting_text": greeting_text,
        "audio_base64": greeting_audio,
        "tts_mode": "elevenlabs" if greeting_audio else "browser",
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type")

            if msg_type == "speech_text":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue

                logger.info("[%s] User: %s", session.session_id, user_text)
                session.add_turn("user", user_text)
                database.log_turn(session.session_id, "user", user_text)

                session_manager.advance_state(session, user_text)

                result = claude_agent.process_turn(session, user_text)
                reply_text = result["text"]

                session.add_turn("assistant", reply_text)
                database.log_turn(session.session_id, "assistant", reply_text)

                audio_b64 = await tts_handler.synthesize(reply_text)

                response = {
                    "type": "agent_response",
                    "text": reply_text,
                    "audio_base64": audio_b64,
                    "state": result["state"],
                    "booking_triggered": result["booking_triggered"],
                    "collected": session.collected,
                    "is_emergency": session.is_emergency,
                }

                if result["booking_triggered"] and session.state == session_manager.CallState.BOOKED:
                    session.state = session_manager.CallState.BOOKED
                    response["appointment_summary"] = session.collected

                await websocket.send_json(response)
                logger.info("[%s] Agent: %s", session.session_id, reply_text[:60])

            elif msg_type == "end_session":
                await websocket.send_json({"type": "session_ended", "session_id": session.session_id})
                break

    except WebSocketDisconnect:
        logger.info("WS disconnected: %s", session.session_id)
    finally:
        session_manager.end_session(session.session_id)
        database.end_session(session.session_id)


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")


@app.post("/api/new-session")
async def new_session_rest():
    session = session_manager.create_session()
    database.create_session(session.session_id)
    greeting = claude_agent.get_greeting()
    audio = await tts_handler.synthesize(greeting)
    session.add_turn("assistant", greeting)
    database.log_turn(session.session_id, "assistant", greeting)
    return JSONResponse({
        "session_id": session.session_id,
        "greeting_text": greeting,
        "greeting_audio_base64": audio,
        "tts_mode": "elevenlabs" if audio else "browser",
    })


class AppointmentRequest(BaseModel):
    session_id: str
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    service_type: str | None = None
    preferred_time: str | None = None
    is_emergency: bool = False


@app.post("/api/book-appointment")
async def book_appointment(body: AppointmentRequest):
    session = session_manager.get_session(body.session_id)
    collected = {}
    if session:
        collected = session.collected.copy()

    collected.update({k: v for k, v in body.model_dump().items() if v is not None and k != "session_id"})

    appt_id = database.save_appointment(body.session_id, collected)
    if session:
        session.state = session_manager.CallState.BOOKED
        session.collected.update(collected)

    return JSONResponse({
        "appointment_id": appt_id,
        "session_id": body.session_id,
        "status": "confirmed",
        "details": collected,
    })


@app.get("/api/sessions")
async def list_sessions():
    sessions = database.get_all_sessions()
    return JSONResponse({"total": len(sessions), "sessions": sessions})


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "service": "VoiceAgent AI",
        "anthropic_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "elevenlabs_key_set": tts_handler.has_elevenlabs(),
        "active_sessions": len([s for s in session_manager._sessions.values()
                                 if s.state != session_manager.CallState.ENDED]),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
