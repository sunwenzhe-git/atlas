#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— tests（H 类：测试现状与运行方式）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）。
本文件是**框架知识的合法落点**：适配器内部识别测试运行器与测试文件命名约定。

做法：探测测试配置与测试文件（类型 / 位置）；**运行命令逐条按测试文件的后缀族推定**，
配置只在同族内细化命令。「现状是否通过」属语义，留给 agent。

为何运行命令不能由配置文件名单独决定（2026-10-15 修，issue #4 现场实证）：接入项目根
有一份只声明 atlas `ac` marker 的 `pytest.ini`，而全仓唯一测试文件是 `.test.ts` ⇒ 旧实现

    { "location": "…/knowledge-param-utils.test.ts", "run_command": "python3 -m pytest" }

产出的是**错误事实**（对 `.test.ts` 给 Python 命令），且「非空且形态合法」⇒ 骗过 §6.2 的
接线前置（`§B118` 只识别「产出为空」那一类假绿灯）。更讽刺的是那份配置是 atlas 侧引入的，
反过来污染了 atlas 自己的事实抽取。

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
VERSION = "0.2.0"

PY_TEST_RE = re.compile(r"^test_.+\.py$|^.+_test\.py$")
JS_TEST_RE = re.compile(r"\.(spec|test)\.(js|jsx|ts|tsx)$")
PYTEST_CONFIG = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py"}
PLAYWRIGHT_CONFIG = {"playwright.config.js", "playwright.config.ts"}
JS_CONFIG = {"vitest.config.js", "vitest.config.ts", "jest.config.js", "jest.config.ts", "package.json"}

# 配置探测扫**整项目**（配置是项目级的，不随 app 变）；测试文件盘点按 app 作用域。
CONFIG_SUFFIXES = (".py", ".ini", ".toml", ".cfg", ".js", ".ts", ".jsx", ".tsx", ".json")
TEST_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx")

RUN_PYTEST = "python3 -m pytest"
RUN_PLAYWRIGHT = "npx playwright test"
RUN_VITEST = "npx vitest run"
RUN_JEST = "npx jest"
RUN_NPM = "npm test"


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
    vitest_cfg = False
    jest_cfg = False

    # ① 配置探测：**整项目范围**。`--app` 下若只扫 app 目录，落在项目根的
    #    `pytest.ini` / `playwright.config.ts` 会被漏掉 ⇒ 逐 app 调用（域级类别的主路径）
    #    把 run_command 静默降级成 null。
    for f in iter_files(root, CONFIG_SUFFIXES, None):
        name = f.name
        rel = f.relative_to(root).as_posix()
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
                vitest_cfg = vitest_cfg or name.startswith("vitest")
                jest_cfg = jest_cfg or name.startswith("jest")

    # ② 测试文件盘点：app 作用域。
    test_files: list[str] = []
    for f in iter_files(root, TEST_SUFFIXES, app_path):
        if PY_TEST_RE.match(f.name) or JS_TEST_RE.search(f.name):
            test_files.append(f.relative_to(root).as_posix())

    node_cfg = playwright_cfg or npm_cfg or vitest_cfg or jest_cfg

    def runner_for(rel: str) -> tuple[str | None, str | None]:
        """(run_command, 冲突说明)。说明非空 ⇒ run_command 置 null 并打 WARN。

        冲突 = 测试文件的后缀族与仓里**唯一**存在的配置族相反。此时**不产矛盾条目**：
        item 仍出（测试文件存在是事实），命令留空（不作主张），并出声点明。
        完全没配置 ⇒ 命令也留空但**不打 WARN**——那是既有正常形态（契约里 `run_command` 本就可空）。
        """
        if PY_TEST_RE.match(Path(rel).name):
            if pytest_cfg:
                return RUN_PYTEST, None
            if node_cfg:
                return None, (f"{rel}：Python 测试文件，但仓里只有 JS/TS 侧测试配置"
                              f"（后缀族与配置族冲突，不合成命令）")
            return None, None
        if playwright_cfg:
            return RUN_PLAYWRIGHT, None
        if vitest_cfg:
            return RUN_VITEST, None
        if jest_cfg:
            return RUN_JEST, None
        if npm_cfg:
            return RUN_NPM, None
        if pytest_cfg:
            return None, (f"{rel}：TS/JS 测试文件，但仓里只有 pytest 配置"
                          f"——对 .test.ts 给出 `{RUN_PYTEST}` 是错误事实（issue #4 现场）")
        return None, None

    items = []
    conflicts: list[str] = []
    for rel in sorted(set(test_files)):
        cmd, why = runner_for(rel)
        if why:
            conflicts.append(why)
        items.append({
            "type": classify(rel, playwright_cfg),
            "location": rel,
            "run_command": cmd,
            "status": None,
        })

    # 出声但**不置非零退出**：非零退出会被 `refresh_structure --chain` 当成适配器失败而中止
    # 整条链（`_lib.die` 是 exit 1）——一个该降级的盘点不该砍掉收口。
    for why in conflicts:
        print(f"WARN[{ADAPTER}]: 运行命令未取定 —— {why}", file=sys.stderr)

    write_json(ADAPTER, args.out, {
        "category": "tests",
        "items": items,
        "source_files": sorted(configs),
        "adapter_version": VERSION,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
