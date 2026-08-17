"""Keeps the chat model resident in VRAM so the first message after a quiet
spell doesn't pay a cold load.

Ollama evicts an idle model after ~5 minutes. On the lab host that reload
measured 11.4s against 2.9s warm -- not a hang, but a wholly avoidable wait
that always lands on a user rather than on a background task.

Why a separate poller rather than a flag on the chat client: the app talks to
Ollama through its **OpenAI-compatible** endpoint (`LLM_BASE_URL` ends in
/v1), and that endpoint silently drops `keep_alive`. Confirmed empirically,
not assumed -- POSTing /v1/chat/completions with `keep_alive: "10m"` left
`ollama ps` reporting the default ~5 minute TTL, so passing it through
ChatOpenAI's `extra_body` (graph.py's `{"think": False}`) would have looked
like a fix and done nothing. Only Ollama's native /api/generate honours it,
hence a direct call here.

The request carries no prompt, which makes it a pure load/refresh: Ollama
returns immediately without generating a single token, so this costs nothing
per tick beyond the round trip and never occupies the model against a real
chat turn.

Runs on its own daemon thread, modelled on JobWatcher in job_watcher.py.
Nothing here is allowed to be load-bearing: Ollama being down, slow, or
missing the model must not stop the backend from starting or serving, since
every one of those is survivable (the user gets a cold load, or an error on
their own request, which is strictly better than a backend that won't boot).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import requests

from app.config import LLM_MODEL, MODEL_KEEPALIVE_INTERVAL, OLLAMA_HOST

_log = logging.getLogger("uvicorn.error")

# Long enough to cover an actual cold load of a 17 GB model (11.4s measured,
# and a busy or shared host can be slower) without wedging the thread if
# Ollama stops answering entirely.
_REQUEST_TIMEOUT = 120


class ModelWarmer:
    def __init__(self, interval: float = MODEL_KEEPALIVE_INTERVAL, model: str = LLM_MODEL):
        self._interval = interval
        self._model = model
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Failures are logged once per outage rather than every tick -- at a
        # 60s interval an overnight Ollama restart would otherwise write
        # hundreds of identical lines into the log someone later has to read
        # a real error out of.
        self._failing = False

    def start(self) -> None:
        if self._thread is not None:
            return
        if self._interval <= 0:
            _log.info("model keep-warm disabled (QC_AGENT_MODEL_KEEPALIVE_INTERVAL=0)")
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="model-warmer")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._ping_once()
            self._stop.wait(self._interval)

    def _ping_once(self) -> None:
        """One keep-alive assertion. Never raises -- see module docstring."""
        try:
            resp = requests.post(
                f"{OLLAMA_HOST.rstrip('/')}/api/generate",
                # keep_alive -1 means "until evicted or told otherwise". No
                # "prompt" key at all: that is what makes this a load-only
                # request instead of a (billed-in-GPU-time) generation.
                json={"model": self._model, "keep_alive": -1},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except Exception as e:
            if not self._failing:
                self._failing = True
                _log.warning(
                    "model keep-warm failed for %r at %s (%s) -- the first chat message "
                    "after an idle period will pay a cold model load until this recovers",
                    self._model, OLLAMA_HOST, e,
                )
            return
        if self._failing:
            self._failing = False
            _log.info("model keep-warm recovered for %r", self._model)


_warmer: Optional[ModelWarmer] = None


def get_model_warmer() -> ModelWarmer:
    global _warmer
    if _warmer is None:
        _warmer = ModelWarmer()
    return _warmer
