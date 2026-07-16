import base64
import json

import websockets

from src.config import SARVAM_API_KEY

WS_URL = (
    "wss://api.sarvam.ai/speech-to-text/ws"
    "?language-code=unknown&model=saaras:v3&sample_rate=16000&high_vad_sensitivity=true"
)


def connect():
    """Opens a websocket connection to Sarvam's streaming STT. Use as `async with live_stt.connect() as upstream`."""
    return websockets.connect(WS_URL, additional_headers={"Api-Subscription-Key": SARVAM_API_KEY})


async def send_chunk(upstream, pcm16_bytes: bytes):
    """pcm16_bytes must be raw 16-bit mono PCM sampled at 16kHz."""
    payload = {
        "audio": {
            "data": base64.b64encode(pcm16_bytes).decode("ascii"),
            "sample_rate": "16000",
            "encoding": "audio/wav",
        }
    }
    await upstream.send(json.dumps(payload))


async def send_flush(upstream):
    await upstream.send(json.dumps({"type": "flush"}))


async def iter_transcripts(upstream):
    """Yields (transcript, language_code) tuples as Sarvam completes each speech segment."""
    async for message in upstream:
        data = json.loads(message)
        if data.get("type") == "data":
            transcript = data["data"].get("transcript", "")
            if transcript:
                yield transcript, data["data"].get("language_code")
