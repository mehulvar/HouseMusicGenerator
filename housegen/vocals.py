"""Vocal casting: who sings, and which voice takes each section, chosen to fit the beat.

The reference track's own singer is deliberately not the anchor; otherwise every song inherits the
same voice. The LLM casts from VOICES (or describes its own); without an LLM, fallback_cast picks a
pairing from tempo, energy and mood.
"""
import random

# tag: the short form ACE-Step reads in lyric section tags; description: the caption wording.
VOICES = {
    "female_soul": {"tag": "female vocal", "description": "warm soulful female lead vocal"},
    "female_airy": {"tag": "female vocal, breathy", "description": "airy breathy female soprano vocal"},
    "female_power": {"tag": "female vocal, powerful", "description": "powerful belting female diva vocal"},
    "male_tenor": {"tag": "male vocal", "description": "smooth soulful male tenor vocal"},
    "male_baritone": {"tag": "male vocal, deep", "description": "deep warm male baritone vocal"},
    "male_falsetto": {"tag": "male vocal, falsetto", "description": "silky male falsetto vocal"},
    "male_raspy": {"tag": "male vocal, raspy", "description": "gritty raspy male vocal"},
}
ARRANGEMENTS = ("solo lead with harmonies", "duet trading sections", "call and response")
VOICE_ROLES = ("lead", "second", "both")

HIGH_ENERGY = 0.75
LOW_ENERGY = 0.5
FAST_BPM = 126


def _voice(key: str) -> dict:
    return {"key": key, **VOICES[key]}


def fallback_cast(spec: dict, rng: random.Random | None = None) -> dict:
    """Pick a lead and contrasting second voice from the beat when no LLM is available."""
    rng = rng or random.Random()
    energy = float(spec.get("energy", 0.7))
    mood = str(spec.get("mood", "")).lower()
    if energy >= HIGH_ENERGY or spec.get("bpm", 124) >= FAST_BPM:
        leads = ["female_power", "male_tenor", "male_raspy"]
    elif energy < LOW_ENERGY or any(w in mood for w in ("deep", "late", "dark", "moody")):
        leads = ["male_baritone", "female_airy", "male_falsetto"]
    else:
        leads = ["female_soul", "male_tenor", "male_falsetto", "female_airy"]
    lead = rng.choice(leads)
    lead_is_male = lead.startswith("male")
    seconds = [k for k in VOICES if k.startswith("female" if lead_is_male else "male")]
    return normalize_cast({"lead": lead, "second": rng.choice(seconds), "arrangement": rng.choice(ARRANGEMENTS)})


def _resolve(voice) -> dict | None:
    """Accept a palette key, or a free-form {"tag", "description"} the LLM wrote itself."""
    if isinstance(voice, str) and voice in VOICES:
        return _voice(voice)
    if isinstance(voice, dict) and voice.get("tag") and voice.get("description"):
        return {"key": voice.get("key", "custom"), "tag": str(voice["tag"]), "description": str(voice["description"])}
    return None


def normalize_cast(raw: dict | None) -> dict | None:
    """Validate a casting; None if there's no usable lead."""
    if not isinstance(raw, dict):
        return None
    lead = _resolve(raw.get("lead"))
    if not lead:
        return None
    second = _resolve(raw.get("second"))
    arrangement = raw.get("arrangement") if raw.get("arrangement") in ARRANGEMENTS else ARRANGEMENTS[0]
    if not second:
        arrangement = ARRANGEMENTS[0]
    style = lead["description"] + (f", with a {second['description']} ({arrangement})" if second else "")
    return {"lead": lead, "second": second, "arrangement": arrangement, "style": style}


def section_tag(cast: dict, voice: str) -> str:
    """The vocal part of an ACE-Step section tag, e.g. 'male vocal, deep' or a duet for 'both'."""
    lead, second = cast["lead"], cast.get("second")
    if voice == "second" and second:
        return second["tag"]
    if voice == "both" and second:
        return f"{lead['tag'].split(',')[0]} and {second['tag'].split(',')[0]}, harmonies"
    return lead["tag"]


def palette_text() -> str:
    return "\n".join(f'- "{k}": {v["description"]}' for k, v in VOICES.items())
