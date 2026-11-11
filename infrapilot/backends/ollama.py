"""Ollama backend: the only file in the project that knows about Ollama.

Talks to a local Ollama server over its /api/chat HTTP endpoint and maps the
reply onto the model-agnostic ModelResponse. All failures become BackendError.
"""

from __future__ import annotations

import time

import requests

from infrapilot.backends.base import BackendError, ModelBackend, ModelResponse

_REQUIRED_KEYS = (
    "base_url",
    "model",
    "num_ctx",
    "num_predict",
    "temperature",
    "think",
    "timeout_s",
)
_ALLOWED_OPTS = ("temperature", "num_predict")


class OllamaBackend(ModelBackend):
    def __init__(self, name: str, config: dict) -> None:
        missing = [key for key in _REQUIRED_KEYS if key not in config]
        if missing:
            raise ValueError(
                f"Backend '{name}' config is missing required key(s): "
                f"{', '.join(missing)}"
            )
        super().__init__(name, config)

    def generate(self, messages: list[dict[str, str]], **opts) -> ModelResponse:
        for key in opts:
            if key not in _ALLOWED_OPTS:
                raise ValueError(
                    f"Unknown generate option '{key}'; "
                    f"allowed: {', '.join(_ALLOWED_OPTS)}"
                )

        cfg = self.config
        base_url = str(cfg["base_url"]).rstrip("/")
        payload = {
            "model": cfg["model"],
            "messages": messages,
            "stream": False,
            "think": cfg["think"],
            "options": {
                "num_ctx": cfg["num_ctx"],
                "num_predict": opts.get("num_predict", cfg["num_predict"]),
                "temperature": opts.get("temperature", cfg["temperature"]),
            },
        }

        start = time.perf_counter()
        try:
            response = requests.post(
                f"{base_url}/api/chat", json=payload, timeout=cfg["timeout_s"]
            )
        except requests.ConnectionError as e:
            raise BackendError(
                f"Cannot reach Ollama at {base_url} - is it running? "
                "Start the Ollama app or run `ollama serve`."
            ) from e
        except requests.Timeout as e:
            raise BackendError(
                f"Ollama at {base_url} did not reply within {cfg['timeout_s']}s. "
                "The model may still be loading; retry or raise timeout_s."
            ) from e
        except requests.RequestException as e:
            raise BackendError(f"Request to Ollama at {base_url} failed: {e}") from e
        latency_s = time.perf_counter() - start

        if not response.ok:
            raise BackendError(
                f"Ollama returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise BackendError(
                f"Ollama returned invalid JSON: {response.text[:300]}"
            ) from e

        message = data.get("message") if isinstance(data, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise BackendError(
                f"Ollama reply has no message.content: {response.text[:300]}"
            )

        done_reason = data.get("done_reason")
        stop_reason = done_reason if done_reason in ("stop", "length") else "other"

        return ModelResponse(
            text=text,
            # Ollama omits prompt_eval_count when the prompt is cached.
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            latency_s=latency_s,
            cost_usd=0.0,
            model=cfg["model"],
            backend=self.name,
            stop_reason=stop_reason,
        )
