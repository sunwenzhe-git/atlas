#!/usr/bin/env python3
"""Atlas Workflow Progress 只读进度探针的回归测试 (RFC-20261122-02)。

覆盖：
1. 四格展开（in_progress）：派工存在性 / 暂存内外中性计数 / 审查跨日轮次 / 矩阵填写进度；
2. 实现格归因（Major-3/证伪条件反向断言）：paths 外文件必须落「外」，不得计入「命中」；
3. 审查格跨日语义（Minor-4）：轮号按日重置，最近轮按（日期,轮号）排序，坏 json 标 unknown；
4. 边界反面包：todo / completed / 组 ID / 坏卡 / 非 git 环境 / 暂存为空 / 无矩阵；
5. 只读保证：探针前后账本逐字节一致；
6. 取号回归：_next_review_round 消费公共构造后行为不变（当日取号、按日重置）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_workflow.py"
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.workflow_finish import scan_review_rounds, staged_files  # noqa: E402
from scripts.atlas_workflow import _next_review_round  # noqa: E402


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=60)


def make_clean_project(root: Path) -> Path:
    (root / "product" / "prd").mkdir(parents=True, exist_ok=True)
    (root / "product" / "prd" / "home-prd.md").write_text(
        "# 首页 PRD\n\n| AC ID | 验收断言 |\n|---|---|\n| AC-HOME-001 | 首页标题展示 |\n",
        encoding="utf-8")
    return root


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def make_in_progress(root: Path, unit: str = "T-P1",
                     paths: list[str] | None = None) -> Path:
    """plan + dispatch 到 in_progress（不需要 git）。"""
    if paths:
        run(root, "plan", "--unit", unit, "--requirement", "落实 AC-HOME-001",
            "--paths", *paths)
    else:
        run(root, "plan", "--unit", unit, "--requirement", "落实 AC-HOME-001")
    p = run(root, "dispatch", "--unit", unit)
    assert p.returncode == 0, p.stdout + p.stderr
    return root / ".atlas" / "tasks" / unit


def add_review_round(root: Path, unit: str, day: str, round_no: int,
                     payload: dict | None = None) -> Path:
    """造一轮审查证据文件（形状同 cli_review_convert 产出：status/ok/round）。"""
    fdir = (root / "product" / "reviews" / f"{day}-impl-review-{unit}" / "findings")
    fdir.mkdir(parents=True, exist_ok=True)
    body = payload if payload is not None else {"status": "PASS", "ok": True,
                                                "round": round_no, "unit": unit}
    f = fdir / f"{unit}.r{round_no}.json"
    f.write_text(json.dumps(body, ensure_ascii=False) + "\n", encoding="utf-8")
    return f


def write_matrix(task_dir: Path) -> None:
    (task_dir / "coverage-matrix.md").write_text(
        "| ID | PRD | 设计文档 | 实现 | E2E |\n"
        "|---|---|---|---|---|\n"
        "| R-1 | 覆盖（a.md） | 覆盖（b.md） | UNRESOLVED | 不涉及（无） |\n"
        "| R-2 | 覆盖（c.md） | | 覆盖（d.md） | 不涉及（无） |\n"
        "| R-3 | UNRESOLVED | UNRESOLVED | 不涉及（无） | 覆盖（e.md） |\n",
        encoding="utf-8")


def ledger_snapshot(tasks_root: Path) -> dict[str, bytes]:
    """账本逐字节快照（只读保证断言用）。"""
    return {str(p.relative_to(tasks_root)): p.read_bytes()
            for p in sorted(tasks_root.rglob("*")) if p.is_file()}


# ---------- 四格展开与归因 ----------

def test_in_progress_four_stages_and_outside_attribution(tmp_path: Path) -> None:
    """证伪条件（discriminating_check）：范围外文件不得计入命中；轮次跨日分段。"""
    root = make_clean_project(tmp_path)
    t_dir = make_in_progress(root, paths=["src/a"])
    write_matrix(t_dir)
    add_review_round(root, "T-P1", "2026-11-20", 1, {"status": "WARN", "ok": False})
    add_review_round(root, "T-P1", "2026-11-22", 1)
    add_review_round(root, "T-P1", "2026-11-22", 2)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "src" / "a").mkdir(parents=True, exist_ok=True)
    (root / "src" / "a" / "x.py").write_text("a\n", encoding="utf-8")
    (root / "other.py").write_text("b\n", encoding="utf-8")
    _git(root, "add", "src/a/x.py", "other.py")

    p = run(root, "progress", "--unit", "T-P1")
    assert p.returncode == 0, p.stdout + p.stderr
    out = p.stdout
    assert "(in_progress)" in out
    assert "dispatch.md 已生成" in out and "AC" in out
    # 归因：内 1 外 1，other.py 必须落「外」
    assert "paths 内 1 / paths 外 1" in out
    assert "内：src/a/x.py" in out and "外：other.py" in out
    assert "范围外含其他在途任务的正常暂存" in out  # Major-3 中性文案
    # 跨日语义：2 日 3 轮，最近轮 = 2026-11-22 r2（按〔日期,轮号〕排序，非轮号）
    assert "跨 2 日共 3 轮" in out
    assert "最近轮 2026-11-22 r2 —— status=PASS ok=true" in out
    # 矩阵：PRD 2/3（UNRESOLVED 1）
    assert "矩阵 3 行" in out and "PRD 2/3（UNRESOLVED 1）" in out


def test_review_latest_ordering_by_date_then_round(tmp_path: Path) -> None:
    """旧日期更大轮号不得盖过新日期：最近轮 = 日期最大者。"""
    root = make_clean_project(tmp_path)
    make_in_progress(root)
    add_review_round(root, "T-P1", "2026-11-20", 5)   # 轮号大但日期旧
    add_review_round(root, "T-P1", "2026-11-21", 1)
    rounds = scan_review_rounds(root, "T-P1")
    assert rounds[-1][0] == "2026-11-21" and rounds[-1][1] == 1
    p = run(root, "progress", "--unit", "T-P1")
    assert "最近轮 2026-11-21 r1" in p.stdout


def test_review_bad_json_shows_unknown(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_in_progress(root)
    add_review_round(root, "T-P1", "2026-11-22", 1, payload={"status": "PASS"})  # 缺 ok
    f = root / "product" / "reviews" / "2026-11-22-impl-review-T-P1" / "findings" / "T-P1.r2.json"
    f.write_text("{broken", encoding="utf-8")
    p = run(root, "progress", "--unit", "T-P1")
    assert "跨 1 日共 2 轮" in p.stdout
    assert "status=UNKNOWN" in p.stdout


def test_json_output_machine_readable(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_in_progress(root)
    p = run(root, "--json", "progress", "--unit", "T-P1")
    assert p.returncode == 0, p.stdout + p.stderr
    snap = json.loads(p.stdout)
    assert snap["unit"] == "T-P1" and snap["status"] == "in_progress"
    st = snap["stages"]
    assert st["dispatch"]["present"] is True and st["dispatch"]["acs"] >= 1
    assert set(st) == {"dispatch", "staged", "review", "matrix"}


# ---------- 边界反面包 ----------

def test_todo_and_completed_cards_show_guidance(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-P2", "--requirement", "落实 AC-HOME-001")
    p = run(root, "progress", "--unit", "T-P2")
    assert "未派工" in p.stdout and "dispatch" in p.stdout

    meta_path = root / ".atlas" / "tasks" / "T-P2" / "task.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["status"] = "completed"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    p = run(root, "progress", "--unit", "T-P2")
    assert "已收口" in p.stdout and "status --all" in p.stdout


def test_group_id_lists_members_without_guessing(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    tasks = root / ".atlas" / "tasks"
    for sub in ("T-G-01", "T-G-02"):
        d = tasks / sub
        d.mkdir(parents=True)
        (d / "task.json").write_text(json.dumps(
            {"id": sub, "title": sub, "status": "in_progress",
             "depends_on": [], "affected_domains": [], "acs": []},
            ensure_ascii=False), encoding="utf-8")
    p = run(root, "progress", "--unit", "T-G")
    assert "组标识" in p.stdout and "T-G-01" in p.stdout and "T-G-02" in p.stdout


def test_corrupt_card_named_by_load_tasks(tmp_path: Path) -> None:
    """坏卡由 load_tasks 指名拦截（PlanError → die(2)），探针无需重复检测。"""
    root = make_clean_project(tmp_path)
    d = root / ".atlas" / "tasks" / "T-BAD"
    d.mkdir(parents=True)
    (d / "task.json").write_text("{broken json", encoding="utf-8")
    p = run(root, "progress", "--unit", "T-BAD")
    assert p.returncode == 2
    assert "任务卡损坏或不可读" in p.stderr and "task.json" in p.stderr


def test_non_git_and_empty_staging_distinguished(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_in_progress(root)
    p = run(root, "progress", "--unit", "T-P1")
    assert "非 git 环境" in p.stdout  # Minor-6：与暂存为空分开

    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    p = run(root, "progress", "--unit", "T-P1")
    assert "暂存区为空" in p.stdout
    assert "非 git 环境" not in p.stdout


def test_no_paths_card_reports_unscoped(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_in_progress(root)  # 未给 --paths
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    (root / "app.py").write_text("x\n", encoding="utf-8")
    _git(root, "add", "app.py")
    p = run(root, "progress", "--unit", "T-P1")
    assert "未声明 paths" in p.stdout


def test_no_matrix_card_is_silent(tmp_path: Path) -> None:
    """plan --requirement 会生成骨架矩阵，故「无矩阵」须用手写非需求驱动卡测。"""
    root = make_clean_project(tmp_path)
    d = root / ".atlas" / "tasks" / "T-NM"
    d.mkdir(parents=True)
    (d / "task.json").write_text(json.dumps(
        {"id": "T-NM", "title": "手写卡", "status": "in_progress",
         "depends_on": [], "affected_domains": [], "acs": []},
        ensure_ascii=False), encoding="utf-8")
    p = run(root, "progress", "--unit", "T-NM")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "无矩阵" in p.stdout
    assert "非需求驱动卡" in p.stdout


def test_probe_is_readonly(tmp_path: Path) -> None:
    """只读保证：探针前后账本逐字节一致、状态不被改写。"""
    root = make_clean_project(tmp_path)
    make_in_progress(root)
    write_matrix(root / ".atlas" / "tasks" / "T-P1")
    add_review_round(root, "T-P1", "2026-11-22", 1)
    before = ledger_snapshot(root / ".atlas" / "tasks")
    run(root, "progress", "--unit", "T-P1")
    run(root, "--json", "progress", "--unit", "T-P1")
    run(root, "progress", "--unit", "T-NOSUCH")
    run(root, "progress", "--unit", "T-P")
    assert ledger_snapshot(root / ".atlas" / "tasks") == before


# ---------- 取号回归（公共构造替换后行为不变） ----------

def test_next_review_round_same_day_reset_semantics(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    unit, today = "T-P1", __import__("datetime").date.today().isoformat()
    assert _next_review_round(root, unit) == 1  # 无证据 ⇒ 1
    add_review_round(root, unit, today, 1)
    add_review_round(root, unit, today, 2)
    assert _next_review_round(root, unit) == 3  # 当日 max+1
    add_review_round(root, unit, "2026-01-01", 9)  # 旧日期更大轮号不得影响当日取号
    assert _next_review_round(root, unit) == 3  # 轮号按日重置语义保持


def test_staged_files_none_vs_empty_semantics(tmp_path: Path) -> None:
    """公共读面语义：None = git 不可用；[] = 暂存为空。"""
    assert staged_files(tmp_path) is None  # tmp_path 非 git 仓库
    root = make_clean_project(tmp_path / "g")
    _git(root, "init", "-q")
    assert staged_files(root) == []
