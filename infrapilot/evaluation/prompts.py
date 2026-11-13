"""Loader and validator for the eval prompt set (eval/prompts.yaml).

Rules and field meanings live in docs/eval_set.md. This module only reads and
checks the data; it does not evaluate anything against a plan.json.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPTS_PATH = REPO_ROOT / "eval" / "prompts.yaml"
DEFAULT_ALLOWLIST_PATH = REPO_ROOT / "config" / "allowlist.yaml"

DIFFICULTIES = ("easy", "medium", "hard")
EXPECTED_PER_DIFFICULTY = {"easy": 10, "medium": 12, "hard": 8}
MAX_SEEN_IN_PHASE2 = 4
# The two requests used as examples in the system prompt (decision 4).
FORBIDDEN_REQUESTS = ("An SNS topic", "A Python Lambda function that logs each event")

_PROMPT_REQUIRED = {
    "id",
    "difficulty",
    "seen_in_phase2",
    "request",
    "expected_resources",
    "behaviours",
}
_PROMPT_KEYS = _PROMPT_REQUIRED | {"plan_checks"}
_CHECK_KEYS = {"id", "type", "attrs", "matches", "references"}
_REFERENCES_KEYS = {"attr", "to"}


class PromptSetError(ValueError):
    """The prompt file or the prompt set breaks a rule in docs/eval_set.md."""


@dataclass(frozen=True)
class PlanCheck:
    id: str
    types: tuple[str, ...]
    attrs: dict
    matches: dict
    references: dict | None


@dataclass(frozen=True)
class EvalPrompt:
    id: str
    difficulty: str
    seen_in_phase2: bool
    request: str
    expected_resources: dict[str, int]
    behaviours: tuple[str, ...]
    plan_checks: tuple[PlanCheck, ...]


def _read_yaml(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_allowlist(path: Path | str | None = None) -> frozenset[str]:
    path = Path(path) if path is not None else DEFAULT_ALLOWLIST_PATH
    data = _read_yaml(path)
    if not isinstance(data, dict) or set(data) != {"resource_types"}:
        raise PromptSetError(f"{path}: must be a mapping with only the key 'resource_types'")
    types = data["resource_types"]
    if not isinstance(types, list) or not all(isinstance(t, str) and t for t in types):
        raise PromptSetError(f"{path}: 'resource_types' must be a list of non-empty strings")
    return frozenset(types)


def _check_keys(where: str, obj: dict, allowed: set[str], required: set[str]) -> None:
    unknown = sorted(str(k) for k in obj if k not in allowed)
    if unknown:
        raise PromptSetError(f"{where}: unknown key(s): {', '.join(unknown)}")
    missing = sorted(required - set(obj))
    if missing:
        raise PromptSetError(f"{where}: missing key(s): {', '.join(missing)}")


def _check_allowlisted(where: str, rtype: Any, allowlist: frozenset[str]) -> None:
    if not isinstance(rtype, str) or rtype not in allowlist:
        raise PromptSetError(f"{where}: resource type {rtype!r} is not in the allowlist")


def _parse_check(pid: str, raw: Any, allowlist: frozenset[str]) -> PlanCheck:
    if not isinstance(raw, dict):
        raise PromptSetError(f"{pid}: each plan check must be a mapping")
    cid = raw.get("id")
    where = f"{pid} check {cid!r}"
    _check_keys(where, raw, _CHECK_KEYS, {"id", "type"})
    if not isinstance(cid, str) or not cid:
        raise PromptSetError(f"{pid}: check id must be a non-empty string")

    raw_type = raw["type"]
    types = (raw_type,) if isinstance(raw_type, str) else raw_type
    if not isinstance(types, (list, tuple)) or not types:
        raise PromptSetError(f"{where}: 'type' must be a string or a non-empty list of strings")
    for t in types:
        _check_allowlisted(f"{where} type", t, allowlist)

    attrs = raw.get("attrs") or {}
    matches = raw.get("matches") or {}
    references = raw.get("references")
    if not isinstance(attrs, dict):
        raise PromptSetError(f"{where}: 'attrs' must be a mapping")
    if not isinstance(matches, dict):
        raise PromptSetError(f"{where}: 'matches' must be a mapping")

    for path, pattern in matches.items():
        if not isinstance(pattern, str):
            raise PromptSetError(f"{where}: matches[{path!r}] must be a regex string")
        try:
            re.compile(pattern)
        except re.error as e:
            raise PromptSetError(
                f"{where}: matches[{path!r}] is not a valid regex ({e}): {pattern!r}"
            ) from e

    if references is not None:
        if not isinstance(references, dict):
            raise PromptSetError(f"{where}: 'references' must be a mapping")
        _check_keys(f"{where} references", references, _REFERENCES_KEYS, {"to"})
        _check_allowlisted(f"{where} references.to", references["to"], allowlist)
        attr = references.get("attr")
        if attr is not None and (not isinstance(attr, str) or not attr):
            raise PromptSetError(f"{where}: references.attr must be a non-empty string")
        references = dict(references)

    if not attrs and not matches and references is None:
        raise PromptSetError(f"{where}: needs at least one of attrs, matches or references")

    return PlanCheck(
        id=cid,
        types=tuple(types),
        attrs=dict(attrs),
        matches=dict(matches),
        references=references,
    )


def _parse_prompt(index: int, raw: Any, allowlist: frozenset[str]) -> EvalPrompt:
    if not isinstance(raw, dict):
        raise PromptSetError(f"prompt #{index}: each prompt must be a mapping")
    pid = raw.get("id")
    label = pid if isinstance(pid, str) and pid else f"prompt #{index}"
    _check_keys(label, raw, _PROMPT_KEYS, _PROMPT_REQUIRED)
    if not isinstance(pid, str) or not pid:
        raise PromptSetError(f"{label}: 'id' must be a non-empty string")

    difficulty = raw["difficulty"]
    if difficulty not in DIFFICULTIES:
        raise PromptSetError(
            f"{pid}: difficulty must be one of {', '.join(DIFFICULTIES)}, got {difficulty!r}"
        )

    seen = raw["seen_in_phase2"]
    if not isinstance(seen, bool):
        raise PromptSetError(f"{pid}: seen_in_phase2 must be true or false")

    request = raw["request"]
    if not isinstance(request, str) or not request.strip():
        raise PromptSetError(f"{pid}: request must be a non-empty string")
    if "${" in request:
        raise PromptSetError(f"{pid}: request must not contain '${{'")

    expected = raw["expected_resources"]
    if not isinstance(expected, dict) or not expected:
        raise PromptSetError(f"{pid}: expected_resources must be a non-empty mapping")
    for rtype, count in expected.items():
        _check_allowlisted(f"{pid} expected_resources", rtype, allowlist)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise PromptSetError(
                f"{pid}: expected count for {rtype} must be an integer >= 1, got {count!r}"
            )

    behaviours = raw["behaviours"]
    if (
        not isinstance(behaviours, list)
        or not behaviours
        or not all(isinstance(b, str) and b.strip() for b in behaviours)
    ):
        raise PromptSetError(f"{pid}: behaviours must be a non-empty list of non-empty strings")

    raw_checks = raw.get("plan_checks") or []
    if not isinstance(raw_checks, list):
        raise PromptSetError(f"{pid}: plan_checks must be a list")
    checks: list[PlanCheck] = []
    seen_ids: set[str] = set()
    for raw_check in raw_checks:
        check = _parse_check(pid, raw_check, allowlist)
        if check.id in seen_ids:
            raise PromptSetError(f"{pid}: duplicate check id {check.id!r}")
        seen_ids.add(check.id)
        checks.append(check)

    return EvalPrompt(
        id=pid,
        difficulty=difficulty,
        seen_in_phase2=seen,
        request=request,
        expected_resources=dict(expected),
        behaviours=tuple(behaviours),
        plan_checks=tuple(checks),
    )


def load_prompts(
    path: Path | str | None = None,
    allowlist: frozenset[str] | None = None,
) -> list[EvalPrompt]:
    """Read and validate every prompt in the file. Set-level rules are in validate_prompt_set."""
    path = Path(path) if path is not None else DEFAULT_PROMPTS_PATH
    if allowlist is None:
        allowlist = load_allowlist()
    data = _read_yaml(path)
    if not isinstance(data, dict) or set(data) != {"prompts"} or not isinstance(data["prompts"], list):
        raise PromptSetError(f"{path}: must be a mapping with only the key 'prompts' (a list)")

    prompts: list[EvalPrompt] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(data["prompts"], start=1):
        prompt = _parse_prompt(index, raw, allowlist)
        if prompt.id in seen_ids:
            raise PromptSetError(f"{prompt.id}: duplicate prompt id")
        seen_ids.add(prompt.id)
        prompts.append(prompt)
    return prompts


def _normalise_request(text: str) -> str:
    return text.strip().rstrip(".").strip().casefold()


def validate_prompt_set(prompts: list[EvalPrompt]) -> None:
    """Set-level rules from docs/eval_set.md (decisions 1, 4 and 5)."""
    for difficulty, want in EXPECTED_PER_DIFFICULTY.items():
        got = sum(1 for p in prompts if p.difficulty == difficulty)
        if got != want:
            raise PromptSetError(f"expected exactly {want} {difficulty} prompts, found {got}")

    seen = [p.id for p in prompts if p.seen_in_phase2]
    if len(seen) > MAX_SEEN_IN_PHASE2:
        raise PromptSetError(
            f"at most {MAX_SEEN_IN_PHASE2} prompts may have seen_in_phase2, "
            f"found {len(seen)}: {', '.join(seen)}"
        )

    forbidden = {_normalise_request(r) for r in FORBIDDEN_REQUESTS}
    for p in prompts:
        if _normalise_request(p.request) in forbidden:
            raise PromptSetError(
                f"{p.id}: request is one of the system-prompt examples and must not be used"
            )
