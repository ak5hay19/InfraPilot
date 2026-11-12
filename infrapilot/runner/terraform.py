"""Run terraform init / validate / plan / show inside a run folder. Never apply or destroy."""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StepResult:
    name: str
    command: list[str]
    exit_code: int | None
    duration_s: float
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class ValidateResult:
    valid: bool
    error_count: int
    warning_count: int
    diagnostics: tuple[dict, ...]
    step: StepResult


@dataclass(frozen=True)
class PlanResult:
    ok: bool
    plan_step: StepResult
    show_step: StepResult | None
    # Every entry of the plan's resource_changes (managed and data); each dict has
    # keys address, type, mode, actions (tuple[str, ...]).
    resource_changes: tuple[dict, ...]


READONLY_PROFILE = "infrapilot-readonly"

# Static credentials in the environment would silently override AWS_PROFILE.
_STRIPPED_AWS_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_DEFAULT_PROFILE",
)


def terraform_binary() -> str:
    path = shutil.which("terraform")
    if path is None:
        raise RuntimeError("terraform binary not found on PATH; install Terraform and retry")
    return path


def default_plugin_cache() -> Path:
    env_value = os.environ.get("TF_PLUGIN_CACHE_DIR")
    if env_value:
        cache = Path(env_value)
    elif sys.platform == "win32":
        cache = Path(os.environ["LOCALAPPDATA"]) / "infrapilot" / "tf-plugin-cache"
    else:
        cache = Path.home() / ".cache" / "infrapilot" / "tf-plugin-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _tf_env() -> dict:
    env = dict(os.environ)
    env["TF_IN_AUTOMATION"] = "1"
    env["TF_INPUT"] = "0"
    env["CHECKPOINT_DISABLE"] = "1"
    env["TF_PLUGIN_CACHE_DIR"] = str(default_plugin_cache())
    return env


def _plan_env(profile: str = READONLY_PROFILE) -> dict:
    """Subprocess env for plan/show: AWS_PROFILE=<profile>, static AWS keys removed.

    Only the child environment is changed; ~/.aws is never read or written here.
    """
    env = _tf_env()
    for key in _STRIPPED_AWS_ENV:
        env.pop(key, None)
    env["AWS_PROFILE"] = profile
    return env


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _write_log(
    run_dir: Path,
    step_name: str,
    command: list[str],
    exit_code: int | None,
    duration_s: float,
    timed_out: bool,
    stdout: str,
    stderr: str,
) -> None:
    exit_text = "none (timed out)" if timed_out else str(exit_code)
    text = (
        f"command: {' '.join(command)}\n"
        f"exit code: {exit_text}\n"
        f"duration: {duration_s:.2f}s\n"
        f"\n--- stdout ---\n{stdout}\n"
        f"\n--- stderr ---\n{stderr}\n"
    )
    with open(run_dir / f"{step_name}.log", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def run_tf(
    args: list[str],
    run_dir: Path,
    step_name: str,
    timeout_s: float,
    env: dict | None = None,
) -> StepResult:
    """Run terraform with cwd=<run_dir>/tf and write <run_dir>/<step_name>.log.

    env=None uses _tf_env().
    """
    command = [terraform_binary(), *args]
    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            cwd=run_dir / "tf",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env if env is not None else _tf_env(),
            timeout=timeout_s,
        )
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        # TimeoutExpired may carry bytes even when text=True was requested.
        stdout, stderr = _to_text(exc.stdout), _to_text(exc.stderr)
    duration_s = time.monotonic() - start

    _write_log(run_dir, step_name, command, exit_code, duration_s, timed_out, stdout, stderr)
    return StepResult(
        name=step_name,
        command=command,
        exit_code=exit_code,
        duration_s=duration_s,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )


def terraform_init(run_dir: Path, timeout_s: float = 300) -> StepResult:
    return run_tf(
        ["init", "-input=false", "-no-color", "-lockfile=readonly"],
        run_dir,
        "init",
        timeout_s,
    )


def _diagnostic(raw: dict) -> dict:
    rng = raw.get("range") or {}
    start = rng.get("start") or {}
    return {
        "severity": raw.get("severity"),
        "summary": raw.get("summary", ""),
        "detail": raw.get("detail", ""),
        "filename": rng.get("filename"),
        "line": start.get("line"),
    }


def _unparseable(step: StepResult) -> ValidateResult:
    diagnostic = {
        "severity": "error",
        "summary": "unparseable validate output",
        "detail": step.stdout[:500] or step.stderr[:500],
        "filename": None,
        "line": None,
    }
    return ValidateResult(
        valid=False,
        error_count=1,
        warning_count=0,
        diagnostics=(diagnostic,),
        step=step,
    )


def terraform_validate(run_dir: Path, timeout_s: float = 120) -> ValidateResult:
    step = run_tf(["validate", "-json", "-no-color"], run_dir, "validate", timeout_s)
    with open(run_dir / "validate.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(step.stdout)

    try:
        data = json.loads(step.stdout)
        if not isinstance(data, dict):
            raise ValueError("validate output is not a JSON object")
        diagnostics = tuple(_diagnostic(d) for d in data.get("diagnostics", []))
        return ValidateResult(
            valid=bool(data["valid"]),
            error_count=int(data.get("error_count", 0)),
            warning_count=int(data.get("warning_count", 0)),
            diagnostics=diagnostics,
            step=step,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return _unparseable(step)


def _resource_change(raw: dict) -> dict:
    change = raw.get("change") or {}
    return {
        "address": raw.get("address"),
        "type": raw.get("type"),
        "mode": raw.get("mode"),
        "actions": tuple(change.get("actions") or ()),
    }


def terraform_plan(
    run_dir: Path, timeout_s: float = 300, profile: str = READONLY_PROFILE
) -> PlanResult:
    """Run `plan -out=plan.tfplan` then `show -json`, both with the read-only AWS profile.

    Saves show's stdout verbatim to <run_dir>/plan.json. resource_changes includes every
    entry (managed and data); filtering is the plan guard's job.

    Call cleanup_providers AFTER terraform_plan: `show` needs <run_dir>/tf/.terraform.
    """
    env = _plan_env(profile)
    plan_step = run_tf(
        ["plan", "-input=false", "-no-color", "-out=plan.tfplan"],
        run_dir,
        "plan",
        timeout_s,
        env=env,
    )
    if not plan_step.ok:
        return PlanResult(ok=False, plan_step=plan_step, show_step=None, resource_changes=())

    show_step = run_tf(["show", "-json", "plan.tfplan"], run_dir, "show", timeout_s, env=env)
    with open(run_dir / "plan.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(show_step.stdout)
    if not show_step.ok:
        return PlanResult(
            ok=False, plan_step=plan_step, show_step=show_step, resource_changes=()
        )

    try:
        data = json.loads(show_step.stdout)
        if not isinstance(data, dict):
            raise ValueError("show output is not a JSON object")
        changes = tuple(_resource_change(rc) for rc in data.get("resource_changes") or [])
    except (ValueError, TypeError, AttributeError):
        return PlanResult(
            ok=False, plan_step=plan_step, show_step=show_step, resource_changes=()
        )
    return PlanResult(ok=True, plan_step=plan_step, show_step=show_step, resource_changes=changes)


def _make_writable_and_retry(func, path, *_exc_info) -> None:
    """rmtree error handler: Windows refuses to delete read-only files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup_providers(run_dir: Path) -> None:
    """Delete <run_dir>/tf/.terraform (provider copies). Touches nothing else."""
    target = run_dir / "tf" / ".terraform"
    if not target.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(target, onerror=_make_writable_and_retry)
