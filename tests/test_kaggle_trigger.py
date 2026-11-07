import json

import pytest

from housegen import kaggle_trigger as kt


class FakeStore:
    def __init__(self, queued=1, worker=False):
        self._health = {"queued": queued, "worker": worker}
        self.keys: dict[str, int] = {}

    def health(self):
        return self._health

    def acquire(self, key, ttl):
        if key in self.keys:
            return False
        self.keys[key] = ttl
        return True

    def hold(self, key, ttl):
        self.keys[key] = ttl


@pytest.fixture
def kaggle_env(monkeypatch):
    monkeypatch.setenv("KAGGLE_NOTEBOOK", "someone/studio")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "test-token")
    pushes = []
    monkeypatch.setattr(kt, "push_and_run", lambda: pushes.append(1) or {})
    monkeypatch.setattr(kt, "session_status", lambda: "complete")
    return pushes


def test_starts_kaggle_when_songs_wait_and_no_studio(kaggle_env):
    store = FakeStore()
    assert kt.maybe_start(store) == "started"
    assert kaggle_env == [1]
    assert store.keys == {kt.LOCK_KEY: kt.BOOT_GRACE_S, kt.STARTED_KEY: kt.BOOT_GRACE_S}


def test_second_request_inside_the_lock_does_not_start_again(kaggle_env):
    store = FakeStore()
    kt.maybe_start(store)
    assert kt.maybe_start(store) == "checked recently"
    assert kaggle_env == [1]


@pytest.mark.parametrize("store,reason", [(FakeStore(queued=0), "queue empty"), (FakeStore(worker=True), "studio online")])
def test_does_nothing_without_waiting_songs_or_with_a_studio_up(kaggle_env, store, reason):
    assert kt.maybe_start(store) == reason
    assert kaggle_env == []


def test_leaves_an_active_kaggle_run_alone(kaggle_env, monkeypatch):
    monkeypatch.setattr(kt, "session_status", lambda: "running")
    store = FakeStore()
    assert kt.maybe_start(store) == "kaggle run already running"
    assert kaggle_env == [] and store.keys == {kt.LOCK_KEY: kt.CHECK_COOLDOWN_S}


def test_kaggle_errors_are_reported_not_raised(kaggle_env, monkeypatch):
    def boom():
        raise kt.KaggleError("HTTP 401 Unauthenticated")
    monkeypatch.setattr(kt, "session_status", boom)
    assert kt.maybe_start(FakeStore()).startswith("error: HTTP 401")


def test_unconfigured_is_a_no_op(monkeypatch):
    for var in ("KAGGLE_NOTEBOOK", "KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert kt.maybe_start(FakeStore()) == "kaggle not configured"


@pytest.mark.parametrize("raw,expected", [("RUNNING", "running"), ("KERNEL_WORKER_STATUS_QUEUED", "queued"),
                                          ("complete", "complete"), ("CANCEL_ACKNOWLEDGED", "cancel_acknowledged"),
                                          (None, "")])
def test_normalize_status(raw, expected):
    assert kt.normalize_status(raw) == expected


def test_notebook_text_is_the_launcher_with_string_sources():
    nb = json.loads(kt.notebook_text())
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code) == 1 and isinstance(code[0]["source"], str)
    assert "kaggle_studio.main()" in code[0]["source"] and code[0]["outputs"] == []


def test_bad_notebook_ref_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("KAGGLE_NOTEBOOK", "no-slash")
    with pytest.raises(kt.KaggleError, match="username/notebook-slug"):
        kt._notebook_ref()
