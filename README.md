# House Music Generator

`python gen.py "make a song like calvin harris's Summer"` → an audio file + a JSON spec explaining why it sounds the way it does.

## Pipeline

| Step | Module | Fallback when a key is missing |
|---|---|---|
| 1. Parse prompt → `{artist, track}` | `housegen/parse.py` (regex, then LLM via Groq, `housegen/llm.py`) | empty reference |
| 2. Resolve on Spotify (client credentials) | `housegen/spotify.py` | skipped |
| 3. Style profile (GetSongBPM + LLM description) | `housegen/profile.py` | house defaults: 122–126 BPM, A minor |
| 4. Style spec JSON (never contains the artist name) | `housegen/spec.py` | — |
| 5. Lyrics from an RSS headline / poem / `--theme` | `housegen/lyrics.py` | built-in lyrics |
| 6A. ElevenLabs Music (vocals) | `housegen/audio_eleven.py` | path B |
| 6B. Procedural MIDI + numpy synth (instrumental) | `housegen/audio_procedural.py` | wav if ffmpeg is missing |

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in whichever keys you have
.venv/bin/python gen.py "make a song like calvin harris's Summer" [--path A|B] [--theme "text"]
```

Outputs go to `output/`: `.mp3` (or `.wav`), `.mid` (path B), and `.json` (reference, profile, spec, lyrics).
mp3 encoding needs a working `ffmpeg` (`brew install ffmpeg`).
