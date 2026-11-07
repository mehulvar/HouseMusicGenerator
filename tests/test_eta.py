from housegen import eta

NOW = 1_800_000_000.0


def iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def test_running_song_counts_down_from_typical_render_time():
    jobs = [{"id": "a", "status": "running", "created_at": iso(NOW - 200), "started_at": iso(NOW - 100)}]
    assert eta.estimates(jobs, NOW, song_s=300, boot_s=0) == {"a": 200}


def test_queued_songs_wait_for_the_running_one_and_each_other_in_order():
    jobs = [
        {"id": "late", "status": "queued", "created_at": iso(NOW - 10)},
        {"id": "run", "status": "running", "created_at": iso(NOW - 500), "started_at": iso(NOW - 60)},
        {"id": "early", "status": "queued", "created_at": iso(NOW - 50)},
    ]
    out = eta.estimates(jobs, NOW, song_s=300, boot_s=999)
    assert out == {"run": 240, "early": 540, "late": 840}  # no boot wait: a studio is already working


def test_studio_boot_is_added_when_nothing_is_running():
    jobs = [{"id": "q", "status": "queued", "created_at": iso(NOW)}]
    assert eta.estimates(jobs, NOW, song_s=300, boot_s=200) == {"q": 500}


def test_overrunning_song_never_shows_zero():
    jobs = [{"id": "slow", "status": "running", "created_at": iso(NOW - 900), "started_at": iso(NOW - 800)}]
    assert eta.estimates(jobs, NOW, song_s=300, boot_s=0) == {"slow": eta.MIN_LEFT_S}


def test_finished_songs_get_no_estimate():
    jobs = [{"id": "d", "status": "done", "created_at": iso(NOW)}, {"id": "f", "status": "failed", "created_at": iso(NOW)}]
    assert eta.estimates(jobs, NOW, song_s=300, boot_s=100) == {}


def test_typical_song_uses_median_of_recent_and_defaults_when_empty():
    assert eta.typical_song_s([]) == eta.DEFAULT_SONG_S
    assert eta.typical_song_s([100, 900, 200]) == 200
    assert eta.typical_song_s([0, -5]) == eta.DEFAULT_SONG_S


def test_boot_wait_depends_on_studio_state():
    assert eta.boot_wait_s(worker_online=True, studio_ready=True) == 0
    assert eta.boot_wait_s(worker_online=True, studio_ready=False, boot_s=200) == 100
    assert eta.boot_wait_s(worker_online=False, studio_ready=False, boot_s=200) == 200
