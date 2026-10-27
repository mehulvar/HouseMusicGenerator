#!/usr/bin/env python3
"""python gen.py "make a song like calvin harris's Summer" [--path A|B] [--theme "..."]"""
import argparse
import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from housegen import audio_eleven, audio_procedural, lyrics, parse, profile, spec, spotify  # noqa: E402


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "song"


def run(prompt: str, path: str | None = None, theme: str | None = None, out_dir: str = "output") -> dict:
    print("1. parse");    ref = parse.parse_prompt(prompt);  print(f"   {ref}")
    print("2. spotify");  meta = spotify.resolve(ref["artist"], ref["track"]); print(f"   {meta}")
    artist = (meta or {}).get("artist") or ref["artist"]
    track = (meta or {}).get("track") or ref["track"]

    print("3. profile")
    prof = profile.build_profile(artist, track, meta)
    print(f"   bpm={prof['bpm']} key={prof['key']} sources={prof['sources']}")

    print("4. spec")
    banned = [n for n in {artist, ref["artist"], *artist.split(", ")} if n]
    style = spec.build_spec(prof, banned)

    print("5. lyrics")
    words = lyrics.write_lyrics(style, lyrics.fetch_inspiration(theme))
    print(f"   \"{words['title']}\" / hook: {words['hook'][0]}")

    path = (path or ("A" if audio_eleven.available() else "B")).upper()
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"{datetime.now():%Y%m%d-%H%M%S}-{slug(words['title'])}")

    print(f"6. audio (path {path})")
    if path == "A":
        audio = audio_eleven.render(style, words, base + ".mp3")
    else:
        audio_procedural.build_midi(style, base + ".mid")
        audio = audio_procedural.render(style, base + ".mp3")

    result = {
        "prompt": prompt,
        "reference": {"parsed": ref, "spotify": meta},  # kept for traceability; never sent to generators
        "profile": prof,
        "spec": style,
        "lyrics": words,
        "audio_path": path,
        "files": {"mp3": audio, **({"midi": base + ".mid"} if path == "B" else {})},
    }
    with open(base + ".json", "w") as f:
        json.dump(result, f, indent=2)
    print(f"done -> {audio}\n        {base}.json")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--path", choices=["A", "B", "a", "b"], help="A=ElevenLabs (vocals), B=procedural (default if no key)")
    ap.add_argument("--theme", help="lyric inspiration text instead of an RSS headline")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    run(a.prompt, a.path, a.theme, a.out)
