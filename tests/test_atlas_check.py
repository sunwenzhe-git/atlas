#!/usr/bin/env python3
"""`atlas_check.py` 聚合入口的回归测试（3509 §B68）。

**只测聚合本身**（一门一行 / 退出码 / 缺件降级），判据仍由各门自己的测试守：
  * 夹具根里没有 `.atlas/` ⇒ 各门应如实记 `SKIP`（不静默当成通过）；
  * 注入一个「用例侧与原型侧不一致」的夹具（软链真实校验器）⇒ 必须 FAIL 且退出码 1。

变异证明：从 `VALIDATORS` 里摘掉一个 ⇒ `test_atlas_check_fails_when_a_gate_fails` 变红。
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import subprocess
import sys
import shutil
import tempfile
import threading
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CK = PKG_ROOT / "scripts" / "atlas_check.py"

HOME_HTML = '<html><body><button data-testid="home-cta-btn">x</button></body></html>'


def _mk_pw_module(nm: Path, version: str = "9.9.9") -> Path:
    """在 `nm` 下造一个**真能被 Node 解析**的 `@playwright/test`（issue #24 夹具）。

    判据本体 = 「从 `product/e2e/scripts/` 出发 `@playwright/test` 可解析」⇒ 空目录糊弄不过去：
    必须有 `package.json` + 入口文件，否则夹具自己就是「解析不到」，红的是夹具不是门。
    """
    pkg = nm / "@playwright" / "test"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": "@playwright/test", "version": version,
                    "main": "index.js", "exports": "./index.js"}),
        encoding="utf-8")
    (pkg / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
    return pkg
CASE_BAD = """
## E2E-HOME-001 首页

```atlas-case
id: E2E-HOME-001
intent: 夹具用例用于触发 testid 双向集合不一致
pages:
  - home
precondition:
  - 已打开首页
step:
  - click home-cta-btn          # 点击
expected:
  - visible home-missing        # 原型上没有这个 testid
testid:
  - home-cta-btn
  - home-missing
```
"""


def run(args: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CK), *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


_LIVE: dict[str, str] = {}


def _live_base() -> str:
    """起一个真能连上的本地靶场（进程级复用；daemon 线程随解释器退出）。

    `check_e2e` 的可达性探针只判 **TCP 可连**（任何 HTTP 状态码都算「栈在跑」），
    所以空 handler 足够；它存在的意义是给「地址已声明**且**可达」的钉子一个真靶场。
    """
    if "url" not in _LIVE:
        class _H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):  # 静音
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _LIVE["url"] = f"http://127.0.0.1:{srv.server_address[1]}"
    return _LIVE["url"]


def test_atlas_check_skips_missing_gates_without_claiming_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        code, out = run(["--root", ".", "--fast", "--json"], Path(td))
        assert code == 0, out
        rows = json.loads(out)["rows"]
        statuses = {r["name"]: r["status"] for r in rows}
        assert statuses.get("validate_e2e_index") == "SKIP", statuses   # 缺件 ⇒ SKIP，不是 ok
        assert "生成物最新" in statuses, statuses
        assert all(r["name"] and r["status"] for r in rows)


def test_f53_factory_gate_skips_when_tests_dir_absent() -> None:
    """D91（2026-10-16，issue #17 残余；RFC-20261016-02 F53）：全量模式的包自检门
    落在装配时可能不会被落下的目录上——`install.sh` 拷贝列表含 `tests`，但 npm 旧发行版
    不发布 `tests/` ⇒ 存量装配恒无 `.atlas/tests`；源包开发态（仓根）同缺。无前置判据时
    pytest exit 4 ⇒ 全量恒红 FAIL，而 `--fast` 一跑就 OK——两相反结论并存（issue #17）。

    修法（D91）：`.atlas/tests` 不是目录 ⇒ SKIP（不是 FAIL），SKIP 不进 failures ⇒
    整体判定不再被这道自己修不了的红压垮；文案必须同时给判据面（实测路径 + 形态区分）
    与出路（pytest tests / install.sh / atlas upgrade）。

    变异 M76：摘掉 `check_factory` 的前置分支 ⇒ 本用例红（回到 exit 4）；还原逐字节一致。
    三种形态同吃 SKIP（D91 判据一道覆盖，收窄注记见 DESIGN.md D86/D91）：① 根本无 `.atlas/`（源包开发态）；
    ② 有 `.atlas/` 无 `tests/`（存量装配态）；③ `.atlas/tests` 是**文件**（装配损坏）。
    """
    for make in (None, "atlas_only", "file_form"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            if make == "atlas_only":
                (root / ".atlas").mkdir()
            elif make == "file_form":
                (root / ".atlas").mkdir()
                (root / ".atlas" / "tests").write_text("not a directory", encoding="utf-8")
            code, out = run(["--root", ".", "--json"], root)
            payload = json.loads(out)
            assert code == 0, out
            row = next(r for r in payload["rows"] if r["name"] == "对齐测试(.atlas/tests)")
            assert row["status"] == "SKIP", (make, row)
            # 出路动作词齐组（M68 同款纪律）：文件面 / 命令 / 重装路缺一即为无出路文案
            for token in (str(root / ".atlas" / "tests"), "pytest tests",
                          "install.sh", "atlas upgrade"):
                assert token in row["detail"], (make, token, row["detail"])
            assert not payload["failures"], (make, payload["failures"])


def test_f53_factory_gate_still_fails_on_red_tests() -> None:
    """D91 反面钉：目录**在场** ⇒ 行为逐字节不变，真红仍 FAIL。

    防「把真失败一并降级成 SKIP」——D91 的降级只吃「目录不在场」这一种断言成立不了；
    有测试对象的装配态里依旧是 FAIL（issue #17 同族不会被本修洗绿）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".atlas" / "tests"
        d.mkdir(parents=True)
        (d / "test_red.py").write_text("def test_red():\n    assert False\n", encoding="utf-8")
        code, out = run(["--root", ".", "--json"], root)
        payload = json.loads(out)
        assert code == 1, out
        st = {r["name"]: r["status"] for r in payload["rows"]}
        assert st.get("对齐测试(.atlas/tests)") == "FAIL", st
        assert any(f["name"] == "对齐测试(.atlas/tests)" for f in payload["failures"])


def test_atlas_check_fails_when_a_gate_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "validators", root / ".atlas" / "validators")
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        # E1：抽取源 = 前端源码（前端有 home-cta-btn ⇒ home 页「已实现」，
        # 而 CASE_BAD 引用 home-missing ⇒ 双向差集 FAIL）
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\napps:\n  - name: web\n    path: web\n    kind: frontend\n"
            "    role: landing\n    stack: x\n", encoding="utf-8")
        (root / "web").mkdir(parents=True, exist_ok=True)
        (root / "web" / "Home.tsx").write_text(HOME_HTML, encoding="utf-8")
        c = root / "product" / "e2e" / "cases"
        c.mkdir(parents=True, exist_ok=True)
        (c / "home.md").write_text(CASE_BAD, encoding="utf-8")
        code, out = run(["--root", ".", "--fast", "--json"], root)
        assert code == 1, out
        rows = {r["name"]: r["status"] for r in json.loads(out)["rows"]}
        assert rows.get("validate_testids") == "FAIL", rows
        # 一门一行（人可读输出）：行数 = 门数
        code2, text = run(["--root", ".", "--fast"], root)
        assert code2 == 1
        body = [l for l in text.strip().splitlines() if l.startswith("  ")]
        assert len(body) == len(rows), (body, rows)


def test_e2e_reset_failure_fails_the_run_row() -> None:
    """台账 P4 机制化（2026-09-30）：`e2e.reset` 声明且执行非零 ⇒ `E2E 真跑` FAIL
    并带 reset 输出尾巴；reset 成功/未声明照常。变异 M30：摘掉 reset 执行 ⇒ 声明
    失败命令不再 FAIL（带着脏状态跑，结论不可信）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "e2e" / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "product" / "e2e" / "scripts" / "config.spec.ts").write_text(
            "test('ok', async () => {});\n", encoding="utf-8")
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\ne2e:\n  runner: node-playwright\n"
            f"  app_base_url: {_live_base()}\n"
            "  reset: \"exit 7\"\n", encoding="utf-8")
        code, out = run(["--root", ".", "--page", "config", "--json"], root)
        rows = {r["name"]: r for r in json.loads(out)["rows"]}
        e2e = rows.get("E2E 真跑[config]")
        assert e2e and e2e["status"] == "FAIL", rows
        assert "e2e.reset 失败" in e2e["detail"] and "exit 7" in e2e["detail"], e2e


def test_generated_gate_reports_not_ready_as_skip() -> None:
    """`3509 §B110`：前置未声明（`app_base_url: null`）⇒ `生成物最新` 记 **SKIP（未就绪）**，不是 FAIL。

    变异：把 `code == GEN_NOT_READY` 分支摘掉（退回一律 FAIL）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\ne2e:\n  runner: node-playwright\n  app_base_url: null\n",
            encoding="utf-8")
        code, out = run(["--root", ".", "--fast", "--json"], root)
        rows = {r["name"]: r for r in json.loads(out)["rows"]}
        assert rows["生成物最新"]["status"] == "SKIP", rows["生成物最新"]
        assert "未就绪" in rows["生成物最新"]["detail"], rows["生成物最新"]
        assert code == 0, out          # SKIP 不影响退出码（未就绪 ≠ 失败）


def test_generated_gate_reports_real_error_as_fail() -> None:
    """反例钉：生成器的**真错**（例：`e2e.runner` 未知，退出码 2）仍须 FAIL 且退出码 1。

    变异：把 `if code != 0` 的 FAIL 退回 SKIP ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\ne2e:\n  runner: 不存在的运行器\n  app_base_url: null\n", encoding="utf-8")
        code, out = run(["--root", ".", "--fast", "--json"], root)
        rows = {r["name"]: r for r in json.loads(out)["rows"]}
        assert rows["生成物最新"]["status"] == "FAIL", rows["生成物最新"]
        assert code == 1, out


def test_atlas_check_cli_lists_every_gate_once() -> None:
    """`VALIDATORS` 里每一项都必须有且只有一行（防止漏挂 / 重复挂）。"""
    with tempfile.TemporaryDirectory() as td:
        code, out = run(["--root", ".", "--fast", "--json"], Path(td))
        names = [r["name"] for r in json.loads(out)["rows"]]
        assert len(names) == len(set(names)), names
        for v in ("validate_e2e_index", "validate_testids", "validate_prd", "validate_structure",
                  "validate_stack_profile", "结构漂移"):
            assert names.count(v) == 1, names


def _load_check():
    spec = importlib.util.spec_from_file_location("atlas_check_under_test", CK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_e2e_skips_when_app_base_url_empty_followed_by_key() -> None:
    """回归（2026-10-04 门禁负向用例 #2）：`app_base_url:` 空值、下一行是 `reset:` ⇒
    不得跨行把键名当成 URL 误判「已声明」而进真跑分支（reset 会被意外执行）。
    变异：值抽取正则退回 `\\s*`（可跨行）⇒ 本用例红。
    """
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n  cases_dir: product/e2e/cases\n  app_base_url:\n  reset: echo hi\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"] == "E2E 真跑"][0]
        assert row["status"] == "SKIP", rows.rows
        assert "app_base_url" in row["detail"], row


def test_check_e2e_skips_when_target_unreachable() -> None:
    """`3509 §B189-1`：地址已声明但靶场**不可达** ⇒ `SKIP` + `ENV_ISSUE`，不是 FAIL。

    实测成因：前端 dev server 未起 ⇒ 整批 `goto` 失败（79 failed / 4 passed），真红（用例真失败）
    与假红（服务没起）不可区分 ⇒ 狼来了效应。本钉子同时证明探针**短路**：夹具里的用例是
    必红的（`assert False`），但不得被跑到。

    变异证明：摘掉可达性探针 ⇒ 本用例红（会走到 pytest 并报 FAIL）。
    """
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("test('boom', async () => { expect(1).toBe(2); });\n", encoding="utf-8")
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n  runner: node-playwright\n  app_base_url: http://127.0.0.1:9\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"] == "E2E 真跑"][0]
        assert row["status"] == "SKIP", rows.rows
        assert "ENV_ISSUE" in row["detail"] and "不可达" in row["detail"], row


def test_check_e2e_reachable_target_is_not_skipped(monkeypatch) -> None:
    """可达靶场不得被探针误 SKIP（门不是恒跳过）：探针放行后照跑并如实报结果。

    变异证明：把探针改成恒不可达 ⇒ 本用例红（报 SKIP 而不是 ok）。
    """
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("test('ok', async () => {});\n", encoding="utf-8")
        # 常规布局：运行器与模块都在 `<root>/node_modules`（Node 从 scripts 起向上搜索的第一跳）。
        nm_dir = root / "node_modules"
        (nm_dir / ".bin").mkdir(parents=True)
        pw = nm_dir / ".bin" / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\nexit 0\n", encoding="utf-8")
        pw.chmod(0o755)
        _mk_pw_module(nm_dir)
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n  runner: node-playwright\n  node_modules: node_modules\n"
            f"  app_base_url: {_live_base()}\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert row["status"] == "ok", rows.rows
        summary_file = root / ".atlas" / "runs" / "e2e-summary.json"
        assert summary_file.is_file(), "E2E 成功时必须写入 e2e-summary.json 凭据快照"
        data = json.loads(summary_file.read_text(encoding="utf-8"))
        assert data["status"] == "ok" and data["page"] == "login"

def test_check_e2e_fails_loudly_when_node_playwright_missing(monkeypatch) -> None:
    """单轨化（B201-4）：node 可执行缺失 ⇒ FAIL 点名（不静默降级、不猜别的运行器）。"""
    mod = _load_check()
    monkeypatch.setattr(mod.shutil, "which", lambda cmd: None)
    monkeypatch.delenv("NODE_PATH", raising=False)
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  app_base_url: {_live_base()}\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"] == "E2E 真跑"][0]
        assert row["status"] == "FAIL", rows.rows
        assert "node-playwright" in row["detail"] and "node_modules" in row["detail"], row


def test_check_e2e_fails_loud_when_browser_missing(monkeypatch) -> None:
    """issue #38 / `DESIGN.md` D124：模块可解析 ≠ launch 可成——npm 装包不自动下载浏览器。

    运行器判据（D101）已过、浏览器未装 ⇒ `E2E 真跑` **FAIL** 且出路文案点名
    `npx playwright install chromium`；真跑**不得被起**（failures[0].command 为空 = 未执行
    `playwright test`，旧行为会照跑并在 launch 阶段炸成「N failed」，门谎报过就绪）。
    变异 **M124**：门内浏览器判据分支退回恒真 ⇒ 本钉红（照跑假 .bin ⇒ 报 ok）。
    """
    mod = _load_check()
    monkeypatch.setattr(mod.pw_runner, "probe_browser",
                        lambda *a, **k: (False, "chromium 浏览器未安装：/no/such/Chrome"
                                               "（npx playwright install chromium）"))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("test('ok', async () => {});\n", encoding="utf-8")
        nm_dir = root / "node_modules"
        (nm_dir / ".bin").mkdir(parents=True)
        pw = nm_dir / ".bin" / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\nexit 0\n", encoding="utf-8")
        pw.chmod(0o755)
        _mk_pw_module(nm_dir)
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n  runner: node-playwright\n  node_modules: node_modules\n"
            f"  app_base_url: {_live_base()}\n", encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"] == "E2E 真跑"][0]
        assert row["status"] == "FAIL", rows.rows
        assert "浏览器判据不成立" in row["detail"] and "install chromium" in row["detail"], row
        assert rows.failures and rows.failures[0]["command"] == "", rows.failures
        # FAIL 不得留下真跑凭据（未跑就不该有 e2e-summary）
        assert not (root / ".atlas" / "runs" / "e2e-summary.json").exists()


def test_check_e2e_node_modules_anchored_to_root(monkeypatch) -> None:
    """验证 node_modules 相对路径能够正确以 root 为基准锚定并寻找 playwright。"""
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        # 相对路径以 **root** 为基准锚定（不是 cwd）；且目录名必须是 `node_modules` 才能落在
        # Node 从 scripts 起向上搜索的路径上（issue #24：判据是「可解析」，不是「文件在不在」）。
        nm_dir = root / "product" / "node_modules"
        pw_mock = nm_dir / ".bin" / "playwright"
        pw_mock.parent.mkdir(parents=True)
        pw_mock.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        pw_mock.chmod(0o755)
        _mk_pw_module(nm_dir)

        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n  runner: node-playwright\n  node_modules: product/node_modules\n"
            f"  app_base_url: {_live_base()}\n",
            encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")
        
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        # node_modules 值以 root 为基准锚定（不是 cwd）⇒ 找到 binary；模块也在搜索路径上 ⇒ 判据本体成立
        assert "node-playwright 可执行文件不存在" not in row["detail"], row
        assert row["status"] == "ok", row


def test_check_e2e_global_playwright_detected(monkeypatch) -> None:
    """F19: stack-profile 未声明 node_modules 时，通过全局 playwright 探测执行真跑。"""
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")

        # 伪造全局 Playwright 可执行文件与全局 node_modules
        fake_bin = root / "fake-bin" / "playwright"
        fake_bin.parent.mkdir(parents=True)
        fake_bin.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        fake_bin.chmod(0o755)

        fake_global_nm = root / "fake-global-nm"
        # issue #24：判据是「可解析」⇒ 夹具必须给**真包**（空目录在真探针下 = 解析不到）
        _mk_pw_module(fake_global_nm, version="9.9.9")

        _real_which = mod.shutil.which
        monkeypatch.setattr(mod.shutil, "which",
                            lambda cmd: str(fake_bin) if cmd == "playwright" else _real_which(cmd))
        monkeypatch.setenv("NODE_PATH", str(fake_global_nm))

        # 未声明 node_modules
        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  app_base_url: {_live_base()}\n",
            encoding="utf-8")

        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert "node-playwright 可执行文件不存在" not in row["detail"], row
        # issue #24：真跑跑得起来（code 0），但运行器来自**机器全局状态**、非项目自足 ⇒ 降档 WARN 并写明白；
        # 旧行为下这里是假 ok（只看 binary 在不在）。
        assert row["status"] == "WARN", row
        assert "@playwright/test" in row["detail"] and "软链" in row["detail"], row
        link = root / "node_modules" / "@playwright" / "test"
        assert link.is_symlink(), f"应已在解析搜索路径上补软链：{link}"
        assert os.path.realpath(link) == os.path.realpath(fake_global_nm / "@playwright" / "test")
        # 幂等：再跑一次不得重复动手（同物则不动，且结论不变）
        before = os.path.realpath(link)
        rows_again = mod.Row()
        mod.check_e2e(root, rows_again, "login")
        row_again = [r for r in rows_again.rows if r["name"].startswith("E2E 真跑")][0]
        assert row_again["status"] == "WARN", row_again
        assert os.path.realpath(link) == before, "幂等：软链不得被重建/改动"


def test_strip_matching_quotes_only_eats_paired_quotes() -> None:
    """D94 ③ 残余清偿（2026-10-17，变异 MB9）：`reset:` 的取值清洗只剥**成对**引号。

    此前用 `.strip("\"\'")` —— 它从**两端**剥掉集合内任意字符：`sh -c 'echo RAN > f'` 这类
    **结尾本身带引号**的合法发令会被吃掉最后一个字符（静默改义、不报错）。本机实测踩到过：
    反侧钉的夹具 `reset: \"sh -c 'echo RAN > f'\"` 因此变成缺引号的命令而失败。
    """
    mod = _load_check()
    # **钉的是门实际调用的那一个函数**（`_reset_command`），不是 helper 本体 ——
    # 否则把调用点改回 `.strip("\"\'")` 时钉照样绿（本轮实测踩到）。
    f = mod._reset_command
    assert f('"echo hi"') == "echo hi"                       # 成对双引号 ⇒ 剥
    assert f("'echo hi'") == "echo hi"                       # 成对单引号 ⇒ 剥
    assert f("echo it's") == "echo it's"                     # 结尾单引号不成对 ⇒ **不动**（旧实现吃成 echo it）
    assert f("sh -c 'echo RAN > f'") == "sh -c 'echo RAN > f'"
    assert f('"echo hi"   # 行内注释') == "echo hi"           # 注释照剥（与引号清洗串联）
    assert f("  echo hi  ") == "echo hi"


def test_check_e2e_runs_with_scripts_dir_as_cwd(monkeypatch) -> None:
    """issue #29 / `DESIGN.md` D106：**真跑门的执行 cwd 必须是生成物目录**（`<scripts_dir>`）。

    生成物里的相对路径全是 **cwd 相对**的：`storageState: ".atlas-auth/state.json"`、
    `outputDir: ".atlas-run"`、mock fixture 路径。此前本门用 `cwd=项目根` + `-c <相对路径>` 跑 ⇒
    Playwright 把 storageState 解析到 `<root>/.atlas-auth/` ⇒ **读不到人工会话**（并在那儿写一个空 state）
    ⇒ 未登录态跑用例 ⇒ 断言 20s 超时**假红**（现场：3 failed 1 passed，而同一份产物在
    `cd scripts` 下跑 8.2s 全绿）。控制台本来就是 `cd scripts` 再跑 —— 两个入口必须一个口径。

    变异 **MB6**：把 cwd 退回 `root` 并改回 `-c <相对路径>` ⇒ 本钉红。
    """
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")
        nm_dir = root / "node_modules"
        (nm_dir / ".bin").mkdir(parents=True)
        pw = nm_dir / ".bin" / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        pw.chmod(0o755)
        _mk_pw_module(nm_dir)
        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  node_modules: node_modules\n"
            f"  app_base_url: {_live_base()}\n", encoding="utf-8")
        captured: dict = {}

        def fake_run(cmd, cwd, timeout=1800, shell=False):
            captured["cmd"] = cmd
            captured["cwd"] = Path(cwd)
            return 1, "1 passed"

        monkeypatch.setattr(mod, "run", fake_run)
        mod.check_e2e(root, mod.Row(), "login")
    assert captured["cwd"] == scripts, f"执行 cwd 必须是生成物目录，实际 {captured['cwd']}"
    assert "playwright.config.ts" in captured["cmd"], captured["cmd"]
    assert "product/e2e/scripts" not in captured["cmd"], f"不应带相对配置路径：{captured['cmd']}"


def test_check_e2e_module_unresolvable_fails_loudly(monkeypatch) -> None:
    """issue #24：判据本体 = 「从 scripts 出发 `@playwright/test` 可解析」——
    即 `gates.md` 2.2 本行早写明的「按**依赖可导入性**，不按路径存在」。

    夹具 = 项目**声明了**运行器目录、binary 也在（旧判据下 = ok），但模块不在 Node 的搜索路径上，
    且无全局兜底 ⇒ 必须 FAIL 并把真原因点出来（旧行为：放行到运行期，报「跑失败 / 无结果」，
    真红与假红不可区分）。

    变异证明：把 probe 摘回「binary 存在即 ok」⇒ 本用例红（status 变 ok）。
    """
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")
        pw = root / "node_modules" / ".bin" / "playwright"
        pw.parent.mkdir(parents=True)
        pw.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        pw.chmod(0o755)
        monkeypatch.setattr(mod.shutil, "which", lambda cmd: None)
        monkeypatch.delenv("NODE_PATH", raising=False)
        monkeypatch.setattr(mod.subprocess, "run",
                            lambda *a, **k: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())
        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  node_modules: node_modules\n"
            f"  app_base_url: {_live_base()}\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert row["status"] == "FAIL", row
        assert "依赖可导入性" in row["detail"], row
        if shutil.which("node"):
            assert "@playwright/test" in row["detail"], row
        # FAIL 不得留下真跑凭据（未跑就不该有 e2e-summary）
        assert not (root / ".atlas" / "runs" / "e2e-summary.json").exists()


def test_check_e2e_strips_inline_comments_from_profile_scalars(monkeypatch) -> None:
    """D94 口径（行内 `#` 注释剥除单源）落到本门四处取值 —— 2026-10-17 现场实证：

    百炼/v2前端 的 `stack-profile.yaml` 写 `reset: null   # 真跑前靶场重置 shell 命令串`
    （**合法 YAML**：`#` 前有空白 ⇒ 是行内注释），而本门四处取值不过剥注释 ⇒ 注释整段被当值
    ⇒ `e2e.reset 失败（exit 127）：/bin/sh: null: command not found` —— **假红，且在跑到用例
    之前**（那时根本还没轮到我写的用例去红）。D94 ③ 把这批「其余文本期门」登记为残余，本处是
    其中一处的现场实证。

    变异证明 **M92**：四处取值退回 `m.group(1)` 原样 ⇒ 本用例红（`reset` 被执行 ⇒ 行变 `FAIL`）。
    """
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")
        nm_dir = root / "node_modules"
        (nm_dir / ".bin").mkdir(parents=True)
        pw = nm_dir / ".bin" / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        pw.chmod(0o755)
        _mk_pw_module(nm_dir)
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n"
            "  runner: node-playwright\n"
            "  node_modules: node_modules   # node 运行器的依赖目录（相对项目根）\n"
            f"  app_base_url: {_live_base()}   # 真实应用地址（单段唯一靶场）\n"
            "  reset: null   # 真跑前靶场重置 shell 命令串；null = 不重置\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert "e2e.reset 失败" not in row["detail"], row
        assert row["status"] == "ok", row


def test_check_e2e_still_runs_a_real_reset_command(monkeypatch) -> None:
    """反侧钉：剥注释**不得把功能修掉** —— 真写的 `reset:` 发令必须照发（否则就是把门修哑）。"""
    mod = _load_check()
    # D124：本钉主题不是浏览器判据 —— 给 probe_browser 旁路假件（浏览器就绪另钉）
    monkeypatch.setattr(mod.pw_runner, "probe_browser", lambda *a, **k: (True, ""))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")
        nm_dir = root / "node_modules"
        (nm_dir / ".bin").mkdir(parents=True)
        pw = nm_dir / ".bin" / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\n", encoding="utf-8")
        pw.chmod(0o755)
        _mk_pw_module(nm_dir)
        (root / "product" / "stack-profile.yaml").write_text(
            "e2e:\n"
            "  runner: node-playwright\n"
            "  node_modules: node_modules\n"
            f"  app_base_url: {_live_base()}\n"
            "  reset: echo RAN > reset-ran.txt   # 真发令 + 行内注释\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        assert (root / "reset-ran.txt").is_file(), "真写的 reset 发令必须照发（剥注释不得把功能修掉）"
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert row["status"] == "ok", row


def test_check_e2e_ignores_python_playwright_without_node_module(monkeypatch) -> None:
    """F19 加固：当系统命中 Python Playwright CLI 时，若无 Node 全局模块，不得采信该 global_pw。"""
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("// dummy\n", encoding="utf-8")
        (scripts / "playwright.config.ts").write_text("// dummy config", encoding="utf-8")

        fake_bin = root / "fake-python-bin" / "playwright"
        fake_bin.parent.mkdir(parents=True)
        fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_bin.chmod(0o755)

        monkeypatch.setattr(mod.shutil, "which", lambda cmd: str(fake_bin) if cmd == "playwright" else None)
        monkeypatch.delenv("NODE_PATH", raising=False)
        monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: type("Proc", (), {"returncode": 1, "stdout": "", "stderr": ""})())

        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  app_base_url: {_live_base()}\n",
            encoding="utf-8")

        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert "node-playwright 可执行文件不存在" in row["detail"], row
        assert row["status"] == "FAIL", row




def test_drift_gate_reads_marker() -> None:
    """「结构漂移」门（gates.md §2.2，2026-10-04 登记）：只读标记、不做二次判定。
    变异：从 main 摘掉 `check_drift` 调用 ⇒ `test_atlas_check_cli_lists_every_gate_once` 红。
    """
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rows = mod.Row()
        mod.check_drift(root, rows)
        assert rows.rows[0]["status"] == "SKIP", rows.rows          # 无 .adapter-out ⇒ 结构环未跑
        od = root / ".adapter-out"
        od.mkdir(parents=True)
        rows2 = mod.Row()
        mod.check_drift(root, rows2)
        assert rows2.rows[0]["status"] == "ok", rows2.rows          # 无标记 ⇒ 最近刷新无漂移
        (od / "_drift.json").write_text(json.dumps(
            {"drifts": [{"kind": "routes", "added": ["app /home2"], "removed": ["app /home"]}]},
            ensure_ascii=False), encoding="utf-8")
        rows3 = mod.Row()
        mod.check_drift(root, rows3)
        assert rows3.rows[0]["status"] == "WARN", rows3.rows
        assert "/home2" in rows3.rows[0]["detail"], rows3.rows
        (od / "_drift.json").write_text("{not-json", encoding="utf-8")
        rows4 = mod.Row()
        mod.check_drift(root, rows4)
        assert rows4.rows[0]["status"] == "WARN", rows4.rows        # 坏标记 ⇒ 响亮 WARN，不得静默


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  \u2713 {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  \u2717 {t.__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())


def test_review_input_manifest_is_pointer_based_and_tracks_current_files() -> None:
    """`3509 §B66`：复核输入是指针清单（sha256），不是副本。

    反向证明：改了被收录的文件之后再产一次清单，其 sha256 **必须变** ——
    若实现退化为「拷副本」，第二次产出的指纹会与第一次相同（副本没更新）。
    """
    script = PKG_ROOT / "scripts" / "make_review_inputs.py"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
        md = root / "product" / "e2e" / "cases" / "home.md"
        md.write_text("## E2E-HOME-001 x\n", encoding="utf-8")
        out = "product/e2e/reviews/2026-01-01-t/inputs"
        p1 = subprocess.run([sys.executable, str(script), "--root", ".", "--out", out],
                            cwd=str(root), capture_output=True, text=True, timeout=120)
        assert p1.returncode == 0, p1.stderr
        m1 = json.loads((root / out / "MANIFEST.json").read_text(encoding="utf-8"))
        f1 = {f["path"]: f["sha256"] for f in m1["files"]}
        assert "product/e2e/cases/home.md" in f1, f1
        assert not (root / out / "snapshot-copies").exists(), "不得产生副本目录"
        md.write_text("## E2E-HOME-001 x\n## E2E-HOME-002 y\n", encoding="utf-8")
        assert subprocess.run([sys.executable, str(script), "--root", ".", "--out", out],
                              cwd=str(root), capture_output=True, timeout=120).returncode == 0
        m2 = json.loads((root / out / "MANIFEST.json").read_text(encoding="utf-8"))
        f2 = {f["path"]: f["sha256"] for f in m2["files"]}
        assert f1["product/e2e/cases/home.md"] != f2["product/e2e/cases/home.md"], "指纹未跟随当前文件"


# ---- 「装配版本」对账（P3，2026-10-05）----


def _stamp(source: Path, root: Path) -> str:
    sys.path.insert(0, str(PKG_ROOT / "scripts"))
    import pkg_digest  # noqa: E402  延迟导入：算法单点，测试同源
    return pkg_digest.stamp_file(source, root / ".atlas" / "VERSION")


def _version_rows(root: Path) -> dict:
    mod = _load_check()
    rows = mod.Row()
    mod.check_version(root, rows)
    return {r["name"]: r for r in rows.rows}


def test_check_version_ok_when_source_unchanged() -> None:
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "tool.py").write_text("print('v1')\n", encoding="utf-8")
        root.mkdir()
        stamped = _stamp(src, root)
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "ok", row
        assert stamped in row["detail"]


def test_check_version_warns_when_source_advanced() -> None:
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "tool.py").write_text("print('v1')\n", encoding="utf-8")
        root.mkdir()
        _stamp(src, root)
        (src / "scripts" / "tool.py").write_text("print('v2 — source advanced')\n", encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN", row          # 漂移是信号不是门禁失败
        # M68 钉（2026-10-15，D79 ⑤）：WARN detail 必须带**可执行动作词齐组**——
        # `atlas upgrade` / `install.sh`（两种源态并列）/ `backflow`（明细通道）；缺一
        # 即文案漂回没有动作的无用警告 ⇒ 本断言红。变异证明：从源 detail 摘掉一个词 ⇒ 红。
        assert "atlas upgrade" in row["detail"], row
        assert "install.sh" in row["detail"], row
        assert "backflow" in row["detail"], row


def test_check_version_skips_legacy_or_lost_source() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "proj"
        root.mkdir()
        assert _version_rows(root)["装配版本"]["status"] == "SKIP"  # 无 VERSION = 旧装配
        import shutil
        src, root2 = Path(td) / "atlas2", Path(td) / "proj2"
        # 源包盒必须落在**装配集**内（`scripts/`），否则 F37 后 `digest()` 抛 EmptyAssembly
        # ——本夹具此前用装配集外的 `s/`，靠旧口径「空装配返回空摘要」才立得住。
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "a.py").write_text("x\n", encoding="utf-8")
        root2.mkdir()
        _stamp(src, root2)
        shutil.rmtree(src)                            # 源包搬家/不可达 ⇒ SKIP 不误报
        assert _version_rows(root2)["装配版本"]["status"] == "SKIP"


def test_f37_bad_empty_stamp_gets_root_cause_warn() -> None:
    """F37（2026-10-15）：历史坏戳（= `sha256('')[:16]`）必须给**根因级**指引（重装），
    不得混进「源包已前进/落后」那条对账文案——后者把人引向对账，而这个戳不承载任何
    内容信息，对账对着的是空气。

    判别性：源包此处**存在且非空**，若没有哨兵，走的正是「源包已前进/落后」分支。
    """
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "tool.py").write_text("print('v1')\n", encoding="utf-8")
        (root / ".atlas").mkdir(parents=True)
        (root / ".atlas" / "VERSION").write_text(
            "e3b0c44298fc1c14\n2026-10-15T14:03:14+08:00\n" + str(src) + "\n", encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN", row
        assert "历史坏戳" in row["detail"], row
        assert "回灌对账" not in row["detail"], row     # 根因是坏戳，不是漂移


def test_f37_empty_assembly_is_warn_not_skip() -> None:
    """F37：装配集为空 ⇒ WARN（摘要不可信），**不得**降级为 SKIP。

    本仓 SKIP 语义 = 合法降级（「源即真相」类）；「装了 0 个文件」是装配出错，不是降级。
    同时钉住 `except EmptyAssembly` 必须排在 `except (OSError, ValueError)` **之前**——
    `EmptyAssembly` 是 `ValueError` 子类，并进同一个 tuple 会滑成 SKIP。
    """
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "docs").mkdir(parents=True)            # 装配集外目录 ⇒ 摘要覆盖不到
        (src / "docs" / "readme.md").write_text("x\n", encoding="utf-8")
        (root / ".atlas").mkdir(parents=True)
        (root / ".atlas" / "VERSION").write_text(
            "deadbeefdeadbeef\n2026-10-15T14:03:14+08:00\n" + str(src) + "\n", encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN", row
        assert "装配集为空" in row["detail"], row


# ---- RFC-20261023-02 ②：装配基线 manifest（逐文件指名 + 配对校验 + 旧装配降级）----


def test_rfc20261023_02_manifest_drift_names_files_with_action_words() -> None:
    """配对成立且漂移 ⇒ 逐文件指名（改/增/删 + 计数）；M68 三词在两分支各自复断言。"""
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "a.py").write_text("a1\n", encoding="utf-8")
        (src / "scripts" / "b.py").write_text("b1\n", encoding="utf-8")
        root.mkdir()
        _stamp(src, root)
        (src / "scripts" / "a.py").write_text("a2\n", encoding="utf-8")
        (src / "scripts" / "c.py").write_text("c1\n", encoding="utf-8")
        (src / "scripts" / "b.py").unlink()
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN", row
        assert "改 1 / 增 1 / 删 1" in row["detail"], row
        for name in ("scripts/a.py", "scripts/c.py", "scripts/b.py"):
            assert name in row["detail"], row
        for word in ("atlas upgrade", "install.sh", "backflow"):      # M68 双分支
            assert word in row["detail"], row


def test_rfc20261023_02_manifest_caps_named_files_and_counts_rest() -> None:
    """cap 10：同类超 10 只点名前 10 + 「等 N 项」（O3：上限改 0 也绿不可接受）。"""
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        for i in range(12):
            (src / "scripts" / f"f{i:02d}.py").write_text("v1\n", encoding="utf-8")
        root.mkdir()
        _stamp(src, root)
        for i in range(12):
            (src / "scripts" / f"f{i:02d}.py").write_text("v2\n", encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN", row
        assert "改 12" in row["detail"] and "等 12 项" in row["detail"], row


def test_rfc20261023_02_manifest_unpaired_warns() -> None:
    """manifest.digest ≠ 装配戳 ⇒ 半态 WARN（配对校验先行，不拿脏 manifest 逐文件指名）。

    变异：**M-new-4** 摘配对校验 ⇒ 本侧红（会落进「逐文件无差异」或错误指名）。
    """
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "a.py").write_text("a1\n", encoding="utf-8")
        root.mkdir()
        _stamp(src, root)
        mf = root / ".atlas" / "MANIFEST.json"
        data = json.loads(mf.read_text(encoding="utf-8"))
        data["digest"] = "deadbeefdeadbeef"
        mf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN" and "不配套" in row["detail"], row
        for word in ("atlas upgrade", "install.sh", "backflow"):
            assert word in row["detail"], row


def test_rfc20261023_02_manifest_malformed_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "a.py").write_text("a1\n", encoding="utf-8")
        root.mkdir()
        _stamp(src, root)
        (root / ".atlas" / "MANIFEST.json").write_text("{not-json", encoding="utf-8")
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "WARN" and "形态非法" in row["detail"], row


def test_rfc20261023_02_manifest_missing_is_legacy_ok_with_footnote() -> None:
    """旧装配（VERSION 在、manifest 缺）⇒ ok + 「正式判据未齐」尾注（S4，不新增红）。"""
    with tempfile.TemporaryDirectory() as td:
        src, root = Path(td) / "atlas", Path(td) / "proj"
        (src / "scripts").mkdir(parents=True)
        (src / "scripts" / "a.py").write_text("a1\n", encoding="utf-8")
        root.mkdir()
        stamped = _stamp(src, root)
        (root / ".atlas" / "MANIFEST.json").unlink()
        row = _version_rows(root)["装配版本"]
        assert row["status"] == "ok" and "旧装配无 manifest" in row["detail"], row
        assert stamped in row["detail"], row


def test_atlas_check_failure_log_written_on_fail_and_cleaned_on_pass() -> None:
    """atlas_check.py 失败时落盘 .atlas/runs/last-check-error.log；全绿时自动清理。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "validators", root / ".atlas" / "validators")
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\napps:\n  - name: web\n    path: web\n    kind: frontend\n"
            "    role: landing\n    stack: x\n", encoding="utf-8")
        c = root / "product" / "e2e" / "cases"
        c.mkdir(parents=True, exist_ok=True)
        (c / "home.md").write_text(CASE_BAD, encoding="utf-8")

        code, out = run(["--root", ".", "--fast"], root)
        assert code == 1
        err_log = root / ".atlas" / "runs" / "last-check-error.log"
        assert err_log.is_file(), "失败时必须生成 last-check-error.log"
        content = err_log.read_text(encoding="utf-8")
        assert "ATLAS CHECK FAILURE LOG" in content
        assert "validate_" in content
        assert "FAIL (详细错误堆栈已落盘至:" in out

        # 在另一个纯空测试目录验证：若存在历史错误日志，全绿 (code 0) 时自动删除
        root_clean = Path(td) / "clean_proj"
        root_clean.mkdir()
        fake_log = root_clean / ".atlas" / "runs" / "last-check-error.log"
        fake_log.parent.mkdir(parents=True)
        fake_log.write_text("old error", encoding="utf-8")
        assert fake_log.is_file()

        code_clean, out_clean = run(["--root", ".", "--fast"], root_clean)
        assert code_clean == 0, out_clean
        assert not fake_log.is_file(), "全绿时必须自动清理旧的 last-check-error.log"


def test_check_events_log_records_durations_on_fail() -> None:
    """P2（2026-10-23）：每轮向 `.atlas/runs/check-events.jsonl` 追加一行，
    行内含门名/状态/耗时；JSON 输出同字段；失败轮也要写，且是追加不是覆盖。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir(parents=True, exist_ok=True)
        os.symlink(PKG_ROOT / "validators", root / ".atlas" / "validators")
        os.symlink(PKG_ROOT / "scripts", root / ".atlas" / "scripts")
        (root / "product").mkdir(parents=True, exist_ok=True)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\napps:\n  - name: web\n    path: web\n    kind: frontend\n"
            "    role: landing\n    stack: x\n", encoding="utf-8")
        c = root / "product" / "e2e" / "cases"
        c.mkdir(parents=True, exist_ok=True)
        (c / "home.md").write_text(CASE_BAD, encoding="utf-8")

        code, out = run(["--root", ".", "--fast", "--json"], root)
        assert code == 1, out
        log = root / ".atlas" / "runs" / "check-events.jsonl"
        assert log.is_file(), "失败轮也必须写运行事件行"
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1, lines
        ev = json.loads(lines[0])
        assert ev["ok"] is False
        assert ev["fast"] is True
        assert ev["page"] is None
        assert ev["timestamp"]
        assert set(ev) >= {"timestamp", "git_head", "git_dirty", "ok", "fast",
                           "page", "ablation_id", "rows"}
        assert all({"name", "status", "duration_ms"} <= set(r) for r in ev["rows"]), ev
        by_name = {r["name"]: r for r in ev["rows"]}
        assert isinstance(by_name["validate_e2e_index"]["duration_ms"], int), by_name
        payload = json.loads(out)
        assert any(r.get("duration_ms") is not None for r in payload["rows"]), payload

        code2, out2 = run(["--root", ".", "--fast"], root)
        assert code2 == 1, out2
        assert len(log.read_text(encoding="utf-8").splitlines()) == 2, "事件行必须追加，不得覆盖"


def test_check_events_log_written_on_ok_run() -> None:
    """P2：全绿轮同样写事件行（ok=true），观测面不为失败轮专属。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        code, out = run(["--root", ".", "--fast", "--json"], root)
        assert code == 0, out
        log = root / ".atlas" / "runs" / "check-events.jsonl"
        assert log.is_file()
        ev = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert ev["ok"] is True
        assert ev["fast"] is True
        assert isinstance(ev["rows"], list)


def test_check_events_log_write_failure_does_not_fail_check() -> None:
    """P2：观测面写失败（`.atlas/runs` 被文件占用）不得反过来把检查判红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas").mkdir()
        (root / ".atlas" / "runs").write_text("not a dir", encoding="utf-8")
        code, out = run(["--root", ".", "--fast"], root)
        assert code == 0, out
        assert "OK" in out


def test_check_events_log_serialization_failure_does_not_raise(monkeypatch) -> None:
    """P2 blocker（评审 2026-10-23）：事件写入只捕 OSError 时，序列化 / 编码异常
    会从观测面漏成检查崩溃。这里让 `json.dumps` 抛 TypeError，助手必须吞掉。"""
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        rows = mod.Row()
        rows.add("x", "ok", "")
        monkeypatch.setattr(mod.json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("boom")))
        mod._write_check_event(Path(td), rows, fast=True, page=None)  # 不得抛


def test_check_event_git_state_ignores_atlas_runtime() -> None:
    """P2 major（评审 2026-10-23）：`.atlas/` 是运行态，不得把仓库判脏；
    非 git 目录无法判定 ⇒ None，不冒充 clean。"""
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def git(*args: str) -> None:
            subprocess.run(["git", *args], cwd=str(root), check=True,
                           capture_output=True, text=True)
        git("init")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (root / "a.txt").write_text("a", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-m", "init")
        head, dirty = mod._git_state(root)
        assert head != "unknown" and dirty is False
        (root / ".atlas" / "runs").mkdir(parents=True)
        (root / ".atlas" / "runs" / "check-events.jsonl").write_text("{}\n", encoding="utf-8")
        _head, dirty_runtime = mod._git_state(root)
        assert dirty_runtime is False, "`.atlas/` 运行态不得把仓库判脏"
        (root / "a.txt").write_text("changed", encoding="utf-8")
        _head, dirty_tracked = mod._git_state(root)
        assert dirty_tracked is True
    with tempfile.TemporaryDirectory() as td:
        _head, dirty_unknown = mod._git_state(Path(td))
        assert dirty_unknown is None, "非 git 目录不得冒充 clean"


def test_check_review_report_exposes_fake_stub_and_warns_baseline() -> None:
    """F21（R6「融与化」）：atlas_check 常驻巡检行对假桩报 FAIL，对基线兜底报 WARN。"""
    spec = importlib.util.spec_from_file_location("atlas_check", CK)
    ac = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ac)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rdir = root / "product" / "e2e" / "reviews"
        rdir.mkdir(parents=True)

        # 1. 手写假桩：只有 status: PASS，缺 expected/reviewed，缺 README.md
        fake_dir = rdir / "2026-10-15-fake-review"
        fake_dir.mkdir()
        (fake_dir / "review.json").write_text(
            json.dumps({"ok": True, "status": "PASS", "scope": "fake", "unit": "cases", "checks": []}),
            encoding="utf-8",
        )
        rows = ac.Row()
        ac.check_review_report(root, rows)
        row = next(r for r in rows.rows if r["name"] == "审查报告形态")
        assert row["status"] == "FAIL", row

        # 2. 合规基线兜底报告：如实 expected=1 / reviewed=0，复算一致 WARN
        shutil.rmtree(fake_dir)
        base_dir = rdir / "2026-10-15-adopt-baseline"
        base_dir.mkdir()
        (base_dir / "review.json").write_text(
            json.dumps({
                "ok": True,
                "status": "WARN",
                "basis": "auto-baseline",
                "root": str(root),
                "scope": "adopt-baseline",
                "unit": "e2e",
                "round": 1,
                "expected": 1,
                "reviewed": 0,
                "budget_exceeded": False,
                "checks": [],
                "other": ["基线兜底"],
            }),
            encoding="utf-8",
        )
        (base_dir / "README.md").write_text("# 审查总结\n- 状态：WARN\n", encoding="utf-8")
        (base_dir / "inputs").mkdir()
        (base_dir / "inputs" / "MANIFEST.json").write_text("{}", encoding="utf-8")

        rows2 = ac.Row()
        ac.check_review_report(root, rows2)
        row2 = next(r for r in rows2.rows if r["name"] == "审查报告形态")
        assert row2["status"] == "WARN", row2




def test_serial_execution_gate_bites_on_parallel_config() -> None:
    """契约 §7.1（`DESIGN` D115）：手改运行器配置成并行 ⇒「执行串行」门 **FAIL**（不是 WARN）。

    直接测门函数（不起子进程）：合规配置 ⇒ `ok`；改成 `workers: 4 / fullyParallel: true` ⇒ `FAIL`。
    变异 MD115：把门里的 `workers` 判据摘掉 ⇒ 本钉后半变红；还原逐字节一致。
    """
    spec = importlib.util.spec_from_file_location("atlas_check_under_test", CK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        cfg = scripts / "playwright.config.ts"
        def gate(text: str) -> str:
            cfg.write_text(text, encoding="utf-8")
            rr = mod.Row()
            mod.check_serial_execution(root, rr)
            return rr.rows[-1]["status"]

        # 合规 ⇒ ok
        assert gate("export default defineConfig({ workers: 1, fullyParallel: false });\n") == "ok"
        # **逐判据隔离**（只破 workers / 只破 fullyParallel 都必须 FAIL）——
        # 否则「两判据同破」的夹具会让任意一条判据被摘掉时仍绿（门钉失效）。
        assert gate("export default defineConfig({ workers: 4, fullyParallel: false });\n") == "FAIL"
        assert gate("export default defineConfig({ workers: 1, fullyParallel: true });\n") == "FAIL"


def test_layout_config_drives_preconditions_and_fails_loud(tmp_path) -> None:
    """RFC-20261026-01：前置路径随布局配置；非法配置 ⇒ 单行 FAIL。"""
    mod = _load_check()
    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    pre = mod._gate_preconditions(tmp_path)
    assert pre["validate_stack_profile"][0] == "docs/stack-profile.yaml"
    assert pre["validate_adr"][0] == "docs/adr"
    rows = mod.Row()
    assert mod.check_layout(tmp_path, rows)
    assert not rows.failed

    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: ../escape\n", encoding="utf-8")
    rows = mod.Row()
    assert not mod.check_layout(tmp_path, rows)
    assert rows.failed
    assert rows.rows[0]["name"] == "项目布局配置"
