"""FastAPI app: web UI + job API. Locally: .venv/bin/uvicorn app:app --reload. On Vercel: deployed as-is.

Generation takes a minute or more, so it's a job API:
  POST /songs                 -> 202 {id, status}
  GET  /songs/{id}            -> status, current step, and result (spec, lyrics, links) when done
  GET  /songs/{id}/audio      -> the audio file (local) or a redirect to it (cloud)
  GET  /songs/{id}/midi       -> MIDI (path B only)
  GET  /songs                 -> all jobs, newest first
  GET  /                      -> the web UI (public/)

Storage mode is picked from the environment (see housegen/store.py): with Upstash Redis configured
(on Vercel) jobs are queued for worker.py on your Mac; otherwise everything runs in this process.
Worker endpoints (/worker/*) need `Authorization: Bearer $WORKER_TOKEN`.
"""
import os
import secrets
import time
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from housegen import eta, kaggle_trigger
from housegen.store import RateLimited, blob_put, get_store

app = FastAPI(title="House Music Generator")
store = get_store()

if store.mode == "local":
    # On Vercel, public/ is served by the CDN; locally FastAPI serves it.
    app.mount("/static", StaticFiles(directory="public/static"), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse("public/index.html")


class SongRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=300, examples=["make a song like calvin harris's Summer"])
    path: Literal["A", "B", "C"] | None = Field(
        None, description="A=ElevenLabs, B=procedural, C=local ACE-Step. Default picks the best available."
    )
    theme: str | None = Field(None, max_length=300, description="Lyric theme (default: one invented to suit the reference's mood)")


def _link(job: dict, kind: str, files: dict) -> str:
    target = files.get(kind)
    return target if str(target).startswith("http") else f"/songs/{job['id']}/{kind}"


def _view(job: dict, etas: dict | None = None) -> dict:
    out = {k: v for k, v in job.items() if k != "result"}
    if etas and job["id"] in etas:
        out["eta_s"] = etas[job["id"]]
    r = job.get("result")
    if r:
        files = r.get("files", {})
        out["result"] = {
            "title": r["lyrics"]["title"],
            "audio_path": r["audio_path"],
            "spec": r["spec"],
            "lyrics": {k: r["lyrics"].get(k) for k in ("title", "hook", "verse", "inspiration", "concept", "vocals")}
            | {"sections": [{k: s.get(k) for k in ("name", "voice", "delivery")}
                            | {"lines": [line["text"] for line in s.get("lines", [])]}
                            for s in r["lyrics"].get("sections", []) if "name" in s]},
            "reference": r["reference"],
            "links": {
                "audio": _link(job, "audio", files),
                **({"midi": _link(job, "midi", files)} if "midi" in files else {}),
            },
        }
    return out


def _get(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "No such song")
    return job


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@app.get("/health")
def health():
    return {"ok": True, **store.health()}


def _etas(jobs: list[dict]) -> dict[str, int]:
    """Countdown seconds for pressing songs; {} if nothing is pressing."""
    if not any(j["status"] in ("queued", "running") for j in jobs):
        return {}
    h = store.health()
    boot = eta.boot_wait_s(bool(h.get("worker")), bool(h.get("acestep")))
    return eta.estimates(jobs, time.time(), eta.typical_song_s(store.song_durations()), boot)


def _start_studio_if_needed(jobs: list[dict] | None = None):
    """Cloud mode: start the Kaggle studio for waiting songs. Never lets a Kaggle hiccup break the API."""
    if store.mode != "cloud" or (jobs is not None and not any(j["status"] == "queued" for j in jobs)):
        return
    try:
        result = kaggle_trigger.maybe_start(store)
        if result.startswith(("started", "error")):
            print(f"[studio] {result}")
    except Exception as e:  # noqa: BLE001 - the site must keep working whatever Kaggle does
        print(f"[studio] start check failed: {type(e).__name__}: {e}")


@app.post("/songs", status_code=202)
def create_song(req: SongRequest, request: Request):
    try:
        job = store.create(req.model_dump(), _client_ip(request))
    except RateLimited as e:
        raise HTTPException(429, str(e))
    _start_studio_if_needed()
    return {"id": job["id"], "status": job["status"], "url": f"/songs/{job['id']}"}


@app.get("/songs")
def list_songs():
    jobs = store.list()
    _start_studio_if_needed(jobs)  # heals a missed start while visitors watch a queued disc
    etas = _etas(jobs)
    return [_view(j, etas) for j in jobs]


@app.get("/songs/{job_id}")
def get_song(job_id: str):
    job = _get(job_id)
    return _view(job, _etas(store.list()) if job["status"] in ("queued", "running") else None)


def _file(job_id: str, kind: str):
    job = _get(job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"Song is {job['status']}")
    target = job["result"].get("files", {}).get(kind)
    if not target:
        raise HTTPException(404, f"No {kind} for this song")
    if str(target).startswith("http"):
        return RedirectResponse(target)
    return FileResponse(target, filename=target.rsplit("/", 1)[-1])


@app.get("/songs/{job_id}/audio")
def get_audio(job_id: str):
    return _file(job_id, "audio")


@app.get("/songs/{job_id}/midi")
def get_midi(job_id: str):
    return _file(job_id, "midi")


# ---------- worker API (cloud mode only) ----------
def _worker_auth(authorization: str = Header("")):
    expected = os.getenv("WORKER_TOKEN")
    if store.mode != "cloud" or not expected:
        raise HTTPException(404)
    if not secrets.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(401, "Bad worker token")


class Heartbeat(BaseModel):
    acestep: bool = False


class JobUpdate(BaseModel):
    status: Literal["running", "done", "failed"] | None = None
    step: str | None = None
    error: str | None = None
    result: dict | None = None


class Publish(BaseModel):
    result: dict
    request: dict
    created_at: str | None = None


@app.post("/worker/heartbeat", dependencies=[Depends(_worker_auth)])
def worker_heartbeat(hb: Heartbeat):
    store.heartbeat(hb.model_dump())
    return {"ok": True}


@app.post("/worker/claim", dependencies=[Depends(_worker_auth)])
def worker_claim(hb: Heartbeat):
    store.heartbeat(hb.model_dump())
    job = store.claim() if hb.acestep else None  # without ACE-Step there'd be no vocals; leave jobs queued
    return job or Response(status_code=204)


@app.post("/worker/jobs/{job_id}", dependencies=[Depends(_worker_auth)])
def worker_update(job_id: str, upd: JobUpdate):
    job = store.update(job_id, upd.model_dump(exclude_none=True))
    if not job:
        raise HTTPException(404, "No such song")
    return {"ok": True}


@app.post("/worker/upload", dependencies=[Depends(_worker_auth)])
async def worker_upload(request: Request, pathname: str, content_type: str = "audio/mpeg"):
    return {"url": blob_put(pathname, await request.body(), content_type)}


@app.post("/worker/publish", dependencies=[Depends(_worker_auth)])
def worker_publish(p: Publish):
    job = store.publish(p.result, p.created_at, p.request)
    return {"id": job["id"]}
