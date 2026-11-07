import random

from housegen import llm, lyric_review, lyrics, vocals
from housegen.spec import STRUCTURE

CAST = vocals.normalize_cast({"lead": "male_tenor", "second": "female_airy", "arrangement": "call and response"})


def section(name, texts, voice="lead"):
    return {"name": name, "voice": voice, "lines": [{"text": t} for t in texts]}


def test_flags_repeated_lines_self_rhymes_cliches_and_unused_second_voice():
    sections = [
        section("Verse 1", ["The crowd ignites", "The night ignites", "Under neon signs"]),
        section("Bridge", ["The crowd ignites"]),
        section("Chorus", ["Hold on", "Hold on"], voice="both"),  # repetition is fine in a chorus...
    ]
    issues = lyric_review.quality_issues(sections, CAST, lyrics.CLICHES)
    text = "\n".join(issues)
    assert 'rhymes "ignites" with itself' in text
    assert 'Bridge repeats the line "The crowd ignites"' in text
    assert 'cliché "neon"' in text
    assert "second voice never sings a section alone" in text
    assert 'rhymes "on" with itself' in text  # ...but rhyming a word with itself is not


def test_clean_draft_has_no_issues():
    sections = [section("Verse 1", ["Rain on the harbour", "Your coat on my shoulder"]),
                section("Bridge", ["I used to run", "Before the morning sun"], voice="second")]
    assert lyric_review.quality_issues(sections, CAST, lyrics.CLICHES) == []


def test_adlibs_are_ignored_when_checking_rhymes():
    sections = [section("Verse 1", ["Take me higher (higher)", "Into the fire (fire) tonight"])]
    issues = lyric_review.quality_issues(sections, vocals.normalize_cast({"lead": "male_tenor"}), ())
    assert issues == []


def _answer(bridge_voice, bridge_lines):
    plan = lyrics.plan_sections(STRUCTURE)
    secs = []
    for p in plan:
        if not p["lines"]:
            continue
        lines = bridge_lines if p["name"] == "Bridge" else [f"{p['name']} {w}" for w in ("one", "two", "three", "four",
                                                                                      "five", "six", "seven", "eight")][: p["lines"]]
        secs.append({"name": p["name"], "voice": bridge_voice if p["name"] == "Bridge" else "lead", "lines": lines})
    return {"title": "T", "concept": "c", "vocals": {"lead": "male_tenor", "second": "female_airy",
                                                      "arrangement": "call and response"}, "sections": secs}


SPEC = {"subgenre": "house", "bpm": 124, "key": "A minor", "mood": "warm", "energy": 0.7, "structure": STRUCTURE}


def test_revision_is_used_when_it_fixes_the_problems(monkeypatch):
    drafts = iter([_answer("lead", ["same", "same", "same", "same"]),
                   _answer("second", ["I kept the key", "You never asked", "The door stayed open", "I walked in"])])
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: next(drafts))
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(0))
    bridge = next(s for s in words["sections"] if s["name"] == "Bridge")
    assert bridge["voice"] == "second" and bridge["lines"][0]["text"] == "I kept the key"


def test_worse_revision_is_discarded(monkeypatch):
    first = _answer("second", ["I kept the key", "You never asked", "The door stayed open", "I walked in"])
    first["sections"][0]["lines"][1] = first["sections"][0]["lines"][0]  # one small issue
    drafts = iter([first, {"sections": [{"name": "Verse 1", "lines": ["x"]}]}])  # revision doesn't even fit
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: next(drafts))
    words = lyrics.write_lyrics(SPEC, {"source": "user", "text": "x"}, None, random.Random(0))
    assert next(s for s in words["sections"] if s["name"] == "Bridge")["lines"][0]["text"] == "I kept the key"
