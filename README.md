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
| 5. Topline: voices cast for the beat (`housegen/vocals.py`) and full lyrics for every section, written from a brief of how the reference's lyrics work (never its words), then an editor pass (`housegen/lyric_review.py`) | `housegen/lyrics.py` | built-in multi-section lyrics + a beat-matched male/female cast |
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

Tests: `.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest`.

## Deployed on Vercel (queue + Mac studio)

ACE-Step needs this Mac, so the deployed site is split in two:

- **Vercel** (`app.py` in cloud mode): the website and API. Songs live in Vercel Blob, the job queue
  in Upstash Redis. Anyone can listen any time; "Press disc" adds a job to the queue
  (`DAILY_SONG_LIMIT` per visitor, default 3).
- **This Mac** (`worker.py`): double-click **`Start Studio.command`**. It starts ACE-Step and the worker,
  which makes queued songs and uploads them. Close the window to stop; new requests wait in the queue.

Env: Vercel has `KV_REST_API_URL`/`KV_REST_API_TOKEN` (Upstash), `BLOB_READ_WRITE_TOKEN`, and
`WORKER_TOKEN`. The Mac's `.env` has `HOUSEGEN_API_URL` (the site URL) and `HOUSEGEN_WORKER_TOKEN`
(same value as `WORKER_TOKEN`). Deploy with `vercel deploy --prod`. To upload songs you made locally
with `gen.py`: `.venv/bin/python worker.py --publish-existing`.

### Cloud studio on Kaggle (free GPU, no Mac needed)

`kaggle_worker.ipynb` runs the same worker on Kaggle's free GPU (about 30 GPU hours a week, no card).
It's a one-cell launcher: it clones this repo and runs `kaggle_studio.py`, which installs the same
ACE-Step commit (turbo model, 1.7B LM, thinking on; float32 on the T4, since its float16 fallback
overflows), boots ACE-Step, makes every queued song with `worker.drain()` and stops. Fixes ship with a
`git push`; the notebook on Kaggle never needs editing. It checks in with the site while running, so
the site shows a studio online.

One-time setup:
1. Make a Kaggle account and verify your phone number (Settings), which unlocks GPUs and internet.
2. Create a notebook → File → Import Notebook → upload `kaggle_worker.ipynb`.
3. Right panel: **Accelerator: GPU T4 x2** (not P100) and **Internet: On**.
4. Add-ons → Secrets: `HOUSEGEN_API_URL`, `HOUSEGEN_WORKER_TOKEN` and `GROQ_API_KEY` (values from `.env`;
   optional: `GROQ_MODEL`, `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `ELEVENLABS_API_KEY`). Tick each one.

**Automatic start:** when a song is queued and no studio is checking in, the site pushes this notebook
through Kaggle's API and runs it (`housegen/kaggle_trigger.py`); the run keeps taking songs until the queue
has been empty for 90 s. Set these on Vercel (`vercel env add`):
- `KAGGLE_NOTEBOOK`: `username/notebook-slug`, from the notebook's URL
- `KAGGLE_API_TOKEN`: Kaggle → Settings → API → Generate New Token
  (or a legacy key: `KAGGLE_USERNAME` + `KAGGLE_KEY` from `kaggle.json`)

To start one by hand: **Save Version → Save & Run All**. Kaggle doesn't keep files between runs, so each run
reinstalls ACE-Step and re-downloads the models (~10 GB) before the first song.

While a disc is pressing the site shows a countdown (`housegen/eta.py`): studio boot time if none is up,
plus the median of recent render times for the song in progress and each song ahead in the queue.

## Web UI + HTTP API (local)

```bash
.venv/bin/uvicorn app:app --port 8000      # UI at http://localhost:8000, API docs at /docs
```

The UI (`public/`) shows every song as a disc on a horizontal shelf (design nod to Ravi Klaassens'
A24 tribute site). Disc art is generated from each song's spec: key picks the inks, BPM and energy
shape the pattern. Click a disc to play it and see its spec, lyrics and downloads; `/#<id>` links
straight to one. Songs already in `output/` are loaded at startup.

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
