"""Turn a raw model reply into Terraform files.

Format: each file is a header line naming it ("### main.tf"; 1-6 '#', optional
backticks and trailing colon) followed, blank lines allowed, by a fenced code
block. Only main.tf (required) and outputs.tf (optional) are accepted; the
runner owns providers.tf and variables.tf. Other text is kept as a warning.

Truncation is checked by the caller (ModelResponse.truncated) BEFORE parsing:
a cut-off reply is a "truncated" failure, not a parse failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ALLOWED_FILES = ("main.tf", "outputs.tf")
REQUIRED_FILES = ("main.tf",)
CATEGORIES = ("parse_error", "provider_block_written")
KNOWN_LANGS = ("hcl", "terraform", "tf", "")

_HEADER_RE = re.compile(r"^\s*#{1,6}\s+`?([^\s`:]+)`?:?\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,})([^`]*)$")
_PROVIDER_RE = re.compile(r'^\s*provider\s+"')
_TERRAFORM_RE = re.compile(r"^\s*terraform\s*\{")


class ParseError(Exception):
    """The reply cannot be turned into files. `category` is the failure type."""

    def __init__(self, category: str, message: str) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown parse failure category: {category}")
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class ParseResult:
    # frozen only stops reassigning the fields; the containers stay mutable.
    files: dict[str, str] = field(default_factory=dict)  # filename -> contents
    warnings: list[str] = field(default_factory=list)  # non-fatal oddities


def _fail(message: str) -> ParseError:
    return ParseError("parse_error", message)


def _normalize(body: list[str]) -> str:
    lines = [line.rstrip() for line in body]
    return "\n".join(lines).rstrip("\n") + "\n"


def parse_reply(text: str) -> ParseResult:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    files: dict[str, str] = {}
    warnings: list[str] = []
    prose_lines = 0
    pending: str | None = None  # filename from a header not yet followed by a fence

    i = 0
    while i < len(lines):
        line = lines[i]

        fence = _FENCE_RE.match(line)
        if fence:
            if pending is None:
                raise _fail(
                    f"line {i + 1}: code block without a '### <filename>' header"
                )
            name, pending = pending, None
            if name not in ALLOWED_FILES:
                raise _fail(
                    f"file '{name}' is not allowed; allowed: "
                    f"{', '.join(ALLOWED_FILES)} (providers.tf and variables.tf "
                    "are written by the runner)"
                )
            if name in files:
                raise _fail(f"duplicate file '{name}'")

            ticks, info = fence.groups()
            words = info.split()
            lang = words[0] if words else ""
            if lang.lower() not in KNOWN_LANGS:
                warnings.append(f"unexpected code fence language '{lang}' in {name}")

            closer = re.compile(rf"^\s*`{{{len(ticks)},}}\s*$")
            j = i + 1
            body: list[str] = []
            while j < len(lines) and not closer.match(lines[j]):
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                raise _fail(
                    f"unclosed code fence for '{name}' (opened at line {i + 1})"
                )
            if not "".join(body).strip():
                raise _fail(f"empty code block for '{name}'")

            files[name] = _normalize(body)
            i = j + 1
            continue

        header = _HEADER_RE.match(line)
        if header:
            if pending is not None:
                prose_lines += 1  # an earlier header that never got a block
            pending = header.group(1)
        elif line.strip():
            if pending is not None:
                prose_lines += 1
                pending = None
            prose_lines += 1
        i += 1

    if pending is not None:
        prose_lines += 1
    if prose_lines:
        warnings.append(f"prose outside code blocks ({prose_lines} lines)")

    if not files:
        raise _fail(
            "no files found: expected '### main.tf' followed by a fenced code block"
        )
    for required in REQUIRED_FILES:
        if required not in files:
            raise _fail(f"{required} is missing (found only: {', '.join(files)})")

    for name, content in files.items():
        for number, line in enumerate(content.split("\n"), start=1):
            if _PROVIDER_RE.match(line) or _TERRAFORM_RE.match(line):
                raise ParseError(
                    "provider_block_written",
                    f"{name} line {number}: model wrote a provider/terraform block "
                    f"({line.strip()}); the runner owns providers.tf",
                )

    return ParseResult(files=files, warnings=warnings)
