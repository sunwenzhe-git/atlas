#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— tests（H 类：测试现状与运行方式）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）。
本文件是**框架知识的合法落点**：适配器内部识别测试运行器与测试文件命名约定。

做法：按 app 探测测试配置（运行命令）与测试文件（类型 / 位置）；
「现状是否通过」属语义，留给 agent（本适配器只给机械字段）。

用法：
    python3 tests.py --root <代码根> [--app <name>] --out <json 路径>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (  # noqa: E402
    die, iter_files, load_apps, resolve_app, write_json,
)

ADAPTER = "tests"
VERSION = "0.1.0"

PY_TEST_RE = re.compile(r"^test_.+\.py$|^.+_test\.py$")
JS_TEST_RE = re.compile(r"\.(spec|test)\.(js|jsx|ts|tsx)$")
PYTEST_CONFIG = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py"}
PLAYWRIGHT_CONFIG = {"playwright.config.js", "playwright.config.ts"}
JS_CONFIG = {"vitest.config.js", "vitest.config.ts", "jest.config.js", "jest.config.ts", "package.json"}


def classify(rel: str, playwright: bool) -> str:
    low = rel.lower()
    if "e2e" in low:
        return "e2e"
    if playwright and JS_TEST_RE.search(low):
        return "e2e"
    if "integration" in low:
        return "integration"
    return "unit"


def has_npm_test(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data.get("scripts"), dict) and "test" in data["scripts"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--app", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        die(ADAPTER, f"--root 不是目录: {root}")
    apps = load_apps(root)
    app_path = resolve_app(root, apps, args.app, ADAPTER)

    configs: set[str] = set()
    pytest_cfg = False
    playwright_cfg = False
    npm_cfg = False
    test_files: list[str] = []

    for f in iter_files(root, (".py", ".ini", ".toml", ".cfg", ".js", ".ts", ".jsx", ".tsx", ".json"), app_path):
        rel = f.relative_to(root).as_posix()
        name = f.name
        if name in PYTEST_CONFIG:
            pytest_cfg = True
            configs.add(rel)
        if name in PLAYWRIGHT_CONFIG:
            playwright_cfg = True
            configs.add(rel)
        if name in JS_CONFIG:
            if name == "package.json":
                if has_npm_test(f):
                    npm_cfg = True
                    configs.add(rel)
            else:
                configs.add(rel)
        if PY_TEST_RE.match(name) or JS_TEST_RE.search(name):
            test_files.append(rel)

    if playwright_cfg:
        run_command = "npx playwright test"
    elif pytest_cfg:
        run_command = "pytest"
    elif npm_cfg:
        run_command = "npm test"
    else:
        run_command = None

    items = [{
        "type": classify(rel, playwright_cfg),
        "location": rel,
        "run_command": run_command,
        "status": None,
    } for rel in sorted(set(test_files))]

    write_json(ADAPTER, args.out, {
        "category": "tests",
        "items": items,
        "source_files": sorted(configs),
        "adapter_version": VERSION,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
