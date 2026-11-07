"""Editor pass for LLM lyrics: find concrete craft problems, and ask for one targeted revision if any.

The checks are deliberately mechanical (repeated lines, a word rhymed with itself, an unused second
voice, banned clichés) so a revision is only requested, and only accepted, when it measurably helps.
"""
import re

CHORUS_NAMES = ("Chorus", "Final Chorus", "Outro")  # sections where repetition is the point


def _end_word(text: str) -> str:
    text = re.sub(r"\([^)]*\)", "", text)  # ignore backing-vocal ad-libs
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return words[-1] if words else ""


def quality_issues(sections: list[dict], cast: dict, cliches: tuple[str, ...]) -> list[str]:
    issues = []
    seen: dict[str, str] = {}
    for s in sections:
        texts = [line["text"] for line in s["lines"]]
        if s["name"] not in CHORUS_NAMES:
            for t in texts:
                key = t.strip().lower()
                if key in seen:
                    issues.append(f'{s["name"]} repeats the line "{t}" (also in {seen[key]}); write a new line')
                else:
                    seen[key] = s["name"]
        ends = [_end_word(t) for t in texts]
        for a, b, t in zip(ends, ends[1:], texts[1:]):
            if a and a == b:
                issues.append(f'{s["name"]} rhymes "{a}" with itself at "{t}"; find a true rhyme')
        for t in texts:
            hits = [c for c in cliches if c in t.lower()]
            if hits:
                issues.append(f'{s["name"]} uses the cliché "{hits[0]}" in "{t}"; replace it with a specific image')
    if cast.get("second") and not any(s["voice"] == "second" for s in sections if s["lines"]):
        issues.append('The second voice never sings a section alone; give it the Bridge or Pre-Chorus ("voice": "second")')
    return issues


def revision_prompt(draft: dict, issues: list[str]) -> str:
    listed = "\n".join(f"- {i}" for i in issues)
    return f"""Here is a draft topline as JSON:
{draft}

An editor found these problems:
{listed}

Fix every problem. Keep the title, concept, voices, section names, line counts and everything that already works;
change only what's needed. Return the full topline in the same JSON shape."""
