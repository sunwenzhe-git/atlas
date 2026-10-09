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
import tempfile
import threading
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CK = PKG_ROOT / "scripts" / "atlas_check.py"

HOME_HTML = '<html><body><button data-testid="home-cta-btn">x</button></body></html>'
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


def test_check_e2e_reachable_target_is_not_skipped() -> None:
    """可达靶场不得被探针误 SKIP（门不是恒跳过）：探针放行后照跑并如实报结果。

    变异证明：把探针改成恒不可达 ⇒ 本用例红（报 SKIP 而不是 ok）。
    """
    mod = _load_check()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        scripts = root / "product" / "e2e" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "login.spec.ts").write_text("test('ok', async () => {});\n", encoding="utf-8")
        nm = root / "fake_nm" / ".bin"
        nm.mkdir(parents=True)
        pw = nm / "playwright"
        pw.write_text("#!/bin/sh\necho '1 passed'\nexit 0\n", encoding="utf-8")
        pw.chmod(0o755)
        (root / "product" / "stack-profile.yaml").write_text(
            f"e2e:\n  runner: node-playwright\n  node_modules: {nm.parent}\n  app_base_url: {_live_base()}\n",
            encoding="utf-8")
        rows = mod.Row()
        mod.check_e2e(root, rows, "login")
        row = [r for r in rows.rows if r["name"].startswith("E2E 真跑")][0]
        assert row["status"] == "ok", rows.rows

def test_check_e2e_fails_loudly_when_node_playwright_missing() -> None:
    """单轨化（B201-4）：node 可执行缺失 ⇒ FAIL 点名（不静默降级、不猜别的运行器）。"""
    mod = _load_check()
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
        od = root / ".trellis" / "spec" / "structure" / ".adapter-out"
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
        assert "回灌对账" in row["detail"]


def test_check_version_skips_legacy_or_lost_source() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "proj"
        root.mkdir()
        assert _version_rows(root)["装配版本"]["status"] == "SKIP"  # 无 VERSION = 旧装配
        src, root2 = Path(td) / "atlas2", Path(td) / "proj2"
        (src / "s").mkdir(parents=True)
        (src / "s" / "a.py").write_text("x\n", encoding="utf-8")
        root2.mkdir()
        _stamp(src, root2)
        import shutil
        shutil.rmtree(src)                            # 源包搬家/不可达 ⇒ SKIP 不误报
        assert _version_rows(root2)["装配版本"]["status"] == "SKIP"
