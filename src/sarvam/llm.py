import httpx
from src.config import SARVAM_API_KEY, SARVAM_BASE_URL

MODEL = "sarvam-105b"


def chat(messages: list, tools: list = None, tool_choice: str = "auto",
         max_tokens: int = 600, reasoning_effort: str = "low") -> dict:
    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    resp = httpx.post(
        f"{SARVAM_BASE_URL}/v1/chat/completions",
        headers={"api-subscription-key": SARVAM_API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
