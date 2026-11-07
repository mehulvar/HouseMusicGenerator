"""Step 5: write original, full-length lyrics and cast the voices, fitted to the song structure.

One LLM call acts as topliner: it reads a brief of the reference song's lyrical approach (themes,
perspective, hook mechanics; never its words), casts voices for this beat, and writes every vocal
section. Without an LLM, a hand-written multi-section fallback keeps songs singable.
"""
import random
import re

from . import llm, lyric_review, vocals

# Public-domain fallback themes (Emily Dickinson, Walt Whitman).
POEMS = [
    "Hope is the thing with feathers that perches in the soul",
    "I celebrate myself, and sing myself",
    "Wild nights - Wild nights! Were I with thee, wild nights should be our luxury",
]

LINES_PER_BARS = 2  # one sung line every two bars
SYLLABLES_PER_LINE = "7-10"
OUTRO_LINES = 2
MIN_FILL = 0.5  # an LLM section with fewer than half its lines is rejected
LYRICS_MAX_TOKENS = 6000  # a full topline used ~3.8k tokens including reasoning

# Patterns the ACE-Step guide calls out as "AI-flavoured", plus stock dance-lyric clichés.
CLICHES = ("neon", "electric hearts", "endless dreams", "set me free", "lose control", "dance the night away",
           "feel the beat", "on the dance floor", "fire inside", "touch the sky", "we are one", "heartbeat")


def fetch_inspiration(user_text: str | None = None, brief: dict | None = None) -> dict:
    """User theme wins; then the reference song's themes; a public-domain poem as last resort."""
    if user_text:
        return {"source": "user", "text": user_text}
    if brief and brief.get("theme"):
        return {"source": "reference song (themes only)", "text": brief["theme"]}
    return {"source": "public-domain poem", "text": random.choice(POEMS)}


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups) - (1 if word.endswith("e") and len(groups) > 1 else 0)
    return max(1, n)


def count_syllables(line: str) -> int:
    return sum(_syllables(w) for w in re.findall(r"[a-zA-Z']+", line))


def plan_sections(structure: list[dict]) -> list[dict]:
    """Name every structure section and size its lyrics; intro stays instrumental."""
    drops = sum(1 for s in structure if s["section"] == "drop")
    seen = {"build": 0, "drop": 0, "break": 0}
    plan = []
    for s in structure:
        kind = s["section"]
        seen[kind] = seen.get(kind, 0) + 1
        lines = s["bars"] // LINES_PER_BARS
        if kind == "intro":
            name, lines = "Intro", 0
        elif kind == "build":
            name = "Verse 1" if seen[kind] == 1 else "Pre-Chorus"
        elif kind == "drop":
            name = "Final Chorus" if seen[kind] == drops and drops > 1 else "Chorus"
        elif kind == "break":
            name = "Bridge"
        elif kind == "outro":
            name, lines = "Outro", OUTRO_LINES
        else:
            name = kind.title()
        plan.append({"name": name, "section": kind, "bars": s["bars"], "lines": lines})
    return plan


def _brief_text(brief: dict | None) -> str:
    if not brief:
        return "No reference brief available; invent a fresh, specific concept."
    fields = ("theme", "story", "perspective", "imagery", "hook_device", "cadence")
    return "\n".join(f"- {f.replace('_', ' ')}: {brief[f]}" for f in fields if brief.get(f))


def _prompt(spec: dict, plan: list[dict], inspiration: dict, brief: dict | None, suggested_lead: str) -> str:
    sung = [p for p in plan if p["lines"]]
    sections = "\n".join(f'- "{p["name"]}" ({p["section"]}, {p["bars"]} bars): exactly {p["lines"]} lines' for p in sung)
    return f"""Write the complete topline for a NEW original {spec['subgenre']} track: {spec['bpm']} BPM, {spec['key']},
mood: {spec['mood']}, energy {spec['energy']}.

Inspiration: "{inspiration['text']}" ({inspiration['source']}).
How the reference song approaches its lyrics (borrow the approach, never its words, phrases or title):
{_brief_text(brief)}

1. CAST THE VOICES for this beat. Choose what suits the tempo, energy and mood of THIS track, not the
reference's singer. Do not default to a female voice: male, female and mixed casts are all on the table.
For variety, start by considering "{suggested_lead}" as the lead and move away from it if something fits better.
Pick from this palette by key (or describe your own as {{"tag": "...", "description": "..."}}):
{vocals.palette_text()}
Optionally add a contrasting "second" voice, and an "arrangement": one of {list(vocals.ARRANGEMENTS)}.

2. WRITE EVERY SECTION below, in order, with exactly the line counts given:
{sections}
Give each section a "voice": "lead", "second" or "both" (switch voices between sections when there is a second
voice; choruses suit "both"), and a 1-3 word "delivery" (e.g. "intimate", "anthemic", "whispered", "belted").

Craft rules:
- One core concept or metaphor, explored from different angles across sections; a story that moves forward.
- Verses: concrete, specific details (places, objects, actions, times), not abstractions.
- The chorus hook is short, singable and repeatable; the Final Chorus varies or escalates it (new last lines,
  ad-libs in parentheses for backing vocals, call-and-response).
- The Bridge turns the story: a new angle, confession or twist. The Pre-Chorus lifts the tension.
- Each line {SYLLABLES_PER_LINE} syllables, singable in one breath, consistent rhyme scheme with internal rhymes.
- Every line in Verse 1, Bridge and Pre-Chorus is different; avoid repeating lines outside the choruses.
- Never rhyme a word with itself. If there is a second voice, it sings at least one section alone.
- Avoid clichés and vague imagery: {", ".join(CLICHES)}. No adjective stacking, no mixed metaphors.

Return {{"title": str, "concept": str, "vocals": {{"lead": key-or-object, "second": key-or-object-or-null,
"arrangement": str}}, "sections": [{{"name": str, "voice": str, "delivery": str, "lines": [str]}}]}}."""


def _fit_sections(plan: list[dict], raw_sections, cast: dict) -> list[dict] | None:
    """Line the LLM's sections up with the plan (by name, else order); None if any sung section is too thin."""
    if not isinstance(raw_sections, list):
        return None
    usable = [s for s in raw_sections if isinstance(s, dict)]
    by_name = {str(s.get("name", "")).strip().lower(): s for s in usable}
    in_order = iter(usable)
    out = []
    for p in plan:
        if not p["lines"]:
            out.append({**p, "voice": "lead", "delivery": "", "lines": []})
            continue
        raw = by_name.get(p["name"].lower()) or next(in_order, None) or {}
        lines = [str(l).strip() for l in raw.get("lines", []) if str(l).strip()][: p["lines"]]
        if len(lines) < p["lines"] * MIN_FILL:
            return None
        voice = raw.get("voice") if raw.get("voice") in vocals.VOICE_ROLES else "lead"
        if voice != "lead" and not cast.get("second"):
            voice = "lead"
        delivery = str(raw.get("delivery", ""))[:30].strip()
        out.append({**p, "voice": voice, "delivery": delivery,
                    "lines": [{"text": l, "syllables": count_syllables(l)} for l in lines]})
    return out


# Hand-written fallback, one entry per planned section name.
FALLBACK_LINES = {
    "Verse 1": ["Streetlights hum along the harbour wall", "Your jacket on my shoulders in the rain",
                "We missed the last train on purpose", "And laughed until the platform cleared"],
    "Chorus": ["Hold the light, don't let it go", "Keep it burning, soft and slow", "Hold the light (hold the light)",
               "Till the morning finds us home", "Every window going gold", "Hold the light, don't let it go",
               "Say my name like it's a song", "Hold the light, hold on"],
    "Bridge": ["I used to leave before the lights came up", "Afraid of what the daylight might say",
               "But you stayed and traced the city on my hand", "And I forgot the way out of this place"],
    "Pre-Chorus": ["Count the seconds, one more round", "Feel the ceiling coming down",
                   "Hands up, heart out, no way back", "Here it comes (here it comes)"],
    "Final Chorus": ["Hold the light, don't let it go", "Keep it burning, soft and slow", "Hold the light (don't let go)",
                     "Till the morning finds us home", "Every window going gold", "Louder now (louder now)",
                     "Say my name like it's a song", "Hold the light, hold on"],
    "Outro": ["Hold the light", "(Hold on)"],
}
FALLBACK_VOICES = {"Chorus": "both", "Final Chorus": "both", "Bridge": "second", "Pre-Chorus": "second"}


def _fallback_sections(plan: list[dict], cast: dict) -> list[dict]:
    out = []
    for p in plan:
        source = FALLBACK_LINES.get(p["name"], FALLBACK_LINES["Verse 1"])
        lines = [source[i % len(source)] for i in range(p["lines"])]
        voice = FALLBACK_VOICES.get(p["name"], "lead") if cast.get("second") else "lead"
        out.append({**p, "voice": voice, "delivery": "",
                    "lines": [{"text": l, "syllables": count_syllables(l)} for l in lines]})
    return out


def _texts(sections: list[dict], *names: str) -> list[str]:
    for s in sections:
        if s["name"] in names and s["lines"]:
            return [l["text"] for l in s["lines"]]
    return []


SONGWRITER = ("You are an elite songwriter and topliner for dance music. You write original, vivid, singable lyrics "
              "with real storytelling. You never quote or paraphrase existing songs.")


def _ask(prompt: str) -> dict:
    return llm.ask_json(SONGWRITER, prompt, max_tokens=LYRICS_MAX_TOKENS,
                        reasoning_effort="medium") or {}  # "low" skimps on line counts


def _review(plan: list[dict], result: dict, sections: list[dict], cast: dict) -> tuple[dict, list[dict]]:
    """One editor round: revise only if the draft has concrete problems, keep the revision only if it's better."""
    issues = lyric_review.quality_issues(sections, cast, CLICHES)
    if not issues:
        return result, sections
    print(f"  [lyrics] editor found {len(issues)} issue(s); revising")
    revised = _ask(lyric_review.revision_prompt(result, issues))
    revised_cast = vocals.normalize_cast(revised.get("vocals")) or cast
    revised_sections = _fit_sections(plan, revised.get("sections"), revised_cast)
    if revised_sections is None:
        return result, sections
    remaining = lyric_review.quality_issues(revised_sections, revised_cast, CLICHES)
    if len(remaining) >= len(issues):
        return result, sections
    return {**result, **revised, "vocals": revised.get("vocals") or result.get("vocals")}, revised_sections


def write_lyrics(spec: dict, inspiration: dict, brief: dict | None = None, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    plan = plan_sections(spec["structure"])
    fallback_cast = vocals.fallback_cast(spec, rng)
    result = _ask(_prompt(spec, plan, inspiration, brief, fallback_cast["lead"]["description"]))

    cast = vocals.normalize_cast(result.get("vocals")) or fallback_cast
    sections = _fit_sections(plan, result.get("sections"), cast)
    if sections is not None:
        result, sections = _review(plan, result, sections, cast)
        cast = vocals.normalize_cast(result.get("vocals")) or cast
    if sections is None:
        if result:
            print("  [lyrics] LLM sections didn't fit the plan; using the fallback lyrics")
        sections = _fallback_sections(plan, cast)
        concept = ""
    else:
        concept = str(result.get("concept", ""))

    return {
        "title": str(result.get("title") or "Hold The Light"),
        "concept": concept,
        "inspiration": inspiration,
        "vocals": cast,
        "sections": sections,
        # Short summaries kept for older readers (site view, ElevenLabs plan).
        "hook": _texts(sections, "Chorus", "Final Chorus")[:4],
        "verse": _texts(sections, "Verse 1"),
    }
