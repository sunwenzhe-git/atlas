#!/usr/bin/env python3
"""E2E 用例评审控制台（随包工具）的回归测试。

守护三件事（`3509 §B16` → `rings/e2e/reference.md` §10.1）：
  ① 控制台**在包内可启动**（不再是项目私有产物）；
  ② 静态资源能**从包内模板目录**取出——这是「随包分发」最容易漏的一环；
  ③ `/api/cases` 在用例真相源缺失时**如实报 problem**，不得静默空表。

    python3 atlas/tests/test_e2e_console.py
    pytest atlas/tests/test_e2e_console.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CONSOLE = PKG_ROOT / "scripts" / "e2e_console.py"
ASSETS = PKG_ROOT / "templates" / "e2e" / "console"


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_project(td: Path) -> Path:
    """迷你项目：`.atlas/{validators,scripts}` + `product/stack-profile.yaml`。

    与 `install.sh` 的落点一致——控制台按 `<root>/.atlas/...` 找解析器。
    """
    (td / ".atlas" / "validators").mkdir(parents=True)
    (td / ".atlas" / "scripts").mkdir(parents=True)
    shutil.copy(PKG_ROOT / "validators" / "validate_e2e_index.py", td / ".atlas" / "validators")
    shutil.copy(PKG_ROOT / "scripts" / "gen_e2e_scripts.py", td / ".atlas" / "scripts")
    (td / "product" / "e2e").mkdir(parents=True)
    # 最小合法索引（列头取契约常量，不手抄）——snapshot 靠列头对齐就会大声报错
    v = load("validate_e2e_index", "validators/validate_e2e_index.py")
    cols = list(v.MAIN_COLUMNS)
    (td / "product" / "e2e" / "e2e-index.md").write_text(
        "# E2E 索引\n\n| " + " | ".join(cols) + " |\n| " + " | ".join(["---"] * len(cols)) + " |\n",
        encoding="utf-8",
    )
    (td / "product" / "stack-profile.yaml").write_text(
        "product: demo\napps: []\ne2e:\n  app_base_url: http://127.0.0.1:9000\n",
        encoding="utf-8",
    )
    (td / "product" / "e2e" / "manual.md").write_text(
        "# 手工走查项\n\n- M-DEMO-001 | home | 演示手工项 | 自己点一遍\n",
        encoding="utf-8",
    )
    return td


def free_port() -> int:
    """**不要**用固定端口：4190 上可能已經跑着另一个控制台（实测踩到——本用例会去
    读别人的项目数据，断言看似“控制台能跑”实则测的不是本 fixture）。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def opener():
    """回环地址必须**直连**：环境里若设了 `HTTP_PROXY`，`urlopen` 会把 127.0.0.1 的请求
    也送去代理（本机实测 `HTTP Error 502` ⇒ 断言实际测的是代理而不是被测服务器）。
    显式绕代理，本用例才在测它声称测的东西。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def test_console_serves_from_package() -> None:
    assert CONSOLE.is_file(), "控制台脚本必须随包（.atlas/scripts/e2e_console.py）"
    assert (ASSETS / "index.html").is_file(), "控制台静态资源必须随包（.atlas/templates/e2e/console/）"

    with tempfile.TemporaryDirectory() as tmp:
        root = build_project(Path(tmp))
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(CONSOLE), "--root", str(root), "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            op = opener()
            page = None
            for _ in range(60):  # 有界等待启动（最多 ~6s）
                try:
                    page = op.open(base + "/", timeout=2).read()
                    break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(0.1)
            assert page is not None, "控制台未能在 6s 内启动"
            assert b"<html" in page.lower(), "根路径没有返回控制台页面"

            cases = json.loads(op.open(base + "/api/cases?source=app", timeout=5).read())
            assert "sources" in cases, cases
            assert cases.get("problem") is None, f"最小合法索引不应报 problem：{cases.get('problem')}"
            assert cases.get("cases") == [], cases.get("cases")
            assert cases["sources"]["app"]["base_url"] == "http://127.0.0.1:9000", cases
            # 手工项（用户 2026-10-01 设计）：payload 携带 manual.md 条目
            assert cases["manual"] == [
                {"id": "M-DEMO-001", "page": "home", "title": "演示手工项", "note": "自己点一遍"},
            ], cases.get("manual")
            assert "prototype" not in cases["sources"], cases["sources"]

            for asset in ("/app.js", "/console.css"):
                body = op.open(base + asset, timeout=5).read()
                assert body, f"{asset} 取不到（静态资源没随包）"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()


def main() -> int:
    tests = [test_console_serves_from_package]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


def test_snapshot_carries_mock_lines_for_badge() -> None:
    """契约 §5.8 桩披露（2026-10-12）：snapshot 把分片 `mock:` 行随用例带给前端——
    MOCKED 徽标的数据面（静态事实 = 用例声明了桩；运行时命中由 `[atlas-mock]` 日志行承载）。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = build_project(Path(tmp))
        v = load("validate_e2e_index", "validators/validate_e2e_index.py")
        cols = list(v.MAIN_COLUMNS)
        (root / "product" / "e2e" / "e2e-index.md").write_text(
            "# E2E 索引\n\n| " + " | ".join(cols) + " |\n| " + " | ".join(["---"] * len(cols)) + " |\n"
            "| E2E-USERS-001 | users | 空态缺省页 | acceptance | AC-U-001 | | red | | "
            "[cases/users.md#e2e-users-001](cases/users.md#e2e-users-001) |\n", encoding="utf-8")
        (root / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
        (root / "product" / "e2e" / "cases" / "users.md").write_text(
            "# users 页面用例\n\n## E2E-USERS-001 空态缺省页\n\n```atlas-case\n"
            "id: E2E-USERS-001\nintent: 列表为空时渲染缺省占位\npages:\n  - users\n"
            "mock:\n  - GET /api/v1/users -> fixtures/users/empty.json\n"
            "step:\n  - goto /users\nexpected:\n  - visible users-empty-placeholder\n"
            "testid:\n  - users-empty-placeholder\n```\n", encoding="utf-8")
        snap = cons.snapshot(root)
        case = next(c for c in snap["cases"] if c["id"] == "E2E-USERS-001")
        assert case["mock"] == ["GET /api/v1/users -> fixtures/users/empty.json"], case["mock"]


def test_node_ids_extracts_ts_lines_and_skips_blocked() -> None:
    """契约 §10.1（2026-10-12 迁移批）：node_ids() 解析 .spec.ts 中的行号，
    作为 Playwright 原生单用例过滤标记（file:line）；且 test.skip（blocked 用例）
    与零步基线不被匹配。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        scripts = Path(td)
        (scripts / "demo.spec.ts").write_text(
            "import { test } from './atlas-hold';\n"
            "test('test_demo__zero_step_baseline', async ({ page }) => {});\n"
            "test('E2E-DEMO-001 正常用例', async ({ page }) => {\n"
            "  await page.goto('/');\n"
            "});\n"
            "test.skip('E2E-DEMO-002 blocked用例', async ({ page }) => {\n"
            "});\n",
            encoding="utf-8"
        )
        mapping = cons.node_ids(scripts)
        assert mapping == {"E2E-DEMO-001": "demo.spec.ts:3"}, mapping


def test_resolve_pw_and_runner_fail_loud_on_missing_executable() -> None:
    """契约 §10.1：Runner 解析不到可执行文件时诚实拒绝，不起盲目失败的子进程。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 无 profile
        pw, nm, why = cons.resolve_pw(root)
        assert pw is None and "stack-profile.yaml" in why

        # profile 未声明 e2e.node_modules
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e: { runner: node-playwright }\n", encoding="utf-8"
        )
        pw, nm, why = cons.resolve_pw(root)
        assert pw is None and "node_modules" in why

        # runner.start 必须直接返回 False 并告知原因
        ledger = cons.Ledger(root, "tester")
        runner = cons.Runner(root, ledger, timeout=60, head=True)
        ok, reason = runner.start({"id": "E2E-DEMO-001"}, "demo.spec.ts:3", 500, "app", "http://127.0.0.1:8000")
        assert not ok
        assert "node-playwright 不可用" in reason
