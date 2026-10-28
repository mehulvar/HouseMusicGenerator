"""Job storage for the API.

LocalStore: jobs in memory, generation runs in-process, files in output/ (your Mac).
CloudStore: jobs in Upstash Redis, audio in Vercel Blob; generation is done by worker.py on your Mac,
which claims queued jobs through the /worker endpoints.
"""
import glob
import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job(request: dict) -> dict:
    return {"id": uuid.uuid4().hex[:12], "status": "queued", "step": None, "request": request,
            "created_at": now(), "updated_at": now()}


class LocalStore:
    mode = "local"

    def __init__(self, out_dir: str = "output"):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        # One worker: ACE-Step processes one song at a time anyway, and the procedural synth is CPU-heavy.
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._load_existing(out_dir)

    def _load_existing(self, out_dir: str):
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
                self._jobs[job_id] = {
                    "id": job_id, "status": "done", "step": None, "request": {"prompt": result.get("prompt")},
                    "created_at": created, "finished_at": created, "result": result,
                }
            except (OSError, ValueError, KeyError):
                continue

    def _update(self, job_id: str, **fields):
        with self._lock:
            self._jobs[job_id].update(fields, updated_at=now())

    def _work(self, job_id: str, req: dict):
        import gen  # heavy imports only where generation actually runs

        self._update(job_id, status="running")
        try:
            result = gen.run(req["prompt"], req.get("path"), req.get("theme"),
                             on_step=lambda s: self._update(job_id, step=s))
            self._update(job_id, status="done", step=None, result=result, finished_at=now())
        except Exception as e:
            traceback.print_exc()
            self._update(job_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=now())

    def create(self, request: dict, client_ip: str) -> dict:
        job = new_job(request)
        with self._lock:
            self._jobs[job["id"]] = job
        self._executor.submit(self._work, job["id"], request)
        return job

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["created_at"], reverse=True)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def health(self) -> dict:
        from housegen import audio_acestep, audio_eleven

        return {"mode": self.mode, "acestep": audio_acestep.available(), "elevenlabs": audio_eleven.available()}


class RateLimited(Exception):
    pass


class CloudStore:
    mode = "cloud"
    HEARTBEAT_S = 90  # worker counts as online if it checked in this recently
    STALE_S = 20 * 60  # a "running" job with no update this long is put back in the queue

    def __init__(self):
        from upstash_redis import Redis

        url = os.getenv("KV_REST_API_URL") or os.environ["UPSTASH_REDIS_REST_URL"]
        token = os.getenv("KV_REST_API_TOKEN") or os.environ["UPSTASH_REDIS_REST_TOKEN"]
        self.r = Redis(url=url, token=token)
        self.daily_limit = int(os.getenv("DAILY_SONG_LIMIT", "3"))

    @staticmethod
    def available() -> bool:
        return bool(os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL"))

    # ---- jobs ----
    def _save(self, job: dict):
        job["updated_at"] = now()
        self.r.set(f"song:{job['id']}", json.dumps(job))

    def get(self, job_id: str) -> dict | None:
        raw = self.r.get(f"song:{job_id}")
        return json.loads(raw) if raw else None

    def list(self, limit: int = 200) -> list[dict]:
        ids = self.r.zrange("songs", 0, limit - 1, rev=True)
        if not ids:
            return []
        return [json.loads(raw) for raw in self.r.mget(*[f"song:{i}" for i in ids]) if raw]

    def _add(self, job: dict):
        self._save(job)
        self.r.zadd("songs", {job["id"]: datetime.fromisoformat(job["created_at"]).timestamp()})

    def create(self, request: dict, client_ip: str) -> dict:
        key = f"rl:{client_ip}:{datetime.now(timezone.utc):%Y-%m-%d}"
        count = self.r.incr(key)
        if count == 1:
            self.r.expire(key, 86400)
        if count > self.daily_limit:
            raise RateLimited(f"Daily limit of {self.daily_limit} songs reached — try again tomorrow.")
        job = new_job(request)
        self._add(job)
        self.r.lpush("queue", job["id"])
        return job

    # ---- worker side ----
    def heartbeat(self, info: dict):
        self.r.set("worker:heartbeat", json.dumps({**info, "at": time.time()}), ex=self.HEARTBEAT_S)

    def health(self) -> dict:
        raw = self.r.get("worker:heartbeat")
        hb = json.loads(raw) if raw else None
        return {"mode": self.mode, "worker": bool(hb), "acestep": bool(hb and hb.get("acestep")),
                "queued": self.r.llen("queue")}

    def claim(self) -> dict | None:
        self._requeue_stale()
        job_id = self.r.rpop("queue")
        if not job_id:
            return None
        job = self.get(job_id)
        if not job or job["status"] != "queued":
            return None
        job.update(status="running", step="starting")
        self._save(job)
        self.r.sadd("running", job_id)
        return job

    def _requeue_stale(self):
        for job_id in self.r.smembers("running") or []:
            job = self.get(job_id)
            if not job or job["status"] != "running":
                self.r.srem("running", job_id)
                continue
            age = time.time() - datetime.fromisoformat(job["updated_at"]).timestamp()
            if age > self.STALE_S:
                job.update(status="queued", step=None)
                self._save(job)
                self.r.srem("running", job_id)
                self.r.rpush("queue", job_id)  # front of the line

    def update(self, job_id: str, fields: dict) -> dict | None:
        job = self.get(job_id)
        if not job:
            return None
        job.update(fields)
        if fields.get("status") in ("done", "failed"):
            job.setdefault("finished_at", now())
            job["step"] = None
            self.r.srem("running", job_id)
        self._save(job)
        return job

    def publish(self, result: dict, created_at: str | None, request: dict) -> dict:
        """Add an already-finished song (used to backfill songs made locally)."""
        job = new_job(request)
        job.update(status="done", result=result, finished_at=created_at or now())
        if created_at:
            job["created_at"] = created_at
        self._add(job)
        return job


# ---- Vercel Blob (REST protocol used by the official @vercel/blob client) ----
def blob_put(pathname: str, data: bytes, content_type: str) -> str:
    r = requests.put(
        "https://vercel.com/api/blob/",
        params={"pathname": pathname},
        data=data,
        headers={
            "authorization": f"Bearer {os.environ['BLOB_READ_WRITE_TOKEN']}",
            "x-api-version": "13",
            "x-vercel-blob-access": "public",
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["url"]


def get_store():
    return CloudStore() if CloudStore.available() else LocalStore()
