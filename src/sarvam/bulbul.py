import base64
import io
import re
import wave
import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL

MAX_CHARS = 2500


def _chunk_text(text: str) -> list:
    if len(text) <= MAX_CHARS:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > MAX_CHARS:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def _synthesize_chunk(chunk: str, target_language_code: str) -> bytes:
    resp = httpx.post(
        f"{SARVAM_BASE_URL}/text-to-speech",
        headers={"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"},
        json={"text": chunk, "target_language_code": target_language_code},
        timeout=30,
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["audios"][0])


def _concat_wav(wav_bytes_list: list) -> bytes:
    if len(wav_bytes_list) == 1:
        return wav_bytes_list[0]
    with wave.open(io.BytesIO(wav_bytes_list[0])) as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for wav_bytes in wav_bytes_list[1:]:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            frames.append(w.readframes(w.getnframes()))
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        for f in frames:
            writer.writeframes(f)
    return out.getvalue()


def synthesize(text: str, target_language_code: str) -> bytes:
    chunks = [_synthesize_chunk(c, target_language_code) for c in _chunk_text(text)]
    return _concat_wav(chunks)
