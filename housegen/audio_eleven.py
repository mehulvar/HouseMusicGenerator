"""Path A: spec + lyrics -> ElevenLabs Music (vocals included)."""
import os

import requests

from .spec import describe

API_URL = "https://api.elevenlabs.io/v1/music"


def available() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY"))


def _section_ms(bars: int, bpm: int) -> int:
    return int(bars * 4 * 60_000 / bpm)


def composition_plan(spec: dict, lyrics: dict) -> dict:
    vocal = {s["section"]: s for s in lyrics["sections"]}
    sections = []
    for i, s in enumerate(spec["structure"]):
        lines = []
        if s["section"] in vocal:
            lines = lyrics["hook"] if s["section"] == "drop" else lyrics["verse"]
        local = {
            "intro": ["sparse drums", "filtered pads"],
            "build": ["rising snare roll", "filter sweep up"],
            "drop": ["full drums", "sidechained bass", "chord stabs"],
            "break": ["no kick", "atmospheric pads"],
            "outro": ["drums thinning out"],
        }.get(s["section"], [])
        sections.append({
            "section_name": f"{s['section']} {i + 1}",
            "positive_local_styles": local,
            "negative_local_styles": [],
            # API limits sections to 3s-120s.
            "duration_ms": max(3000, min(120_000, _section_ms(s["bars"], spec["bpm"]))),
            "lines": lines,
        })
    return {
        "positive_global_styles": [describe(spec)],
        "negative_global_styles": ["lo-fi", "acoustic", "rock"],
        "sections": sections,
    }


def render(spec: dict, lyrics: dict, out_path: str) -> str:
    resp = requests.post(
        API_URL,
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"composition_plan": composition_plan(spec, lyrics)},
        timeout=600,
    )
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)
    return out_path
