from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelResponse:
    text: str  # raw model reply
    tokens_in: int  # prompt tokens
    tokens_out: int  # generated tokens
    latency_s: float  # wall-clock seconds for the call
    cost_usd: float  # 0.0 for local models
    model: str  # e.g. "qwen3:8b"
    backend: str  # config name, e.g. "local"
    stop_reason: str  # normalized: "stop", "length" or "other"

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "length"


class BackendError(Exception):
    """The model could not be reached, or it returned an HTTP/API error.

    This is an infrastructure failure, NOT a model failure, and must never be
    counted as one in evals.
    """


class ModelBackend(abc.ABC):
    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self.config = config

    @abc.abstractmethod
    def generate(self, messages: list[dict[str, str]], **opts) -> ModelResponse:
        """Send a chat to the model and return its reply.

        messages are {"role": ..., "content": ...} dicts with roles "system",
        "user" or "assistant". Implementations must fill every ModelResponse
        field, normalize stop_reason to "stop", "length" or "other", and raise
        BackendError (not requests/boto exceptions) on connection or API errors.
        """
