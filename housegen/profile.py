"""Step 3: build a style profile from ReccoBeats audio features and/or an LLM description, with house defaults."""
import random

import requests

from . import llm
from .spec import NOTE_NAMES

DEFAULTS = {
    "bpm": None,  # filled with 122-126 at build time
    "key": "A minor",
    "subgenre": "deep house",
    "drum_feel": "four-on-the-floor kick, offbeat open hats, clap on 2 and 4",
    "instruments": ["analog bass", "warm pads", "plucked synth", "piano stabs"],
    "mood": "uplifting, warm, late-night",
    "energy": 0.7,
}


def _reccobeats(spotify_id: str | None) -> dict | None:
    """Spotify-style audio features by Spotify track ID. Free, no key."""
    if not spotify_id:
        return None
    try:
        r = requests.get(
            "https://api.reccobeats.com/v1/audio-features", params={"ids": spotify_id}, timeout=10
        )
        r.raise_for_status()
        content = r.json().get("content") or []
        if not content:
            return None
        f = content[0]
        out = {}
        if f.get("tempo"):
            out["bpm"] = round(float(f["tempo"]))
        if f.get("key") is not None and f["key"] >= 0:  # -1 means no key detected
            out["key"] = f"{NOTE_NAMES[f['key']]} {'major' if f.get('mode') == 1 else 'minor'}"
        if f.get("energy") is not None:
            out["energy"] = round(float(f["energy"]), 2)
        return out or None
    except Exception as e:
        print(f"  [reccobeats] failed: {e}")
        return None


def _llm_describe(artist: str, track: str, meta: dict | None) -> dict | None:
    ref = f'"{track}" by {artist}' + (f" ({meta['year']})" if meta and meta.get("year") else "")
    return llm.ask_json(
        "You are a music producer who describes the sound of tracks in technical, artist-agnostic terms.",
        f"Describe the production style of {ref}.\n"
        'Return {"bpm": int, "key": "e.g. F minor", "subgenre": str, "drum_feel": str, '
        '"instruments": [str], "mood": str, "energy": float 0-1}. '
        "Never mention any artist or song names in the values.",
        max_tokens=500,
    )


def build_profile(artist: str, track: str, meta: dict | None) -> dict:
    profile = dict(DEFAULTS)
    sources = []

    described = _llm_describe(artist, track, meta) if track else None
    if described:
        profile.update({k: v for k, v in described.items() if v not in (None, "", [])})
        sources.append("llm")

    # Measured BPM/key/energy beat the LLM's guess.
    measured = _reccobeats((meta or {}).get("id"))
    if measured:
        profile.update(measured)
        sources.append("reccobeats")

    if not profile.get("bpm"):
        profile["bpm"] = random.randint(122, 126)
        sources.append("default-bpm")
    profile["sources"] = sources or ["defaults"]
    return profile
