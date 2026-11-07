import random

from housegen import vocals


def test_fallback_cast_pairs_contrasting_voices():
    for seed in range(30):
        cast = vocals.fallback_cast({"bpm": 124, "energy": 0.7, "mood": "warm"}, random.Random(seed))
        lead_male = cast["lead"]["key"].startswith("male")
        second_male = cast["second"]["key"].startswith("male")
        assert lead_male != second_male
        assert cast["arrangement"] in vocals.ARRANGEMENTS


def test_fallback_cast_varies_across_songs():
    leads = {vocals.fallback_cast({"bpm": 124, "energy": 0.7, "mood": ""}, random.Random(s))["lead"]["key"]
             for s in range(40)}
    assert len(leads) >= 3
    assert any(k.startswith("male") for k in leads)


def test_normalize_cast_accepts_palette_keys_and_custom_voices():
    cast = vocals.normalize_cast({"lead": "male_baritone",
                                  "second": {"tag": "female vocal", "description": "bright pop female vocal"},
                                  "arrangement": "call and response"})
    assert cast["lead"]["tag"] == "male vocal, deep"
    assert cast["second"]["description"] == "bright pop female vocal"
    assert "call and response" in cast["style"]


def test_normalize_cast_rejects_missing_lead_and_fixes_bad_arrangement():
    assert vocals.normalize_cast({"lead": "nobody"}) is None
    assert vocals.normalize_cast(None) is None
    solo = vocals.normalize_cast({"lead": "female_soul", "arrangement": "duet trading sections"})
    assert solo["second"] is None and solo["arrangement"] == vocals.ARRANGEMENTS[0]


def test_section_tag_switches_voice_by_role():
    cast = vocals.normalize_cast({"lead": "male_tenor", "second": "female_airy", "arrangement": "duet trading sections"})
    assert vocals.section_tag(cast, "lead") == "male vocal"
    assert vocals.section_tag(cast, "second") == "female vocal, breathy"
    assert vocals.section_tag(cast, "both") == "male vocal and female vocal, harmonies"
    solo = vocals.normalize_cast({"lead": "male_tenor"})
    assert vocals.section_tag(solo, "second") == "male vocal"
