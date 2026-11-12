import pytest

from infrapilot.generator.parser import ParseError, parse_reply

MAIN = 'resource "aws_s3_bucket" "this" {\n  bucket = var.name\n}\n'
OUTPUTS = 'output "arn" {\n  value = aws_s3_bucket.this.arn\n}\n'

# Real qwen3:8b reply from Phase 0: no file headers, writes a provider block.
QWEN3_REPLY = """\
Here's a Terraform configuration that creates an **AWS S3 bucket with versioning enabled**:

```hcl
provider "aws" {
  region = "us-west-2"
}

resource "aws_s3_bucket" "example_bucket" {
  bucket = "example-bucket-name"
  region = "us-west-2"

  versioning {
    enabled = true
  }
}
```

### Explanation:
- **`aws_s3_bucket`**: Creates the S3 bucket.
"""


def block(name, body, lang="hcl", header="###"):
    return f"{header} {name}\n```{lang}\n{body}```\n"


def test_main_only():
    result = parse_reply(block("main.tf", MAIN))
    assert result.files == {"main.tf": MAIN}
    assert result.warnings == []


def test_main_and_outputs():
    result = parse_reply(block("main.tf", MAIN) + "\n" + block("outputs.tf", OUTPUTS))
    assert result.files == {"main.tf": MAIN, "outputs.tf": OUTPUTS}
    assert result.warnings == []


def test_header_variants():
    text = block("`main.tf`:", MAIN, header="##") + "\n" + block(
        "outputs.tf", OUTPUTS, header="####"
    )
    result = parse_reply(text)
    assert set(result.files) == {"main.tf", "outputs.tf"}
    assert result.warnings == []


def test_blank_lines_between_header_and_fence():
    result = parse_reply(f"### main.tf\n\n\n```hcl\n{MAIN}```\n")
    assert result.files == {"main.tf": MAIN}


def test_empty_and_terraform_language_tags_are_fine():
    for lang in ("", "terraform", "tf", "HCL"):
        result = parse_reply(block("main.tf", MAIN, lang=lang))
        assert result.warnings == []


def test_prose_before_and_after_is_a_warning():
    text = "Sure, here you go:\n\n" + block("main.tf", MAIN) + "\nHope this helps!\nBye\n"
    result = parse_reply(text)
    assert result.files == {"main.tf": MAIN}
    assert result.warnings == ["prose outside code blocks (3 lines)"]


def test_heading_without_block_counts_as_prose():
    result = parse_reply(block("main.tf", MAIN) + "\n### Explanation:\n- a note\n")
    assert result.warnings == ["prose outside code blocks (2 lines)"]


def test_unknown_language_tag_is_a_warning():
    result = parse_reply(block("main.tf", MAIN, lang="json"))
    assert result.files == {"main.tf": MAIN}
    assert len(result.warnings) == 1
    assert "json" in result.warnings[0]


def test_block_without_header():
    with pytest.raises(ParseError) as exc:
        parse_reply(f"```hcl\n{MAIN}```\n")
    assert exc.value.category == "parse_error"
    assert "code block without a '### <filename>' header" in exc.value.message


def test_second_block_without_header():
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", MAIN) + f"\nSome text\n```hcl\n{OUTPUTS}```\n")
    assert exc.value.category == "parse_error"
    assert "without a '### <filename>' header" in exc.value.message


def test_providers_tf_is_rejected():
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", MAIN) + block("providers.tf", "x = 1\n"))
    assert exc.value.category == "parse_error"
    assert "providers.tf" in exc.value.message


def test_variables_tf_is_rejected():
    with pytest.raises(ParseError) as exc:
        parse_reply(block("variables.tf", 'variable "x" {}\n'))
    assert exc.value.category == "parse_error"
    assert "variables.tf" in exc.value.message


def test_duplicate_main_tf():
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", MAIN) + block("main.tf", MAIN))
    assert exc.value.category == "parse_error"
    assert "duplicate" in exc.value.message and "main.tf" in exc.value.message


def test_empty_block():
    with pytest.raises(ParseError) as exc:
        parse_reply("### main.tf\n```hcl\n\n  \n```\n")
    assert exc.value.category == "parse_error"
    assert "empty" in exc.value.message


def test_unclosed_fence():
    with pytest.raises(ParseError) as exc:
        parse_reply(f"### main.tf\n```hcl\n{MAIN}")
    assert exc.value.category == "parse_error"
    assert "unclosed" in exc.value.message


def test_only_outputs_tf_means_main_missing():
    with pytest.raises(ParseError) as exc:
        parse_reply(block("outputs.tf", OUTPUTS))
    assert exc.value.category == "parse_error"
    assert "main.tf is missing" in exc.value.message


def test_no_files_at_all():
    with pytest.raises(ParseError) as exc:
        parse_reply("I cannot help with that.")
    assert exc.value.category == "parse_error"
    assert "no files" in exc.value.message


def test_provider_block_in_main_tf_reports_line_number():
    body = 'resource "aws_s3_bucket" "this" {}\n\nprovider "aws" {\n  region = "x"\n}\n'
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", body))
    assert exc.value.category == "provider_block_written"
    assert "main.tf" in exc.value.message
    assert "line 3" in exc.value.message


def test_terraform_block_in_outputs_tf():
    body = 'terraform {\n  required_version = ">= 1.0"\n}\n' + OUTPUTS
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", MAIN) + block("outputs.tf", body))
    assert exc.value.category == "provider_block_written"
    assert "outputs.tf" in exc.value.message
    assert "line 1" in exc.value.message


def test_commented_provider_is_not_flagged():
    body = '# provider "aws" {}\n' + MAIN
    result = parse_reply(block("main.tf", body))
    assert "main.tf" in result.files


def test_structure_errors_win_over_provider_check():
    # A bad structure is reported as parse_error even if a provider block exists.
    with pytest.raises(ParseError) as exc:
        parse_reply(block("main.tf", 'provider "aws" {}\n') + block("main.tf", MAIN))
    assert exc.value.category == "parse_error"


def test_crlf_and_trailing_whitespace_are_normalized():
    text = (
        "### main.tf\r\n```hcl\r\n"
        'resource "a" "b" {   \r\n'
        "  x = 1\t\r\n"
        "}\r\n\r\n\r\n"
        "```\r\n"
    )
    result = parse_reply(text)
    assert result.files["main.tf"] == 'resource "a" "b" {\n  x = 1\n}\n'
    assert "\r" not in result.files["main.tf"]


def test_exactly_one_trailing_newline():
    no_newline = parse_reply("### main.tf\n```hcl\nx = 1\n```")
    many_blank = parse_reply("### main.tf\n```hcl\nx = 1\n\n\n\n```")
    assert no_newline.files["main.tf"] == "x = 1\n"
    assert many_blank.files["main.tf"] == "x = 1\n"


def test_real_qwen3_reply_without_headers_fails():
    with pytest.raises(ParseError) as exc:
        parse_reply(QWEN3_REPLY)
    assert exc.value.category == "parse_error"
    assert "without a '### <filename>' header" in exc.value.message
