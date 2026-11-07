"""Starts the Kaggle cloud studio when songs are waiting and no studio is working on them.

Called by the API when a song is queued (and again while visitors' pages poll a queued song, so a
missed start heals itself). Pushing the launcher notebook through Kaggle's API saves a new version
of it and runs it on a T4, the same as clicking Save Version -> Save & Run All.

Env: KAGGLE_NOTEBOOK ("username/notebook-slug") plus either KAGGLE_API_TOKEN (new-style token) or
KAGGLE_USERNAME + KAGGLE_KEY (legacy kaggle.json key).
"""
import json
import os
from pathlib import Path

import requests

API = "https://api.kaggle.com/v1/kernels.KernelsApiService"
NOTEBOOK_FILE = Path(__file__).resolve().parent.parent / "kaggle_worker.ipynb"
TIMEOUT_S = 15
CHECK_COOLDOWN_S = 45  # between Kaggle status checks while a run is booting or finishing
BOOT_GRACE_S = 10 * 60  # after a push, wait this long for the run to check in before trying again
ACTIVE_STATUSES = ("queued", "running", "new_script", "cancel_requested")
LOCK_KEY = "kaggle:trigger"
STARTED_KEY = "kaggle:started"


class KaggleError(Exception):
    pass


def configured() -> bool:
    has_key = os.getenv("KAGGLE_API_TOKEN") or (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
    return bool(os.getenv("KAGGLE_NOTEBOOK") and has_key)


def _notebook_ref() -> tuple[str, str]:
    owner, _, slug = os.environ["KAGGLE_NOTEBOOK"].strip().partition("/")
    if not owner or not slug:
        raise KaggleError('KAGGLE_NOTEBOOK must look like "username/notebook-slug"')
    return owner, slug


def _call(method: str, body: dict) -> dict:
    token = os.getenv("KAGGLE_API_TOKEN")
    auth = None if token else (os.environ["KAGGLE_USERNAME"], os.environ["KAGGLE_KEY"])
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.post(f"{API}/{method}", json=body, headers=headers, auth=auth, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise KaggleError(f"{method}: {e}") from e
    data = resp.json() if "application/json" in resp.headers.get("content-type", "") else {}
    if not resp.ok or (isinstance(data.get("code"), int) and data["code"] >= 400):
        nested = data.get("error") if isinstance(data.get("error"), dict) else {}
        message = data.get("message") or nested.get("message") or resp.text[:200]
        raise KaggleError(f"{method}: HTTP {resp.status_code} {message}")
    return data


def normalize_status(raw: str | None) -> str:
    """Kaggle reports e.g. "RUNNING" or "KERNEL_WORKER_STATUS_RUNNING"; reduce it to "running"."""
    status = str(raw or "").lower()
    for known in ("cancel_acknowledged", "cancel_requested", "new_script", "queued", "running", "complete", "error"):
        if status.endswith(known):
            return known
    return status


def session_status() -> str:
    owner, slug = _notebook_ref()
    return normalize_status(_call("GetKernelSessionStatus", {"userName": owner, "kernelSlug": slug}).get("status"))


def notebook_text(path: Path = NOTEBOOK_FILE) -> str:
    """The launcher notebook as Kaggle's push expects it: outputs cleared, each cell's source one string."""
    nb = json.loads(path.read_text())
    cells = [{**c, "source": "".join(c["source"]) if isinstance(c.get("source"), list) else c.get("source", ""),
              **({"outputs": []} if c.get("cell_type") == "code" else {})} for c in nb["cells"]]
    return json.dumps({**nb, "cells": cells})


def push_and_run() -> dict:
    owner, slug = _notebook_ref()
    data = _call("SaveKernel", {
        "slug": f"{owner}/{slug}",
        "text": notebook_text(),
        "language": "python",
        "kernelType": "notebook",
        "isPrivate": True,
        "enableGpu": True,
        "enableInternet": True,
        "machineShape": "NvidiaTeslaT4",
    })
    if data.get("error"):
        raise KaggleError(f"SaveKernel: {data['error']}")
    return data


def maybe_start(store) -> str:
    """Start a Kaggle run if songs wait and no studio is up. Returns what happened, for logs."""
    if not configured():
        return "kaggle not configured"
    health = store.health()
    if not health.get("queued"):
        return "queue empty"
    if health.get("worker"):
        return "studio online"
    if not store.acquire(LOCK_KEY, CHECK_COOLDOWN_S):
        return "checked recently"
    try:
        status = session_status()
        if status in ACTIVE_STATUSES:
            return f"kaggle run already {status}"
        push_and_run()
    except KaggleError as e:
        print(f"[kaggle] couldn't start the studio: {e}")
        return f"error: {e}"
    store.hold(LOCK_KEY, BOOT_GRACE_S)  # give the new run time to boot and check in
    store.hold(STARTED_KEY, BOOT_GRACE_S)
    print("[kaggle] started the cloud studio")
    return "started"
