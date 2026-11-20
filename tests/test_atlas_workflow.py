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
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


def _month() -> str:
    """归档月份目录名（与写入侧同口径：归档当天）。"""
    return date.today().strftime("%Y-%m")


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

    archived_card = (root / ".atlas" / "tasks" / "archive" / _month() / "T-05")
    meta = json.loads((archived_card / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["e2e_precondition"]["status"] == "SKIP"  # 无 E2E 索引：显式 SKIP，不静默通过
    assert not (root / ".atlas" / "tasks" / "T-05").exists()  # 已归档出活跃区

    # 正例：归档卡仍在判据（archive/*/*/prd.md）与封条（archive/*/<ID>/<tail>）的扫描面内
    assert archived_card.joinpath("prd.md") in set(
        (root / ".atlas" / "tasks").glob("archive/*/*/prd.md"))
    from _support.solution_seal import _resolve_card_file
    sealed = _resolve_card_file(root, ".atlas/tasks/T-05/prd.md")
    assert sealed is not None and sealed.resolve() == (archived_card / "prd.md").resolve()

    # finish 幂等：已归档任务重跑不报错、不重复移动
    p2 = run(root, "finish", "--unit", "T-05")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "already" in p2.stdout


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


def test_verify_session_executor_unblocks_finish(tmp_path: Path) -> None:
    """无审查 CLI 的宿主：verify 先待审（派工包），子代理产物落盘后复跑即可收口（issue #68）。"""
    root = make_clean_project(tmp_path)
    subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(root), check=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    run(root, "plan", "--unit", "T-12", "--requirement", "落实 AC-HOME-001")
    run(root, "dispatch", "--unit", "T-12")
    subprocess.run(["git", "add", "src/a.ts"], cwd=str(root), check=True)

    p1 = run(root, "verify", "--unit", "T-12")
    assert p1.returncode == 2, p1.stdout + p1.stderr
    assert "PENDING" in p1.stdout and "review-request.md" in p1.stdout

    r_dir = root / "product" / "reviews" / f"{date.today().isoformat()}-impl-review-T-12"
    (r_dir / "cli.json").write_text(json.dumps({
        "status": "completed",
        "summary": {"files_reviewed": 1, "comments": 0},
        "comments": [], "warnings": [],
        "manifest": {"coverage": {
            "selected": [{"path": "src/a.ts"}],
            "completed": [{"path": "src/a.ts"}],
            "failed": [], "waived": [], "reused": [],
        }},
    }), encoding="utf-8")

    p2 = run(root, "verify", "--unit", "T-12")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert (r_dir / "review.json").is_file()

    p3 = run(root, "finish", "--unit", "T-12")
    assert p3.returncode == 0, p3.stdout + p3.stderr
    meta = json.loads((root / ".atlas" / "tasks" / "archive" / _month() / "T-12"
                       / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"


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


def test_finish_does_not_match_longer_unit(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-1", "--requirement", "短 id")
    run(root, "dispatch", "--unit", "T-1")
    run(root, "plan", "--unit", "T-10", "--requirement", "长 id")
    run(root, "dispatch", "--unit", "T-10")
    reviews = root / "product" / "reviews"
    (reviews / "2026-11-19-impl-review-T-10").mkdir(parents=True)
    (reviews / "2026-11-19-impl-review-T-10" / "review.json").write_text(
        json.dumps({"schema_version": 4, "ok": True, "status": "PASS"}), encoding="utf-8")
    p = run(root, "finish", "--unit", "T-1")
    assert p.returncode == 1, "T-1 不得复用 T-10 的 PASS 报告"
    assert "T-1" in p.stderr


def test_dispatch_refuses_completed_and_blocked(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-11", "--requirement", "落实 AC-HOME-001")
    run(root, "dispatch", "--unit", "T-11")
    r_dir = root / "product" / "reviews" / "2026-11-19-impl-review-T-11"
    r_dir.mkdir(parents=True)
    (r_dir / "review.json").write_text(
        json.dumps({"schema_version": 4, "ok": True, "status": "PASS"}), encoding="utf-8")
    assert run(root, "finish", "--unit", "T-11").returncode == 0

    p = run(root, "dispatch", "--unit", "T-11")
    assert p.returncode == 2 and "completed" in p.stderr


def test_finish_unknown_or_traversal_unit(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "finish", "--unit", "NOPE", "--force")
    assert p.returncode == 2
    assert not (root / ".atlas" / "tasks" / "NOPE" / "task.json").exists()

    p2 = run(root, "finish", "--unit", "../escape", "--force")
    assert p2.returncode != 0


def test_dispatch_paths_persist_to_card(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-12", "--requirement", "落实 AC-HOME-001")
    p = run(root, "dispatch", "--unit", "T-12", "--paths", "apps/web/a.ts")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/T-12/task.json").read_text(encoding="utf-8"))
    assert meta["paths"] == ["apps/web/a.ts"]


E2E_HEADER = (
    "| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
)


def _write_pass_review(root: Path, unit: str) -> None:
    r_dir = root / "product" / "reviews" / f"2026-11-19-impl-review-{unit}"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(
        json.dumps({"schema_version": 4, "ok": True, "status": "PASS"}), encoding="utf-8")


def _write_e2e_index(root: Path, row: str) -> None:
    p = root / "product" / "e2e" / "e2e-index.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# E2E 索引\n\n" + E2E_HEADER + row + "\n", encoding="utf-8")


def test_finish_blocks_e2e_red_for_task_acs(tmp_path: Path) -> None:
    """#69：本任务 AC 关联的 E2E 用例为 red 时，finish 必须阻断。"""
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-20", "--requirement", "落实 AC-HOME-001")
    run(root, "dispatch", "--unit", "T-20")
    _write_pass_review(root, "T-20")
    _write_e2e_index(
        root, "| E2E-HOME-001 | home | 首页 | 功能 | AC-HOME-001 | T-20 | red | 断言失败 | cases/home.md |")

    p = run(root, "finish", "--unit", "T-20")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "red" in p.stderr and "E2E" in p.stderr
    meta = json.loads((root / ".atlas/tasks/T-20/task.json").read_text(encoding="utf-8"))
    assert meta["status"] != "completed"


def test_finish_records_e2e_pass_and_acceptance(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-21", "--requirement", "落实 AC-HOME-001")
    run(root, "dispatch", "--unit", "T-21")
    _write_pass_review(root, "T-21")
    _write_e2e_index(
        root, "| E2E-HOME-001 | home | 首页 | 功能 | AC-HOME-001 | T-21 | green | | cases/home.md |")
    acc = root / "product" / "e2e" / "reviews" / "2026-11-20-acceptance-home"
    acc.mkdir(parents=True)
    (acc / "README.md").write_text("# 验收走查\n", encoding="utf-8")

    p = run(root, "finish", "--unit", "T-21")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-21/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["e2e_precondition"]["status"] == "PASS"
    assert meta["e2e_precondition"]["acceptance"]["status"] == "PASS"


def test_finish_skips_e2e_when_task_acs_unmapped(tmp_path: Path) -> None:
    """任务卡无 AC：E2E 结论无法定位适用面 ⇒ 显式 SKIP，不静默当通过。"""
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-22", "--requirement", "普通任务")
    run(root, "dispatch", "--unit", "T-22")
    _write_pass_review(root, "T-22")
    _write_e2e_index(
        root, "| E2E-OTHER-001 | other | 其他 | 功能 | AC-OTHER-001 | T-99 | red | x | cases/other.md |")

    p = run(root, "finish", "--unit", "T-22")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-22/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["e2e_precondition"]["status"] == "SKIP"
    assert "无法定位" in meta["e2e_precondition"]["reason"]


def test_archive_migrates_completed_and_status_all(tmp_path: Path) -> None:
    """#70：既存 completed 单元可一次性迁入 archive；status 默认只看活跃，--all 才显示归档。"""
    root = make_clean_project(tmp_path)
    t_dir = root / ".atlas" / "tasks" / "T-30"
    t_dir.mkdir(parents=True)
    (t_dir / "task.json").write_text(json.dumps({
        "id": "T-30", "title": "旧完成项", "status": "completed", "depends_on": [], "acs": [],
    }), encoding="utf-8")

    assert "[T-30]" in run(root, "status").stdout  # 尚未归档，仍在活跃区
    p = run(root, "archive", "--unit", "T-30")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / ".atlas/tasks/archive" / _month() / "T-30/task.json").is_file()

    assert "[T-30]" not in run(root, "status").stdout
    p_all = run(root, "status", "--all")
    assert "[T-30]" in p_all.stdout and "[archived]" in p_all.stdout

    p_again = run(root, "archive", "--unit", "T-30")
    assert p_again.returncode == 0 and "无待归档项" in p_again.stdout


def test_archive_relocates_legacy_flat_layout(tmp_path: Path) -> None:
    """历史扁平存档（archive/<ID>/）应迁入当月，重新进入判据扫描面。"""
    root = make_clean_project(tmp_path)
    flat = root / ".atlas" / "tasks" / "archive" / "T-40"
    flat.mkdir(parents=True)
    (flat / "task.json").write_text(json.dumps({
        "id": "T-40", "title": "旧扁平存档", "status": "completed", "depends_on": [], "acs": [],
    }), encoding="utf-8")

    p = run(root, "archive", "--unit", "T-40")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / ".atlas/tasks/archive" / _month() / "T-40/task.json").is_file()
    assert not flat.exists()


def test_archive_refuses_non_completed(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-31", "--requirement", "普通任务")
    p = run(root, "archive", "--unit", "T-31")
    assert p.returncode == 1 and "尚未 completed" in p.stderr
    assert (root / ".atlas/tasks/T-31/task.json").is_file()


def test_status_filters_by_unit_and_reports_corrupt_card(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-13", "--requirement", "落实 AC-HOME-001")
    run(root, "plan", "--unit", "OTHER", "--requirement", "落实 AC-HOME-001")
    p = run(root, "status", "--unit", "T-13")
    assert p.returncode == 0
    assert "T-13" in p.stdout and "OTHER" not in p.stdout

    (root / ".atlas/tasks/OTHER/task.json").write_text("{bad", encoding="utf-8")
    p2 = run(root, "status")
    assert p2.returncode == 2
    assert "任务卡损坏" in p2.stderr and "Traceback" not in p2.stderr


def test_run_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "run", "--unit", "T-14", "--requirement", "落实 AC-HOME-001", "--dry-run")
    assert p.returncode == 0
    assert not (root / ".atlas/tasks/T-14").exists()


def test_plan_prunes_orphan_subcards(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req2 = "### 步骤一：A AC-HOME-001\n### 步骤二：B"
    run(root, "plan", "--unit", "T-15", "--requirement", req2)
    assert (root / ".atlas/tasks/T-15-02").is_dir()
    run(root, "plan", "--unit", "T-15", "--requirement", "落实 AC-HOME-001")
    assert not (root / ".atlas/tasks/T-15-02").exists()


def test_verify_refuses_empty_staged(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    run(root, "plan", "--unit", "T-16", "--requirement", "落实 AC-HOME-001")
    p = run(root, "verify", "--unit", "T-16")
    assert p.returncode == 2 and "暂存区为空" in p.stderr


def test_finish_scope_mismatch_blocks_stale_review(tmp_path: Path) -> None:
    sys.path.insert(0, str(PKG_ROOT))
    from _support import review_scope_core as scope_core
    from _support.workflow_finish import _scope_matches

    root = make_clean_project(tmp_path)
    assert subprocess.run(["git", "init", "-q"], cwd=root).returncode == 0
    (root / "app.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
    manifest = scope_core.build_manifest(root, ["app.txt"])
    data = {"review_scope": {"sha256": manifest["scope_sha256"]}}
    assert _scope_matches(root, data)[0]
    (root / "app.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
    ok, why = _scope_matches(root, data)
    assert not ok and "已变化" in why


def write_spec(root: Path, rel: str, globs: list[str], body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\npaths:\n" + "".join(f"  - '{g}'\n" for g in globs) + "---\n\n"
    p.write_text(fm + body, encoding="utf-8")


def test_context_is_read_only_and_scoped(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    write_spec(root, ".atlas/spec/structure/tour.md", ["**"], "# 导航")
    write_spec(root, ".atlas/spec/structure/domains/web.md", ["apps/web/**"], "# 前端规范")
    write_spec(root, ".atlas/spec/structure/domains/api.md", ["apps/api/**"], "# 后端规范")

    p = run(root, "context", "--paths", "apps/web/a.ts")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "web.md" in p.stdout and "前端规范" in p.stdout
    assert "api.md" not in p.stdout
    assert not (root / ".atlas" / "tasks").exists(), "context 不得建任务目录"
    assert not (root / ".atlas" / "tasks" / "T-01" / "dispatch.md").exists()


def test_context_explicit_scope_has_no_tour_fallback(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    write_spec(root, ".atlas/spec/structure/tour.md", ["**"], "# 导航")
    p = run(root, "context", "--paths", "apps/web/a.ts")
    assert p.returncode == 0
    assert "tour.md" not in p.stdout and "导航" not in p.stdout


def test_context_unit_matches_dispatch(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    write_spec(root, ".atlas/spec/structure/domains/web.md", ["apps/web/**"], "# 前端规范")
    write_spec(root, ".atlas/spec/structure/domains/api.md", ["apps/api/**"], "# 后端规范")
    run(root, "plan", "--unit", "T-02", "--requirement", "请落实 AC-HOME-001")
    run(root, "dispatch", "--unit", "T-02", "--paths", "apps/web/a.ts")

    p = run(root, "context", "--unit", "T-02")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "web.md" in p.stdout and "api.md" not in p.stdout


def test_context_requires_paths_or_unit(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "context")
    assert p.returncode == 2 and "至少提供" in p.stderr
