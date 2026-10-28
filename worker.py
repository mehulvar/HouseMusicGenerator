#!/usr/bin/env python3
"""Mac-side worker for the deployed site: claims queued songs from the Vercel API, generates them
locally (ACE-Step + your API keys), and uploads the results.

  python worker.py                     # run forever (launchd keeps this alive, see scripts/)
  python worker.py --publish-existing  # one-off: upload songs already in output/ to the site

Needs HOUSEGEN_API_URL and HOUSEGEN_WORKER_TOKEN in .env.
"""
import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # output/ and relative paths, even under launchd

import gen  # noqa: E402
from housegen import audio_acestep  # noqa: E402

API = os.environ.get("HOUSEGEN_API_URL", "").rstrip("/")
HEADERS = {"Authorization": f"Bearer {os.environ.get('HOUSEGEN_WORKER_TOKEN', '')}"}
PUBLISHED = "output/.published.json"  # local JSON paths already uploaded


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


def run_job(job: dict):
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
        log(f"job {jid}: done — {result['lyrics']['title']}")
    except Exception as e:
        traceback.print_exc()
        post(f"/worker/jobs/{jid}", json={"status": "failed", "error": f"{type(e).__name__}: {e}"})


def loop():
    log(f"worker up, polling {API}")
    while True:
        try:
            up = audio_acestep.available()
            r = post("/worker/claim", json={"acestep": up})
            if r.status_code == 200:
                run_job(r.json())
                continue  # check for the next one straight away
        except requests.RequestException as e:
            log(f"api unreachable: {e}")
        time.sleep(5)


def publish_existing():
    done = set(json.load(open(PUBLISHED))) if os.path.exists(PUBLISHED) else set()
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
    a = ap.parse_args()
    if not API or not os.environ.get("HOUSEGEN_WORKER_TOKEN"):
        raise SystemExit("Set HOUSEGEN_API_URL and HOUSEGEN_WORKER_TOKEN in .env")
    publish_existing() if a.publish_existing else loop()
