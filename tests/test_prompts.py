import pytest

from infrapilot.generator.parser import parse_reply
from infrapilot.generator.prompts import (
    build_messages,
    example_reply,
    load_system_prompt,
)


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


def test_example_reply_passes_our_own_parser_cleanly():
    result = parse_reply(example_reply())
    assert set(result.files) == {"main.tf", "outputs.tf"}
    assert result.warnings == []
