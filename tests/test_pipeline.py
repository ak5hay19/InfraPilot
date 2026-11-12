"""Pipeline tests with a fake backend. Unmarked: no terraform needed. `terraform`: real
binary, no AWS calls. `terraform` + `aws`: also plans with the read-only profile."""

import json
import shutil

import pytest

from infrapilot.backends import BackendError, ModelBackend, ModelResponse
from infrapilot.pipeline import CATEGORIES, run_generate

needs_terraform = pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not on PATH")

SNS_MAIN = 'resource "aws_sns_topic" "main" {\n  name = "${var.name_prefix}-topic"\n}\n'
SNS_OUTPUTS = 'output "topic_arn" {\n  value = aws_sns_topic.main.arn\n}\n'


def reply_text(**files: str) -> str:
    return "\n".join(f"### {name}\n```hcl\n{body}```\n" for name, body in files.items())


VALID_REPLY = reply_text(**{"main.tf": SNS_MAIN, "outputs.tf": SNS_OUTPUTS})
BOGUS_ARG_REPLY = reply_text(
    **{"main.tf": 'resource "aws_sns_topic" "main" {\n  name      = "x"\n  bogus_arg = true\n}\n'}
)
INLINE_VERSIONING_REPLY = reply_text(
    **{
        "main.tf": (
            'resource "aws_s3_bucket" "main" {\n  bucket_prefix = "${var.name_prefix}-"\n\n'
            "  versioning {\n    enabled = true\n  }\n}\n"
        )
    }
)
PROVIDER_REPLY = reply_text(
    **{"main.tf": 'provider "aws" {\n  region = "ap-south-1"\n}\n' + SNS_MAIN}
)


class FakeBackend(ModelBackend):
    def __init__(self, text: str = "", stop_reason: str = "stop", error: Exception | None = None):
        super().__init__("fake", {})
        self.text = text
        self.stop_reason = stop_reason
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages, **opts) -> ModelResponse:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return ModelResponse(
            text=self.text,
            tokens_in=11,
            tokens_out=22,
            latency_s=0.5,
            cost_usd=0.0,
            model="fake-model",
            backend="fake",
            stop_reason=self.stop_reason,
        )


def generate(tmp_path, backend, do_plan=True, request="an SNS topic"):
    return run_generate(request, "fake", do_plan=do_plan, runs_dir=tmp_path, backend=backend)


def read_meta(run_dir) -> dict:
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))


def check_early_failure(result, category, replied):
    """Failures before any file is written: meta.json, maybe reply.md, never tf/."""
    assert result.category == category
    assert category in CATEGORIES
    meta = read_meta(result.run_dir)
    assert meta["category"] == category
    assert meta == result.meta
    assert meta["category_detail"]
    assert (result.run_dir / "request.txt").read_text(encoding="utf-8") == "an SNS topic"
    assert (result.run_dir / "messages.json").is_file()
    assert (result.run_dir / "reply.md").is_file() == replied
    assert not (result.run_dir / "tf").exists()
    assert meta["steps"] == {}
    assert meta["validate_clean"] is False
    assert meta["plan_ran"] is False
    return meta


def test_backend_error(tmp_path):
    result = generate(tmp_path, FakeBackend(error=BackendError("connection refused")))
    meta = check_early_failure(result, "backend_error", replied=False)
    assert meta["category_detail"] == "connection refused"
    for key in ("model", "tokens_in", "tokens_out", "latency_s", "cost_usd", "stop_reason"):
        assert meta[key] is None
    assert meta["system_prompt_sha256"]


def test_truncated(tmp_path):
    result = generate(tmp_path, FakeBackend(text="### main.tf\n```hcl\nresource", stop_reason="length"))
    meta = check_early_failure(result, "truncated", replied=True)
    assert meta["stop_reason"] == "length"
    assert meta["tokens_out"] == 22


def test_parse_error_without_headers(tmp_path):
    result = generate(tmp_path, FakeBackend(text="Sure! Here is some Terraform, but no files."))
    meta = check_early_failure(result, "parse_error", replied=True)
    assert meta["model"] == "fake-model"
    assert (result.run_dir / "reply.md").read_text(encoding="utf-8") == (
        "Sure! Here is some Terraform, but no files."
    )


def test_provider_block_written(tmp_path):
    result = generate(tmp_path, FakeBackend(text=PROVIDER_REPLY))
    check_early_failure(result, "provider_block_written", replied=True)


def test_internal_error_writes_meta_and_reraises(tmp_path):
    with pytest.raises(RuntimeError, match="boom"):
        generate(tmp_path, FakeBackend(error=RuntimeError("boom")))
    (run_dir,) = tmp_path.iterdir()
    meta = read_meta(run_dir)
    assert meta["category"] == "internal_error"
    assert "boom" in meta["category_detail"]


def test_backend_is_called_with_built_messages(tmp_path):
    backend = FakeBackend(error=BackendError("down"))
    result = generate(tmp_path, backend)
    messages = json.loads((result.run_dir / "messages.json").read_text(encoding="utf-8"))
    assert backend.calls == [messages]
    assert [m["role"] for m in messages] == ["system", "user"]


@pytest.mark.terraform
@needs_terraform
def test_valid_sns_reply_is_ok(tmp_path):
    result = generate(tmp_path, FakeBackend(text=VALID_REPLY), do_plan=False)
    assert result.category == "ok"
    meta = read_meta(result.run_dir)
    assert meta["category"] == "ok"
    assert meta["category_detail"] is None
    assert meta["validate_clean"] is True
    assert meta["plan_ran"] is False
    assert "plan" not in meta["steps"]
    assert meta["steps"]["init"]["ok"] is True
    assert meta["steps"]["validate"]["valid"] is True
    assert meta["files"] == ["main.tf", "outputs.tf"]
    assert (result.run_dir / "reply.md").read_text(encoding="utf-8") == VALID_REPLY
    assert (result.run_dir / "tf" / "main.tf").is_file()
    assert not (result.run_dir / "tf" / ".terraform").exists()


@pytest.mark.terraform
@needs_terraform
def test_bogus_argument_is_validate_error(tmp_path):
    result = generate(tmp_path, FakeBackend(text=BOGUS_ARG_REPLY), do_plan=False)
    assert result.category == "validate_error"
    meta = read_meta(result.run_dir)
    assert meta["category"] == "validate_error"
    assert meta["validate_clean"] is False
    assert meta["steps"]["validate"]["valid"] is False
    assert any(
        d["severity"] == "error" and "bogus_arg" in (d["summary"] + d["detail"])
        for d in meta["validate_diagnostics"]
    )
    assert not (result.run_dir / "tf" / ".terraform").exists()


@pytest.mark.terraform
@needs_terraform
def test_inline_versioning_is_ok_but_not_clean(tmp_path):
    result = generate(tmp_path, FakeBackend(text=INLINE_VERSIONING_REPLY), do_plan=False)
    assert result.category == "ok"
    meta = read_meta(result.run_dir)
    assert meta["validate_clean"] is False
    assert meta["steps"]["validate"]["valid"] is True
    assert meta["steps"]["validate"]["warning_count"] >= 1
    assert any(d["severity"] == "warning" for d in meta["validate_diagnostics"])


@pytest.mark.terraform
@pytest.mark.aws
@needs_terraform
def test_valid_sns_reply_plans(tmp_path):
    result = generate(tmp_path, FakeBackend(text=VALID_REPLY), do_plan=True)
    assert result.category == "ok"
    meta = read_meta(result.run_dir)
    assert meta["plan_ran"] is True
    assert meta["steps"]["plan"]["ok"] is True
    addresses = [change[0] for change in meta["steps"]["plan"]["resource_changes"]]
    assert "aws_sns_topic.main" in addresses
    assert not (result.run_dir / "tf" / ".terraform").exists()
