"""Tests for the eval prompt loader. No terraform, no AWS."""

from __future__ import annotations

import dataclasses

import pytest

from infrapilot.evaluation import (
    EvalPrompt,
    PlanCheck,
    PromptSetError,
    load_allowlist,
    load_prompts,
    validate_prompt_set,
)

ALLOWLIST = frozenset({"aws_s3_bucket", "aws_s3_bucket_public_access_block", "aws_sqs_queue"})

BASE = """\
prompts:
  - id: T01
    difficulty: easy
    seen_in_phase2: false
    request: An S3 bucket with all public access blocked.
    expected_resources:
      aws_s3_bucket: 1
    behaviours:
      - Public access is blocked.
    plan_checks:
      - id: blocked
        type: aws_s3_bucket_public_access_block
        attrs: {block_public_acls: true}
        matches: {bucket: '^x'}
        references: {attr: bucket, to: aws_s3_bucket}
"""


def load(tmp_path, text, allowlist=ALLOWLIST):
    path = tmp_path / "prompts.yaml"
    path.write_text(text, encoding="utf-8")
    return load_prompts(path, allowlist)


def edit(old, new):
    """BASE with one substring replaced (fails loudly if the substring is not there)."""
    assert old in BASE, old
    return BASE.replace(old, new)


def expect_error(tmp_path, text, *fragments):
    with pytest.raises(PromptSetError) as exc:
        load(tmp_path, text)
    for fragment in fragments:
        assert fragment in str(exc.value)


# ---------------------------------------------------------------- real files


def test_real_files_load_and_validate():
    allowlist = load_allowlist()
    prompts = load_prompts(allowlist=allowlist)
    validate_prompt_set(prompts)
    assert len(prompts) == 30
    assert sum(len(p.plan_checks) for p in prompts) == 81
    assert len({p.id for p in prompts}) == 30


def test_base_fixture_loads(tmp_path):
    (prompt,) = load(tmp_path, BASE)
    assert prompt.id == "T01"
    assert prompt.expected_resources == {"aws_s3_bucket": 1}
    assert prompt.behaviours == ("Public access is blocked.",)
    (check,) = prompt.plan_checks
    assert check.types == ("aws_s3_bucket_public_access_block",)
    assert check.attrs == {"block_public_acls": True}
    assert check.matches == {"bucket": "^x"}
    assert check.references == {"attr": "bucket", "to": "aws_s3_bucket"}


def test_dataclasses_are_frozen(tmp_path):
    (prompt,) = load(tmp_path, BASE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.id = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.plan_checks[0].id = "other"


def test_type_list_becomes_tuple(tmp_path):
    text = edit(
        "type: aws_s3_bucket_public_access_block",
        "type: [aws_s3_bucket, aws_sqs_queue]",
    )
    (prompt,) = load(tmp_path, text)
    assert prompt.plan_checks[0].types == ("aws_s3_bucket", "aws_sqs_queue")


def test_optional_plan_checks_and_check_fields(tmp_path):
    text = """\
prompts:
  - id: T01
    difficulty: easy
    seen_in_phase2: false
    request: A queue.
    expected_resources: {aws_sqs_queue: 1}
    behaviours: [It exists.]
  - id: T02
    difficulty: easy
    seen_in_phase2: false
    request: Another queue.
    expected_resources: {aws_sqs_queue: 1}
    behaviours: [It exists.]
    plan_checks:
      - id: only_refs
        type: aws_sqs_queue
        references: {to: aws_sqs_queue}
"""
    first, second = load(tmp_path, text)
    assert first.plan_checks == ()
    check = second.plan_checks[0]
    assert check.attrs == {} and check.matches == {}
    assert check.references == {"to": "aws_sqs_queue"}


def test_load_allowlist(tmp_path):
    path = tmp_path / "allow.yaml"
    path.write_text("resource_types:\n  - aws_a\n  - aws_b\n", encoding="utf-8")
    assert load_allowlist(path) == frozenset({"aws_a", "aws_b"})


# ------------------------------------------------- load_prompts error rules


def test_unknown_prompt_key(tmp_path):
    expect_error(tmp_path, edit("    seen_in_phase2: false\n", "    seen_in_phase2: false\n    extra: 1\n"), "T01", "extra")


def test_missing_prompt_key(tmp_path):
    expect_error(tmp_path, edit("    seen_in_phase2: false\n", ""), "T01", "seen_in_phase2")


def test_unknown_check_key(tmp_path):
    expect_error(tmp_path, edit("      - id: blocked\n", "      - id: blocked\n        bogus: 1\n"), "T01", "blocked", "bogus")


def test_missing_check_key(tmp_path):
    text = edit("        type: aws_s3_bucket_public_access_block\n", "")
    expect_error(tmp_path, text, "T01", "blocked", "type")


@pytest.mark.parametrize("bad", ["trivial", "Easy", "null"])
def test_bad_difficulty(tmp_path, bad):
    expect_error(tmp_path, edit("difficulty: easy", f"difficulty: {bad}"), "T01", "difficulty")


def test_duplicate_prompt_id(tmp_path):
    second = BASE.split("prompts:\n", 1)[1]
    expect_error(tmp_path, BASE + second, "T01", "duplicate prompt id")


def test_duplicate_check_id(tmp_path):
    extra = (
        "      - id: blocked\n"
        "        type: aws_s3_bucket\n"
        "        attrs: {bucket: x}\n"
    )
    expect_error(tmp_path, BASE + extra, "T01", "duplicate check id", "blocked")


@pytest.mark.parametrize("empty", ["''", "'   '"])
def test_empty_request(tmp_path, empty):
    text = edit("request: An S3 bucket with all public access blocked.", f"request: {empty}")
    expect_error(tmp_path, text, "T01", "request")


@pytest.mark.parametrize("empty", ["[]", "['']"])
def test_empty_behaviours(tmp_path, empty):
    text = edit("    behaviours:\n      - Public access is blocked.\n", f"    behaviours: {empty}\n")
    expect_error(tmp_path, text, "T01", "behaviours")


@pytest.mark.parametrize("count", ["0", "-1"])
def test_expected_count_below_one(tmp_path, count):
    expect_error(tmp_path, edit("aws_s3_bucket: 1", f"aws_s3_bucket: {count}"), "T01", "aws_s3_bucket", ">= 1")


def test_expected_type_not_allowlisted(tmp_path):
    expect_error(tmp_path, edit("aws_s3_bucket: 1", "aws_nat_gateway: 1"), "T01", "aws_nat_gateway", "allowlist")


def test_check_type_not_allowlisted(tmp_path):
    text = edit("type: aws_s3_bucket_public_access_block", "type: aws_instance")
    expect_error(tmp_path, text, "T01", "blocked", "aws_instance", "allowlist")


def test_check_type_in_list_not_allowlisted(tmp_path):
    text = edit("type: aws_s3_bucket_public_access_block", "type: [aws_s3_bucket, aws_instance]")
    expect_error(tmp_path, text, "T01", "aws_instance", "allowlist")


def test_references_to_not_allowlisted(tmp_path):
    text = edit("to: aws_s3_bucket}", "to: aws_kms_key}")
    expect_error(tmp_path, text, "T01", "blocked", "aws_kms_key", "allowlist")


def test_matches_regex_does_not_compile(tmp_path):
    text = edit("matches: {bucket: '^x'}", "matches: {bucket: '(unclosed'}")
    expect_error(tmp_path, text, "T01", "blocked", "regex")


def test_check_with_no_conditions(tmp_path):
    text = edit(
        "        attrs: {block_public_acls: true}\n"
        "        matches: {bucket: '^x'}\n"
        "        references: {attr: bucket, to: aws_s3_bucket}\n",
        "",
    )
    expect_error(tmp_path, text, "T01", "blocked", "attrs, matches or references")


def test_references_without_to(tmp_path):
    text = edit("references: {attr: bucket, to: aws_s3_bucket}", "references: {attr: bucket}")
    expect_error(tmp_path, text, "T01", "blocked", "to")


def test_dollar_brace_in_request(tmp_path):
    text = edit("request: An S3 bucket with all public access blocked.", "request: A bucket named ${var.x}.")
    expect_error(tmp_path, text, "T01", "${")


# ---------------------------------------------------- validate_prompt_set


def make(pid, difficulty, request=None, seen=False):
    return EvalPrompt(
        id=pid,
        difficulty=difficulty,
        seen_in_phase2=seen,
        request=request or f"Request {pid}",
        expected_resources={"aws_sqs_queue": 1},
        behaviours=("It works.",),
        plan_checks=(PlanCheck("c", ("aws_sqs_queue",), {"a": 1}, {}, None),),
    )


def good_set():
    return (
        [make(f"E{i:02}", "easy") for i in range(10)]
        + [make(f"M{i:02}", "medium") for i in range(12)]
        + [make(f"H{i:02}", "hard") for i in range(8)]
    )


def test_good_set_passes():
    validate_prompt_set(good_set())


@pytest.mark.parametrize("difficulty,count", [("easy", 9), ("easy", 11), ("medium", 11), ("hard", 9)])
def test_wrong_difficulty_count(difficulty, count):
    prompts = [p for p in good_set() if p.difficulty != difficulty]
    prompts += [make(f"X{i:02}", difficulty) for i in range(count)]
    with pytest.raises(PromptSetError) as exc:
        validate_prompt_set(prompts)
    assert difficulty in str(exc.value)


def test_four_seen_in_phase2_is_allowed():
    prompts = good_set()
    for i in range(4):
        prompts[i] = dataclasses.replace(prompts[i], seen_in_phase2=True)
    validate_prompt_set(prompts)


def test_more_than_four_seen_in_phase2():
    prompts = good_set()
    for i in range(5):
        prompts[i] = dataclasses.replace(prompts[i], seen_in_phase2=True)
    with pytest.raises(PromptSetError, match="seen_in_phase2"):
        validate_prompt_set(prompts)


@pytest.mark.parametrize(
    "request_text",
    [
        "An SNS topic",
        "An SNS topic.",
        "an sns TOPIC",
        "  An SNS topic.  ",
        "A Python Lambda function that logs each event",
        "a python lambda function that logs each event.",
    ],
)
def test_system_prompt_example_requests_rejected(request_text):
    prompts = good_set()
    prompts[3] = dataclasses.replace(prompts[3], request=request_text)
    with pytest.raises(PromptSetError, match=prompts[3].id):
        validate_prompt_set(prompts)


def test_similar_request_is_not_rejected():
    prompts = good_set()
    prompts[3] = dataclasses.replace(prompts[3], request="An SNS topic with an SQS queue subscribed.")
    validate_prompt_set(prompts)
