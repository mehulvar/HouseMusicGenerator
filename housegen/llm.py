"""Thin Groq wrapper (OpenAI-compatible API). Returns None when no API key is configured so callers can fall back."""
import json
import os
import re
import time

import requests

API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


RATE_LIMIT_RETRIES = 2
MAX_RETRY_WAIT_S = 30.0  # Groq's free tier asks for short waits; longer ones mean the daily cap is hit


def _retry_wait(resp: requests.Response) -> float | None:
    """Seconds to wait before retrying a rate-limited call, or None if it isn't worth waiting."""
    if resp.status_code != 429:
        return None
    try:
        wait = float(resp.headers.get("retry-after", "5"))
    except ValueError:
        wait = 5.0
    return wait if wait <= MAX_RETRY_WAIT_S else None


def _post(body: dict) -> requests.Response:
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
    resp = requests.post(API_URL, headers=headers, json=body, timeout=90)
    for _ in range(RATE_LIMIT_RETRIES):
        wait = _retry_wait(resp)
        if wait is None:
            return resp
        print(f"  [llm] rate limited; retrying in {wait:.0f}s")
        time.sleep(wait)
        resp = requests.post(API_URL, headers=headers, json=body, timeout=90)
    return resp


REASONING_HEADROOM = 2000  # reasoning models think before answering; budget for it on top of the answer
JSON_ATTEMPTS = 2  # reasoning length varies, so an answer cut off once usually fits on a second try


def _is_bad_json(resp: requests.Response) -> bool:
    return resp.status_code == 400 and "json_validate_failed" in resp.text


def ask_json(system: str, prompt: str, max_tokens: int = 1500, reasoning_effort: str | None = None):
    """Ask the model for a JSON object. Returns a dict, or None on any failure."""
    if not available():
        return None
    body = {
        "model": os.getenv("GROQ_MODEL") or DEFAULT_MODEL,
        "max_completion_tokens": max_tokens + REASONING_HEADROOM,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system + "\nRespond with a single JSON object only."},
            {"role": "user", "content": prompt},
        ],
        **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
    }
    try:
        for attempt in range(1, JSON_ATTEMPTS + 1):
            resp = _post(body)
            if not (_is_bad_json(resp) and attempt < JSON_ATTEMPTS):
                break
            print("  [llm] answer wasn't valid JSON (likely cut off); retrying")
        if not resp.ok:
            print(f"  [llm] HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        text = resp.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:  # network, bad JSON
        print(f"  [llm] failed: {e}")
        return None
