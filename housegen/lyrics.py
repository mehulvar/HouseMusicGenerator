"""Step 5: fetch outside text for inspiration, then write original lyrics fitted to the structure."""
import random
import re
import xml.etree.ElementTree as ET

import requests

from . import llm

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
]

# Public-domain fallback (Emily Dickinson, Walt Whitman).
POEMS = [
    "Hope is the thing with feathers that perches in the soul",
    "I celebrate myself, and sing myself",
    "Wild nights - Wild nights! Were I with thee, wild nights should be our luxury",
]


def fetch_inspiration(user_text: str | None = None) -> dict:
    if user_text:
        return {"source": "user", "text": user_text}
    for url in RSS_FEEDS:
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            titles = [t.text for t in ET.fromstring(r.content).iter("title") if t.text]
            if len(titles) > 2:
                return {"source": url, "text": random.choice(titles[2:])}  # skip feed titles
        except Exception:
            continue
    return {"source": "public-domain poem", "text": random.choice(POEMS)}


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups) - (1 if word.endswith("e") and len(groups) > 1 else 0)
    return max(1, n)


def count_syllables(line: str) -> int:
    return sum(_syllables(w) for w in re.findall(r"[a-zA-Z']+", line))


def _vocal_sections(spec: dict) -> list[dict]:
    """Drops carry the hook, builds carry verses. One line per 2 bars, ~8 syllables per line."""
    out = []
    for s in spec["structure"]:
        if s["section"] in ("drop", "build", "break"):
            kind = "hook" if s["section"] == "drop" else "verse"
            out.append({"section": s["section"], "kind": kind, "lines": s["bars"] // 2, "syllables": 8})
    return out


def write_lyrics(spec: dict, inspiration: dict) -> dict:
    plan = _vocal_sections(spec)
    result = llm.ask_json(
        "You are a dance-music topliner. You write original, singable lyrics. Never quote existing songs.",
        f'Inspiration (theme only, do not copy): "{inspiration["text"]}"\n'
        f"Mood: {spec['mood']}. Subgenre: {spec['subgenre']}.\n"
        "Write a short repeating HOOK (2 lines, ~6-8 syllables each) and a VERSE (4 lines, ~8 syllables each).\n"
        'Return {"title": str, "hook": [str], "verse": [str]}.',
    )
    if not result:
        result = {
            "title": "Hold The Light",
            "hook": ["Hold the light, don't let it go", "Feel it rising, soft and slow"],
            "verse": [
                "City glowing after midnight",
                "Every heartbeat finds the bassline",
                "We were waiting for a signal",
                "Now the floor is all we know",
            ],
        }

    sections = []
    for p in plan:
        src = result["hook"] if p["kind"] == "hook" else result["verse"]
        lines = [src[i % len(src)] for i in range(min(p["lines"], 4))]
        sections.append({**p, "lines": [{"text": l, "syllables": count_syllables(l)} for l in lines]})
    return {
        "title": result.get("title", "Untitled"),
        "inspiration": inspiration,
        "hook": result["hook"],
        "verse": result["verse"],
        "sections": sections,
    }
