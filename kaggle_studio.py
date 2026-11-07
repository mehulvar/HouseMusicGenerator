"""Cloud studio on Kaggle's free GPU: installs ACE-Step, makes every queued song, then stops.

The Kaggle notebook (kaggle_worker.ipynb) only clones this repo and calls main(), so fixes land here
with a git push and the notebook on Kaggle never needs editing. Every step prints as it runs, has a
time limit, and never waits for input, so a stuck step shows up in the log instead of hanging silently.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
ACE_DIR = Path("/tmp/ace")
# Same ACE-Step commit as the Mac install, so the Take 4 sound carries over.
ACE_REPO = "https://github.com/ACE-Step/ACE-Step-1.5.git"
ACE_COMMIT = "ca1e85fe9430179831e6bc6be790c332190a3866"
ACE_PORT = 8001
ACE_BOOT_TIMEOUT_S = 25 * 60  # first boot downloads the models
ACE_LOG = Path("/tmp/acestep.log")
SAVED_LOG = Path("/kaggle/working/acestep.log")  # shows under the notebook's Output tab
LOG_TAIL_LINES = 80

REQUIRED_SECRETS = ("HOUSEGEN_API_URL", "HOUSEGEN_WORKER_TOKEN")
OPTIONAL_SECRETS = ("GROQ_API_KEY", "GROQ_MODEL", "SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "ELEVENLABS_API_KEY")

# Match the Mac studio: regular turbo DiT (not XL) and the 1.7B planner LM, thinking on.
ACE_SETTINGS = {
    "ACESTEP_CONFIG_PATH": "acestep-v15-turbo",
    "ACESTEP_LM_MODEL_PATH": "acestep-5Hz-lm-1.7B",
    "ACESTEP_LM_BACKEND": "pt",
    "ACESTEP_URL": f"http://127.0.0.1:{ACE_PORT}",
    "TOKENIZERS_PARALLELISM": "false",
    # float32 doubles the music model's size, so park models on the CPU while they aren't in use.
    "ACESTEP_OFFLOAD_TO_CPU": "true",
}
# Never let a tool stop to ask a question: there is nobody to answer in a background run.
NO_PROMPTS = {"DEBIAN_FRONTEND": "noninteractive", "GIT_TERMINAL_PROMPT": "0", "PIP_NO_INPUT": "1"}
# Jupyter sets MPLBACKEND to its inline backend, which ACE-Step's own venv can't load.
HEADLESS = {"MPLBACKEND": "Agg"}

# The T4 has no bfloat16, and ACE-Step's float16 fallback overflows to NaN there; use float32 instead.
DTYPE_PATCHES = (  # (file under ACE-Step's handler dir, float16 fallback, float32 replacement)
    ("init_service_orchestrator.py",
     "else:\n                    self.dtype = torch.float16\n",
     "else:\n                    self.dtype = torch.float32\n"),
    ("memory_utils.py",
     'return torch.bfloat16\n            return torch.float16\n        if target_device == "xpu":',
     'return torch.bfloat16\n            return torch.float32\n        if target_device == "xpu":'),
)
HANDLER_SUBDIR = Path("acestep/core/generation/handler")

MINUTE = 60


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_step(name: str, cmd: list[str], timeout_s: int, cwd: Path | None = None) -> None:
    """Run a command, streaming its output; fail loudly on error or when it runs past timeout_s."""
    say(f"{name}...")
    started = time.time()
    proc = subprocess.Popen(
        cmd, cwd=cwd, env={**os.environ, **NO_PROMPTS}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    watchdog = threading.Timer(timeout_s, proc.kill)  # also stops a step that hangs without printing
    watchdog.start()
    try:
        for line in proc.stdout:
            print(f"    {line}", end="", flush=True)
        code = proc.wait()
    finally:
        watchdog.cancel()
    elapsed = time.time() - started
    if elapsed >= timeout_s:
        raise TimeoutError(f"{name} took longer than {timeout_s // MINUTE} min and was stopped")
    if code != 0:
        raise RuntimeError(f"{name} failed (exit code {code})")
    say(f"{name} done in {elapsed:.0f}s")


def load_secrets() -> None:
    from kaggle_secrets import UserSecretsClient  # only exists on Kaggle

    client = UserSecretsClient()

    def load(name: str) -> bool:
        try:
            os.environ[name] = client.get_secret(name)
            return True
        except Exception:  # Kaggle raises a generic error for a missing or unticked secret
            return False

    missing = [name for name in REQUIRED_SECRETS if not load(name)]
    if missing:
        raise RuntimeError(f"Add these Kaggle secrets (Add-ons -> Secrets) and tick them for this notebook: {missing}")
    loaded = [name for name in OPTIONAL_SECRETS if load(name)]
    say(f"secrets ok; optional loaded: {loaded or 'none'}")
    if "GROQ_API_KEY" not in loaded:
        say("warning: no GROQ_API_KEY, so lyric themes fall back to a public-domain poem")


def check_gpu() -> None:
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                         capture_output=True, text=True, timeout=MINUTE)
    if gpu.returncode != 0:
        raise RuntimeError("No GPU: Settings -> Accelerator -> GPU T4 x2")
    say(f"GPU: {', '.join(gpu.stdout.split())}")
    if "P100" in gpu.stdout:
        raise RuntimeError("ACE-Step's PyTorch build doesn't support the P100; switch to GPU T4 x2")


def patch_dtypes(ace_dir: Path) -> None:
    for name, old, new in DTYPE_PATCHES:
        path = ace_dir / HANDLER_SUBDIR / name
        src = path.read_text()
        if src.count(old) != 1:
            raise RuntimeError(f"ACE-Step dtype patch target not found in {name}; the pinned commit changed")
        path.write_text(src.replace(old, new))
    say("patched ACE-Step: float32 on pre-Ampere GPUs")


def install() -> None:
    shutil.rmtree(ACE_DIR, ignore_errors=True)
    run_step("clone ACE-Step", ["git", "clone", "--quiet", ACE_REPO, str(ACE_DIR)], 10 * MINUTE)
    run_step("check out pinned commit", ["git", "-C", str(ACE_DIR), "checkout", "--quiet", ACE_COMMIT], MINUTE)
    patch_dtypes(ACE_DIR)
    run_step("install uv", [sys.executable, "-m", "pip", "install", "-q", "uv"], 5 * MINUTE)
    run_step("install ACE-Step (uv sync)",
             [sys.executable, "-m", "uv", "sync", "--frozen", "--no-dev", "--python", "3.11"], 25 * MINUTE, cwd=ACE_DIR)
    run_step("install housegen requirements",
             [sys.executable, "-m", "pip", "install", "-q", "-r", str(REPO_DIR / "requirements.txt")], 10 * MINUTE)
    if shutil.which("ffmpeg") is None:
        run_step("apt-get update", ["apt-get", "update", "-qq"], 5 * MINUTE)
        run_step("install ffmpeg", ["apt-get", "install", "-y", "-qq", "ffmpeg"], 10 * MINUTE)


def log_tail() -> str:
    lines = ACE_LOG.read_text(errors="replace").splitlines() if ACE_LOG.exists() else []
    return "\n".join(lines[-LOG_TAIL_LINES:])


def wait_for_acestep(server: subprocess.Popen, is_up) -> None:
    deadline = time.time() + ACE_BOOT_TIMEOUT_S
    while not is_up():
        if server.poll() is not None:
            print(log_tail())
            raise RuntimeError(f"ACE-Step exited during startup (code {server.returncode})")
        if time.time() > deadline:
            print(log_tail())
            raise TimeoutError(f"ACE-Step not healthy after {ACE_BOOT_TIMEOUT_S // MINUTE} min")
        time.sleep(5)
    say("ACE-Step is up")


def make_songs() -> None:
    os.environ.update(ACE_SETTINGS)  # before importing worker/housegen, which read them
    sys.path.insert(0, str(REPO_DIR))
    import worker
    from housegen import audio_acestep

    with worker.Heartbeat(), ACE_LOG.open("w") as ace_log:  # site shows a studio online while this runs
        say("starting ACE-Step (first boot downloads the models)")
        server = subprocess.Popen(
            [str(ACE_DIR / ".venv/bin/acestep-api"), "--host", "127.0.0.1", "--port", str(ACE_PORT)],
            cwd=ACE_DIR, stdout=ace_log, stderr=subprocess.STDOUT, env={**os.environ, **HEADLESS},
        )
        try:
            wait_for_acestep(server, audio_acestep.available)
            result = worker.drain()
            say(f"made {result.made} song(s), {result.failed} failed")
        finally:
            server.terminate()
            server.wait(timeout=MINUTE)
            if SAVED_LOG.parent.exists():
                shutil.copy(ACE_LOG, SAVED_LOG)

    if result.failed:
        print(log_tail())
        raise RuntimeError(f"{result.failed} song(s) failed; full ACE-Step log saved to {SAVED_LOG}")


def main() -> None:
    load_secrets()
    check_gpu()
    install()
    make_songs()


if __name__ == "__main__":
    main()
