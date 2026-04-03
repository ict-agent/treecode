"""Output style loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openharness.config.paths import get_config_dir


@dataclass(frozen=True)
class OutputStyle:
    """A named output style."""

    name: str
    content: str
    source: str


def get_output_styles_dir() -> Path:
    """Return the custom output styles directory."""
    path = get_config_dir() / "output_styles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_output_styles() -> list[OutputStyle]:
    """Load bundled and custom output styles."""
    styles = [
        OutputStyle(
            name="default",
            content="Standard rich console output. Be concise and direct. Prefer short responses unless detail is requested.",
            source="builtin",
        ),
        OutputStyle(
            name="minimal",
            content="Very terse plain-text output. Focus strictly on the results of commands and minimal explanation.",
            source="builtin",
        ),
        OutputStyle(
            name="explanatory",
            content="Explain your implementation choices and codebase patterns in detail. Help the user understand the 'why' behind the changes.",
            source="builtin",
        ),
        OutputStyle(
            name="learning",
            content="Pause and ask the user to write small pieces of code for hands-on practice. Guide them through the implementation step-by-step, acting as a mentor.",
            source="builtin",
        ),
    ]
    for path in sorted(get_output_styles_dir().glob("*.md")):
        styles.append(
            OutputStyle(
                name=path.stem,
                content=path.read_text(encoding="utf-8"),
                source="user",
            )
        )
    return styles
