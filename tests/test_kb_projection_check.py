#!/usr/bin/env python3
"""KB 投影对账门(kb_projection_check.mjs + kb_index_refresh.mjs)的回归测试。

背景:open-zk-kb 索引只在 MCP 工具调用时更新,盘上手改 vault 文件不重索引 ⇒ 投影会
静默漂移(2026-09-29 实测 `3501` 快照滞留 12 天,`3508 §134`,§B103 同族)。本测试守的是:
  * 刷新后对账必须绿(索引 ⇔ 本体一致);
  * 门必须咬得住四类漂移:DRIFTED(内容改)/ UNINDEXED(新增未索引)/ ORPHAN(删文件留行);
  * 刷新脚本离线可用(embeddingConfig=null,不碰网络——MCP 通道 rebuild/embed 超时的根因)。

夹具 = 临时目录迷你 vault,经 kb_index_refresh.mjs 用真实包索引;bun 或 open-zk-kb 包
缺失 ⇒ SKIP(未就绪,不是通过)。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CHECK = PKG_ROOT / "scripts" / "kb_projection_check.mjs"
REFRESH = PKG_ROOT / "scripts" / "kb_index_refresh.mjs"
BUN = shutil.which("bun")
PKG = Path(os.environ.get("OPEN_ZK_KB_PKG", Path.home() / ".pi/agent/npm/node_modules/open-zk-kb"))

NOTE_A = """---
id: 2026010100000001
title: 夹具甲
kind: reference
status: permanent
lifecycle: living
type: atomic
tags:
  - atlas
  - scope:global
created: 2026-01-01
updated: 2026-01-01
tagline: 夹具甲一句话
---

# 夹具甲

> 夹具甲一句话

正文甲。

## Guidance

先读总览。
"""

NOTE_B = NOTE_A.replace("2026010100000001", "2026010100000002").replace("夹具甲", "夹具乙")


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BUN, str(script), *args], capture_output=True, text=True, timeout=120
    )


def setup_module(module) -> None:
    if BUN is None:
        raise AssertionError("bun 不可用")  # 会被下方 skipif 拦住,双保险
    if not (PKG / "package.json").exists():
        raise AssertionError("open-zk-kb 包缺失")


def test_projection_gate_bites_and_refresh_converges() -> None:
    if BUN is None or not (PKG / "package.json").exists():
        print(f"SKIP: bun={BUN} pkg={PKG}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        (vault / "atlas").mkdir(parents=True)
        (vault / "atlas" / "2026010100000001-note-a.md").write_text(NOTE_A, encoding="utf-8")
        (vault / "atlas" / "2026010100000002-note-b.md").write_text(NOTE_B, encoding="utf-8")

        # ① 刷新建索引 ⇒ 对账必须绿
        refreshed = run_script(REFRESH, "--vault", str(vault))
        assert refreshed.returncode == 0, f"refresh 失败:\n{refreshed.stdout}\n{refreshed.stderr}"
        assert "0 errors" in refreshed.stdout
        checked = run_script(CHECK, "--vault", str(vault))
        assert checked.returncode == 0, f"刷新后对账应绿:\n{checked.stdout}\n{checked.stderr}"
        assert "issues=0" in checked.stdout

        # ② 变异:改乙的正文 ⇒ 必须红,且指名道姓 DRIFTED + content
        target = vault / "atlas" / "2026010100000002-note-b.md"
        target.write_text(NOTE_B.replace("正文甲。", "正文乙(被改过)。").replace("正文甲", "正文乙"), encoding="utf-8")
        mutated = run_script(CHECK, "--vault", str(vault))
        assert mutated.returncode == 1, f"内容漂移应红:\n{mutated.stdout}\n{mutated.stderr}"
        assert "DRIFTED" in mutated.stdout and "note-b" in mutated.stdout

        # ③ 变异:新增文件不入索引 ⇒ UNINDEXED
        (vault / "atlas" / "2026010100000003-note-c.md").write_text(NOTE_A.replace("2026010100000001", "2026010100000003"), encoding="utf-8")
        added = run_script(CHECK, "--vault", str(vault))
        assert added.returncode == 1
        assert "UNINDEXED" in added.stdout and "note-c" in added.stdout

        # ④ 变异:删文件留索引行 ⇒ ORPHAN
        (vault / "atlas" / "2026010100000001-note-a.md").unlink()
        deleted = run_script(CHECK, "--vault", str(vault))
        assert deleted.returncode == 1
        assert "ORPHAN" in deleted.stdout and "note-a" in deleted.stdout

        # ⑤ 再刷新 ⇒ 全部漂移收敛,回到绿(修法的闭环)
        converged = run_script(REFRESH, "--vault", str(vault))
        assert converged.returncode == 0
        final = run_script(CHECK, "--vault", str(vault))
        assert final.returncode == 0, f"再刷新后应绿:\n{final.stdout}\n{final.stderr}"
        assert "issues=0" in final.stdout


if __name__ == "__main__":
    test_projection_gate_bites_and_refresh_converges()
    print("PASS")
    sys.exit(0)
