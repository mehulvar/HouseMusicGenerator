from types import SimpleNamespace

import requests

import kaggle_studio
from housegen import llm
from housegen.store import render_seconds


def fake_worker(batches):
    """worker stand-in whose drain() returns the given (made, failed) pairs, then empty forever."""
    from worker import DrainResult
    it = iter(batches)
    return SimpleNamespace(DrainResult=DrainResult, drain=lambda: DrainResult(*next(it, (0, 0))))


def test_drain_until_idle_picks_up_songs_that_arrive_late(monkeypatch):
    monkeypatch.setattr(kaggle_studio, "IDLE_GRACE_S", 0.3)
    monkeypatch.setattr(kaggle_studio, "IDLE_POLL_S", 0.05)
    result = kaggle_studio.drain_until_idle(fake_worker([(1, 0), (0, 0), (2, 1)]))
    assert (result.made, result.failed) == (3, 1)


def test_render_seconds():
    job = {"started_at": "2026-11-07T04:16:52+00:00", "finished_at": "2026-11-07T04:21:27+00:00"}
    assert render_seconds(job) == 275
    assert render_seconds({"finished_at": "2026-11-07T04:21:27+00:00"}) is None
    assert render_seconds({**job, "finished_at": "2026-11-07T04:00:00+00:00"}) is None


def response(status, headers=None):
    r = requests.Response()
    r.status_code, r.headers = status, requests.structures.CaseInsensitiveDict(headers or {})
    return r


def test_llm_retries_short_rate_limits_then_returns(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    calls, sleeps = [], []
    answers = iter([response(429, {"retry-after": "2"}), response(200)])
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: calls.append(1) or next(answers))
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    assert llm._post({}).status_code == 200
    assert len(calls) == 2 and sleeps == [2.0]


def test_llm_gives_up_on_long_rate_limits(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: response(429, {"retry-after": "600"}))
    monkeypatch.setattr(llm.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("should not wait")))
    assert llm._post({}).status_code == 429


def test_llm_retries_once_when_the_answer_is_cut_off(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    bad = response(400)
    bad._content = b'{"error":{"code":"json_validate_failed"}}'
    good = response(200, {"content-type": "application/json"})
    good._content = b'{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}'
    answers = iter([bad, good])
    monkeypatch.setattr(llm, "_post", lambda body: next(answers))
    assert llm.ask_json("s", "p") == {"ok": True}
