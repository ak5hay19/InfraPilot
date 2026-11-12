"""System prompt and message builder for the generator.

The prompt lives in system_prompt.txt next to this file (declared as package
data in pyproject.toml so it ships in non-editable installs).
"""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
EXAMPLE_START = "Reply:"


def load_system_prompt() -> str:
    # Raw bytes + explicit utf-8: no locale decoding (cp1252 on Windows) and no
    # newline translation, so a CRLF checkout would show up as "\r" in the text.
    return PROMPT_PATH.read_bytes().decode("utf-8")


def build_messages(request: str) -> list[dict[str, str]]:
    request = request.strip()
    if not request:
        raise ValueError("request must not be empty")
    return [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": request},
    ]


def example_replies() -> list[str]:
    """The reply text of each example in the prompt. Used only by tests.

    A reply starts after a line that is exactly 'Reply:' and ends before the next
    line starting with 'EXAMPLE ' (or at the end of the prompt).
    """
    replies: list[str] = []
    current: list[str] | None = None
    for line in load_system_prompt().split("\n"):
        if line.startswith("EXAMPLE "):
            if current is not None:
                replies.append("\n".join(current).strip())
            current = None
        elif current is not None:
            current.append(line)
        elif line == EXAMPLE_START:
            current = []
    if current is not None:
        replies.append("\n".join(current).strip())
    if not replies:
        raise ValueError(f"system prompt has no '{EXAMPLE_START}' line")
    return replies
