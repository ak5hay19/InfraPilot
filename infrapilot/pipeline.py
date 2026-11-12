"""The generate pipeline: request -> model -> parse -> init -> validate -> plan.

Steps stop at the first failure. Every run, however it ends, gets a meta.json
in its run folder and has its provider copies (tf/.terraform) deleted.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from infrapilot.backends import BackendError, ModelBackend, get_backend
from infrapilot.generator.parser import ParseError, parse_reply
from infrapilot.generator.prompts import build_messages
from infrapilot.runner.terraform import (
    cleanup_providers,
    terraform_init,
    terraform_plan,
    terraform_validate,
)
from infrapilot.runner.workspace import init_run_dir, write_tf_files

CATEGORIES = (
    "ok",
    "backend_error",
    "truncated",
    "parse_error",
    "provider_block_written",
    "init_error",
    "validate_error",
    "plan_error",
    "internal_error",
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    category: str
    meta: dict


def _git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except Exception:
        return None
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and commit else None


def _git_dirty() -> bool | None:
    """True if the working tree has uncommitted or untracked (non-ignored) changes."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return bool(proc.stdout.strip())


def _write_text(path: Path, text: str) -> None:
    # newline="" keeps the text byte-for-byte (no \n -> \r\n translation on Windows).
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _initial_meta(run_dir: Path, request: str, backend_name: str) -> dict:
    return {
        "run_id": run_dir.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "request": request,
        "backend": backend_name,
        "model": None,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "system_prompt_sha256": None,
        "tokens_in": None,
        "tokens_out": None,
        "latency_s": None,
        "cost_usd": None,
        "stop_reason": None,
        "parse_warnings": [],
        "files": [],
        "steps": {},
        "validate_diagnostics": [],
        "validate_clean": False,
        "plan_ran": False,
        "category": None,
        "category_detail": None,
        "total_duration_s": None,
    }


def _plan_failure_detail(plan) -> str:
    if not plan.plan_step.ok:
        step = plan.plan_step
    elif plan.show_step is not None and not plan.show_step.ok:
        step = plan.show_step
    else:
        return "terraform show produced unparseable JSON (see show.log)"
    if step.timed_out:
        return f"terraform {step.name} timed out (see {step.name}.log)"
    return f"terraform {step.name} failed with exit code {step.exit_code} (see {step.name}.log)"


def _execute(
    run_dir: Path, request: str, backend: ModelBackend, do_plan: bool, meta: dict
) -> tuple[str, str | None]:
    """Run the steps, filling `meta` as it goes. Returns (category, category_detail)."""
    _write_text(run_dir / "request.txt", request)
    messages = build_messages(request)
    meta["system_prompt_sha256"] = hashlib.sha256(
        messages[0]["content"].encode("utf-8")
    ).hexdigest()
    _write_json(run_dir / "messages.json", messages)

    try:
        response = backend.generate(messages)
    except BackendError as exc:
        return "backend_error", str(exc)

    meta.update(
        model=response.model,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        latency_s=response.latency_s,
        cost_usd=response.cost_usd,
        stop_reason=response.stop_reason,
    )
    _write_text(run_dir / "reply.md", response.text)
    if response.truncated:
        return "truncated", (
            f"model reply was cut off (stop_reason=length, {response.tokens_out} tokens out)"
        )

    try:
        parsed = parse_reply(response.text)
    except ParseError as exc:
        return exc.category, exc.message
    meta["parse_warnings"] = list(parsed.warnings)
    meta["files"] = list(parsed.files)

    write_tf_files(run_dir, parsed.files)

    init = terraform_init(run_dir)
    meta["steps"]["init"] = {
        "ok": init.ok,
        "exit_code": init.exit_code,
        "duration_s": round(init.duration_s, 3),
    }
    if not init.ok:
        how = "timed out" if init.timed_out else f"failed with exit code {init.exit_code}"
        return "init_error", f"terraform init {how} (see init.log)"

    validate = terraform_validate(run_dir)
    meta["steps"]["validate"] = {
        "valid": validate.valid,
        "error_count": validate.error_count,
        "warning_count": validate.warning_count,
        "duration_s": round(validate.step.duration_s, 3),
    }
    meta["validate_diagnostics"] = [
        {
            "severity": d["severity"],
            "summary": d["summary"],
            "detail": (d["detail"] or "")[:500],
            "filename": d["filename"],
            "line": d["line"],
        }
        for d in validate.diagnostics
    ]
    meta["validate_clean"] = (
        validate.valid and validate.error_count == 0 and validate.warning_count == 0
    )
    if not validate.valid:
        errors = [d for d in validate.diagnostics if d["severity"] == "error"]
        first = errors[0]["summary"] if errors else "validate reported the config invalid"
        return "validate_error", f"terraform validate found {validate.error_count} error(s): {first}"

    if do_plan:
        meta["plan_ran"] = True
        plan = terraform_plan(run_dir)
        meta["steps"]["plan"] = {
            "ok": plan.ok,
            "duration_s": round(
                plan.plan_step.duration_s
                + (plan.show_step.duration_s if plan.show_step is not None else 0.0),
                3,
            ),
            "resource_changes": [
                [rc["address"], rc["mode"], list(rc["actions"])] for rc in plan.resource_changes
            ],
        }
        if not plan.ok:
            return "plan_error", _plan_failure_detail(plan)

    return "ok", None


def run_generate(
    request: str,
    backend_name: str,
    do_plan: bool = True,
    runs_dir: Path | None = None,
    backend: ModelBackend | None = None,
) -> RunResult:
    started = time.monotonic()
    if backend is None:
        # Before the run folder exists: an unknown backend leaves no folder behind.
        backend = get_backend(backend_name)
    run_dir = init_run_dir(runs_dir=runs_dir)
    meta = _initial_meta(run_dir, request, backend_name)

    category, detail = "internal_error", None
    error: BaseException | None = None
    try:
        category, detail = _execute(run_dir, request, backend, do_plan, meta)
    except BaseException as exc:
        category, detail, error = "internal_error", repr(exc), exc
        exc.add_note(f"run dir: {run_dir}")
    finally:
        try:
            if (run_dir / "tf").exists():
                cleanup_providers(run_dir)
        except Exception as exc:
            if error is None:
                category, detail, error = "internal_error", repr(exc), exc
                exc.add_note(f"run dir: {run_dir}")
        meta["category"] = category
        meta["category_detail"] = detail
        meta["total_duration_s"] = round(time.monotonic() - started, 3)
        _write_json(run_dir / "meta.json", meta)

    if error is not None:
        raise error
    return RunResult(run_dir=run_dir, category=category, meta=meta)
