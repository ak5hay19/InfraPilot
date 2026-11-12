import pytest

from infrapilot.generator.parser import parse_reply
from infrapilot.generator.prompts import (
    build_messages,
    example_replies,
    load_system_prompt,
)
from infrapilot.runner.terraform import (
    cleanup_providers,
    terraform_init,
    terraform_validate,
)
from infrapilot.runner.workspace import prepare_run

from test_terraform import terraform_test


def test_build_messages_shape():
    messages = build_messages("  An SQS queue.\n")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == load_system_prompt()
    assert messages[1]["content"] == "An SQS queue."


@pytest.mark.parametrize("request_text", ["", "   ", "\n\t \n"])
def test_empty_request_raises(request_text):
    with pytest.raises(ValueError):
        build_messages(request_text)


def test_system_prompt_basics():
    prompt = load_system_prompt()
    assert "### main.tf" in prompt
    assert "\r" not in prompt


def test_system_prompt_has_exact_lambda_logging_policy_arn():
    assert "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" in load_system_prompt()


def test_example_replies_pass_our_own_parser_cleanly():
    replies = example_replies()
    assert len(replies) == 2
    for reply in replies:
        result = parse_reply(reply)
        assert result.warnings == []
        assert set(result.files) == {"main.tf", "outputs.tf"}


@terraform_test
@pytest.mark.parametrize("index", [0, 1])
def test_example_replies_validate_with_no_errors_or_warnings(index, tmp_path):
    result = parse_reply(example_replies()[index])
    run_dir = prepare_run(result.files, run_id=f"example{index + 1}", runs_dir=tmp_path)
    try:
        init = terraform_init(run_dir)
        assert init.ok, init.stderr
        validation = terraform_validate(run_dir)
        assert validation.valid is True, validation.diagnostics
        assert validation.error_count == 0
        assert validation.warning_count == 0, validation.diagnostics
    finally:
        cleanup_providers(run_dir)
