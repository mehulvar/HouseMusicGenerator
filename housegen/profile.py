"""Step 3: build a style profile from GetSongBPM and/or an LLM description, with house defaults."""
import os
import random
import re

import requests

from . import llm

DEFAULTS = {
    "bpm": None,  # filled with 122-126 at build time
    "key": "A minor",
    "subgenre": "deep house",
    "drum_feel": "four-on-the-floor kick, offbeat open hats, clap on 2 and 4",
    "instruments": ["analog bass", "warm pads", "plucked synth", "piano stabs"],
    "mood": "uplifting, warm, late-night",
    "energy": 0.7,
}


def _getsongbpm(artist: str, track: str) -> dict | None:
    key = os.getenv("GETSONGBPM_API_KEY")
    if not (key and track):
        return None
    try:
        lookup = f"song:{track}" + (f" artist:{artist}" if artist else "")
        r = requests.get(
            "https://api.getsong.co/search/",
            params={"api_key": key, "type": "both", "lookup": lookup},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json().get("search")
        if not isinstance(results, list) or not results:
            return None
        hit = results[0]
        out = {}
        if hit.get("tempo"):
            out["bpm"] = round(float(hit["tempo"]))
        if hit.get("key_of"):
            out["key"] = _normalize_key(hit["key_of"])
        return out or None
    except Exception as e:
        print(f"  [getsongbpm] failed: {e}")
        return None


def _normalize_key(k: str) -> str:
    """'Am' -> 'A minor', 'F#' -> 'F# major', 'C minor' stays."""
    k = k.strip()
    if re.search(r"major|minor", k, re.I):
        return k
    m = re.match(r"^([A-G][#b♯♭]?)(m|min)?$", k)
    if not m:
        return k
    return f"{m[1].replace('♯', '#').replace('♭', 'b')} {'minor' if m[2] else 'major'}"


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

    # Measured BPM/key beat the LLM's guess.
    measured = _getsongbpm(artist, track)
    if measured:
        profile.update(measured)
        sources.append("getsongbpm")

    if not profile.get("bpm"):
        profile["bpm"] = random.randint(122, 126)
        sources.append("default-bpm")
    profile["sources"] = sources or ["defaults"]
    return profile
