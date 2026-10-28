# House Music Generator

`python gen.py "make a song like calvin harris's Summer"` → an audio file + a JSON spec explaining why it sounds the way it does.

[GetSongBPM](https://getsongbpm.com)

## Pipeline

| Step | Module | Fallback when a key is missing |
|---|---|---|
| 1. Parse prompt → `{artist, track}` | `housegen/parse.py` (regex, then LLM via Groq, `housegen/llm.py`) | empty reference |
| 2. Resolve on Spotify (client credentials) | `housegen/spotify.py` | skipped |
| 3. Style profile ([ReccoBeats](https://reccobeats.com) audio features + LLM description) | `housegen/profile.py` | house defaults: 122–126 BPM, A minor |
| 4. Style spec JSON (never contains the artist name) | `housegen/spec.py` | — |
| 5. Lyrics from an RSS headline / poem / `--theme` | `housegen/lyrics.py` | built-in lyrics |
| 6C. Local ACE-Step 1.5 server (free, vocals) | `housegen/audio_acestep.py` | path A |
| 6A. ElevenLabs Music (paid, vocals) | `housegen/audio_eleven.py` | path B |
| 6B. Procedural MIDI + numpy synth (instrumental) | `housegen/audio_procedural.py` | wav if ffmpeg is missing |

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in whichever keys you have
.venv/bin/python gen.py "make a song like calvin harris's Summer" [--path A|B] [--theme "text"]
```

Outputs go to `output/`: `.mp3` (or `.wav`), `.mid` (path B), and `.json` (reference, profile, spec, lyrics).
mp3 encoding needs a working `ffmpeg` (`brew install ffmpeg`).

## HTTP API

```bash
.venv/bin/uvicorn app:app --port 8000      # docs at http://localhost:8000/docs
```

Generation takes a minute or more, so it's a job API:

```bash
curl -X POST localhost:8000/songs -H 'content-type: application/json' \
  -d '{"prompt": "make a song like calvin harris'"'"'s Summer", "theme": "optional lyric idea"}'
# -> {"id": "a1e66ac2bf99", "status": "queued", "url": "/songs/a1e66ac2bf99"}

curl localhost:8000/songs/a1e66ac2bf99           # status, current step; spec + lyrics + links when done
curl -o song.mp3 localhost:8000/songs/a1e66ac2bf99/audio
```

| Endpoint | |
|---|---|
| `POST /songs` | `{prompt, path?: "A"\|"B"\|"C", theme?}` → 202 with a job id |
| `GET /songs/{id}` | `status` (queued/running/done/failed), `step`, `result` or `error` |
| `GET /songs/{id}/audio` | the audio file (409 until done) |
| `GET /songs/{id}/midi` | MIDI, path B only |
| `GET /songs` | all jobs, newest first |
| `GET /health` | which audio backends are available |

Jobs run one at a time and are kept in memory (lost on restart; files in `output/` stay).

## Free vocals with ACE-Step (path C)

ACE-Step 1.5 runs locally as a separate server (it needs Python 3.11–3.12, so it has its own env).
Install once, inside this repo (it's gitignored):

```bash
brew install uv
git clone https://github.com/ACE-Step/ACE-Step-1.5.git ACE-Step-1.5
cd ACE-Step-1.5 && uv sync
```

Start the server in its own terminal (models download on first run, several GB):

```bash
cd ACE-Step-1.5
ACESTEP_LM_BACKEND=mlx TOKENIZERS_PARALLELISM=false uv run acestep-api --host 127.0.0.1 --port 8001
```

While it's running, `gen.py` uses it automatically (or force it with `--path C`).
