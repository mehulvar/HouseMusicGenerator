"""Step 4: the style spec — the heart of the app. Must never contain the reference artist's name."""
import re

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}

# Scale degrees (0-based) for common house progressions.
PROGRESSIONS = {
    "minor": [[0, 5, 2, 6], [0, 3, 4, 0], [0, 5, 6, 4]],  # i-VI-III-VII, i-iv-v-i, i-VI-VII-v
    "major": [[0, 4, 5, 3], [3, 4, 0, 5], [0, 5, 3, 4]],  # I-V-vi-IV, IV-V-I-vi, I-vi-IV-V
}

STRUCTURE = [
    {"section": "intro", "bars": 16},
    {"section": "build", "bars": 8},
    {"section": "drop", "bars": 16},
    {"section": "break", "bars": 8},
    {"section": "build", "bars": 8},
    {"section": "drop", "bars": 16},
    {"section": "outro", "bars": 8},
]


def parse_key(key: str) -> tuple[str, str]:
    m = re.match(r"\s*([A-Ga-g])([#b]?)\s*(major|minor|maj|min|m)?", key or "")
    if not m:
        return "A", "minor"
    root = m[1].upper() + m[2]
    root = FLATS.get(root, root)
    mode = "major" if (m[3] or "minor").startswith("maj") else "minor"
    return root, mode


def scrub(value, banned: list[str]):
    """Recursively remove banned names (artist, track) from every string in the spec."""
    if isinstance(value, str):
        for name in banned:
            if name:
                value = re.sub(re.escape(name), "", value, flags=re.I)
        return re.sub(r"\s{2,}", " ", value).strip(" ,-")
    if isinstance(value, list):
        return [scrub(v, banned) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v, banned) for k, v in value.items()}
    return value


def build_spec(profile: dict, banned_names: list[str]) -> dict:
    root, mode = parse_key(profile.get("key", ""))
    energy = float(profile.get("energy", 0.7))
    prog_idx = sum(map(ord, root + mode)) % 3  # deterministic per key
    spec = {
        "bpm": int(profile["bpm"]),
        "key": f"{root} {mode}",
        "subgenre": profile.get("subgenre", "house"),
        "drums": {
            "feel": profile.get("drum_feel", "four-on-the-floor"),
            "kick": "four-on-the-floor",
            "hats": "offbeat open hats, 16th closed hats in drops",
            "clap": "beats 2 and 4",
        },
        "bass": {
            "style": "offbeat sidechained bassline" if energy >= 0.5 else "sustained sub bass",
            "sidechain": True,
        },
        "chords": {
            "progression_degrees": PROGRESSIONS[mode][prog_idx],
            "voicing": "minor 7ths, wide pads" if mode == "minor" else "major 7ths, bright stabs",
            "bars_per_chord": 2,
        },
        "instruments": list(profile.get("instruments", [])),
        "vocals": {"style": profile.get("vocal_style") or "warm soulful female lead vocal"},
        "mood": profile.get("mood", ""),
        "energy": energy,
        "structure": STRUCTURE,
    }
    return scrub(spec, banned_names)


def describe(spec: dict) -> str:
    """Natural-language prompt for text-to-music APIs, built only from descriptors."""
    return (
        f"{spec['subgenre']} track at {spec['bpm']} BPM in {spec['key']}. "
        f"Drums: {spec['drums']['feel']}. Bass: {spec['bass']['style']}. "
        f"Chords: {spec['chords']['voicing']}. "
        f"Instruments: {', '.join(spec['instruments'])}. Mood: {spec['mood']}."
    )
