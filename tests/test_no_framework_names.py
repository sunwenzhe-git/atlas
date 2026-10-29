#!/usr/bin/env python3
"""守恒：`validators/` 不得出现具体测试框架名 / pytest 文件命名约定。

`shared/global-rules.md` §1：框架知识只有两个合法来源——项目 `stack-profile.yaml`
与 `adapters/`；validator 只消费归一化记录。本测试用 AST 做标识符/导入级匹配，
不做裸子串匹配（避免 `expression` 命中 `express` 这类假红）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
DENYLIST = {
    "pytest", "jest", "vitest", "junit", "junit5", "testng", "spring", "fastapi",
    "flask", "django", "nestjs", "express", "mocha",
}
TEXT_RE = re.compile(r"\b(?:pytest|jest|vitest|junit\d*|testng|mocha)\b", re.I)
TEXT_EXTS = {".md", ".yaml", ".yml", ".html"}
SCAN_DIRS = ("shared", "rings", "templates", "patches")


def _finding_for_source(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DENYLIST:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in DENYLIST:
                hits.append(f"from {node.module}")
            for alias in node.names:
                if alias.name in DENYLIST:
                    hits.append(f"from {node.module or ''} import {alias.name}")
        elif isinstance(node, ast.Name) and node.id in DENYLIST:
            hits.append(f"Name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in DENYLIST:
            hits.append(f"Attribute .{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in DENYLIST:
            hits.append(f"string {node.value!r}")
    return hits


def test_validators_have_no_framework_names() -> None:
    bad: list[str] = []
    for path in sorted((PKG_ROOT / "validators").glob("*.py")):
        for hit in _finding_for_source(path.read_text(encoding="utf-8")):
            bad.append(f"{path.relative_to(PKG_ROOT)}: {hit}")
    assert not bad, "validators/ 出现框架名：\n" + "\n".join(bad)


def test_expression_is_not_express() -> None:
    assert _finding_for_source("expression = 1\n") == []
    assert not TEXT_RE.search("expression = 1")


def test_ac_validator_has_no_pytest_file_convention() -> None:
    source = (PKG_ROOT / "validators" / "validate_ac_alignment.py").read_text(encoding="utf-8")
    for needle in ("test_*.py", "import ast", "pytestmark", "skipif",
                   "PyTestACVisitor", "pytest.mark"):
        assert needle not in source, f"validate_ac_alignment.py 仍含 {needle!r}"


def test_shared_rings_templates_patches_have_no_framework_names() -> None:
    bad: list[str] = []
    for dirname in SCAN_DIRS:
        base = PKG_ROOT / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix in {".pyc"}:
                continue
            rel = path.relative_to(PKG_ROOT).as_posix()
            if path.suffix == ".py":
                for hit in _finding_for_source(path.read_text(encoding="utf-8")):
                    bad.append(f"{rel}: {hit}")
            elif path.suffix in TEXT_EXTS:
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    for m in TEXT_RE.finditer(line):
                        bad.append(f"{rel}:{i} 含 {m.group(0)!r}")
    assert not bad, "契约/模板/补丁出现测试框架名：\n" + "\n".join(bad)
