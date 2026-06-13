import os
import base64
import logging
import hashlib
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "TxGEqnHWrfWFTfGW9XjX")  # Josh — warm, smooth and steady male voice
AUDIO_CACHE_DIR = Path("tts_cache")


def _cache_key(text: str) -> Path:
    digest = hashlib.md5(text.encode()).hexdigest()
    return AUDIO_CACHE_DIR / f"{digest}.mp3"


async def synthesize(text: str) -> str | None:
    """Return base64-encoded MP3, or None (triggers browser TTS fallback)."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        return None

    AUDIO_CACHE_DIR.mkdir(exist_ok=True)
    cache_file = _cache_key(text)

    if cache_file.exists():
        return base64.b64encode(cache_file.read_bytes()).decode()

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            if resp.status_code != 200:
                logger.warning("ElevenLabs %s: %s", resp.status_code, resp.text[:100])
                return None
            audio_bytes = resp.content
            cache_file.write_bytes(audio_bytes)
            return base64.b64encode(audio_bytes).decode()
    except Exception as exc:
        logger.warning("ElevenLabs error: %s", exc)
        return None


def has_elevenlabs() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY", ""))
