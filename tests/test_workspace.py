import re
from datetime import datetime
from pathlib import Path

import pytest

from infrapilot.runner.workspace import RUNNER_FILES, TEMPLATES_DIR, new_run_id, prepare_run

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_FILES = {
    "main.tf": 'resource "aws_sns_topic" "main" {\n  name = "${var.name_prefix}-topic"\n}\n',
    "outputs.tf": 'output "topic_arn" {\n  value = aws_sns_topic.main.arn\n}\n',
}


def test_new_run_id_format_and_uses_now():
    now = datetime(2026, 11, 12, 9, 5, 7)
    run_id = new_run_id(now)
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", run_id)
    assert run_id.startswith("20261112-090507-")


def test_prepare_run_writes_model_and_runner_files(tmp_path):
    run_dir = prepare_run(MODEL_FILES, run_id="r1", runs_dir=tmp_path)
    written = {p.name for p in (run_dir / "tf").iterdir()}
    assert written == {"main.tf", "outputs.tf", *RUNNER_FILES}


def test_model_files_have_no_carriage_returns(tmp_path):
    run_dir = prepare_run(MODEL_FILES, run_id="r1", runs_dir=tmp_path)
    for name in MODEL_FILES:
        assert b"\r" not in (run_dir / "tf" / name).read_bytes()


def test_copied_lock_file_is_byte_identical(tmp_path):
    run_dir = prepare_run(MODEL_FILES, run_id="r1", runs_dir=tmp_path)
    copied = (run_dir / "tf" / ".terraform.lock.hcl").read_bytes()
    assert copied == (TEMPLATES_DIR / ".terraform.lock.hcl").read_bytes()


def test_template_lock_matches_learning_lock():
    template = (TEMPLATES_DIR / ".terraform.lock.hcl").read_bytes()
    assert template == (REPO_ROOT / "learning" / ".terraform.lock.hcl").read_bytes()


def test_existing_run_dir_raises(tmp_path):
    (tmp_path / "r1").mkdir()
    with pytest.raises(FileExistsError):
        prepare_run(MODEL_FILES, run_id="r1", runs_dir=tmp_path)


@pytest.mark.parametrize("bad_name", ["providers.tf", "../x.tf", "sub/x.tf"])
def test_bad_file_names_raise(tmp_path, bad_name):
    with pytest.raises(ValueError):
        prepare_run({"main.tf": "", bad_name: ""}, run_id="r1", runs_dir=tmp_path)
    assert not (tmp_path / "r1").exists()


def test_returns_run_dir_with_tf_child(tmp_path):
    run_dir = prepare_run(MODEL_FILES, run_id="r1", runs_dir=tmp_path)
    assert run_dir == tmp_path / "r1"
    assert (run_dir / "tf").is_dir()
