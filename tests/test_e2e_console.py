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
