#!/usr/bin/env python3
"""行级锚定测量面测试（RFC-20261122-08）。

四态口径 + 两级匹配 + 三模式 diff 基准 + executor 分轨 + 永不 die（RFC
§2.1-件② 约束①③）。变异钉：**M203**（摘 `line_anchor.normalize_line` 的
`+/-` 剥离 ⇒ mismatch 翻转，钉 `test_normalize_strips_markers` 红）/
**M204**（摘 `line_anchor.resolve_from_file` 的 L2 全文回退 ⇒ pre_existing
anchored 翻 unresolved，钉 `test_l2_fallback_pre_existing` 红）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _support import line_anchor  # noqa: E402

CONVERT = HERE.parent / "scripts" / "cli_review_convert.py"

DIFF_WITH_HUNK = (
    "diff --git a/src/api.ts b/src/api.ts\n"
    "--- a/src/api.ts\n"
    "+++ b/src/api.ts\n"
    "@@ -10,0 +11,2 @@\n"
    "+export function refreshToken(token: string) {\n"
    "+  return fetch('/refresh', {method: 'POST'});\n"
    "}\n"
)


def _comment(path="src/api.ts", start=11, end=12, code=None, **kw):
    c = {"severity": "high", "category": "bug",
         "path": path, "start_line": start, "end_line": end,
         "existing_code": code if code is not None
         else "export function refreshToken(token: string) {\n"
              "  return fetch('/refresh', {method: 'POST'});"}
    c.update(kw)
    return c


def _fixture_payload(comments, executor=None):
    p = {"summary": {"files_reviewed": 1}, "comments": comments}
    if executor:
        p["executor"] = executor
    return p


def _stats(comments, root, diff_text=DIFF_WITH_HUNK, **kw):
    return line_anchor.compute_stats(root, comments, diff_text=diff_text, **kw)


# ---- 钉1：四态夹具（RFC §2.2 证伪条件主链） ----

def test_four_state_counts(tmp_path):
    """correct→anchored / mismatch→mismatch / unresolved→unresolved /
    legacy→unanchored_legacy；reported 与 resolved 明细逐条落档。"""
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "api.ts").write_text("export function refreshToken(token: string) {\n"
                                         "  return fetch('/refresh', {method: 'POST'});\n}\n")
    comments = [
        _comment(start=11, end=12),                          # anchored（L1 命中且相交）
        _comment(start=50, end=51),                          # mismatch（命中无交集）
        _comment(path="src/ghost.ts", start=1, end=2,        # unresolved（L1 无 + L2 读不到）
                 code="definitely not anywhere xyz"),
        _comment(path="src/api.ts", start=0, end=0,          # legacy（行号 0）
                 code="export function refreshToken(token: string) {"),
    ]
    s = _stats(comments, root)
    assert (s["anchored"], s["mismatch"], s["unresolved"],
            s["unanchored_legacy"], s["unanchored_no_field"], s["unresolvable"]) == (1, 1, 1, 1, 0, 0)
    assert s["total"] == 4
    by_state = {c["state"]: c for c in s["comments"]}
    assert by_state["anchored"]["resolved"] == [11, 12]
    assert by_state["mismatch"]["resolved"] == [11, 12]


def test_anchored_predicate_is_intersection(tmp_path):
    """R-2 谓词：摘录为报告区间子集 ⇒ anchored（相交含子集），不是 mismatch。"""
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "api.ts").write_text("a1\nb2\nc3\nd4\ne5\n")
    diff = ("diff --git a/src/api.ts b/src/api.ts\n"
            "+++ b/src/api.ts\n@@ -0,0 +1,5 @@\n+a1\n+b2\n+c3\n+d4\n+e5\n")
    s = _stats([_comment(start=2, end=4, code="b2\nc3")], root, diff_text=diff)
    assert s["anchored"] == 1 and s["mismatch"] == 0


# ---- 钉1 附加：no-field 变体 + executor 分轨（R1-M5/R-5） ----

def test_no_field_and_executor_passthrough(tmp_path):
    """无 existing_code 键 ⇒ unanchored_no_field；executor 原值透传；
    无键 ⇒ unknown；判据窗语义 = 只有 session-subagent 进判据（此处只验记录）。"""
    s = _stats([{"path": "src/api.ts", "start_line": 1, "end_line": 1}],
               tmp_path, executor="session-subagent")
    assert s["unanchored_no_field"] == 1 and s["executor"] == "session-subagent"
    s2 = _stats([{"path": "src/api.ts", "start_line": 1, "end_line": 1}], tmp_path)
    assert s2["unanchored_no_field"] == 1 and s2["executor"] == "unknown"


# ---- 钉2：pre_existing L2 回退 + hunk 计数器/元行（R1-M1 修正面） ----

def test_l2_fallback_pre_existing(tmp_path):
    """**M204**：path 不在 diff ⇒ 跳 L1 直入 L2（pre_existing 口径前提）；
    摘 resolve_from_file ⇒ 本测试 anchored 翻 unresolved。"""
    root = tmp_path
    (root / "legacy").mkdir()
    (root / "legacy" / "old.py").write_text("KEEP_ONE\nKEEP_TWO\n")
    s = _stats([_comment(path="legacy/old.py", start=1, end=2, code="KEEP_ONE\nKEEP_TWO")],
               root, diff_text=DIFF_WITH_HUNK)
    assert s["anchored"] == 1 and s["unresolved"] == 0


def test_hunk_counter_and_no_newline_meta(tmp_path):
    """hunk 头计数器推算 + `\\ No newline at end of file` 元行跳过（R-4 边界）。"""
    diff = ("diff --git a/src/api.ts b/src/api.ts\n"
            "+++ b/src/api.ts\n@@ -7,0 +8,1 @@\n"
            "+export const LIMIT = 3\n"
            "\\ No newline at end of file\n")
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "api.ts").write_text("export const LIMIT = 3\n")
    s = _stats([_comment(start=8, end=8, code="export const LIMIT = 3")], root, diff_text=diff)
    assert s["anchored"] == 1
    assert s["comments"][0]["resolved"] == [8, 8]


def test_normalize_strips_markers(tmp_path):
    """**M203**：摘录带 diff 标记前缀（+/-/前导空白）仍命中；
    摘 normalize_line 的 `+/-` 剥离 ⇒ 本测试 anchored 翻 unresolved。"""
    s = _stats([_comment(start=11, end=12,
                         code="+export function refreshToken(token: string) {\n"
                              "-  return fetch('/refresh', {method: 'POST'});")],
               tmp_path, diff_text=DIFF_WITH_HUNK)
    assert s["anchored"] == 1


# ---- 钉3：三模式 diff 基准（R1-M2/R-3） ----

def test_diff_mode_none_grounding_fail(tmp_path):
    """无基准参数 ⇒ 整轮 unresolvable + grounding_ok False + diff_mode none
    （grounding 缺失时统计显式失能，防假 anchored）。"""
    s = _stats([_comment()], tmp_path, diff_text=None)
    assert s["grounding_ok"] is False and s["diff_mode"] == "none"
    assert s["unresolvable"] == 1 and s["anchored"] == 0


def test_git_failure_grounding_fail(tmp_path):
    """base/head 给了但目录非 git 仓 ⇒ git 失败 ⇒ 整轮 unresolvable。"""
    s = line_anchor.compute_stats(tmp_path, [_comment()], base="HEAD", head="HEAD~1")
    assert s["grounding_ok"] is False and s["diff_mode"] == "range"
    assert s["unresolvable"] == 1


# ---- 钉3 附加：端到端（转换器子进程，--diff-staged + 判收链零影响 + 永不 die） ----

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _run_convert(root, outdir, diff_args):
    fixture = root / "fixture.json"
    fixture.write_text(json.dumps(_fixture_payload([_comment(start=1, end=2)],
                                                   executor="session-subagent"),
                                  ensure_ascii=False))
    return subprocess.run(
        [sys.executable, str(CONVERT), "--input", str(fixture), "--out", str(outdir),
         "--unit", "RFC08-T", "--expected-files", "1", *diff_args],
        cwd=str(root), capture_output=True, text=True)


def test_e2e_staged_warn_and_verdict_chain_untouched(tmp_path):
    """端到端：真 git 仓 + --diff-staged ⇒ anchoring-stats.json 落盘 + stderr
    WARN 行 + review.json 判收链零影响（rc/字段/指纹不变）。"""
    root = tmp_path
    (root / "src").mkdir()
    _git(root, "init", "-q")
    (root / "src" / "api.ts").write_text("old\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    (root / "src" / "api.ts").write_text("export function refreshToken(token: string) {\n"
                                         "  return fetch('/refresh', {method: 'POST'});\n}\n")
    _git(root, "add", ".")  # 暂存区 = HEAD..INDEX
    outdir = root / "out"
    pr = _run_convert(root, outdir, ["--diff-staged"])
    assert pr.returncode == 0, pr.stderr
    assert "WARN（行级锚定）" in pr.stderr
    stats = json.loads((outdir / "anchoring-stats.json").read_text(encoding="utf-8"))
    assert stats["diff_mode"] == "staged" and stats["executor"] == "session-subagent"
    assert stats["anchored"] == 1
    review = json.loads((outdir / "review.json").read_text(encoding="utf-8"))
    assert "anchoring" not in json.dumps(review)  # 判收链零影响


def test_e2e_stats_write_failure_degrades_warn(tmp_path):
    """约束①③：stats 写失败（outdir 只读）⇒ stderr WARN 降级，退出码与
    review.json 产物不变（永不 die）。"""
    root = tmp_path
    (root / "src").mkdir()
    _git(root, "init", "-q")
    (root / "src" / "api.ts").write_text("export function refreshToken(token: string) {}\n")
    _git(root, "add", ".")
    outdir = root / "out"
    outdir.mkdir()
    # 精确隔离：让 stats 落盘路径是目录 ⇒ write_text 撞 IsADirectoryError（OSError），
    # 其余写盘链（findings/review.json/README）不受影响——只打链尾最后一步。
    (outdir / "anchoring-stats.json").mkdir()
    pr = _run_convert(root, outdir, ["--diff-staged"])
    assert pr.returncode == 0, pr.stderr
    assert "统计未产出" in pr.stderr
    assert (outdir / "review.json").is_file()
