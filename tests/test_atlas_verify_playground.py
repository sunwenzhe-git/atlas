#!/usr/bin/env python3
"""验收执行器的**常驻真跑回归**(RFC-20261025-02 / `DESIGN.md` D150;固化自 2026-10-25
合成靶场首咬,资产 = `tests/fixtures/verify_playground/`)。

设计:
- 资产 = 一棵最小合法采纳仓(beta.10 装配口径):stack-profile(`mode: none`)+ 单页 2 用例
  (改态语义,防恒真)+ 最小 PRD 组(变更/增量起步)+ 审查报告夹具 + 项目 prepare 钩子 + 静态页。
- 测试内装配:`install.sh --force` 装进 tmp(`--force` = tmp 无 git);`gen_e2e_scripts --apply`
  生成脚本;`http.server` 线程当靶场。**零后端依赖、零 /tmp 残留**——执行器的真跑级回归场。
- 前置判据:模块可解析(`pw_runner.probe`)+ 浏览器在(`probe_browser`)任一不成立 ⇒
  `pytest.skip`(真跑级测试如实跳过,与「E2E 真跑」门 SKIP 同语义,不假装绿)。
- 每测试自清场(`.atlas-run/` + `reviews/*-verify/`),互不依赖执行顺序。

断言对齐 D150 出库实录:全链绿批(pre 真跑/run=atlas_check 真跑/report 留档)、短路复跑、
注红批(run FAIL + trace 留证 + 不落档)、恢复复绿。
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
import functools
import http.server
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
ASSETS = PKG_ROOT / "tests" / "fixtures" / "verify_playground"
INSTALL = PKG_ROOT / "install.sh"
VERIFY = PKG_ROOT / "scripts" / "atlas_verify.py"


def _load_pw_runner():
    spec = importlib.util.spec_from_file_location(
        "pw_runner_under_test", PKG_ROOT / "_support" / "pw_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pw_ready(tmp: Path) -> bool:
    """真跑前置 = 模块可解析 **加** 浏览器在(D124 两件事);只读探测,不动全局。"""
    pw = _load_pw_runner()
    d = tmp / "probe-scripts"
    d.mkdir(parents=True, exist_ok=True)
    ok, _ = pw.probe(d)
    if not ok:
        return False
    browser_ok, _ = pw.probe_browser(d)
    return browser_ok


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def playground():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "playground"
        shutil.copytree(ASSETS, root)
        port = _free_port()
        profile = root / "product" / "stack-profile.yaml"
        profile.write_text(
            (ASSETS / "product" / "stack-profile.yaml.tpl").read_text(encoding="utf-8")
            .replace("{PORT}", str(port)), encoding="utf-8")

        r = subprocess.run(["bash", str(INSTALL), "--target", str(root), "--force"],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr[-800:]
        assert (root / ".atlas" / "scripts" / "atlas_verify.py").is_file()

        g = subprocess.run([sys.executable, str(root / ".atlas" / "scripts" / "gen_e2e_scripts.py"),
                            "--root", str(root), "--apply"],
                           capture_output=True, text=True, timeout=300)
        assert g.returncode == 0, g.stderr[-800:]

        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(root / "site"))
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield root
        finally:
            srv.shutdown()


def _clean_batches(root: Path) -> None:
    shutil.rmtree(root / "product/e2e/scripts/.atlas-run", ignore_errors=True)
    for d in (root / "product/e2e/reviews").glob("*-verify"):
        shutil.rmtree(d, ignore_errors=True)


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VERIFY), "--root", str(root), *extra],
                          capture_output=True, text=True, timeout=900)


def _archive(root: Path) -> Path | None:
    ds = list((root / "product/e2e/reviews").glob("*-verify"))
    return ds[0] if ds else None


# 自指守卫:install.sh 把本文件打进装配副本(.atlas/tests/)——副本态再跑会递归装仓
# (2026-10-25 实测:setup ERROR ×2)。真跑回归只在**源包态**运行(有 install.sh);
# 副本态 = 已在被执行的采纳仓内,如实 skip。
pytestmark = pytest.mark.skipif(
    not (PKG_ROOT / "install.sh").is_file(),
    reason="装配副本态(无 install.sh)= 采纳仓内,真跑回归只在源包态运行")

@pytest.mark.skipif(not ASSETS.is_dir(), reason="固化资产缺失")
def test_playground_full_green_batch_and_short_circuit(playground) -> None:
    """真跑级咬合①②(D150 实录同款):全链绿批(pre 真跑/run=atlas_check 真跑/report 留档)
    + 短路复跑(real_run 0)。"""
    root = playground
    _clean_batches(root)
    r = _run(root)
    assert r.returncode == 0, (r.stdout[-800:], r.stderr[-400:])
    arch = _archive(root)
    assert arch is not None, r.stdout[-400:]
    report = json.loads((arch / "report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True and report["real_run_count"] == 1, report
    steps = {s["name"]: s for s in report["steps"]}
    assert steps["pre"]["status"] == "ok"                       # prepare 真跑
    assert (root / ".verify/last-prepare").is_file()          # prepare cwd = 项目根(atlas-prepare.mjs 同款)
    assert any(row["name"].startswith("E2E") and row["status"] in {"ok", "WARN"}
               for row in report["rows"]), report["rows"]        # 真跑门(全局兜底 ⇒ WARN 合法;门名含空格,rows.name 只取首词——_parse_rows 已知局限)

    r2 = _run(root, "--json")
    assert r2.returncode == 0
    data = json.loads(r2.stdout)
    assert data["short_circuit"] is True and data["real_run_count"] == 0


def test_playground_red_batch_keeps_evidence_and_skips_archive(playground) -> None:
    """真跑级咬合③(D150 实录同款):注红(产品态破坏)⇒ run FAIL + trace 留证 + **不落档**;
    恢复后复绿重落档。注红 = 取证动作,red 不计缺陷判据(D148 注红条款)。"""
    root = playground
    _clean_batches(root)
    site = root / "site" / "index.html"
    original = site.read_text(encoding="utf-8")
    try:
        site.write_text(original.replace("验收靶场", "验收耙场"), encoding="utf-8")
        r = _run(root)
        assert r.returncode == 1, (r.stdout[-600:], r.stderr[-400:])
        traces = list((root / "product/e2e/scripts/.atlas-run").rglob("trace.zip"))
        assert traces, "失败批必须留 D108 证据(trace)"
        assert _archive(root) is None                            # 失败批不落档
    finally:
        site.write_text(original, encoding="utf-8")

    r2 = _run(root)
    assert r2.returncode == 0, r2.stdout[-600:]                   # 恢复后复绿重落档
    assert _archive(root) is not None
