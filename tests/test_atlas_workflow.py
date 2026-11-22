#!/usr/bin/env python3
"""Atlas Workflow 自建执行层调度器的单元回归测试 (D204)。

覆盖：
1. Plan 阶段：大任务拆解、生成标准 Task Card (`prd.md` + `task.json`)；
2. Dispatch 阶段：状态流转为 in_progress，生成最小上下文派单包 (`dispatch.md`)；
3. Verify 阶段：参数透传与 staged 调用；
4. Finish 阶段：无合格 review.json 时强制阻断，有合规报告时顺利收口；
5. Status 阶段：任务清单与依赖状态呈现。
6. 需求条目与覆盖（#71/#72/#73）：plan 骨架生成、覆盖矩阵判据词表、条目 ⇄ 矩阵差集对账。
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
    assert not ok and "已变化" in why and "重新审查" in why


def test_finish_scope_extra_review_products_points_to_unstage(tmp_path: Path) -> None:
    """审查产物误入暂存面 ⇒ 指名路径 + unstage 指引（实审文件未变时重跑 verify 无效）。"""
    sys.path.insert(0, str(PKG_ROOT))
    from _support import review_scope_core as scope_core
    from _support.workflow_finish import _scope_matches

    root = make_clean_project(tmp_path)
    assert subprocess.run(["git", "init", "-q"], cwd=root).returncode == 0
    (root / "app.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
    manifest = scope_core.build_manifest(root, ["app.txt"])
    data = {"review_scope": {"sha256": manifest["scope_sha256"],
                             "files": manifest["files"]}}
    assert _scope_matches(root, data)[0]
    # 审查产物进入暂存面（实审文件 app.txt 未动）
    rev = root / "product" / "reviews" / "2026-11-21-impl-review-X"
    rev.mkdir(parents=True)
    (rev / "review.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "product/reviews/"], cwd=root, check=True)
    ok, why = _scope_matches(root, data)
    assert not ok
    assert "git restore --staged product/reviews/2026-11-21-impl-review-X/review.json" in why
    assert "重跑 verify 无效" in why


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


# ── 需求条目与覆盖（#71/#72/#73，2026-11-21）────────────────────────────────

from _support.workflow_verify import coverage_matrix_findings  # noqa: E402


def test_plan_with_requirement_writes_items_and_matrix(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "plan", "--unit", "T-01", "--requirement", "请落实 AC-HOME-001")
    assert p.returncode == 0, p.stdout + p.stderr
    task_dir = root / ".atlas" / "tasks" / "T-01"
    items_text = (task_dir / "requirement-items.md").read_text(encoding="utf-8")
    assert "| ID | 页码 | 章节 | 原文 |" in items_text
    assert "条目总数" in items_text
    matrix_text = (task_dir / "coverage-matrix.md").read_text(encoding="utf-8")
    assert "| ID | PRD | 设计文档 | 实现 | E2E |" in matrix_text


def test_plan_without_requirement_skips_skeletons(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "plan", "--unit", "T-03")
    assert p.returncode == 0, p.stdout + p.stderr
    task_dir = root / ".atlas" / "tasks" / "T-03"
    assert not (task_dir / "requirement-items.md").exists()
    assert not (task_dir / "coverage-matrix.md").exists()


def test_coverage_matrix_skips_cards_without_items(tmp_path: Path) -> None:
    assert coverage_matrix_findings(tmp_path) == []


def _write_items(task_dir: Path, ids: list[str], *, no_req_marker: bool = False) -> None:
    lines = ["# 需求条目表", "", "| ID | 页码 | 章节 | 原文 |", "|---|---|---|---|"]
    lines += [f"| {i} | p{i} | §1 | 原文 {i} |" for i in ids]
    if no_req_marker:
        lines += ["", "条目总数：0（本卡无外部需求原件）"]
    (task_dir / "requirement-items.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_matrix(task_dir: Path, rows: list[tuple[str, ...]],
                  header: str = "| ID | PRD | 设计文档 | 实现 | E2E |") -> None:
    lines = ["# 需求条目覆盖矩阵", "", header, "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    (task_dir / "coverage-matrix.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def test_matrix_missing_is_reported(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001"])
    findings = coverage_matrix_findings(tmp_path)
    assert len(findings) == 1 and "coverage-matrix.md 不存在" in findings[0]


def test_items_zero_rows_undeclared_is_reported(tmp_path: Path) -> None:
    _write_items(tmp_path, [])
    findings = coverage_matrix_findings(tmp_path)
    assert any("零数据行" in f for f in findings)


def test_items_zero_rows_declared_only_matrix_missing(tmp_path: Path) -> None:
    _write_items(tmp_path, [], no_req_marker=True)
    findings = coverage_matrix_findings(tmp_path)
    assert len(findings) == 1 and "coverage-matrix.md 不存在" in findings[0]


def test_matrix_blank_and_unresolved_cells_are_reported(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001", "R-002"])
    _write_matrix(tmp_path, [
        ("R-001", "覆盖（new-version-selector.tsx）", "", "不涉及（无 UI）", "覆盖（cases/app.md）"),
        ("R-002", "UNRESOLVED", "覆盖（prd.md）", "覆盖（impl.ts）", "覆盖（e2e.md）"),
    ])
    findings = coverage_matrix_findings(tmp_path)
    assert any("留空" in f and "R-001" in f for f in findings)
    assert any("UNRESOLVED" in f and "R-002" in f for f in findings)
    assert not any("漏覆盖" in f or "幽灵行" in f for f in findings)


def test_matrix_illegal_cell_value_is_reported(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001"])
    _write_matrix(tmp_path, [("R-001", "已做", "覆盖（b）", "覆盖（c）", "覆盖（d）")])
    findings = coverage_matrix_findings(tmp_path)
    assert any("值非法" in f and "已做" in f for f in findings)


def test_matrix_bad_header_is_reported(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001"])
    _write_matrix(tmp_path, [("R-001", "覆盖（a）", "覆盖（b）", "覆盖（c）", "覆盖（d）")],
                  header="| ID | PRD | 设计 | 实现 | E2E |")
    findings = coverage_matrix_findings(tmp_path)
    assert any("表头缺「设计文档」" in f for f in findings)


def test_matrix_clean_passes(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001"])
    _write_matrix(tmp_path, [("R-001", "覆盖（prd.md）", "覆盖（design.md）",
                              "覆盖（impl.ts）", "覆盖（e2e.md）")])
    assert coverage_matrix_findings(tmp_path) == []


def test_matrix_row_diff_reported_both_directions(tmp_path: Path) -> None:
    _write_items(tmp_path, ["R-001", "R-002"])
    _write_matrix(tmp_path, [
        ("R-001", "覆盖（a）", "覆盖（b）", "覆盖（c）", "覆盖（d）"),
        ("R-999", "覆盖（a）", "覆盖（b）", "覆盖（c）", "覆盖（d）"),
    ])
    findings = coverage_matrix_findings(tmp_path)
    assert any("漏覆盖" in f and "R-002" in f for f in findings)
    assert any("幽灵行" in f and "R-999" in f for f in findings)


# ── 需求落点模式（RFC-20261122-03，2026-11-22）────────────────────────────────

from _support.workflow_plan import (  # noqa: E402
    CLAIM_NONE_MARKER, REQUIREMENT_DOC_FILE, detect_requirement_root,
    requirement_pointer_text,
)
from _support.workflow_verify import (  # noqa: E402
    read_requirement_status, requirement_root_findings,
)


def make_requirement_root(root: Path, slug: str = "demo-req", *,
                          status: str | None = "已确认",
                          item_ids: tuple[str, ...] = ("R-01", "R-02")) -> Path:
    """需求落点夹具：<assets_root>/requirements/<slug>/（确认稿 + 条目表 + 转换稿）。"""
    req_dir = root / "product" / "requirements" / slug
    (req_dir / "work").mkdir(parents=True, exist_ok=True)
    doc = f"# 演示需求\n\n## Scope\n\n- 事项甲\n- 事项乙\n"
    if status is not None:
        doc = f"# 演示需求\n\n**状态**：{status}\n\n## Scope\n\n- 事项甲\n- 事项乙\n"
    (req_dir / REQUIREMENT_DOC_FILE).write_text(doc, encoding="utf-8")
    lines = ["# 落点条目表", "", "| ID | 页码 | 章节 | 原文 |", "|---|---|---|---|"]
    lines += [f"| {i} | p1 | §2 | 条目原文 {i} |" for i in item_ids]
    (req_dir / "items.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (req_dir / "work" / "需求PDF-全文.md").write_text(
        "<!-- page 1 -->\n条目原文 R-01\n", encoding="utf-8")
    return req_dir


def _write_claims(task_dir: Path, ids: list[str], *,
                  root_rel: str = "product/requirements/demo-req",
                  source_cell: str | None = None,
                  none_marker: bool = False) -> None:
    """领取引用表夹具：source_cell 非空时覆盖所有行的来源列（非法形态测试用）。"""
    lines = ["# 需求条目领取表", "", "| ID | 来源 |", "|---|---|"]
    for i in ids:
        cell = source_cell if source_cell is not None else f"{root_rel}#{i}"
        lines.append(f"| {i} | {cell} |")
    if none_marker:
        lines += ["", f"领取条目数：0（{CLAIM_NONE_MARKER}）"]
    (task_dir / "requirement-items.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def test_detect_requirement_root_modes(tmp_path: Path) -> None:
    req_dir = make_requirement_root(tmp_path)
    assert detect_requirement_root(req_dir) == req_dir
    assert detect_requirement_root(req_dir / REQUIREMENT_DOC_FILE) == req_dir
    plain = tmp_path / "plain.txt"
    plain.write_text("普通直填文本", encoding="utf-8")
    assert detect_requirement_root(plain) is None
    assert detect_requirement_root(tmp_path / "no-such-dir") is None


def test_plan_requirement_root_mode_points_not_copies(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req_dir = make_requirement_root(root)
    p = run(root, "plan", "--unit", "T-10", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "落点模式" in p.stdout

    task_dir = root / ".atlas" / "tasks" / "T-10"
    prd_text = (task_dir / "prd.md").read_text(encoding="utf-8")
    # 单源：卡 §1 是指针，不复制确认稿/条目正文
    assert "唯一住址" in prd_text
    assert "事项甲" not in prd_text and "条目原文" not in prd_text
    items_text = (task_dir / "requirement-items.md").read_text(encoding="utf-8")
    assert "| ID | 来源 |" in items_text
    assert "条目原文" not in items_text  # 领取表不复制正文
    meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert meta["requirement_root"] == "product/requirements/demo-req"
    matrix_text = (task_dir / "coverage-matrix.md").read_text(encoding="utf-8")
    assert "| ID | PRD | 设计文档 | 实现 | E2E |" in matrix_text


def test_plan_requirement_root_unconfirmed_warns_not_blocks(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="候选")
    p = run(root, "plan", "--unit", "T-11", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 0, p.stdout + p.stderr  # 软校验：WARN 不拦停
    assert "候选" in p.stderr and "确认门" in p.stderr

    root2 = make_clean_project(tmp_path / "s2")
    make_requirement_root(root2, status=None)
    p2 = run(root2, "plan", "--unit", "T-11", "--requirement",
             "product/requirements/demo-req")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "状态行" in p2.stderr

    root3 = make_clean_project(tmp_path / "s3")
    make_requirement_root(root3, status="已确认")
    p3 = run(root3, "plan", "--unit", "T-11", "--requirement",
             "product/requirements/demo-req")
    assert p3.returncode == 0 and "WARN（需求落点）" not in p3.stderr


def test_plan_requirement_root_skeleton_idempotent(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    run(root, "plan", "--unit", "T-12", "--requirement", "product/requirements/demo-req")
    task_dir = root / ".atlas" / "tasks" / "T-12"
    _write_claims(task_dir, ["R-01"])
    run(root, "plan", "--unit", "T-12", "--requirement", "product/requirements/demo-req")
    text = (task_dir / "requirement-items.md").read_text(encoding="utf-8")
    assert "| R-01 | product/requirements/demo-req#R-01 |" in text  # 重跑不覆盖已填


def test_claim_mode_per_card_findings(tmp_path: Path) -> None:
    # a) 来源列非法（正文复制进卡 = 单源击穿）
    _write_claims(tmp_path, ["R-01"], source_cell="条目原文 R-01 被复制进卡")
    findings = coverage_matrix_findings(tmp_path)
    assert any("「来源」列非法" in f for f in findings)
    # b) 引用 ID 与本行 ID 不一致
    _write_claims(tmp_path, ["R-01"], source_cell="product/requirements/demo-req#R-02")
    findings = coverage_matrix_findings(tmp_path)
    assert any("引用 ID 不一致" in f for f in findings)
    # c) 零领取且未声明豁免
    _write_claims(tmp_path, [])
    findings = coverage_matrix_findings(tmp_path)
    assert any("零领取行" in f for f in findings)
    # d) 零领取但显式豁免 ⇒ 只剩矩阵缺席
    _write_claims(tmp_path, [], none_marker=True)
    findings = coverage_matrix_findings(tmp_path)
    assert len(findings) == 1 and "coverage-matrix.md 不存在" in findings[0]
    # e) 干净：合法引用 + 矩阵覆盖
    _write_claims(tmp_path, ["R-01"])
    _write_matrix(tmp_path, [("R-01", "覆盖（prd.md）", "覆盖（design.md）",
                              "覆盖（impl.ts）", "覆盖（e2e.md）")])
    assert coverage_matrix_findings(tmp_path) == []


def _make_claim_card(root: Path, unit: str, req_root_rel: str,
                     claim_ids: list[str], *, status: str = "in_progress") -> None:
    """跨卡对账夹具：手工落一张带 requirement_root 的卡（不经 plan 全流程）。"""
    t_dir = root / ".atlas" / "tasks" / unit
    t_dir.mkdir(parents=True, exist_ok=True)
    meta = {"id": unit, "title": unit, "status": status, "depends_on": [],
            "affected_domains": [], "acs": [],
            "created_at": "2026-11-22", "requirement_root": req_root_rel}
    (t_dir / "task.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if claim_ids:
        _write_claims(t_dir, claim_ids, root_rel=req_root_rel)


def test_requirement_root_coverage_scenarios(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root)  # items: R-01, R-02
    rel = "product/requirements/demo-req"
    _make_claim_card(root, "T-A", rel, ["R-01"])
    findings = requirement_root_findings(root)
    assert any("漏领条目" in f and "R-02" in f for f in findings)

    root = make_clean_project(tmp_path / "ghost")
    make_requirement_root(root)
    _make_claim_card(root, "T-A", rel, ["R-01", "R-09"])
    findings = requirement_root_findings(root)
    assert any("幽灵引用" in f and "R-09" in f for f in findings)

    root = make_clean_project(tmp_path / "noclaim")
    make_requirement_root(root)
    _make_claim_card(root, "T-A", rel, [])
    findings = requirement_root_findings(root)
    assert any("无任何卡领取" in f for f in findings)

    root = make_clean_project(tmp_path / "unconfirmed")
    make_requirement_root(root, status="候选")
    _make_claim_card(root, "T-A", rel, ["R-01"])
    findings = requirement_root_findings(root)
    assert any("状态 = 候选" in f and "确认门" in f for f in findings)

    root = make_clean_project(tmp_path / "stuckclosed")
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", rel, ["R-01", "R-02"], status="completed")
    findings = requirement_root_findings(root)
    assert any("已全部收口" in f and "已收口" in f for f in findings)

    root = make_clean_project(tmp_path / "noitems")
    make_requirement_root(root)
    (root / "product" / "requirements" / "demo-req" / "items.md").unlink()
    _make_claim_card(root, "T-A", rel, ["R-01"])
    findings = requirement_root_findings(root)
    assert any("缺 items.md" in f for f in findings)

    root = make_clean_project(tmp_path / "clean")
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", rel, ["R-01", "R-02"])
    assert requirement_root_findings(root) == []


def test_requirement_root_escape_and_empty_root(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    _make_claim_card(root, "T-A", "../outside/req", ["R-01"])
    findings = requirement_root_findings(root)
    assert any("路径越界" in f for f in findings)
    assert requirement_root_findings(tmp_path / "no-tasks-dir") == []


def test_read_requirement_status(tmp_path: Path) -> None:
    req_dir = make_requirement_root(tmp_path, status="已确认")
    assert read_requirement_status(req_dir) == "已确认"
    make_requirement_root(tmp_path / "s2", status=None)
    assert read_requirement_status(tmp_path / "s2" / "demo-req") is None
    assert read_requirement_status(tmp_path / "nope") is None


def test_finish_requirement_root_writeback_reminder(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    run(root, "plan", "--unit", "T-13", "--requirement", "product/requirements/demo-req")
    run(root, "dispatch", "--unit", "T-13")
    r_dir = root / "product" / "reviews" / "2026-11-22-impl-review-T-13"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "PASS", "checks": [], "other": []
    }), encoding="utf-8")
    p = run(root, "finish", "--unit", "T-13")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "回写提醒" in p.stdout and "已收口" in p.stdout and "demo-req" in p.stdout


def test_requirement_pointer_text_mentions_authority_order() -> None:
    text = requirement_pointer_text("product/requirements/x")
    assert "唯一住址" in text
    assert "需求原文 > 需求 PRD > 任务 PRD" in text


# ── 机制文档机器面（RFC-20261122-04，提示语族 WARN）────────────────────────

from _support.workflow_verify import (  # noqa: E402
    MECHANISM_WARN_CAP, _mech_glob_regex, mechanism_doc_findings
)


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path,
                   check=True, capture_output=True)
    return tmp_path


def _mech_doc(root: Path, rel: str, globs: list[str]) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "mechanism-paths:\n" + "".join(f"  - '{g}'\n" for g in globs)
    p.write_text(f"---\n{fm}---\n\n# 机制篇\n正文\n", encoding="utf-8")


def test_mechanism_doc_touch_warn_lists_files(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/trace.md", ["backend/**"])
    (root / "backend" / "svc.py").parent.mkdir(parents=True)
    (root / "backend" / "svc.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root, ["backend/svc.py", "other.py"])
    assert len(findings) == 1, findings
    assert "docs/architecture/trace.md" in findings[0]
    assert "命中 1 文件" in findings[0] and "backend/svc.py" in findings[0]
    assert "查看该机制篇是否跟改" in findings[0]  # 提示语措辞锁（评审 s3）
    # 未触及 ⇒ 沉默（无机制文档缺席假阳性）
    assert mechanism_doc_findings(root, ["other.py"]) == []


def test_mechanism_doc_dead_paths_warn_and_alive_silent(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/old.md", ["gone/**"])
    _mech_doc(root, "docs/architecture/live.md", ["backend/**"])
    (root / "backend" / "a.py").parent.mkdir(parents=True)
    (root / "backend" / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root, [])
    dead = [f for f in findings if "疑似死 paths" in f]
    assert len(dead) == 1 and "docs/architecture/old.md" in dead[0]
    assert not any("live.md" in f and "疑似死" in f for f in findings)


def test_mechanism_doc_pending_skips_all(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/new.md", ["pending"])
    findings = mechanism_doc_findings(root, ["anything.py"])
    assert findings == []  # 冷启动豁免（评审 s1）：零命中判据不红、触及不判


def test_mechanism_doc_single_star_glob_named_not_matched(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/wide.md", ["src/*.py", "backend/**"])
    (root / "src" / "a.py").parent.mkdir(parents=True)
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    (root / "backend" / "b.py").parent.mkdir(parents=True)
    (root / "backend" / "b.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root, ["src/a.py"])
    assert any("单星 glob" in f and "'src/*.py'" in f for f in findings)
    assert not any("可能被本次改动触及" in f for f in findings)  # 非法 glob 不参与命中
    assert not any("疑似死 paths" in f for f in findings)  # backend/** 仍活


def test_mechanism_doc_cap_and_overflow_summary(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    changed = []
    for n in range(MECHANISM_WARN_CAP + 1):
        _mech_doc(root, f"docs/architecture/m{n}.md", [f"svc{n}/**"])
        (root / f"svc{n}" / "x.py").parent.mkdir(parents=True)
        (root / f"svc{n}" / "x.py").write_text("x\n", encoding="utf-8")
        changed.append(f"svc{n}/x.py")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root, changed)
    touches = [f for f in findings if "可能被本次改动触及" in f]
    summary = [f for f in findings if "另有" in f and "略）" in f]
    assert len(touches) == MECHANISM_WARN_CAP
    assert len(summary) == 1 and "1 篇" in summary[0]
    assert not any("疑似死 paths" in f for f in findings)


def test_mechanism_glob_engine_agrees_with_context() -> None:
    from _support.workflow_context import _glob_regex
    cases = [
        ("a/**", "a"), ("a/**", "a/b/c.py"), ("a/**", "ab.py"),
        ("backend/**", "backend/svc/deep/x.py"), ("docs/x.md", "docs/x.md"),
        ("docs/x.md", "docs/y.md"), ("**/*.md", "a/b.md"), ("dir/", "dir/f.py"),
    ]
    for glob, path in cases:
        mine = _mech_glob_regex(glob).fullmatch(path) is not None
        theirs = _glob_regex(glob).fullmatch(path) is not None
        assert mine == theirs, (glob, path, mine, theirs)
    assert _mech_glob_regex("a/**").fullmatch("a/b/c.py") is not None
    assert _mech_glob_regex("a/**").fullmatch("ab.py") is None


# ---------------------------------------------------------------------------
# finish 结构事实新鲜度前置（RFC-20261122-05）
# ---------------------------------------------------------------------------

def _commit_all(root: Path, msg: str = "c") -> str:
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", msg], cwd=str(root), check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout.strip()


def _write_meta(root: Path, commit: str) -> None:
    p = root / ".atlas" / "spec" / "structure" / "_meta.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"baseline": {"branch": "main", "commit": commit},
                             "domains": []}, ensure_ascii=False), encoding="utf-8")


def _plan_and_dispatch(root: Path, unit: str) -> None:
    run(root, "plan", "--unit", unit, "--requirement", "落实 AC-HOME-001")
    run(root, "dispatch", "--unit", unit)


def test_finish_structure_skip_without_meta(tmp_path: Path) -> None:
    """RFC-20261122-05：结构环未开户（无 _meta.json）⇒ SKIP，不拦收口。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-S1")
    p = run(root, "finish", "--unit", "T-S1", "--force")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-S1/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["structure_freshness"]["status"] == "SKIP"


def test_finish_structure_skip_non_git_with_meta(tmp_path: Path) -> None:
    """RFC-20261122-05：有 _meta.json 但非 git 仓 ⇒ SKIP（存量手工仓不追杀）。"""
    root = make_clean_project(tmp_path)
    _write_meta(root, "abc1234")
    _plan_and_dispatch(root, "T-S2")
    p = run(root, "finish", "--unit", "T-S2", "--force")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-S2/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["structure_freshness"]["status"] == "SKIP"


def test_finish_structure_blocks_bad_meta_json(tmp_path: Path) -> None:
    """RFC-20261122-05：_meta.json 坏 JSON ⇒ FAIL（响亮可修），不得静默放行。"""
    root = make_clean_project(_git_repo(tmp_path))
    _commit_all(root, "init")
    p_meta = root / ".atlas" / "spec" / "structure" / "_meta.json"
    p_meta.parent.mkdir(parents=True, exist_ok=True)
    p_meta.write_text("{oops", encoding="utf-8")
    _plan_and_dispatch(root, "T-S3")
    p = run(root, "finish", "--unit", "T-S3", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "无法解析" in p.stderr
    meta = json.loads((root / ".atlas/tasks/T-S3/task.json").read_text(encoding="utf-8"))
    assert meta["status"] != "completed"


def test_finish_structure_blocks_placeholder_baseline(tmp_path: Path) -> None:
    """RFC-20261122-05：baseline 占位（模板兜底 `[必填` 与 `—` 两种）⇒ FAIL。"""
    root = make_clean_project(_git_repo(tmp_path))
    _commit_all(root, "init")
    for unit, ph in (("T-S4", "[必填：commit]"), ("T-S5", "—")):
        _write_meta(root, ph)
        _plan_and_dispatch(root, unit)
        p = run(root, "finish", "--unit", unit, "--force")
        assert p.returncode == 1, (unit, p.stdout + p.stderr)
        assert "baseline 未登记" in p.stderr


def test_finish_structure_blocks_stale_baseline(tmp_path: Path) -> None:
    """M196：摘 finish_task 的结构新鲜度门调用 ⇒ 本钉变绿（FAIL 不再发生）。

    RFC-20261122-05 主钉：提交后未重刷结构事实（baseline 落后 HEAD）必须拒收，
    文案带 --chain 与 --advance-baseline 双通道；--force 不绕本门（评审 M4）。
    """
    root = make_clean_project(_git_repo(tmp_path))
    sha1 = _commit_all(root, "init")
    _write_meta(root, sha1)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    _commit_all(root, "feat")
    _plan_and_dispatch(root, "T-S6")
    p = run(root, "finish", "--unit", "T-S6", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "refresh_structure.py" in p.stderr and "--advance-baseline" in p.stderr
    meta = json.loads((root / ".atlas/tasks/T-S6/task.json").read_text(encoding="utf-8"))
    assert meta["status"] != "completed"


def test_finish_structure_blocks_unstaged_dirty(tmp_path: Path) -> None:
    """RFC-20261122-05：未跟踪 / 未暂存修改 ⇒ FAIL；文案不指引提交（评审 C1）。"""
    root = make_clean_project(_git_repo(tmp_path))
    sha1 = _commit_all(root, "init")
    _write_meta(root, sha1)
    _plan_and_dispatch(root, "T-S7")
    # 未跟踪（非豁免路径）
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    p = run(root, "finish", "--unit", "T-S7", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "未暂存/未跟踪" in p.stderr
    # 未暂存修改（已跟踪文件再改；先提交并重锚 baseline，隔离出脏路径单因素）
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "src"], cwd=str(root), check=True, capture_output=True)
    sha2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), check=True,
                          capture_output=True, text=True).stdout.strip()
    _write_meta(root, sha2)
    (root / "src" / "a.py").write_text("x2\n", encoding="utf-8")
    p = run(root, "finish", "--unit", "T-S7", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "未暂存/未跟踪" in p.stderr
    # 暂存面不入判据（评审 C1）：同文件 git add 后放行
    subprocess.run(["git", "add", "src/a.py"], cwd=str(root), check=True, capture_output=True)
    p = run(root, "finish", "--unit", "T-S7", "--force")
    assert p.returncode == 0, p.stdout + p.stderr


def test_finish_structure_blocks_broken_git(tmp_path: Path) -> None:
    """评审 M1：`.git` 在而 git 探测失败 ⇒ FAIL，不得混叠成「非 git」SKIP。"""
    root = make_clean_project(tmp_path)
    (root / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
    _write_meta(root, "abc1234")
    _plan_and_dispatch(root, "T-S8")
    p = run(root, "finish", "--unit", "T-S8", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "git 探测失败" in p.stderr


def test_finish_structure_passes_anchored_clean(tmp_path: Path) -> None:
    """RFC-20261122-05：baseline ≡ HEAD 且无非豁免未暂存/未跟踪改动 ⇒ PASS 留痕。"""
    root = make_clean_project(_git_repo(tmp_path))
    sha = _commit_all(root, "init")
    _write_meta(root, sha)
    _plan_and_dispatch(root, "T-S9")
    p = run(root, "finish", "--unit", "T-S9", "--force")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-S9/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["structure_freshness"]["status"] == "PASS"


def test_finish_c1_staged_impl_with_scope_seal_passes(tmp_path: Path) -> None:
    """RFC-20261122-05 评审 C1 e2e：暂存实现 + v4 scope 封口一致 ⇒ 两门共存放行。

    收口契约 = finish 时实现恰在暂存区（review 封口门对暂存面整体摘要）；
    结构门只判未暂存/未跟踪侧 + baseline ≡ HEAD，不得把暂存面算脏。
    """
    from _support import review_scope_core as scope_core
    root = make_clean_project(_git_repo(tmp_path))
    sha = _commit_all(root, "init")
    _write_meta(root, sha)
    (root / "src").mkdir()
    (root / "src" / "impl.py").write_text("impl v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/impl.py"], cwd=str(root), check=True, capture_output=True)
    manifest = scope_core.build_manifest(root, ["src/impl.py"])
    r_dir = root / "product" / "reviews" / "2026-11-22-impl-review-T-S10"
    r_dir.mkdir(parents=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "PASS",
        "review_scope": {"sha256": manifest["scope_sha256"], "files": manifest["files"]},
    }), encoding="utf-8")
    _plan_and_dispatch(root, "T-S10")
    p = run(root, "finish", "--unit", "T-S10")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas/tasks/archive" / _month() / "T-S10/task.json")
                      .read_text(encoding="utf-8"))
    assert meta["structure_freshness"]["status"] == "PASS"


def test_finish_structure_import_failure_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """评审 M2：判据单源导入失败 ⇒ FAIL（响亮指名重装配），不走 WARN 降级。"""
    from _support import workflow_finish
    root = make_clean_project(_git_repo(tmp_path))
    _write_meta(root, "abc1234")
    monkeypatch.setattr(workflow_finish, "_load_refresh_helpers", lambda: None)
    res = workflow_finish.check_structure_freshness(root)
    assert res["status"] == "FAIL" and "install.sh" in res["reason"]


def test_finish_adapterless_reanchor_channel_reachable(tmp_path: Path) -> None:
    """RFC-20261122-05 评审 C2 e2e：空转态仓（无适配器）经 --chain --advance-baseline
    显式人工背书重锚后，finish 可达 PASS（修复路径不可达 = 门锁死仓，方案错）。
    """
    root = make_clean_project(_git_repo(tmp_path))
    sha1 = _commit_all(root, "init")
    _write_meta(root, sha1)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    sha2 = _commit_all(root, "feat")
    _plan_and_dispatch(root, "T-S11")
    p = run(root, "finish", "--unit", "T-S11", "--force")
    assert p.returncode == 1, p.stdout + p.stderr
    r = subprocess.run(
        [sys.executable, str(PKG_ROOT / "scripts" / "refresh_structure.py"),
         "--root", str(root), "--chain", "--advance-baseline"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    meta_now = json.loads((root / ".atlas" / "spec" / "structure" / "_meta.json")
                          .read_text(encoding="utf-8"))
    assert meta_now["baseline"]["commit"] == sha2
    p = run(root, "finish", "--unit", "T-S11", "--force")
    assert p.returncode == 0, p.stdout + p.stderr
