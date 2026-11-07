#!/usr/bin/env python3
"""Mac-side worker for the deployed site: claims queued songs from the Vercel API, generates them
locally (ACE-Step + your API keys), and uploads the results.

  python worker.py                     # run forever (Start Studio.command)
  python worker.py --drain             # make every queued song, then exit (the Kaggle notebook uses drain())
  python worker.py --publish-existing  # one-off: upload songs already in output/ to the site

Needs HOUSEGEN_API_URL and HOUSEGEN_WORKER_TOKEN in .env.
"""
import argparse
import json
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import NamedTuple

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # output/ and relative paths, even under launchd

import gen  # noqa: E402
from housegen import audio_acestep  # noqa: E402

API = os.environ.get("HOUSEGEN_API_URL", "").rstrip("/")
HEADERS = {"Authorization": f"Bearer {os.environ.get('HOUSEGEN_WORKER_TOKEN', '')}"}
PUBLISHED = "output/.published.json"  # local JSON paths already uploaded
HEARTBEAT_EVERY_S = 30  # well inside the site's 90s "worker online" window
IDLE_POLL_S = 5


def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def post(path: str, **kw) -> requests.Response:
    r = requests.post(f"{API}{path}", headers=HEADERS, timeout=kw.pop("timeout", 30), **kw)
    r.raise_for_status()
    return r


def upload(local_path: str, job_id: str) -> str:
    ext = local_path.rsplit(".", 1)[-1]
    ctype = {"mp3": "audio/mpeg", "wav": "audio/wav", "mid": "audio/midi"}.get(ext, "application/octet-stream")
    with open(local_path, "rb") as f:
        return post("/worker/upload", params={"pathname": f"songs/{job_id}.{ext}", "content_type": ctype},
                    data=f.read(), timeout=300).json()["url"]


def cloud_result(result: dict, job_id: str) -> dict:
    """Swap local file paths for Blob URLs."""
    files = {k: upload(v, job_id) for k, v in result["files"].items() if k in ("audio", "midi") and os.path.exists(v)}
    return {**result, "files": files}


def run_job(job: dict) -> bool:
    """Make one queued song; True if it was made and uploaded."""
    jid, req = job["id"], job["request"]
    log(f"job {jid}: {req['prompt']!r}")

    def step(name: str):
        try:
            post(f"/worker/jobs/{jid}", json={"step": name})
        except requests.RequestException:
            pass  # progress is best-effort

    try:
        result = gen.run(req["prompt"], req.get("path"), req.get("theme"), on_step=step)
        step("uploading")
        post(f"/worker/jobs/{jid}", json={"status": "done", "result": cloud_result(result, jid)})
        mark_published(result["files"]["json"])  # it's on the site already; --publish-existing must skip it
        log(f"job {jid}: done — {result['lyrics']['title']}")
        return True
    except Exception as e:
        traceback.print_exc()
        post(f"/worker/jobs/{jid}", json={"status": "failed", "error": f"{type(e).__name__}: {e}"})
        return False


def claim_next() -> dict | None:
    r = post("/worker/claim", json={"acestep": audio_acestep.available()})
    return r.json() if r.status_code == 200 else None


class DrainResult(NamedTuple):
    made: int
    failed: int


def drain() -> DrainResult:
    """Make queued songs until the queue is empty."""
    made = failed = 0
    while job := claim_next():
        if run_job(job):
            made += 1
        else:
            failed += 1
    return DrainResult(made, failed)


class Heartbeat:
    """Checks in with the site in the background, so it knows a studio is busy (or booting) even
    during a long render; the cloud scheduler only starts a GPU when no studio is checking in."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                post("/worker/heartbeat", json={"acestep": audio_acestep.available()})
            except requests.RequestException as e:
                log(f"heartbeat failed: {e}")
            self._stop.wait(HEARTBEAT_EVERY_S)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


def loop():
    log(f"worker up, polling {API}")
    with Heartbeat():
        while True:
            try:
                drain()
            except requests.RequestException as e:
                log(f"api unreachable: {e}")
            time.sleep(IDLE_POLL_S)


def _published() -> set:
    return set(json.load(open(PUBLISHED))) if os.path.exists(PUBLISHED) else set()


def mark_published(json_path: str):
    done = _published() | {json_path}
    json.dump(sorted(done), open(PUBLISHED, "w"), indent=1)


def publish_existing():
    done = _published()
    import glob

    for path in sorted(glob.glob("output/*.json")):
        if path in done:
            continue
        result = json.load(open(path))
        files = result.get("files", {})
        audio = files.get("audio") or files.get("mp3")
        if not audio or not os.path.exists(audio):
            continue
        files["audio"] = audio
        key = os.path.basename(path).rsplit(".", 1)[0]
        created = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
        res = cloud_result({**result, "files": files}, key)
        post("/worker/publish", json={"result": res, "request": {"prompt": result.get("prompt")}, "created_at": created})
        done.add(path)
        json.dump(sorted(done), open(PUBLISHED, "w"), indent=1)
        log(f"published {result['lyrics']['title']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish-existing", action="store_true")
    ap.add_argument("--drain", action="store_true", help="make every queued song, then exit")
    a = ap.parse_args()
    if not API or not os.environ.get("HOUSEGEN_WORKER_TOKEN"):
        raise SystemExit("Set HOUSEGEN_API_URL and HOUSEGEN_WORKER_TOKEN in .env")
    if a.publish_existing:
        publish_existing()
    elif a.drain:
        with Heartbeat():
            result = drain()
            log(f"made {result.made} song(s), {result.failed} failed")
    else:
        loop()
