"""Tests that run the real terraform binary (init + validate only; no AWS calls)."""

import os
import shutil
import stat

import pytest

from infrapilot.runner.terraform import (
    cleanup_providers,
    terraform_init,
    terraform_validate,
)
from infrapilot.runner.workspace import prepare_run

pytestmark = [
    pytest.mark.terraform,
    pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not on PATH"),
]

VALID_MAIN = 'resource "aws_sns_topic" "main" {\n  name = "${var.name_prefix}-topic"\n}\n'

INLINE_VERSIONING_MAIN = """\
resource "aws_s3_bucket" "main" {
  bucket_prefix = "${var.name_prefix}-"

  versioning {
    enabled = true
  }
}
"""

BOGUS_ARG_MAIN = """\
resource "aws_sns_topic" "main" {
  name      = "${var.name_prefix}-topic"
  bogus_arg = true
}
"""

UNDECLARED_REF_MAIN = VALID_MAIN + 'output "arn" {\n  value = aws_sqs_queue.nope.arn\n}\n'

NULL_RESOURCE_MAIN = 'resource "null_resource" "x" {}\n'


@pytest.fixture(scope="module")
def initialized_run(tmp_path_factory):
    run_dir = prepare_run(
        {"main.tf": VALID_MAIN},
        run_id="shared",
        runs_dir=tmp_path_factory.mktemp("tf_runs"),
    )
    init = terraform_init(run_dir)
    yield run_dir, init
    cleanup_providers(run_dir)  # each run copies ~820 MB of providers on Windows


def _validate_with(run_dir, main_tf):
    (run_dir / "tf" / "main.tf").write_text(main_tf, encoding="utf-8", newline="\n")
    return terraform_validate(run_dir)


def test_init_ok_and_log_has_command(initialized_run):
    run_dir, init = initialized_run
    assert init.ok, init.stderr
    log = (run_dir / "init.log").read_text(encoding="utf-8")
    assert "init -input=false -no-color -lockfile=readonly" in log


def test_valid_sns_config(initialized_run):
    run_dir, _ = initialized_run
    result = _validate_with(run_dir, VALID_MAIN)
    assert result.valid is True
    assert result.error_count == 0
    assert result.warning_count == 0
    assert (run_dir / "validate.json").read_text(encoding="utf-8") == result.step.stdout
    assert (run_dir / "validate.log").exists()


def test_inline_versioning_is_a_deprecation_warning(initialized_run):
    run_dir, _ = initialized_run
    result = _validate_with(run_dir, INLINE_VERSIONING_MAIN)
    assert result.valid is True
    assert result.warning_count >= 1
    assert any("deprecated" in d["summary"].lower() for d in result.diagnostics)


def test_unsupported_argument(initialized_run):
    run_dir, _ = initialized_run
    result = _validate_with(run_dir, BOGUS_ARG_MAIN)
    assert result.valid is False
    assert result.error_count >= 1
    errors = [d for d in result.diagnostics if d["severity"] == "error"]
    assert errors[0]["filename"] == "main.tf"
    assert isinstance(errors[0]["line"], int)


def test_undeclared_reference(initialized_run):
    run_dir, _ = initialized_run
    result = _validate_with(run_dir, UNDECLARED_REF_MAIN)
    assert result.valid is False
    assert result.error_count >= 1


def test_new_provider_blocked_by_readonly_lockfile(tmp_path):
    run_dir = prepare_run({"main.tf": NULL_RESOURCE_MAIN}, run_id="null", runs_dir=tmp_path)
    try:
        init = terraform_init(run_dir)
    finally:
        cleanup_providers(run_dir)
    assert not init.ok
    log = (run_dir / "init.log").read_text(encoding="utf-8").lower()
    assert "lock file" in log or "null" in log


def test_cleanup_providers_removes_only_dot_terraform(tmp_path):
    # Synthetic .terraform (with a read-only file) so this test doesn't copy providers
    # or depend on test order.
    run_dir = prepare_run({"main.tf": VALID_MAIN}, run_id="cleanup", runs_dir=tmp_path)
    (run_dir / "init.log").write_text("init output\n", encoding="utf-8")
    nested = run_dir / "tf" / ".terraform" / "providers" / "x"
    nested.mkdir(parents=True)
    readonly = nested / "terraform-provider-fake.exe"
    readonly.write_bytes(b"fake")
    os.chmod(readonly, stat.S_IREAD)

    cleanup_providers(run_dir)

    assert not (run_dir / "tf" / ".terraform").exists()
    assert (run_dir / "tf" / "main.tf").exists()
    assert (run_dir / "init.log").exists()
    cleanup_providers(run_dir)  # no-op when already gone
