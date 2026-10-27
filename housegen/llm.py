"""Thin Groq wrapper (OpenAI-compatible API). Returns None when no API key is configured so callers can fall back."""
import json
import os
import re

import requests

API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def ask_json(system: str, prompt: str, max_tokens: int = 1500):
    """Ask the model for a JSON object. Returns a dict, or None on any failure."""
    if not available():
        return None
    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            json={
                "model": os.getenv("GROQ_MODEL") or DEFAULT_MODEL,
                # Reasoning models spend tokens thinking before answering; leave headroom.
                "max_completion_tokens": max_tokens + 2000,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system + "\nRespond with a single JSON object only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60,
        )
        if not resp.ok:
            print(f"  [llm] HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        text = resp.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:  # network, bad JSON
        print(f"  [llm] failed: {e}")
        return None
