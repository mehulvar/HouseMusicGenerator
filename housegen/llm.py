"""Thin Claude wrapper. Returns None when no API key is configured so callers can fall back."""
import json
import os
import re

_client = None


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def ask_json(system: str, prompt: str, max_tokens: int = 1500):
    """Ask the model for a JSON object. Returns a dict, or None on any failure."""
    if not available():
        return None
    try:
        resp = _get_client().messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            max_tokens=max_tokens,
            system=system + "\nRespond with a single JSON object only, no prose, no code fences.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:  # network, auth, bad JSON
        print(f"  [llm] failed: {e}")
        return None
