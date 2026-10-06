"""Browser smoke tests: the real pages in Chromium against the real server, no model calls."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(url + "/healthz", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        server.kill()
        raise RuntimeError("server did not start")
    yield url
    server.terminate()
    server.wait(timeout=10)


@pytest.fixture
def errors(page):
    """Console errors and uncaught exceptions; every test ends by asserting this is empty."""
    seen = []
    page.on("console", lambda m: seen.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: seen.append(str(e)))
    page.emulate_media(reduced_motion="reduce")  # the replay renders its held frame at once
    return seen
