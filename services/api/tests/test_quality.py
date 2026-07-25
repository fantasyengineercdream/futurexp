from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "services" / "api" / "app"
README_PATH = ROOT / "services" / "api" / "README.md"


def test_production_code_contains_no_assert_statements() -> None:
    offending: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
            offending.append(str(path.relative_to(ROOT)))

    assert offending == []


def test_readme_warns_that_demo_must_not_be_exposed_publicly() -> None:
    content = README_PATH.read_text(encoding="utf-8")

    assert "127.0.0.1" in content
    assert "不得暴露公网" in content
