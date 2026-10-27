"""Step 1: turn 'make a song like X's Y' into {artist, track}."""
import re

from . import llm

_PATTERNS = [
    # "like calvin harris's summer", "like calvin harris' summer"
    re.compile(r"like\s+(?P<artist>.+?)['’]s?\s+(?P<track>.+)$", re.I),
    # "like summer by calvin harris"
    re.compile(r"like\s+(?P<track>.+?)\s+by\s+(?P<artist>.+)$", re.I),
    # "calvin harris - summer"
    re.compile(r"^(?P<artist>[^-–]+?)\s+[-–]\s+(?P<track>.+)$"),
]


def _clean(s: str) -> str:
    return s.strip().strip("\"'“”.!?").strip()


def parse_prompt(prompt: str) -> dict:
    text = prompt.strip()
    for pat in _PATTERNS:
        m = pat.search(text)
        if m:
            return {"artist": _clean(m["artist"]), "track": _clean(m["track"]), "via": "regex"}

    result = llm.ask_json(
        "You extract a reference song from a music request.",
        f'Request: "{text}"\nReturn {{"artist": str|null, "track": str|null}}.',
        max_tokens=200,
    )
    if result and (result.get("artist") or result.get("track")):
        return {"artist": result.get("artist") or "", "track": result.get("track") or "", "via": "llm"}

    return {"artist": "", "track": "", "via": "none"}
