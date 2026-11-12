"""Create a run folder and write the Terraform files into it. No terraform commands here."""

import secrets
import shutil
from datetime import datetime
from pathlib import Path

RUNNER_FILES = ("providers.tf", "variables.tf", ".terraform.lock.hcl")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"


def new_run_id(now: datetime | None = None) -> str:
    """Return 'YYYYMMDD-HHMMSS-xxxx' using local time and 4 random hex chars."""
    if now is None:
        now = datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _check_model_filenames(files: dict[str, str]) -> None:
    for name in files:
        if name in RUNNER_FILES:
            raise ValueError(f"model may not write runner-owned file: {name!r}")
        if "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"invalid file name (path separator or '..'): {name!r}")


def prepare_run(
    files: dict[str, str],
    run_id: str | None = None,
    runs_dir: Path | None = None,
) -> Path:
    """Create <runs_dir>/<run_id>/tf/ with the model files plus the runner templates.

    Returns the run directory (not the tf/ subfolder). Never overwrites a run:
    raises FileExistsError if the run directory already exists.
    """
    _check_model_filenames(files)

    if runs_dir is None:
        runs_dir = DEFAULT_RUNS_DIR
    if run_id is None:
        run_id = new_run_id()

    run_dir = runs_dir / run_id
    tf_dir = run_dir / "tf"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir()  # raises FileExistsError if the run already exists
    tf_dir.mkdir()

    for name, content in files.items():
        with open(tf_dir / name, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    for name in RUNNER_FILES:
        shutil.copyfile(TEMPLATES_DIR / name, tf_dir / name)

    return run_dir
