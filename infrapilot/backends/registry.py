"""Backend registry: turns a config name (e.g. "local") into a ModelBackend.

Reads config/backends.yaml and maps each entry's "type" to a backend class.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from infrapilot.backends.base import ModelBackend
from infrapilot.backends.ollama import OllamaBackend

# Phase 5 adds "bedrock" here; nothing else should change.
BACKEND_TYPES: dict[str, type[ModelBackend]] = {
    "ollama": OllamaBackend,
}

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "backends.yaml"


def get_backend(name: str, config_path: Path | None = None) -> ModelBackend:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Backend config file not found: {path}")

    with path.open(encoding="utf-8") as f:
        configs = yaml.safe_load(f)
    if not isinstance(configs, dict):
        raise ValueError(f"Backend config {path} must be a mapping of name -> settings")

    if name not in configs:
        raise ValueError(
            f"Unknown backend '{name}'; available: {', '.join(sorted(configs))}"
        )

    entry = configs[name]
    if not isinstance(entry, dict):
        raise ValueError(f"Backend '{name}' in {path} must be a mapping of settings")

    known = ", ".join(sorted(BACKEND_TYPES))
    backend_type = entry.get("type")
    if backend_type is None:
        raise ValueError(f"Backend '{name}' has no 'type'; known types: {known}")
    if backend_type not in BACKEND_TYPES:
        raise ValueError(
            f"Backend '{name}' has unknown type '{backend_type}'; known types: {known}"
        )

    return BACKEND_TYPES[backend_type](name, entry)
