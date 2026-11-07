import random

import pytest

from housegen import llm, lyrics
from housegen.audio_acestep import tagged_lyrics
from housegen.spec import STRUCTURE

SPEC = {"subgenre": "progressive house", "bpm": 124, "key": "A# minor", "mood": "euphoric", "energy": 0.8,
        "structure": STRUCTURE}


def test_plan_covers_every_section_with_distinct_names_and_line_counts():
    plan = lyrics.plan_sections(STRUCTURE)
    assert [p["name"] for p in plan] == ["Intro", "Verse 1", "Chorus", "Bridge", "Pre-Chorus", "Final Chorus", "Outro"]
    assert [p["lines"] for p in plan] == [0, 4, 8, 4, 4, 8, 2]
    assert sum(p["lines"] for p in plan) == 30  # was 6 unique lines before


def llm_answer(sections_override=None):
    plan = lyrics.plan_sections(STRUCTURE)
    sections = [{"name": p["name"], "voice": "both" if "Chorus" in p["name"] else "lead", "delivery": "anthemic",
                 "lines": [f"{p['name']} line {i}" for i in range(p["lines"])]} for p in plan if p["lines"]]
    return {"title": "Harbour Lights", "concept": "a lighthouse",
            "vocals": {"lead": "male_tenor", "second": "female_power", "arrangement": "duet trading sections"},
            "sections": sections if sections_override is None else sections_override}


def test_write_lyrics_uses_llm_sections_and_cast(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: llm_answer())
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "lighthouse"}, None, random.Random(1))
    assert words["title"] == "Harbour Lights"
    assert words["vocals"]["lead"]["key"] == "male_tenor"
    chorus = next(s for s in words["sections"] if s["name"] == "Chorus")
    assert chorus["voice"] == "both" and len(chorus["lines"]) == 8
    assert words["hook"] == [f"Chorus line {i}" for i in range(4)]
    assert words["verse"] == [f"Verse 1 line {i}" for i in range(4)]


def test_thin_llm_sections_fall_back_to_full_handwritten_lyrics(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: llm_answer([{"name": "Verse 1", "lines": ["only one"]}]))
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(2))
    assert [len(s["lines"]) for s in words["sections"]] == [0, 4, 8, 4, 4, 8, 2]
    assert words["vocals"]["lead"]["key"] == "male_tenor"  # the LLM's cast is still used


def test_no_llm_still_gives_cast_and_every_section(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: None)
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(3))
    assert words["vocals"]["second"] is not None
    assert {s["voice"] for s in words["sections"] if s["lines"]} >= {"lead", "both"}


def test_solo_cast_forces_every_section_to_lead(monkeypatch):
    answer = llm_answer()
    answer["vocals"] = {"lead": "female_soul"}
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: answer)
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(4))
    assert {s["voice"] for s in words["sections"]} == {"lead"}


def test_inspiration_prefers_user_then_reference_brief():
    assert lyrics.fetch_inspiration("mine", {"theme": "ref"})["text"] == "mine"
    assert lyrics.fetch_inspiration(None, {"theme": "ref"})["source"] == "reference song (themes only)"
    assert lyrics.fetch_inspiration(None, None)["source"] == "public-domain poem"


def test_acestep_tags_name_the_voice_for_each_section(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: llm_answer())
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(5))
    text = tagged_lyrics(words)
    assert text.startswith("[Intro - instrumental]")
    assert "[Verse 1 - male vocal, anthemic]\nVerse 1 line 0" in text
    assert "[Chorus - male vocal and female vocal, harmonies, anthemic]" in text
    assert text.count("line") == 30


@pytest.mark.parametrize("cliche", ["neon", "heartbeat"])
def test_prompt_steers_away_from_cliches(cliche):
    plan = lyrics.plan_sections(STRUCTURE)
    prompt = lyrics._prompt(SPEC, plan, {"source": "user", "text": "x"}, {"theme": "longing"}, "deep warm male baritone vocal")
    assert cliche in prompt and "never its words" in prompt and "Do not default to a female voice" in prompt
