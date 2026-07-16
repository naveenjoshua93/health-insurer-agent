import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL


def translate(text: str, source_language_code: str, target_language_code: str) -> str:
    if source_language_code == target_language_code:
        return text
    resp = httpx.post(
        f"{SARVAM_BASE_URL}/translate",
        headers={"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"},
        json={
            "input": text,
            "source_language_code": source_language_code,
            "target_language_code": target_language_code,
            "model": "sarvam-translate:v1",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["translated_text"]
