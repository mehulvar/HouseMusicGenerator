"""Path C: spec + lyrics -> local ACE-Step 1.5 server (free, sung vocals). See README for running the server."""
import json
import os
import time

import requests

from .spec import parse_key

TAGS = {"intro": "intro", "build": "verse", "drop": "chorus", "break": "bridge", "outro": "outro"}


def _base() -> str:
    return os.getenv("ACESTEP_URL", "http://127.0.0.1:8001").rstrip("/")


def _headers() -> dict:
    key = os.getenv("ACESTEP_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def available() -> bool:
    try:
        return requests.get(f"{_base()}/health", timeout=2).ok
    except requests.RequestException:
        return False


def tagged_lyrics(spec: dict, lyrics: dict) -> str:
    """ACE-Step wants section-tagged lyrics; instrumental sections get a bare tag."""
    blocks = []
    for s in spec["structure"]:
        tag = TAGS.get(s["section"], s["section"])
        lines = []
        if s["section"] == "drop":
            lines = lyrics["hook"] * 2
        elif s["section"] in ("build", "break"):
            lines = lyrics["verse"]
        blocks.append("\n".join([f"[{tag}]", *lines]))
    return "\n\n".join(blocks)


def duration_s(spec: dict) -> float:
    bars = sum(s["bars"] for s in spec["structure"])
    return min(600.0, bars * 4 * 60 / spec["bpm"])


def caption(spec: dict, clarity: bool = True) -> str:
    """ACE-Step caption: concrete genre, instruments, vocal and production descriptors (per its guide)."""
    # Space words pull the whole mix (vocals included) toward heavy reverb, and "vocal chops"-style
    # instruments make the lead sound processed/robotic; the vocal is described separately below.
    blocked = ("reverb", "atmospher", "ethereal", "vocal", "voice")
    instruments = [i for i in spec["instruments"] if not any(w in i.lower() for w in blocked)]
    vocal = spec.get("vocals", {}).get("style", "warm soulful female lead vocal")
    vocal = vocal[:1].upper() + vocal[1:]
    return (
        f"{spec['subgenre']}, classic house groove at {spec['bpm']} BPM, punchy four-on-the-floor kick, "
        f"crisp offbeat open hi-hats, claps on 2 and 4, {spec['bass']['style']}, {spec['chords']['voicing']}, "
        f"{', '.join(instruments)}. Mood: {spec['mood']}. "
        f"{vocal}, natural human singing, dry and upfront, close-mic'd, intimate, minimal reverb. "
        + (CLARITY if clarity else "")
        + "Polished modern club production, tight low end."
    )


# Describing tone alone left lyrics hard to make out; ask for intelligibility and vocal level explicitly.
CLARITY = (
    "Clear diction and crisp consonants, every word of the lyrics intelligible, "
    "lead vocal loud and centered, sitting clearly above the instrumental. "
)


def settings() -> dict:
    """Generation knobs, overridable from .env for tuning."""
    out = {
        "inference_steps": int(os.getenv("ACESTEP_STEPS", "8")),
        "thinking": os.getenv("ACESTEP_THINKING", "true").lower() == "true",
    }
    if os.getenv("ACESTEP_MODEL"):
        out["model"] = os.environ["ACESTEP_MODEL"]
    return out


def render(spec: dict, lyrics: dict, out_path: str, timeout_s: int = 1800, **overrides) -> str:
    """overrides are merged into the request body last (e.g. seed, thinking, prompt) for A/B tests."""
    root, mode = parse_key(spec["key"])
    body = {
        "prompt": caption(spec),
        "lyrics": tagged_lyrics(spec, lyrics),
        "vocal_language": "en",
        "audio_duration": duration_s(spec),
        "bpm": spec["bpm"],
        "key_scale": f"{root} {mode.capitalize()}",
        "time_signature": "4",
        "audio_format": "mp3",
        "batch_size": 1,
        **settings(),
        **overrides,
    }
    r = requests.post(f"{_base()}/release_task", json=body, headers=_headers(), timeout=30)
    r.raise_for_status()
    task_id = r.json()["data"]["task_id"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        items = requests.post(
            f"{_base()}/query_result", json={"task_id_list": [task_id]}, headers=_headers(), timeout=30
        ).json()["data"]
        item = items[0]
        if item["status"] == 1:
            break
        if item["status"] == 2:
            raise RuntimeError(f"ACE-Step task failed: {item.get('result')}")
        time.sleep(3)
    else:
        raise TimeoutError(f"ACE-Step task {task_id} did not finish in {timeout_s}s")

    outputs = json.loads(item["result"])
    # The server reports success even when saving the file failed (e.g. broken ffmpeg); check its log.
    if not outputs or not outputs[0].get("file"):
        raise RuntimeError(f"ACE-Step returned no audio file (see the server log): {item['result'][:300]}")
    audio = requests.get(_base() + outputs[0]["file"], headers=_headers(), timeout=120)
    audio.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(audio.content)
    return out_path
