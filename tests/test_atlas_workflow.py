#!/usr/bin/env python3
"""Atlas Workflow 自建执行层调度器的单元回归测试 (D204)。

覆盖：
1. Plan 阶段：大任务拆解、生成标准 Task Card (`prd.md` + `task.json`)；
2. Dispatch 阶段：状态流转为 in_progress，生成最小上下文派单包 (`dispatch.md`)；
3. Verify 阶段：参数透传与 staged 调用；
4. Finish 阶段：无合格 review.json 时强制阻断，有合规报告时顺利收口；
5. Status 阶段：任务清单与依赖状态呈现。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_workflow.py"


def run(root: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=60, env=e)


def make_clean_project(root: Path) -> Path:
    (root / "product" / "prd").mkdir(parents=True, exist_ok=True)
    (root / "product" / "prd" / "home-prd.md").write_text(
        "# 首页 PRD\n\n| AC ID | 验收断言 |\n|---|---|\n| AC-HOME-001 | 首页标题展示 |\n",
        encoding="utf-8"
    )
    return root


def test_plan_creates_task_card_and_meta(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "plan", "--unit", "T-01", "--requirement", "请落实 AC-HOME-001 首页标题修改")
    assert p.returncode == 0, p.stdout + p.stderr

    task_dir = root / ".atlas" / "tasks" / "T-01"
    assert (task_dir / "prd.md").is_file()
    assert (task_dir / "task.json").is_file()

    prd_text = (task_dir / "prd.md").read_text(encoding="utf-8")
    assert "atlas-acceptance: AC-HOME-001" in prd_text
    assert "## 2. 确认口径与证据台账 (Confirmed)" in prd_text

    meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert meta["id"] == "T-01"
    assert meta["status"] == "todo"
    assert "AC-HOME-001" in meta["acs"]


def test_plan_decomposes_multiple_tasks(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req = """### 步骤一：改动接口 AC-HOME-001
修改首页接口字段

### 步骤二：前端展示
页面挂载组件并增加单元测试"""
    p = run(root, "plan", "--unit", "T-02", "--requirement", req)
    assert p.returncode == 0, p.stdout + p.stderr

    t1_dir = root / ".atlas" / "tasks" / "T-02-01"
    t2_dir = root / ".atlas" / "tasks" / "T-02-02"
    assert t1_dir.is_dir() and t2_dir.is_dir()

    meta2 = json.loads((t2_dir / "task.json").read_text(encoding="utf-8"))
    assert meta2["depends_on"] == ["T-02-01"]


def test_dispatch_generates_curated_context(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-03", "--requirement", "落实 AC-HOME-001")
    p = run(root, "dispatch", "--unit", "T-03")
    assert p.returncode == 0, p.stdout + p.stderr

    t_dir = root / ".atlas" / "tasks" / "T-03"
    dispatch_file = t_dir / "dispatch.md"
    assert dispatch_file.is_file()
    text = dispatch_file.read_text(encoding="utf-8")
    assert "AC-HOME-001" in text
    assert "atlas review --unit T-03 --staged" in text

    meta = json.loads((t_dir / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "in_progress"


def test_finish_blocks_without_review(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-04", "--requirement", "普通任务")
    run(root, "dispatch", "--unit", "T-04")

    # 未执行 review，尝试 finish 应被阻断
    p = run(root, "finish", "--unit", "T-04")
    assert p.returncode == 1
    assert "无法收口" in p.stderr or "未找到" in p.stderr


def test_finish_succeeds_with_valid_review(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-05", "--requirement", "测试收口")
    run(root, "dispatch", "--unit", "T-05")

    # 构造与 cli_review_convert 实际产出一致的审查报告（status/ok/checks；无 summary 键）
    r_dir = root / "product" / "reviews" / "2026-11-19-impl-review-T-05"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "PASS", "checks": [], "other": []
    }), encoding="utf-8")

    p = run(root, "finish", "--unit", "T-05")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "status: completed" in p.stdout

    meta = json.loads((root / ".atlas" / "tasks" / "T-05" / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"


def test_finish_blocks_warn_report(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-07", "--requirement", "测试 WARN 阻断")
    run(root, "dispatch", "--unit", "T-07")

    r_dir = root / "product" / "reviews" / "2026-11-19-impl-review-T-07"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "WARN",
        "checks": [{"id": "D1", "level": "Major", "check": "design_consistency",
                    "target": "src/a.ts:1-2", "detail": "x", "disposition": "open"}],
    }), encoding="utf-8")

    p = run(root, "finish", "--unit", "T-07")
    assert p.returncode == 1
    assert "WARN" in p.stderr


def test_replan_preserves_advanced_status(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req = "落实 AC-HOME-001"
    run(root, "plan", "--unit", "T-08", "--requirement", req)
    run(root, "dispatch", "--unit", "T-08")
    run(root, "plan", "--unit", "T-08", "--requirement", req)

    meta = json.loads((root / ".atlas" / "tasks" / "T-08" / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "in_progress"


def test_dispatch_group_prefix_resolves_first_subtask(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req = """### 步骤一 AC-HOME-001
改接口

### 步骤二
改页面"""
    run(root, "plan", "--unit", "T-09", "--requirement", req)
    p = run(root, "dispatch", "--unit", "T-09")
    assert p.returncode == 0, p.stdout + p.stderr

    meta = json.loads((root / ".atlas" / "tasks" / "T-09-01" / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "in_progress"
    assert (root / ".atlas" / "tasks" / "T-09-01" / "dispatch.md").is_file()


def test_run_stops_before_verify_when_index_empty(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(root), check=True)

    p = run(root, "run", "--unit", "T-10", "--requirement", "落实 AC-HOME-001")
    assert p.returncode == 2
    assert "暂存区为空" in p.stdout
    assert (root / ".atlas" / "tasks" / "T-10" / "dispatch.md").is_file()


def test_plan_writes_atlas_store(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    (root / ".atlas" / "tasks").mkdir(parents=True, exist_ok=True)
    p = run(root, "plan", "--unit", "T-11", "--requirement", "落实 AC-HOME-001")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / ".atlas" / "tasks" / "T-11" / "task.json").is_file()


def test_next_review_round_autoincrements(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("atlas_workflow", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    d = (tmp_path / "product" / "reviews"
         / f"{date.today().isoformat()}-impl-review-U" / "findings")
    d.mkdir(parents=True)
    (d / "U.r1.json").write_text("{}", encoding="utf-8")
    (d / "U.r2.json").write_text("{}", encoding="utf-8")

    assert mod._next_review_round(tmp_path, "U") == 3
    assert mod._next_review_round(tmp_path, "V") == 1


def test_status_presents_task_list(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-06", "--requirement", "查看状态")
    p = run(root, "status")
    assert p.returncode == 0
    assert "[T-06]" in p.stdout
