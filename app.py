"""FastAPI wrapper around gen.run. Run with: .venv/bin/uvicorn app:app --reload

Generation takes a minute or more, so it's a job API:
  POST /songs                 -> 202 {id, status}
  GET  /songs/{id}            -> status, current step, and result (spec, lyrics, links) when done
  GET  /songs/{id}/audio      -> the audio file
  GET  /songs/{id}/midi       -> MIDI (path B only)
  GET  /songs                 -> all jobs, newest first
  GET  /                      -> the web UI (static/)

Jobs live in memory, but finished songs in output/ are reloaded at startup.
"""
import glob
import hashlib
import json
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import gen
from housegen import audio_acestep, audio_eleven

app = FastAPI(title="House Music Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")

# One worker: ACE-Step processes one song at a time anyway, and the procedural synth is CPU-heavy.
_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _load_existing(out_dir: str = "output"):
    """Rebuild finished jobs from the JSON files gen.run leaves next to each song."""
    for path in glob.glob(os.path.join(out_dir, "*.json")):
        try:
            with open(path) as f:
                result = json.load(f)
            files = result.get("files", {})
            audio = files.get("audio") or files.get("mp3")  # older runs used an "mp3" key
            if not audio or not os.path.exists(audio):
                continue
            files["audio"] = audio
            job_id = hashlib.sha1(path.encode()).hexdigest()[:12]
            created = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
            _jobs[job_id] = {
                "id": job_id, "status": "done", "step": None, "request": {"prompt": result.get("prompt")},
                "created_at": created, "finished_at": created, "result": result,
            }
        except (OSError, ValueError, KeyError):
            continue


_load_existing()


class SongRequest(BaseModel):
    prompt: str = Field(..., min_length=1, examples=["make a song like calvin harris's Summer"])
    path: Literal["A", "B", "C"] | None = Field(
        None, description="A=ElevenLabs, B=procedural, C=local ACE-Step. Default picks the best available."
    )
    theme: str | None = Field(None, description="Lyric theme (default: one invented to suit the reference's mood)")


def _update(job_id: str, **fields):
    with _lock:
        _jobs[job_id].update(fields)


def _work(job_id: str, req: SongRequest):
    _update(job_id, status="running")
    try:
        result = gen.run(req.prompt, req.path, req.theme, on_step=lambda s: _update(job_id, step=s))
        _update(job_id, status="done", step=None, result=result, finished_at=_now())
    except Exception as e:
        traceback.print_exc()
        _update(job_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=_now())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _view(job: dict) -> dict:
    out = {k: v for k, v in job.items() if k != "result"}
    r = job.get("result")
    if r:
        out["result"] = {
            "title": r["lyrics"]["title"],
            "audio_path": r["audio_path"],
            "spec": r["spec"],
            "lyrics": {k: r["lyrics"].get(k) for k in ("title", "hook", "verse", "inspiration")},
            "reference": r["reference"],
            "links": {
                "audio": f"/songs/{job['id']}/audio",
                **({"midi": f"/songs/{job['id']}/midi"} if "midi" in r["files"] else {}),
            },
        }
    return out


def _get(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "No such song")
        return dict(job)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"ok": True, "acestep": audio_acestep.available(), "elevenlabs": audio_eleven.available()}


@app.post("/songs", status_code=202)
def create_song(req: SongRequest):
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"id": job_id, "status": "queued", "step": None, "request": req.model_dump(), "created_at": _now()}
    _executor.submit(_work, job_id, req)
    return {"id": job_id, "status": "queued", "url": f"/songs/{job_id}"}


@app.get("/songs")
def list_songs():
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
        return [_view(j) for j in jobs]


@app.get("/songs/{job_id}")
def get_song(job_id: str):
    return _view(_get(job_id))


def _file(job_id: str, kind: str) -> FileResponse:
    job = _get(job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"Song is {job['status']}")
    path = job["result"]["files"].get(kind)
    if not path:
        raise HTTPException(404, f"No {kind} for this song")
    return FileResponse(path, filename=path.rsplit("/", 1)[-1])


@app.get("/songs/{job_id}/audio")
def get_audio(job_id: str):
    return _file(job_id, "audio")


@app.get("/songs/{job_id}/midi")
def get_midi(job_id: str):
    return _file(job_id, "midi")
