import re
from pathlib import Path

import pytest


def extract_python_codeblocks(text: str) -> list[tuple[str, int]]:
    pattern = re.compile(r"```(?:python|py)\s*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
    blocks: list[tuple[str, int]] = []
    for match in pattern.finditer(text):
        code = match.group(1)
        start_line = text.count("\n", 0, match.start(1)) + 1
        blocks.append((code, start_line))
    return blocks


README_TEXT = Path("README.md").read_text(encoding="utf-8")
PYTHON_BLOCKS = extract_python_codeblocks(README_TEXT)


@pytest.mark.parametrize(
    ("code", "start_line"),
    PYTHON_BLOCKS,
    ids=[f"README.md:L{ln}" for _, ln in PYTHON_BLOCKS],
)
def test_readme_codeblock_executes(code: str, start_line: int) -> None:
    namespace: dict[str, object] = {"__name__": "__main__"}
    compiled = compile(code, f"README.md:L{start_line}", "exec")
    exec(compiled, namespace)  # noqa: S102
