"""Estimated seconds until each pressing song is done, for the countdown on its disc.

Songs are made one at a time, oldest first. A queued song waits for the song in progress, every song
ahead of it, and (if no studio is ready) for a studio to boot.
"""
from datetime import datetime
from statistics import median

DEFAULT_SONG_S = 300  # a Kaggle T4 render, measured at ~4.5 min
DEFAULT_BOOT_S = 210  # Kaggle start + install + ACE-Step boot, measured at ~2 min plus queueing
MIN_LEFT_S = 15  # never promise "0:00" while a song is still pressing
BOOTING_FRACTION = 0.5  # a studio that's checking in but not ready is roughly halfway booted
RECENT_SONGS = 20


def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def typical_song_s(durations: list[float]) -> float:
    """Median of recent render times; robust to the odd slow first run."""
    recent = [d for d in durations[:RECENT_SONGS] if d > 0]
    return median(recent) if recent else DEFAULT_SONG_S


def boot_wait_s(worker_online: bool, studio_ready: bool, boot_s: float = DEFAULT_BOOT_S) -> float:
    if studio_ready:
        return 0.0
    return boot_s * BOOTING_FRACTION if worker_online else boot_s


def estimates(jobs: list[dict], now: float, song_s: float, boot_s: float) -> dict[str, int]:
    """{job id: seconds left} for every queued or running job."""
    running = sorted((j for j in jobs if j.get("status") == "running"), key=lambda j: j.get("started_at") or "")
    queued = sorted((j for j in jobs if j.get("status") == "queued"), key=lambda j: j["created_at"])
    out: dict[str, int] = {}
    ahead = 0.0
    for job in running:
        started = _ts(job.get("started_at")) or _ts(job.get("updated_at")) or now
        left = max(MIN_LEFT_S, song_s - (now - started))
        out[job["id"]] = round(left)
        ahead += left
    ahead += 0 if running else boot_s
    for job in queued:
        ahead += song_s
        out[job["id"]] = round(max(MIN_LEFT_S, ahead))
    return out
