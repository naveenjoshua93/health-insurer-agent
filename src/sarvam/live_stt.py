import base64
import json

import websockets

from src.config import SARVAM_API_KEY

WS_URL = (
    "wss://api.sarvam.ai/speech-to-text/ws"
    "?language-code=unknown&model=saaras:v3&sample_rate=16000"
    "&high_vad_sensitivity=false&vad_signals=true"
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


async def iter_events(upstream):
    """Yields dicts describing either a transcript segment or a VAD speech-boundary signal:
    {"kind": "transcript", "transcript": str, "language_code": str}
    {"kind": "vad", "signal_type": "START_SPEECH" | "END_SPEECH"}
    """
    async for message in upstream:
        data = json.loads(message)
        msg_type = data.get("type")
        if msg_type == "data":
            transcript = data["data"].get("transcript", "")
            if transcript:
                yield {"kind": "transcript", "transcript": transcript, "language_code": data["data"].get("language_code")}
        elif msg_type == "events":
            signal_type = data["data"].get("signal_type")
            if signal_type:
                yield {"kind": "vad", "signal_type": signal_type}
