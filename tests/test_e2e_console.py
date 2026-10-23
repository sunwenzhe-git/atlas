#!/usr/bin/env python3
"""E2E 用例评审控制台（随包工具）的回归测试。

守护三件事（`3509 §B16` → `rings/e2e/reference.md` §10.1）：
  ① 控制台**在包内可启动**（不再是项目私有产物）；
  ② 静态资源能**从包内模板目录**取出——这是「随包分发」最容易漏的一环；
  ③ `/api/cases` 在用例真相源缺失时**如实报 problem**，不得静默空表。

    python3 tests/test_e2e_console.py
    pytest tests/test_e2e_console.py
"""

from __future__ import annotations

import importlib.util
import json
import os
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
            # 存在性披露（RFC-20261015-01）：文件在 ⇒ created
            assert cases["manual_state"] == "created", cases.get("manual_state")
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


def test_manual_absence_is_disclosed_not_silent() -> None:
    """`manual.md` 不存在 ⇒ payload 带 `manual_state: "missing"`（前端据此在 meta 行显式披露
    「未创建」）。`RFC-20261015-01` / issue #10：文件缺失 = 空清单不阻塞不变，但「没有」
    与「忘了」不得同形——明确级别的暴露载体。变异证明 **M73**：摘掉 `manual_state` 通道
    ⇒ 本用例红（回落静默空栏）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = build_project(Path(tmp))
        (root / "product" / "e2e" / "manual.md").unlink()      # 夹具前提：清单未创建
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(CONSOLE), "--root", str(root), "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            op = opener()
            page = None
            for _ in range(60):
                try:
                    page = op.open(base + "/", timeout=2).read()
                    break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(0.1)
            assert page is not None
            cases = json.loads(op.open(base + "/api/cases?source=app", timeout=5).read())
            assert cases["manual"] == [], cases.get("manual")
            assert cases["manual_state"] == "missing", cases.get("manual_state")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()


def main() -> int:
    tests = [test_console_serves_from_package, test_manual_absence_is_disclosed_not_silent]
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


def test_resolve_pw_and_runner_fail_loud_on_missing_executable(monkeypatch) -> None:
    """契约 §10.1：Runner 解析不到可执行文件时诚实拒绝，不起盲目失败的子进程。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    monkeypatch.setattr(cons.shutil, "which", lambda cmd: None)
    monkeypatch.delenv("NODE_PATH", raising=False)
    monkeypatch.setattr(cons.subprocess, "run", lambda *args, **kwargs: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 无 profile
        pw, nm, why, _note = cons.resolve_pw(root)
        assert pw is None and "stack-profile.yaml" in why

        # profile 未声明 e2e.node_modules
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e: { runner: node-playwright }\n", encoding="utf-8"
        )
        pw, nm, why, _note = cons.resolve_pw(root)
        assert pw is None and "node_modules" in why

        # runner.start 必须直接返回 False 并告知原因
        ledger = cons.Ledger(root, "tester")
        runner = cons.Runner(root, ledger, timeout=60, head=True)
        ok, reason = runner.start({"id": "E2E-DEMO-001"}, "demo.spec.ts:3", 500, "app", "http://127.0.0.1:8000")
        assert not ok
        assert "node-playwright 不可用" in reason


def test_runner_injects_slowmo_via_env_not_cli_flag() -> None:
    """F11（2026-10-14）：Playwright `test` 子命令**没有** `--slowmo` 旗标
    （1.64 实测 `unknown option '--slowmo=…'`，回放直接 exit 1）——慢动作经
    `ATLAS_SLOWMO` 环境变量注入生成配置的 `launchOptions.slowMo`。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    captured: dict = {}

    class FakeProc:
        stdout = iter(())
        returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(cmd, cwd=None, stdout=None, stderr=None, text=None, bufsize=None, env=None):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(env or {})
        return FakeProc()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger = cons.Ledger(root, "tester")
        runner = cons.Runner(root, ledger, timeout=60, head=True, keep_open=False)
        orig = cons.subprocess.Popen
        cons.subprocess.Popen = fake_popen
        try:
            runner._run({"id": "E2E-DEMO-001"}, "demo.spec.ts:3", 700, "app",
                        "http://127.0.0.1:8000",
                        Path("/nonexistent/playwright"), Path("/nonexistent/nm"))
        finally:
            cons.subprocess.Popen = orig

    assert not any(str(a).startswith("--slowmo") for a in captured["cmd"]), captured["cmd"]
    assert "--headed" in captured["cmd"], captured["cmd"]
    assert captured["env"].get("ATLAS_SLOWMO") == "700", captured["env"]
    assert captured["env"].get("ATLAS_BASE_URL") == "http://127.0.0.1:8000"


def test_runner_disables_playwright_test_timeout_only_in_hold_mode() -> None:
    """D126（2026-10-21）：Playwright 默认 test timeout（30s）**覆盖 fixture teardown**——
    `atlas-hold.ts` 的留窗等待会在约 30s 处被判超时并强制关窗（实测：
    `Tearing down "atlasHold" exceeded the test timeout of 30000ms`）⇒ 用户看到「跑完仍自动
    关闭」。持窗模式必须传 `--timeout=0`，让控制台的 wall-clock `--timeout` 成为唯一超时
    真相源；自动关窗模式不传，保留运行器原生 30s 兜底（防孤儿进程）。

    变异 **M127**：摘掉持窗分支的 `--timeout=0` ⇒ 本钉红，还原逐字节一致。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")

    class FakeProc:
        stdout = iter(())
        returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            pass

    def run_with(keep_open: bool) -> tuple[list[str], dict]:
        captured: dict = {}

        def fake_popen(cmd, cwd=None, stdout=None, stderr=None, text=None, bufsize=None, env=None):
            captured["cmd"] = list(cmd)
            captured["env"] = dict(env or {})
            return FakeProc()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = cons.Ledger(root, "tester")
            runner = cons.Runner(root, ledger, timeout=60, head=True, keep_open=keep_open)
            orig = cons.subprocess.Popen
            cons.subprocess.Popen = fake_popen
            try:
                runner._run({"id": "E2E-DEMO-001"}, "demo.spec.ts:3", 0, "app",
                            "http://127.0.0.1:8000",
                            Path("/nonexistent/playwright"), Path("/nonexistent/nm"))
            finally:
                cons.subprocess.Popen = orig
        return captured["cmd"], captured["env"]

    hold_cmd, hold_env = run_with(True)
    assert "--timeout=0" in hold_cmd, hold_cmd
    assert hold_env.get("ATLAS_KEEP_OPEN") == "1", hold_env

    auto_cmd, auto_env = run_with(False)
    assert "--timeout=0" not in auto_cmd, auto_cmd
    assert "ATLAS_KEEP_OPEN" not in auto_env, auto_env


# ── 2026-10-18 v3 现场实证移植批（D110）：执行前的项目数据准备钩子 ──────────────────────
def test_prepare_hook_runs_before_case_and_refuses_on_failure() -> None:
    """契约 §10「执行」（D110，v3 现场实证移植）：项目自带 `product/e2e/scripts/atlas-prepare.mjs`
    ⇒ 控制台**每条用例先跑它**（`node`，cwd = 项目根，180s 上限，且不占用例超时窗——在计时
    起点之前）；失败（非零）/ 起不动 ⇒ **拒绝执行该用例**并按 `done` 完整形状如实上报（带
    `prep_failed` 标记），真跑子进程**不得被启动**。共享状态型靶场的残留实体会让 count 类
    断言系统性偏移，拒跑优于静默跑偏。

    变异证明 **M94**：摘掉 prepare 钩子段（`if prep.is_file():` 恒假）⇒ 本钉红（真跑被起、
    无 `prep_failed`），还原逐字节一致。

    D121（2026-10-20）：prepare 子进程 env 必带 `ATLAS_CASE_ID` = 当前用例 ID——项目脚本据此
    只准备该用例依赖的数据，避免一组用例的前置缺失把无关用例挡在 prepare 阶段。变异 **M121**：
    摘掉 env 传参 ⇒ 本钉红（case 上下文丢失），还原逐字节一致。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    seen: dict = {"rc": 0}

    def fake_run(cmd, cwd=None, timeout=None, **kw):
        seen["calls"] = seen.get("calls", [])
        seen["calls"].append(("prepare", cmd[0], cwd, timeout,
                              (kw.get("env") or {}).get("ATLAS_CASE_ID"),
                              (kw.get("env") or {}).get("NODE_PATH")))
        if seen.get("explode"):
            raise subprocess.TimeoutExpired("node", 180)
        return type("Proc", (), {"returncode": seen["rc"], "stdout": "prep ok\n", "stderr": "err"})()

    class FakeProc:
        stdout = iter(())
        returncode = 0

        def poll(self) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(cmd, cwd=None, **kw):
        seen["calls"].append(("真跑", cmd[0]))
        return FakeProc()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "atlas-prepare.mjs").write_text("// prep\n", encoding="utf-8")
        ledger = cons.Ledger(root, "tester")
        runner = cons.Runner(root, ledger, timeout=60, head=True, keep_open=False)

        seen["calls"] = []
        seen["explode"], seen["rc"] = False, 0
        orig_run, orig_popen = cons.subprocess.run, cons.subprocess.Popen
        cons.subprocess.run, cons.subprocess.Popen = fake_run, fake_popen
        try:
            runner._run({"id": "E2E-PREP-001"}, "p.spec.ts:1", 500, "app",
                        "http://127.0.0.1:8000", Path("/pw"), Path("/nm"))
            # ① 钩子在真跑之前；参数形态钉死（node / cwd=项目根 / 180s / 用例 ID 经 env 传入 / NODE_PATH 注入）
            assert seen["calls"] == [
                ("prepare", "node", str(root), 180, "E2E-PREP-001", str(Path("/nm"))),
                ("真跑", "/pw"),
            ], seen["calls"]
            assert runner.done["ok"] is True, runner.done
            assert "prep_failed" not in runner.done, runner.done

            # ② prepare 非零 ⇒ 拒绝执行：真跑不被起，done 完整形状 + prep_failed
            seen["calls"], seen["rc"] = [], 3
            runner._run({"id": "E2E-PREP-002"}, "p.spec.ts:1", 500, "app",
                        "http://127.0.0.1:8000", Path("/pw"), Path("/nm"))
            assert [c for c in seen["calls"] if c[0] == "prepare"] == [
                ("prepare", "node", str(root), 180, "E2E-PREP-002", str(Path("/nm")))]
            assert not any(c[0] == "真跑" for c in seen["calls"]), seen["calls"]
            ev = runner.done
            assert ev["ok"] is False and ev["exit"] == 3 and ev["prep_failed"] is True, ev
            assert ev["timeout"] is False and ev["held"] is False, ev
            assert ev["case"] == "E2E-PREP-002" and ev["source"] == "app", ev
            assert "atlas-prepare 失败" in ev["tail"], ev["tail"]

            # ③ 起不动（node 缺失 / 超时抛出）⇒ 同样拒绝，exit 如实（−2）
            seen["calls"], seen["explode"] = [], True
            runner._run({"id": "E2E-PREP-003"}, "p.spec.ts:1", 500, "app",
                        "http://127.0.0.1:8000", Path("/pw"), Path("/nm"))
            assert runner.done["ok"] is False and runner.done["exit"] == -2, runner.done
            assert runner.done["prep_failed"] is True, runner.done
            assert not any(c[0] == "真跑" for c in seen["calls"]), seen["calls"]
        finally:
            cons.subprocess.run, cons.subprocess.Popen = orig_run, orig_popen


def test_resolve_pw_global_playwright(monkeypatch) -> None:
    """F19: 支持全局 Playwright（npm i -g @playwright/test）执行与 PATH 探测。

    当 stack-profile 未声明 node_modules 时，通过 shutil.which("playwright") 探测系统全局命令，
    并经 NODE_PATH 解析全局路径赋值给 NODE_PATH。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True)
        # 纯 Python 或存量项目：未声明 e2e.node_modules
        (root / "product" / "stack-profile.yaml").write_text(
            "product: legacy-python\napps: []\ne2e:\n  runner: node-playwright\n", encoding="utf-8"
        )
        fake_pw = root / "fake-global-bin" / "playwright"
        fake_pw.parent.mkdir(parents=True)
        fake_pw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_pw.chmod(0o755)

        fake_global_nm = root / "fake-global-node-modules"
        fake_global_nm.mkdir(parents=True)
        (fake_global_nm / "@playwright" / "test").mkdir(parents=True)

        monkeypatch.setattr(cons.shutil, "which", lambda cmd: str(fake_pw) if cmd == "playwright" else None)
        monkeypatch.setenv("NODE_PATH", str(fake_global_nm))

        pw, nm, why, _note = cons.resolve_pw(root)
        assert why == "", why
        assert pw == fake_pw, pw
        assert nm == fake_global_nm, nm
        assert _note == "", _note


def test_resolve_pw_ignores_python_playwright_without_node_module(monkeypatch) -> None:
    """F19 加固：当系统命中 Python Playwright CLI 时，若无 Node 全局模块，不得采信该 global_pw。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: legacy-python\napps: []\ne2e:\n  runner: node-playwright\n", encoding="utf-8"
        )
        fake_py_pw = root / "fake-python-bin" / "playwright"
        fake_py_pw.parent.mkdir(parents=True)
        fake_py_pw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_py_pw.chmod(0o755)

        monkeypatch.setattr(cons.shutil, "which", lambda cmd: str(fake_py_pw) if cmd == "playwright" else None)
        monkeypatch.delenv("NODE_PATH", raising=False)
        monkeypatch.setattr(cons.subprocess, "run", lambda *args, **kwargs: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())

        pw, nm, why, _note = cons.resolve_pw(root)
        assert pw is None, f"不应采信 Python Playwright: {pw}"
        assert "stack-profile 未声明 e2e.node_modules" in why, why



def _mk_resolvable_pw_module(nm: Path, version: str = "9.9.9") -> Path:
    """在 `nm` 下造一个**真能被 Node 解析**的 `@playwright/test`（issue #24 夹具）。

    判据本体 = 「从 scripts 出发 `@playwright/test` 可解析」⇒ 空目录糊弄不过去。
    """
    pkg = nm / "@playwright" / "test"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@playwright/test", "version": version,
                    "main": "index.js", "exports": "./index.js"}),
        encoding="utf-8")
    (pkg / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
    return pkg


def _global_pw_fixture(root: Path, cons, monkeypatch):
    """全局兜底夹具：伪全局 bin + **真包**的全局 `@playwright/test`。

    `shutil.which` 只接管 `playwright`（其余透传原实现）——探针自己要找 `node`，
    整包置 None 会把「模块不可解析」换成「探针跑不起来」（两种红不同因）。
    """
    fake_pw = root / "fake-global-bin" / "playwright"
    fake_pw.parent.mkdir(parents=True, exist_ok=True)
    fake_pw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_pw.chmod(0o755)
    g_nm = root / "fake-global-node-modules"
    pkg = _mk_resolvable_pw_module(g_nm)
    real_which = shutil.which
    monkeypatch.setattr(cons.shutil, "which",
                        lambda cmd: str(fake_pw) if cmd == "playwright" else real_which(cmd))
    monkeypatch.setenv("NODE_PATH", str(g_nm))
    return fake_pw, g_nm, pkg


def test_resolve_pw_repairs_unresolvable_module_from_global(monkeypatch) -> None:
    """issue #24（**执行器侧**）：判据本体 = 「生成物能不能 import 到 `@playwright/test`」。

    现场（百炼/v2前端，`package.json` 有 `"type": "module"`）：全局兜底（F19）找得到 binary，
    但 Node 的 ESM 解析器**不读 `NODE_PATH`** ⇒ 模块解析不到，错误落到运行期。本钉子锁三件：
    ① `repair=False`（纯解析口径）不写盘、不给 note；
    ② `repair=True` 在 **Node 的搜索路径**上补软链 + 复检通过 ⇒ note 点名全局与补链位置；
    ③ 第二次调用幂等（同物不动且 note 不变）。

    变异证明：摘掉 `_support/pw_runner.py` 的软链步 ⇒ ② 红（仍报不可解析，且 note 为空）。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e:\n  runner: node-playwright\n", encoding="utf-8")
        (root / "product" / "e2e" / "scripts").mkdir(parents=True)
        fake_pw, _g_nm, pkg = _global_pw_fixture(root, cons, monkeypatch)
        if not shutil.which("node"):
            # 无 node ⇒ 探针无法运行：此时必须走「如实拒绝」，不得当成修好了
            _p, _n, why, _note = cons.resolve_pw(root, repair=True)
            assert _p is None and "node" in why, why
            return

        # ① 纯解析：不写盘、无 note
        pw, _nm, why, note = cons.resolve_pw(root)
        assert pw == fake_pw and why == "" and note == "", (pw, why, note)
        assert not (root / "node_modules").exists(), "纯解析不得写盘"

        # ② 修复 + 复检
        pw, _nm, why, note = cons.resolve_pw(root, repair=True)
        assert pw == fake_pw and why == "", (pw, why)
        assert "@playwright/test" in note and "软链" in note, note
        link = root / "node_modules" / "@playwright" / "test"
        assert link.is_symlink(), f"应在解析搜索路径上补软链：{link}"
        assert os.path.realpath(link) == os.path.realpath(pkg)

        # ③ 幂等：第二次不再动手（同物不动），而「用了机器全局状态」这个**前提事实**照样读得回
        before = os.path.realpath(link)
        pw2, _nm2, _why2, note2 = cons.resolve_pw(root, repair=True)
        assert pw2 == fake_pw, pw2
        assert os.path.realpath(link) == before, "幂等：软链不得被重建/改动"
        assert "@playwright/test" in note2 and "全局" in note2, (
            f"第二次调用必须仍能读回「用了机器全局状态」这一前提事实（实际 note={note2!r}）")


def test_resolve_pw_refuses_when_module_unresolvable_without_global(monkeypatch) -> None:
    """issue #24：本地 binary 在、模块不在，且无全局兜底 ⇒ **不得**默默开跑（旧行为 = 放行）。

    这是把「运行期跑失败 / 无结果」提前成「起跑前如实拒绝」的那一半。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e" / "scripts").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e:\n  runner: node-playwright\n"
            "  node_modules: node_modules\n", encoding="utf-8")
        pw = root / "node_modules" / ".bin" / "playwright"
        pw.parent.mkdir(parents=True)
        pw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        pw.chmod(0o755)
        real_which = shutil.which
        monkeypatch.setattr(cons.shutil, "which",
                            lambda cmd: None if cmd == "playwright" else real_which(cmd))
        monkeypatch.delenv("NODE_PATH", raising=False)
        monkeypatch.setattr(cons.subprocess, "run",
                            lambda *a, **k: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())
        p, _nm, why, note = cons.resolve_pw(root, repair=True)
        assert p is None, (p, why)
        assert "不可解析" in why or "node" in why, why
        assert note == "", note


def test_resolve_pw_refuses_to_clobber_foreign_path(monkeypatch) -> None:
    """坏输入：解析路径上已有**非本工具所建**的 `@playwright/test` ⇒ 拒绝，不覆盖。

    （修复手段是软链；链接位被人占着时静默覆盖 = 替人删文件。）
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e" / "scripts").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e:\n  runner: node-playwright\n", encoding="utf-8")
        foreign = root / "node_modules" / "@playwright" / "test"
        foreign.parent.mkdir(parents=True)
        foreign.symlink_to(root / "nowhere-else")   # 悬空符号链接：探针不过、修复也不得覆盖
        _fake_pw, _g_nm, _pkg = _global_pw_fixture(root, cons, monkeypatch)
        if not shutil.which("node"):
            return
        p, _nm, why, note = cons.resolve_pw(root, repair=True)
        assert p is None, (p, why)
        assert "占用" in why, why
        assert note == "", note
        assert os.path.realpath(str(foreign)) == os.path.realpath(str(root / "nowhere-else"))


# ── 2026-10-20 issue #38（D124）：浏览器就绪判据（真跑依赖的第二件事）───────────────────
def test_probe_browser_three_states(monkeypatch) -> None:
    """`_support/pw_runner.py::probe_browser` 三态 + 旁路不 spawn：

    ① playwright 自算路径**存在** ⇒ ok；② 给出不存在的路径 ⇒ 不成立且出路文案点名
    `npx playwright install chromium`；③ 探针自身报错（如模块未导出 chromium）⇒ 如实给尾行原因；
    ④ `ATLAS_PLAYWRIGHT_CHANNEL` 已设 ⇒ 旁路（launch 走系统通道浏览器，缓存判据不适用）——
    **不得起探针子进程**。路径由 playwright 自算（吃 `PLAYWRIGHT_BROWSERS_PATH`），Python 只判存在。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    kr = cons.pw_runner
    with tempfile.TemporaryDirectory() as td:
        scripts = Path(td)
        marker = scripts / "chromium-marker"
        marker.write_text("x", encoding="utf-8")

        # ① 路径存在 ⇒ ok
        monkeypatch.setattr(kr.subprocess, "run",
                            lambda *a, **k: type("Proc", (), {
                                "returncode": 0, "stdout": f"{marker}\n", "stderr": ""})())
        ok, detail = kr.probe_browser(scripts, node="/fake/node")
        assert ok is True and detail == "", (ok, detail)

        # ② 路径不存在 ⇒ 拒 + 指名安装命令
        monkeypatch.setattr(kr.subprocess, "run",
                            lambda *a, **k: type("Proc", (), {
                                "returncode": 0, "stdout": "/no/such/Chrome for Testing\n", "stderr": ""})())
        ok, detail = kr.probe_browser(scripts, node="/fake/node")
        assert ok is False, (ok, detail)
        assert "install chromium" in detail and "/no/such/Chrome for Testing" in detail, detail

        # ③ 探针自身报错 ⇒ 尾行原因（不把「判据不成立」变成「工具坏了」）
        monkeypatch.setattr(kr.subprocess, "run",
                            lambda *a, **k: type("Proc", (), {
                                "returncode": 1, "stdout": "", "stderr": "ERR no chromium export\n"})())
        ok, detail = kr.probe_browser(scripts, node="/fake/node")
        assert ok is False and "no chromium export" in detail, (ok, detail)

        # ④ channel 旁路：不起子进程
        monkeypatch.setenv(kr.CHANNEL_ENV, "chrome")

        def _no_spawn(*a, **k):
            raise AssertionError("channel 已设 ⇒ 缓存判据旁路，不得起探针子进程")
        monkeypatch.setattr(kr.subprocess, "run", _no_spawn)
        ok, detail = kr.probe_browser(scripts, node="/fake/node")
        assert ok is True and detail == "", (ok, detail)


def test_start_refuses_when_browser_missing(monkeypatch) -> None:
    """issue #38（D124）：模块可解析但浏览器未装 ⇒ `Runner.start` 起跑前诚实拒绝，真跑线程
    不被起；拒绝文案点名安装出路。变异 **M125**：摘 start 的浏览器判据段 ⇒ 本钉红（照常起跑）。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger = cons.Ledger(root, "tester")
        runner = cons.Runner(root, ledger, timeout=60, head=True, keep_open=False)
        monkeypatch.setattr(cons, "resolve_pw",
                            lambda r, repair=False: (Path("/pw"), Path("/nm"), "", ""))
        monkeypatch.setattr(cons.pw_runner, "probe_browser",
                            lambda *a, **k: (False, "chromium 浏览器未安装：/no/such"
                                                   "（npx playwright install chromium）"))
        ok, msg = runner.start({"id": "E2E-BR-001"}, "p.spec.ts:1", 0, "app",
                               "http://127.0.0.1:8000")
        assert ok is False, (ok, msg)
        assert "浏览器未就绪" in msg and "install chromium" in msg, msg


def test_manual_block_steps_parsed_and_legacy_compatible() -> None:
    """D143：`## ID 标题` + `atlas-manual` 块（扁平行式）与旧单行格式共存；
    id/title 只从标题行取，块内重复声明 ⇒ 响亮失败。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    text = """- MANUAL-OLD-001 | home | 旧项 | 自己点一遍

## MANUAL-NEW-001 结构化项

```atlas-manual
page: home
precondition:
  - 已登录
step:
  - 打开页面 | 页面出现 |
  - 保存 | payload 不含字段 | const p = 1
evidence:
  - 截图
```
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e").mkdir(parents=True)
        (root / "product" / "e2e" / "manual.md").write_text(text, encoding="utf-8")
        items = cons.read_manual(root)
    assert items[0] == {"id": "MANUAL-OLD-001", "page": "home", "title": "旧项",
                        "note": "自己点一遍"}, items[0]
    assert items[1]["id"] == "MANUAL-NEW-001", items[1]
    assert items[1]["title"] == "结构化项", items[1]
    assert items[1]["page"] == "home" and items[1]["precondition"] == ["已登录"], items[1]
    assert items[1]["steps"] == [
        {"action": "打开页面", "expect": "页面出现", "command": ""},
        {"action": "保存", "expect": "payload 不含字段", "command": "const p = 1"},
    ], items[1]
    assert items[1]["evidence"] == ["截图"], items[1]

    # 块内再写 id/title ⇒ 解析错误（两处真相）
    bad = text.replace("page: home\n", "id: MANUAL-NEW-001\npage: home\n")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e").mkdir(parents=True)
        (root / "product" / "e2e" / "manual.md").write_text(bad, encoding="utf-8")
        try:
            cons.read_manual(root)
        except ValueError as exc:
            assert "id/title" in str(exc), exc
        else:
            raise AssertionError("块内重复 id/title 未被拒绝")


def test_manual_open_url_keeps_base_query_and_path_prefix() -> None:
    """issue #27 / D104（评审 SHOULD：**第五消费者**）：控制台手工项「打开」的地址构造。

    旧实现 `base.rstrip("/") + route` 在 base 带 query 时必产畸形 URL
    （`…?switchAgent=7202/console/#/…`）；路径形态路由（`/console/#/…`）也会被拼成双前缀。
    本钉两侧：① base 带 query ⇒ origin + 合并后的路径（query 在 path 与 hash 之间）；
    ② base 不带 query ⇒ 行为与旧实现等价（`origin + route`）。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product").mkdir(parents=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e:\n  runner: node-playwright\n"
            "  app_base_url: http://localhost:2000/console/?switchAgent=7202\n", encoding="utf-8")
        url = cons.manual_open_url(root, "/console/#/app/agent/detail")
        assert url == "http://localhost:2000/console/?switchAgent=7202#/app/agent/detail", url

        (root / "product" / "stack-profile.yaml").write_text(
            "product: demo\napps: []\ne2e:\n  runner: node-playwright\n"
            "  app_base_url: http://localhost:2000/console/\n", encoding="utf-8")
        url2 = cons.manual_open_url(root, "/console/#/app/agent/detail")
        assert url2 == "http://localhost:2000/console/#/app/agent/detail", url2


def test_node_ids_maps_multi_segment_case_id() -> None:
    """契约 §5.3：`PAGE` 段 = 页面 slug 的大写原文（多段 slug 连字符原样保留）。

    ⇒ `node_ids()` 必须能把多段 ID 的生成行映射回用例 ID —— 否则控制台取不到 node id，
    该用例在控制台上不可单条执行（`file:line` 是 Playwright 的原生过滤形态）。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        scripts = Path(td)
        (scripts / "app-agent-detail.spec.ts").write_text(
            "import { test } from './atlas-hold';\n"
            "test('E2E-APP-AGENT-DETAIL-001 多段 slug 页用例', async ({ page }) => {\n"
            "  await page.goto('/');\n"
            "});\n",
            encoding="utf-8"
        )
        mapping = cons.node_ids(scripts)
    assert mapping == {"E2E-APP-AGENT-DETAIL-001": "app-agent-detail.spec.ts:2"}, mapping


def test_snapshot_missing_index_fails_loud_not_empty_list() -> None:
    """契约 §10：索引不存在时大声报错 SnapshotError，不得静默穿透为裸 FileNotFoundError。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = build_project(Path(td))
        index = root / "product" / "e2e" / "e2e-index.md"
        if index.exists():
            index.unlink()
        try:
            cons.snapshot(root)
            raise AssertionError("应抛 SnapshotError")
        except cons.SnapshotError as err:
            assert "索引文件缺失" in str(err), str(err)


def test_console_app_js_handles_prep_failed_distinctly() -> None:
    """前端 UI（D125）：`prep_failed` 显式分流，badge 为「前置失败」（warn 级），
    通告指明「与用例脚本本身无关」，消除「改用例」误导。
    """
    app_js = (Path(__file__).parent.parent / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    assert "prep_failed ? '<span class=\"pill warn\">前置失败</span>'" in app_js
    assert "与用例脚本本身无关" in app_js
    assert "prep_failed: Boolean(d.prep_failed)" in app_js



def test_committed_snapshot_merges_partial_submits() -> None:
    """D127：单次提交只携带页面草稿（部分用例），「已提交」必须按事件流累积合并；
    否则后一次部分提交会把之前提交过的用例从 committed 视图抹掉，控制台表现为
    已执行/已评审的用例变回「未跑」。
    """
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger = cons.Ledger(root, "tester")
        ledger.append({"kind": "submit", "source": "app",
                       "cases": {"A": {"ok": True, "reviewed": {"pass": True}}}})
        ledger.append({"kind": "submit", "source": "app",
                       "cases": {"B": {"ok": True, "reviewed": {"pass": False}}}})
        snap = ledger.committed_snapshot("app")
        assert set(snap["cases"]) == {"A", "B"}, snap
        assert snap["cases"]["A"]["reviewed"]["pass"] is True, snap

        # 后提交覆盖同名用例，其余用例保留
        ledger.append({"kind": "submit", "source": "app", "cases": {"A": {"ok": False}}})
        snap = ledger.committed_snapshot("app")
        assert set(snap["cases"]) == {"A", "B"}, snap
        assert snap["cases"]["A"]["ok"] is False, snap

        # 其他 source 不混入；legacy list 形态不污染累积视图
        ledger.append({"kind": "submit", "source": "prototype", "cases": {"C": {"ok": True}}})
        ledger.append({"kind": "submit", "source": "app", "cases": [{"id": "legacy"}]})
        app_snap = ledger.committed_snapshot("app")
        assert set(app_snap["cases"]) == {"A", "B"}, app_snap
        assert set(ledger.committed_snapshot("prototype")["cases"]) == {"C"}


# ── 2026-10-21 D128：评审绑定提交指纹与陈旧度（stale）判定 ────────────────────────
def test_scripts_hash_excludes_runtime_artifacts_and_whitelists_scripts() -> None:
    """D128：scripts_hash 必须对源码脚本敏感、对运行期产物免疫。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        s_dir = root / "product" / "e2e" / "scripts"
        s_dir.mkdir(parents=True)
        # 空目录 => None
        assert cons.scripts_hash(root) is None

        # 写入源码脚本 => 产生 hash
        spec = s_dir / "demo.spec.ts"
        spec.write_text("test('a', async () => {});\n", encoding="utf-8")
        h1 = cons.scripts_hash(root)
        assert h1 is not None and len(h1) == 16, h1

        # 写入运行期产物（trace、png、test-results）=> hash 严格不变
        results = s_dir / "test-results" / "run-1"
        results.mkdir(parents=True)
        (results / "trace.zip").write_bytes(b"trace-bytes")
        (s_dir / "failure.png").write_bytes(b"png-bytes")
        (s_dir / ".last-run.json").write_text("{}", encoding="utf-8")
        h2 = cons.scripts_hash(root)
        assert h2 == h1, (h1, h2)

        # 修改源码脚本 => hash 变化
        spec.write_text("test('a-modified', async () => {});\n", encoding="utf-8")
        h3 = cons.scripts_hash(root)
        assert h3 != h1, (h1, h3)

        # 增加 atlas-prepare.mjs 钩子 => hash 包含钩子
        (root / "atlas-prepare.mjs").write_text("// prep\n", encoding="utf-8")
        h4 = cons.scripts_hash(root)
        assert h4 != h3, (h3, h4)


def test_case_review_state_lifecycle() -> None:
    """D128：case_review_state 四态闭集（unreviewed / fresh / stale / legacy）。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    # ① 未评审
    st1 = cons.case_review_state({"ok": True, "reviewed": {"pass": False}}, None)
    assert st1["state"] == "unreviewed", st1

    # ② 历史账本无指纹 => legacy
    st2 = cons.case_review_state({"ok": True, "reviewed": {"pass": True}}, {"head_sha": "abc", "scripts_hash": "123"})
    assert st2["state"] == "legacy", st2

    # ③ 指纹完全匹配 => fresh
    prov = {"head_sha": "abc1234567890", "scripts_hash": "hash1234", "git_dirty": False, "actor_type": "human"}
    current = dict(prov)
    st3 = cons.case_review_state({"ok": True, "reviewed": {"pass": True}, "prov": prov}, current)
    assert st3["state"] == "fresh", st3
    assert "warning" not in st3, st3

    # ④ 提交时工作区 dirty => fresh 但带警告
    prov_dirty = dict(prov, git_dirty=True)
    st4 = cons.case_review_state({"ok": True, "reviewed": {"pass": True}, "prov": prov_dirty}, current)
    assert st4["state"] == "fresh" and "dirty" in st4.get("warning", ""), st4

    # ⑤ HEAD 变动 => stale
    cur_new_head = dict(current, head_sha="def9999999999")
    st5 = cons.case_review_state({"ok": True, "reviewed": {"pass": True}, "prov": prov}, cur_new_head)
    assert st5["state"] == "stale" and "HEAD变动" in st5["reason"], st5

    # ⑥ 脚本变动 => stale
    cur_new_scripts = dict(current, scripts_hash="hash9999")
    st6 = cons.case_review_state({"ok": True, "reviewed": {"pass": True}, "prov": prov}, cur_new_scripts)
    assert st6["state"] == "stale" and "脚本变动" in st6["reason"], st6


def test_submit_attaches_provenance_and_committed_computes_stale() -> None:
    """D128：_compact 留存 prov，committed_snapshot 注入 review_state 且重算最新新鲜度。"""
    cons = load("e2e_console", "scripts/e2e_console.py")
    prov_v1 = {"head_sha": "11111112222222", "scripts_hash": "aaaa1111", "git_dirty": False, "actor_type": "human"}
    compacted = cons._compact({"ok": True, "reviewed": {"pass": True, "checked_at": "12:00"}}, prov=prov_v1)
    assert compacted["prov"]["head_sha"] == "11111112222222"
    assert compacted["reviewed"]["pass"] is True

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger = cons.Ledger(root, "tester")
        ledger.append({
            "kind": "submit",
            "source": "app",
            "prov": prov_v1,
            "reviewed_scope": ["E2E-001"],
            "cases": {"E2E-001": compacted},
        })
        # 用相同指纹读取 => fresh
        snap_fresh = ledger.committed_snapshot("app", current=prov_v1)
        assert snap_fresh["cases"]["E2E-001"]["review_state"]["state"] == "fresh"

        # 换新提交指纹读取 => 自动判定为 stale，不污染底表
        prov_v2 = dict(prov_v1, head_sha="33333334444444")
        snap_stale = ledger.committed_snapshot("app", current=prov_v2)
        assert snap_stale["cases"]["E2E-001"]["review_state"]["state"] == "stale"
        assert "HEAD变动" in snap_stale["cases"]["E2E-001"]["review_state"]["reason"]

        # reviewed_scope 必须有消费者（否则是死字段）：committed 视图 + 人读账本都要暴露
        assert snap_fresh["reviewed_scope"] == ["E2E-001"] and snap_fresh["reviewed_count"] == 1, snap_fresh
        ledger_md = (root / "product" / "e2e" / "reviews" / "console" / "ledger.md").read_text(encoding="utf-8")
        assert "本次评审范围：**1 条**" in ledger_md, ledger_md
        # 旧事件（无 reviewed_scope）⇒ 空范围，不谎报条数
        assert ledger.committed_snapshot("prototype")["reviewed_count"] == 0


def test_console_app_js_handles_stale_and_legacy_and_provenance() -> None:
    """前端 UI（D128）：stale 与 legacy 同等「需重审」，meta 行暴露当前提交/脚本指纹。

    **Blocker 回归防护**：`rowHTML` 里 `const canCheck` 曾出现两次声明（同作用域重复 `const`
    = JS SyntaxError ⇒ 控制台整页白屏），而字符串 grep 拦不住 ⇒ 本钉按**出现次数**判，
    杜绝「关键字读得到、语法其实炸」的假绿。
    """
    app_js = (Path(__file__).parent.parent / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    assert app_js.count("const canCheck") == 1, "同作用域重复 const canCheck ⇒ app.js 语法错，控制台全灭"
    assert "STALE 需重审" in app_js
    assert "LEGACY" in app_js
    assert "HEAD=" in app_js
    assert "评审范围" in app_js          # reviewed_scope 的前端消费者（死字段防护）
    assert "needsRecheck" in app_js
    # legacy 不得冒充有效评审（旧账本可被重勾洗白 = 审查逃逸）
    assert "st.state === 'stale' || st.state === 'legacy'" in app_js
    assert "statList.push(['需重审', k.stale])" in app_js

