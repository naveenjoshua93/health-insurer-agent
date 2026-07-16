import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL


def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> dict:
    resp = httpx.post(
        f"{SARVAM_BASE_URL}/speech-to-text",
        headers={"api-subscription-key": SARVAM_API_KEY},
        files={"file": (filename, audio_bytes, "audio/wav")},
        data={"model": "saaras:v3", "language_code": "unknown"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
