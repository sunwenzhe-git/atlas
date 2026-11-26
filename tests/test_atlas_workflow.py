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

    # 未执行 review，尝试 finish 应被阻断。退出码语义（RFC-20261122-07）：
    # 报告缺失 = 流程顺序错（no_review_report，不扣）⇒ 2（前置不满足），非门红 1。
    p = run(root, "finish", "--unit", "T-04")
    assert p.returncode == 2
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
    # 退出码随 cause 分流更新（RFC-20261122-07：no_review_report ⇒ 2；v1 口径 rc==1 已废）
    assert p.returncode == 2, "T-1 不得复用 T-10 的 PASS 报告"
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
    # 顺序错归「前置不满足」（RFC-20261122-07 退出码语义修正：1→2）
    assert p.returncode == 2 and "尚未 completed" in p.stderr
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


def test_finish_preserves_governance_unverified_cause_and_rc2(tmp_path, monkeypatch):
    from _support import workflow_finish
    from _support.workflow_causes import exit_code_for
    from _support.workflow_plan import load_tasks

    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-GOV")
    task = load_tasks(root / ".atlas" / "tasks")[0]
    task["resolves_incidents"] = ["INC-20261125-001"]
    monkeypatch.setattr(workflow_finish, "validate_task_incidents", lambda *_args, **_kwargs: [{
        "module": "incident", "verdict": "UNVERIFIED", "rc": 2,
        "cause": None, "findings": [{"message": "evidence unavailable"}],
    }])
    with pytest.raises(workflow_finish.FinishError) as caught:
        workflow_finish.finish_task(root, task, force=True)
    assert caught.value.cause == "incident_unverified"
    assert exit_code_for(caught.value.cause) == 2


def test_verify_malformed_topology_returns_structured_rc2_and_records_attempt(tmp_path):
    root = _git_repo(tmp_path)
    make_clean_project(root)
    _commit_all(root, "base")
    _plan_and_dispatch(root, "T-TOP")
    (root / "compose.yaml").write_text("services:\n  api:\n    image: demo:1\n")
    subprocess.run(["git", "add", "compose.yaml"], cwd=root, check=True)
    topology = root / ".adapter-out/topology.json"
    topology.parent.mkdir(parents=True, exist_ok=True)
    topology.write_text("{broken")
    result = run(root, "verify", "--unit", "T-TOP", "--json")
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["cause"] == "topology_unverified"
    from _support.workflow_causes import load_attempts
    rows, bad = load_attempts(root / ".atlas/tasks", "T-TOP")
    assert bad == 0 and rows[-1]["cause"] == "topology_unverified" and rows[-1]["charged"] is False


def test_finish_receipt_enforce_keeps_origin_tree_and_immediate_verify_green(tmp_path):
    from _support import review_scope_core
    from _support.workflow_receipt import create_workflow_origin, verify_receipt

    root = _git_repo(tmp_path)
    make_clean_project(root)
    _commit_all(root, "base")
    _plan_and_dispatch(root, "T-RCPT")
    (root / "src").mkdir(exist_ok=True)
    (root / "src/a.ts").write_text("export const a = 1\n")
    subprocess.run(["git", "add", "src/a.ts"], cwd=root, check=True)
    review = root / "product/reviews/2026-11-25-impl-review-T-RCPT/review.json"
    review.parent.mkdir(parents=True)
    staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=root, text=True).splitlines()
    scope = review_scope_core.build_manifest(root, staged)
    review.write_text(json.dumps({"status": "PASS", "ok": True, "review_scope": {"sha256": scope["scope_sha256"]}}))
    create_workflow_origin(root, "T-RCPT", review.relative_to(root).as_posix())
    config = root / ".atlas/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('receipt_mode: "enforce"\n')
    result = run(root, "finish", "--unit", "T-RCPT")
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((root / ".atlas/runs/workflow-receipt.json").read_text())
    current = subprocess.check_output(["git", "write-tree"], cwd=root, text=True).strip()
    assert current != receipt["tree_hash"]
    assert subprocess.check_output(["git", "ls-files", "--", ".atlas/runs/workflow-review-origin.json"],
                                   cwd=root, text=True).strip() == ""
    checked = verify_receipt(root, mode="enforce", check_current_tree=True)
    assert checked["verdict"] == "PASS", checked


def test_finish_receipt_off_blocks_without_completing_or_archiving(tmp_path):
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-OFF")
    config = root / ".atlas/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('receipt_mode: "off"\n')
    review = root / "product/reviews/2026-11-25-impl-review-T-OFF/review.json"
    review.parent.mkdir(parents=True)
    review.write_text(json.dumps({"status": "PASS", "checks": []}))
    result = run(root, "finish", "--unit", "T-OFF", "--force", "--json")
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["paused_reason"] == "receipt_unverified"
    task = json.loads((root / ".atlas/tasks/T-OFF/task.json").read_text())
    assert task["status"] == "in_progress"
    assert not (root / ".atlas/runs/workflow-receipt.json").exists()


@pytest.mark.parametrize("module", ["incident", "docs"])
def test_verify_runs_governed_reference_checks_before_review(tmp_path, monkeypatch, module):
    from argparse import Namespace
    from scripts import atlas_workflow
    from _support import incident, docs_governance

    root = _git_repo(tmp_path)
    make_clean_project(root)
    _commit_all(root, "base")
    _plan_and_dispatch(root, "T-GVERIFY")
    (root / "src").mkdir(exist_ok=True)
    (root / "src/a.ts").write_text("export const a = 1\n")
    subprocess.run(["git", "add", "src/a.ts"], cwd=root, check=True)
    task_path = root / ".atlas/tasks/T-GVERIFY/task.json"
    task = json.loads(task_path.read_text())
    task["resolves_incidents" if module == "incident" else "doc_ids"] = [
        "INC-20261125-001" if module == "incident" else "DOC-guide"]
    task_path.write_text(json.dumps(task))
    blocked = {"module": module, "verdict": "UNVERIFIED", "rc": 2,
               "cause": None, "findings": [{"message": "governed evidence unavailable"}]}
    monkeypatch.setattr(incident, "validate_task_incidents", lambda *_a, **_k: [blocked])
    monkeypatch.setattr(docs_governance, "check_docs_for_ids", lambda *_a, **_k: blocked)
    original_run = atlas_workflow.subprocess.run

    def review_forbidden(command, *args, **kwargs):
        if isinstance(command, list) and any(str(item).endswith("atlas_review.py") for item in command):
            pytest.fail("review started before governance check")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(atlas_workflow.subprocess, "run", review_forbidden)
    rc = atlas_workflow.cmd_verify(Namespace(unit="T-GVERIFY", dry_run=False, json=True,
                                             round=None, check_cmd=None, resolves=None), root)
    assert rc == 2
    assert not list((root / "product/reviews").rglob("review-request.md"))


def test_finish_receipt_enforce_rejects_direct_review_without_workflow_origin(tmp_path):
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-DIRECT")
    config = root / ".atlas/config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('receipt_mode: "enforce"\n')
    review = root / "product/reviews/2026-11-25-impl-review-T-DIRECT/review.json"
    review.parent.mkdir(parents=True)
    review.write_text(json.dumps({"status": "PASS", "ok": True, "checks": []}))
    result = run(root, "finish", "--unit", "T-DIRECT")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "workflow verify" in result.stderr


def test_finish_blocks_missing_or_abstain_task_classification_without_receipt(tmp_path):
    from _support import workflow_finish
    from _support.workflow_causes import exit_code_for
    from _support.workflow_plan import load_tasks

    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-CLASS")
    task = load_tasks(root / ".atlas" / "tasks")[0]
    task["classification_required"] = True
    with pytest.raises(workflow_finish.FinishError) as caught:
        workflow_finish.finish_task(root, task, force=True)
    assert caught.value.cause == "calibration_unverified"
    assert exit_code_for(caught.value.cause) == 2
    result_path = root / ".atlas/runs/workflow-classification.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({"decision": "abstain", "verdict": "UNVERIFIED", "rc": 2}))
    with pytest.raises(workflow_finish.FinishError) as caught:
        workflow_finish.finish_task(root, task, force=True)
    assert caught.value.cause == "calibration_unverified"


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
                          item_ids: tuple[str, ...] = ("R-01", "R-02"),
                          kind: str | None = None,
                          related: str | None = None) -> Path:
    """需求落点夹具：<assets_root>/requirements/<slug>/（确认稿 + 条目表 + 转换稿）。"""
    req_dir = root / "product" / "requirements" / slug
    (req_dir / "work").mkdir(parents=True, exist_ok=True)
    lines = ["# 演示需求", ""]
    if kind is not None:
        lines.append(f"**类型**：{kind}")
    if related is not None:
        lines.append(f"**关联需求**：{related}")
    if status is not None:
        lines.append(f"**状态**：{status}")
    lines += ["", "## Scope", "", "- 事项甲", "- 事项乙", ""]
    (req_dir / REQUIREMENT_DOC_FILE).write_text("\n".join(lines), encoding="utf-8")
    table = ["# 落点条目表", "", "| ID | 页码 | 章节 | 原文 |", "|---|---|---|---|"]
    table += [f"| {i} | p1 | §2 | 条目原文 {i} |" for i in item_ids]
    (req_dir / "items.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    source_name = {"缺陷": "缺陷报告.md", "需求变更": "变更请求.md"}.get(
        kind, "需求PDF-全文.md")
    source_text = "<!-- page 1 -->\n条目原文 R-01\n"
    if kind == "需求变更":
        source_text += "\n**变更原因**：验收范围调整。\n**阶段**：prod\n"
    (req_dir / "work" / source_name).write_text(source_text, encoding="utf-8")
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
    source = root / ".atlas" / "tasks" / "T-A"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    findings = requirement_root_findings(root)
    assert any("已全部归档且 completed" in f and "已收口" in f for f in findings)

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


def test_plan_warns_on_invalid_requirement_type(tmp_path: Path) -> None:
    """M209：摘除类型/关联检查调用后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind="未知类型")
    p = run(root, "plan", "--unit", "T-14", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "类型" in p.stderr and "非法" in p.stderr


@pytest.mark.parametrize("kind", ["需求变更", "缺陷"])
def test_plan_warns_when_change_or_bug_has_no_related_requirement(
        tmp_path: Path, kind: str) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind=kind)
    p = run(root, "plan", "--unit", "T-15", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and "必填" in p.stderr


def test_plan_warns_on_missing_related_target_and_item(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path / "missing")
    make_clean_project(root)
    make_requirement_root(root, slug="change", kind="需求变更", related="absent#R-01")
    p = run(root, "plan", "--unit", "T-16", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and "absent" in p.stderr

    root2 = make_clean_project(tmp_path / "item")
    make_requirement_root(root2)
    make_requirement_root(root2, slug="change", kind="需求变更",
                          related="demo-req#R-99")
    p2 = run(root2, "plan", "--unit", "T-16", "--requirement",
             "product/requirements/change")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "R-99" in p2.stderr


def test_plan_resolves_archived_related_requirement(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    base = make_requirement_root(root)
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    base.rename(archive / base.name)
    make_requirement_root(root, slug="change", kind="需求变更",
                          related="demo-req#R-01")
    p = run(root, "plan", "--unit", "T-17", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" not in p.stderr


def test_plan_warns_on_related_requirement_cycle(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, slug="a", kind="需求变更", related="b#R-01")
    make_requirement_root(root, slug="b", kind="需求变更", related="a#R-01")
    p = run(root, "plan", "--unit", "T-18", "--requirement",
            "product/requirements/a")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and "循环" in p.stderr


def test_plan_warns_on_self_relation_and_ambiguous_archive(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path / "self")
    make_requirement_root(root, slug="a", kind="需求变更", related="a#R-01")
    p = run(root, "plan", "--unit", "T-18A", "--requirement",
            "product/requirements/a")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "自引" in p.stderr

    root2 = make_clean_project(tmp_path / "ambiguous")
    for month in ("2026-10", "2026-11"):
        target = root2 / "product" / "requirements" / "archive" / month / "base"
        target.mkdir(parents=True)
        (target / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
        (target / "items.md").write_text(
            "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
            encoding="utf-8")
    make_requirement_root(root2, slug="change", kind="需求变更", related="base#R-01")
    p2 = run(root2, "plan", "--unit", "T-18B", "--requirement",
             "product/requirements/change")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "唯一落点" in p2.stderr


def test_requirement_root_rejects_cross_root_claim(tmp_path: Path) -> None:
    """M207：摘除领取来源路径校验后，跨落点冒领必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, slug="a")
    make_requirement_root(root, slug="b")
    _make_claim_card(root, "T-A", "product/requirements/a", ["R-01"])
    claims = root / ".atlas" / "tasks" / "T-A" / "requirement-items.md"
    claims.write_text(
        "# 领取表\n\n| ID | 来源 |\n|---|---|\n"
        "| R-01 | product/requirements/b#R-01 |\n", encoding="utf-8")
    findings = requirement_root_findings(root)
    assert any("来源路径" in f and "冒领" in f for f in findings)


def test_requirement_root_resolves_archived_task_target(tmp_path: Path) -> None:
    """M208：摘除归档 slug 回落解析后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    req_dir = make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01", "R-02"])
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    req_dir.rename(archive / req_dir.name)
    findings = requirement_root_findings(root)
    assert findings == []


def test_requirement_root_resolves_custom_assets_root_archive(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    req_dir = make_requirement_root(root, status="已拆")
    docs = root / "docs"
    docs.mkdir()
    (root / "product" / "requirements").rename(docs / "requirements")
    moved = docs / "requirements" / "demo-req"
    archive = docs / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    moved.rename(archive / moved.name)
    (root / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    _make_claim_card(root, "T-A", "docs/requirements/demo-req", ["R-01", "R-02"])
    findings = requirement_root_findings(root)
    assert findings == []


def test_replan_without_requirement_preserves_pointer(tmp_path: Path) -> None:
    """M211：摘除重跑指针保持后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    run(root, "plan", "--unit", "T-19", "--requirement",
        "product/requirements/demo-req")
    p = run(root, "plan", "--unit", "T-19", "--requirement", "重新拆解")
    assert p.returncode == 0, p.stdout + p.stderr
    prd = (root / ".atlas" / "tasks" / "T-19" / "prd.md").read_text(encoding="utf-8")
    assert "需求正文唯一住址" in prd
    assert "product/requirements/demo-req" in prd


@pytest.mark.parametrize(
    ("kind", "expected_writeback"),
    [("初始需求", "required"), ("需求变更", "required")],
)
def test_requirement_closeout_returns_type_aware_result(
        tmp_path: Path, kind: str, expected_writeback: str) -> None:
    """M210：摘除 finish 类型收口待办后，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    related = "demo-req#R-01" if kind != "初始需求" else None
    if related:
        make_requirement_root(root)
    make_requirement_root(root, slug="typed", kind=kind, related=related)
    _make_claim_card(root, "T-20", "product/requirements/typed", ["R-01"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-20"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-20"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    closeout = requirement_closeout(root, "product/requirements/typed")
    assert closeout["type"] == kind
    assert closeout["product_fact_writeback"] == expected_writeback
    assert closeout["requirement_status_target"] == "已收口"


def test_requirement_closeout_defect_is_conditional(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    make_requirement_root(root, slug="typed", kind="缺陷", related="demo-req#R-01")
    _make_claim_card(root, "T-20", "product/requirements/typed", ["R-01"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-20"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-20"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    closeout = requirement_closeout(root, "product/requirements/typed")
    assert closeout["type"] == "缺陷"
    assert closeout["product_fact_writeback"] == "conditional"
    assert closeout["requirement_status_target"] == "已收口"


@pytest.mark.parametrize(
    ("other_status", "other_archived"),
    [("todo", False), ("completed", False), ("todo", True)],
)
def test_finish_waits_for_all_requirement_cards(
        tmp_path: Path, other_status: str, other_archived: bool) -> None:
    """M212：把归档条件退回 completed 或 archived 任一成立，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01"])
    _make_claim_card(root, "T-B", "product/requirements/demo-req", ["R-02"],
                     status=other_status)
    if other_archived:
        source = root / ".atlas" / "tasks" / "T-B"
        dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-B"
        dest.parent.mkdir(parents=True)
        source.rename(dest)
    run(root, "dispatch", "--unit", "T-A")
    r_dir = root / "product" / "reviews" / "2026-11-22-impl-review-T-A"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "PASS", "checks": [], "other": []
    }), encoding="utf-8")
    p = run(root, "finish", "--unit", "T-A", "--json")
    assert p.returncode == 0, p.stdout + p.stderr
    closeout = json.loads(p.stdout)["requirement_closeout"]
    assert closeout["all_cards_closed"] is False
    assert closeout["product_fact_writeback"] == "pending"
    assert closeout["requirement_status_target"] is None


@pytest.mark.parametrize(
    ("status", "archived", "expect_closed"),
    [("completed", False, False), ("todo", True, False), ("completed", True, True)],
)
def test_requirement_root_closeout_requires_archived_completed_card(
        tmp_path: Path, status: str, archived: bool, expect_closed: bool) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01", "R-02"],
                     status=status)
    if archived:
        source = root / ".atlas" / "tasks" / "T-A"
        dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
        dest.parent.mkdir(parents=True)
        source.rename(dest)
    findings = requirement_root_findings(root)
    assert any("已全部归档且 completed" in f for f in findings) is expect_closed


def test_finish_invalid_type_does_not_issue_closeout(tmp_path: Path) -> None:
    """M216：非法类型不再阻断收口待办时，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind="未知类型")
    closeout = requirement_closeout(root, "product/requirements/demo-req")
    assert closeout["type"] == "未知"
    assert closeout["product_fact_writeback"] == "pending"
    assert closeout["requirement_status_target"] is None


def test_finish_ambiguous_archive_does_not_issue_closeout(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    for month in ("2026-10", "2026-11"):
        target = root / "product" / "requirements" / "archive" / month / "base"
        target.mkdir(parents=True)
        (target / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
        (target / "items.md").write_text(
            "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
            encoding="utf-8")
    closeout = requirement_closeout(root, "product/requirements/base")
    assert closeout["type"] == "未知"
    assert closeout["product_fact_writeback"] == "pending"
    assert closeout["requirement_status_target"] is None


def test_requirement_root_rejects_non_requirements_directory(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    rogue = root / "product" / "prd"
    (rogue / "requirement.md").write_text("**状态**：已拆\n", encoding="utf-8")
    (rogue / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
        encoding="utf-8")
    _make_claim_card(root, "T-A", "product/prd", ["R-01"])
    findings = requirement_root_findings(root)
    assert any("需求落点" in f and "非法" in f for f in findings)


def test_requirement_relation_rejects_symlink_escape(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    (outside / "work").mkdir(parents=True)
    (outside / "requirement.md").write_text("**状态**：已确认\n", encoding="utf-8")
    (outside / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
        encoding="utf-8")
    link = root / "product" / "requirements" / "base"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-21", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and ("根内" in p.stderr or "非法" in p.stderr)


def test_requirement_relation_ignores_fenced_item(tmp_path: Path) -> None:
    """M214：嵌套围栏关闭条件放宽后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    base = make_requirement_root(root, item_ids=())
    (base / "items.md").write_text(
        "# items\n\n````md\n```md\n| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | p1 | §1 | fake |\n```\n````\n", encoding="utf-8")
    make_requirement_root(root, slug="change", kind="需求变更",
                          related="demo-req#R-01")
    p = run(root, "plan", "--unit", "T-22", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "R-01" in p.stderr and "不存在" in p.stderr


def test_requirement_relation_rejects_candidate_baseline(tmp_path: Path) -> None:
    """M215：候选基线不再被拒绝时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="候选")
    make_requirement_root(root, slug="change", kind="需求变更",
                          related="demo-req#R-01")
    p = run(root, "plan", "--unit", "T-23", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "候选" in p.stderr and "基线" in p.stderr


def test_requirement_relation_rejects_slug_reuse_and_bad_archive_month(
        tmp_path: Path) -> None:
    """M213：活跃/归档同名 slug 不再视为复用时，本用例必须红。"""
    root = make_clean_project(tmp_path / "reuse")
    archived = root / "product" / "requirements" / "archive" / "2026-10" / "base"
    archived.mkdir(parents=True)
    (archived / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
    (archived / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | old |\n",
        encoding="utf-8")
    make_requirement_root(root, slug="base")
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-24", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "复用" in p.stderr or "唯一落点" in p.stderr

    root2 = make_clean_project(tmp_path / "month")
    bad = root2 / "product" / "requirements" / "archive" / "not-a-month" / "base"
    bad.mkdir(parents=True)
    (bad / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
    (bad / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | old |\n",
        encoding="utf-8")
    make_requirement_root(root2, slug="change", kind="需求变更", related="base#R-01")
    p2 = run(root2, "plan", "--unit", "T-24", "--requirement",
             "product/requirements/change")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert "唯一落点" in p2.stderr

    root3 = make_clean_project(tmp_path / "invalid-collision")
    (root3 / "product" / "requirements" / "archive" / "not-a-month" / "base").mkdir(
        parents=True)
    make_requirement_root(root3, slug="base")
    make_requirement_root(root3, slug="change", kind="需求变更", related="base#R-01")
    p3 = run(root3, "plan", "--unit", "T-24C", "--requirement",
             "product/requirements/change")
    assert p3.returncode == 0, p3.stdout + p3.stderr
    assert "唯一落点" in p3.stderr


def test_requirement_relation_rejects_incomplete_archive_collision(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    (root / "product" / "requirements" / "archive" / "2026-10" / "base").mkdir(parents=True)
    make_requirement_root(root, slug="base")
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-27", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "唯一落点" in p.stderr


def test_requirement_root_rejects_stale_default_root_when_assets_root_changed(
        tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    (root / "docs").mkdir()
    (root / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01", "R-02"])
    findings = requirement_root_findings(root)
    assert any("需求落点" in f and "非法" in f for f in findings)


def test_requirement_root_normalizes_logical_paths(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01"])
    _make_claim_card(root, "T-B", "product/requirements/./demo-req", ["R-02"])
    assert requirement_root_findings(root) == []


def test_requirement_metadata_ignores_fenced_example(tmp_path: Path) -> None:
    from _support.workflow_plan import requirement_type

    root = make_clean_project(tmp_path)
    req = make_requirement_root(root)
    (req / "requirement.md").write_text(
        "# demo\n\n````md\n**类型**：未知\n**状态**：候选\n```\n````\n\n"
        "**状态**：已确认\n", encoding="utf-8")
    assert requirement_type(req) == "初始需求"
    assert read_requirement_status(req) == "已确认"


def test_requirement_relation_rejects_symlinked_authority_files(tmp_path: Path) -> None:
    """M221：权威文件 symlink 边界摘除后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-files"
    outside.mkdir()
    (outside / "requirement.md").write_text("**状态**：已确认\n", encoding="utf-8")
    (outside / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
        encoding="utf-8")
    base = root / "product" / "requirements" / "base"
    base.mkdir(parents=True)
    (base / "requirement.md").symlink_to(outside / "requirement.md")
    (base / "items.md").symlink_to(outside / "items.md")
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-25", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and "唯一落点" in p.stderr


def test_requirement_relation_rejects_symlinked_archive_month(tmp_path: Path) -> None:
    """M220：归档月份 symlink 守卫摘除后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    real = root / "product" / "requirements" / "archive" / "foo" / "base"
    real.mkdir(parents=True)
    (real / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
    (real / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
        encoding="utf-8")
    (real.parent.parent / "2026-11").symlink_to(real.parent, target_is_directory=True)
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-26", "--requirement",
            "product/requirements/change")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "关联需求" in p.stderr and "唯一落点" in p.stderr


@pytest.mark.parametrize("archive_path", ["archive/not-a-month/T-B", "archive/T-B"])
def test_finish_closeout_rejects_invalid_task_archive(
        tmp_path: Path, archive_path: str) -> None:
    """M217：任务归档不再校验月份形态时，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    _make_claim_card(root, "T-B", "product/requirements/demo-req", ["R-01", "R-02"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-B"
    dest = root / ".atlas" / "tasks" / archive_path
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    closeout = requirement_closeout(root, "product/requirements/demo-req")
    assert closeout["all_cards_closed"] is False
    assert closeout["requirement_status_target"] is None


def test_archived_and_logical_refs_share_one_requirement_identity(tmp_path: Path) -> None:
    """M218：归档实体不再归一为逻辑 slug 时，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    req = make_requirement_root(root, status="已拆")
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    req.rename(archive / req.name)
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01"],
                     status="completed")
    _make_claim_card(root, "T-B", "product/requirements/archive/2026-11/demo-req",
                     ["R-02"], status="todo")
    assert requirement_root_findings(root) == []
    closeout = requirement_closeout(root, "product/requirements/demo-req")
    assert closeout["all_cards_closed"] is False


def test_finish_closeout_handles_io_error(tmp_path: Path, monkeypatch) -> None:
    """M219：finish 不再捕获 OSError 时，本用例必须红。"""
    from _support import workflow_finish

    root = make_clean_project(tmp_path)
    make_requirement_root(root)

    def fail(_req_root):
        raise OSError("read failed")

    monkeypatch.setattr(workflow_finish, "requirement_type", fail)
    closeout = workflow_finish.requirement_closeout(root, "product/requirements/demo-req")
    assert closeout["type"] == "未知"
    assert closeout["product_fact_writeback"] == "pending"
    assert closeout["requirement_status_target"] is None
    assert closeout["findings"]


def test_requirement_closeout_reports_relation_findings(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind="需求变更")
    closeout = requirement_closeout(root, "product/requirements/demo-req")
    assert any("关联需求" in finding for finding in closeout["findings"])
    assert closeout["product_fact_writeback"] == "pending"


def test_finish_closeout_handles_requirement_read_error(
        tmp_path: Path, monkeypatch) -> None:
    """M219：真实需求文件读取错误未被转成 pending 时，本用例必须红。"""
    from _support import workflow_finish

    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path.name == "requirement.md":
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    closeout = workflow_finish.requirement_closeout(root, "product/requirements/demo-req")
    assert closeout["type"] == "未知"
    assert closeout["product_fact_writeback"] == "pending"
    assert closeout["requirement_status_target"] is None
    assert closeout["findings"]


def test_archive_month_requires_directory_name_match(tmp_path: Path) -> None:
    """M222：归档目录名不等于任务 ID 仍被认作已归档时，本用例必须红。"""
    from _support.workflow_finish import archive_month

    tasks = tmp_path / ".atlas" / "tasks"
    wrong = tasks / "archive" / "2026-11" / "WRONG"
    wrong.mkdir(parents=True)
    assert archive_month(wrong, tasks, "T-A") is None


def test_load_tasks_rejects_duplicate_ids(tmp_path: Path) -> None:
    """M223：重复任务 ID 不再拒绝时，本用例必须红。"""
    from _support.workflow_plan import PlanError, load_tasks

    root = make_clean_project(tmp_path)
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-A"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01"])
    with pytest.raises(PlanError, match="重复"):
        load_tasks(root / ".atlas" / "tasks", include_archived=True)


def test_requirement_pointer_uses_generic_source_for_bug(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind="缺陷", related="base#R-01")
    make_requirement_root(root, slug="base")
    run(root, "plan", "--unit", "T-29", "--requirement",
        "product/requirements/demo-req")
    prd = (root / ".atlas" / "tasks" / "T-29" / "prd.md").read_text(encoding="utf-8")
    assert "work/ 来源材料" in prd
    assert "work/需求PDF-全文.md" not in prd


def test_requirement_root_bug_closeout_does_not_require_fact_writeback(
        tmp_path: Path) -> None:
    """M224：缺陷关闭提示不再区分类型时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, slug="bug", kind="缺陷", related="base#R-01",
                          status="已拆")
    make_requirement_root(root, slug="base")
    _make_claim_card(root, "T-A", "product/requirements/bug", ["R-01", "R-02"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-A"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    findings = requirement_root_findings(root)
    assert any("仅当产品事实缺失或错误时回写" in f for f in findings)
    assert not any("按域沉淀回产品事实" in f for f in findings)


def test_plan_accepts_logical_slug_for_archived_requirement(tmp_path: Path) -> None:
    """M225：逻辑 slug 不再回落唯一归档实体时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    req = make_requirement_root(root)
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    req.rename(archive / req.name)
    p = run(root, "plan", "--unit", "T-30", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas" / "tasks" / "T-30" / "task.json").read_text())
    assert meta["requirement_root"] == "product/requirements/demo-req"
    assert (root / ".atlas" / "tasks" / "T-30" / "requirement-items.md").is_file()


def test_plan_rejects_rebuilding_archived_task_id(tmp_path: Path) -> None:
    """M226：已归档任务 ID 重建 guard 摘除后，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    run(root, "plan", "--unit", "T-31", "--requirement",
        "product/requirements/demo-req")
    source = root / ".atlas" / "tasks" / "T-31"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-31"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    p = run(root, "plan", "--unit", "T-31", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 2
    assert "归档命名空间" in p.stderr
    assert not (root / ".atlas" / "tasks" / "T-31").exists()


def test_requirement_root_rejects_duplicate_ids_across_archive_months(
        tmp_path: Path) -> None:
    """M227：verify 不再拒绝重复任务 ID 时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    for month in ("2026-10", "2026-11"):
        task = root / ".atlas" / "tasks" / "archive" / month / "T-A"
        task.mkdir(parents=True)
        (task / "task.json").write_text(json.dumps({
            "id": "T-A", "title": "T-A", "status": "completed", "depends_on": [],
            "affected_domains": [], "acs": [], "created_at": "2026-11-01",
            "requirement_root": "product/requirements/demo-req",
        }), encoding="utf-8")
        _write_claims(task, ["R-01", "R-02"])
    findings = requirement_root_findings(root)
    assert any("任务 ID 重复" in f for f in findings)
    assert not any("已全部归档且 completed" in f for f in findings)


def test_requirement_root_invalid_type_does_not_close(tmp_path: Path) -> None:
    """M228：verify 非法类型不再阻断收口时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, kind="未知类型", status="已拆")
    _make_claim_card(root, "T-A", "product/requirements/demo-req", ["R-01", "R-02"],
                     status="completed")
    source = root / ".atlas" / "tasks" / "T-A"
    dest = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    dest.parent.mkdir(parents=True)
    source.rename(dest)
    findings = requirement_root_findings(root)
    assert any("类型非法" in f for f in findings)
    assert not any("推进为「已收口」" in f for f in findings)


def test_normalize_requirement_ref_accepts_null(tmp_path: Path) -> None:
    from _support.workflow_plan import normalize_requirement_ref

    assert normalize_requirement_ref(tmp_path, None) == ""


def test_finish_task_load_error_does_not_report_all_done(
        tmp_path: Path, monkeypatch) -> None:
    """M229：账本失败兜底不再禁止 all_done 时，本用例必须红。"""
    from _support import workflow_finish
    from _support.workflow_plan import load_tasks

    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    run(root, "plan", "--unit", "T-32", "--requirement",
        "product/requirements/demo-req")
    run(root, "dispatch", "--unit", "T-32")
    task = load_tasks(root / ".atlas" / "tasks")[0]
    r_dir = root / "product" / "reviews" / "2026-11-22-impl-review-T-32"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "PASS", "checks": [], "other": []
    }), encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise OSError("ledger unreadable")

    monkeypatch.setattr(workflow_finish, "load_tasks", fail)
    result = workflow_finish.finish_task(root, task)
    assert result["all_done"] is False
    assert result["task_load_error"]
    assert result["requirement_closeout"]["product_fact_writeback"] == "pending"


def test_plan_rejects_unresolved_requirement_path(tmp_path: Path) -> None:
    """M230：路径型需求引用解析失败不再退成直填时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    for month in ("2026-10", "2026-11"):
        target = root / "product" / "requirements" / "archive" / month / "base"
        target.mkdir(parents=True)
        (target / "requirement.md").write_text("**状态**：已收口\n", encoding="utf-8")
        (target / "items.md").write_text(
            "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
            encoding="utf-8")
    p = run(root, "plan", "--unit", "T-33", "--requirement",
            "product/requirements/base")
    assert p.returncode == 2
    assert "无法解析" in p.stderr
    assert not (root / ".atlas" / "tasks" / "T-33").exists()


def test_requirement_root_duplicate_without_root_invalidates_closeout(
        tmp_path: Path) -> None:
    """M231：无落点同 ID 卡不再参与全局重复校验时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    task = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "id": "T-A", "title": "T-A", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "created_at": "2026-11-01",
        "requirement_root": "product/requirements/demo-req",
    }), encoding="utf-8")
    _write_claims(task, ["R-01", "R-02"])
    _make_claim_card(root, "T-A", "product/requirements/other", ["R-01"])
    findings = requirement_root_findings(root)
    assert any("任务 ID 重复" in f for f in findings)
    assert not any("已全部归档且 completed" in f for f in findings)


def test_requirement_root_bad_ledger_invalidates_closeout(tmp_path: Path) -> None:
    """M232：损坏任务账本不再阻断收口提示时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    task = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "id": "T-A", "title": "T-A", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "created_at": "2026-11-01",
        "requirement_root": "product/requirements/demo-req",
    }), encoding="utf-8")
    _write_claims(task, ["R-01", "R-02"])
    broken = root / ".atlas" / "tasks" / "broken"
    broken.mkdir()
    (broken / "task.json").write_text("{", encoding="utf-8")
    findings = requirement_root_findings(root)
    assert any("任务账本不可读" in f for f in findings)
    assert not any("已全部归档且 completed" in f for f in findings)


def test_plan_reserves_ids_in_invalid_archive_paths(tmp_path: Path) -> None:
    """M233：非法归档形态中的 ID 不再保留时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    task = root / ".atlas" / "tasks" / "archive" / "not-a-month" / "T-34"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "id": "T-34", "title": "T-34", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "created_at": "2026-11-01",
    }), encoding="utf-8")
    p = run(root, "plan", "--unit", "T-34", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 2
    assert "归档命名空间" in p.stderr
    assert not (root / ".atlas" / "tasks" / "T-34").exists()


def test_requirement_archive_root_symlink_is_rejected(tmp_path: Path) -> None:
    """M234：归档根 symlink 逃逸不再拒绝时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-archive"
    (outside / "2026-11" / "base").mkdir(parents=True)
    (outside / "2026-11" / "base" / "requirement.md").write_text(
        "**状态**：已收口\n", encoding="utf-8")
    (outside / "2026-11" / "base" / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n| R-01 | p1 | §1 | x |\n",
        encoding="utf-8")
    archive_link = root / "product" / "requirements" / "archive"
    archive_link.parent.mkdir(parents=True)
    archive_link.symlink_to(outside, target_is_directory=True)
    make_requirement_root(root, slug="base")
    make_requirement_root(root, slug="change", kind="需求变更", related="base#R-01")
    p = run(root, "plan", "--unit", "T-35", "--requirement",
            "product/requirements/change")
    assert p.returncode == 2
    assert "symlink" in p.stderr


def test_normalize_requirement_ref_handles_symlink_loop(tmp_path: Path) -> None:
    """M235：规范化路径的 OSError 不再被兜底时，本用例必须红。"""
    from _support.workflow_plan import normalize_requirement_ref

    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    assert normalize_requirement_ref(tmp_path, "loop") == "loop"


def test_plan_keeps_plain_file_direct_mode(tmp_path: Path) -> None:
    """M236：普通文件直填被路径型入口守卫误拒时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    req = root / "req.txt"
    req.write_text("实现首页标题", encoding="utf-8")
    p = run(root, "plan", "--unit", "T-36", "--requirement", "req.txt")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((root / ".atlas" / "tasks" / "T-36" / "task.json").read_text())
    assert "requirement_root" not in meta


def test_plan_rejects_missing_absolute_requirement_path(tmp_path: Path) -> None:
    root = make_clean_project(tmp_path)
    p = run(root, "plan", "--unit", "T-37", "--requirement",
            str(tmp_path / "missing.md"))
    assert p.returncode == 2
    assert "无法解析" in p.stderr


def test_plan_reserves_archive_directory_without_task_json(tmp_path: Path) -> None:
    """M237：无 task.json 的归档目录 ID 不再保留时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root)
    (root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-38").mkdir(parents=True)
    p = run(root, "plan", "--unit", "T-38", "--requirement",
            "product/requirements/demo-req")
    assert p.returncode == 2
    assert "归档命名空间" in p.stderr
    assert not (root / ".atlas" / "tasks" / "T-38").exists()


def test_requirement_root_symlink_loop_returns_finding(tmp_path: Path) -> None:
    """M238：verify 后续 resolve 不再捕获 symlink loop 时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    (root / "loop").symlink_to(root / "loop")
    _make_claim_card(root, "T-A", "loop", ["R-01"])
    findings = requirement_root_findings(root)
    assert any("路径不可解析" in f or "无法解析" in f for f in findings)


def test_requirement_root_invalid_utf8_returns_finding(tmp_path: Path) -> None:
    """M239：非法 UTF-8 账本不再转坏账本 finding 时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    make_requirement_root(root, status="已拆")
    broken = root / ".atlas" / "tasks" / "broken"
    broken.mkdir(parents=True)
    (broken / "task.json").write_bytes(b"\xff")
    findings = requirement_root_findings(root)
    assert any("任务账本不可读" in f for f in findings)


def test_finish_closeout_rejects_cross_root_claim(tmp_path: Path) -> None:
    """M240：finish 不再拒绝跨落点冒领时，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root, slug="a", status="已拆")
    make_requirement_root(root, slug="b", status="已拆")
    task = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "id": "T-A", "title": "T-A", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "created_at": "2026-11-01",
        "requirement_root": "product/requirements/a",
    }), encoding="utf-8")
    _write_claims(task, ["R-01", "R-02"], root_rel="product/requirements/b")
    closeout = requirement_closeout(root, "product/requirements/a")
    assert closeout["all_cards_closed"] is False
    assert closeout["requirement_status_target"] is None
    assert any("冒领" in f for f in closeout["findings"])


def test_plan_keeps_slash_text_direct_mode(tmp_path: Path) -> None:
    """M241：含斜杠普通需求文本不再被误拒时，本用例必须红。"""
    root = make_clean_project(tmp_path)
    p = run(root, "plan", "--unit", "T-41", "--requirement", "实现 /api/users 接口")
    assert p.returncode == 0, p.stdout + p.stderr


def test_load_tasks_rejects_non_string_id(tmp_path: Path) -> None:
    """M242：任务 ID 非字符串不再拒绝时，本用例必须红。"""
    from _support.workflow_plan import PlanError, load_tasks

    root = make_clean_project(tmp_path)
    task = root / ".atlas" / "tasks" / "bad"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({"id": ["T-A"]}), encoding="utf-8")
    with pytest.raises(PlanError, match="合法字符串 id"):
        load_tasks(root / ".atlas" / "tasks")


def test_archive_task_rejects_symlink_month(tmp_path: Path) -> None:
    """M243：归档月份 symlink 不再拒绝时，本用例必须红。"""
    from _support.workflow_finish import FinishError, archive_task

    root = make_clean_project(tmp_path)
    tasks = root / ".atlas" / "tasks"
    source = tasks / "T-A"
    source.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-month"
    outside.mkdir()
    (tasks / "archive").mkdir()
    (tasks / "archive" / "2026-11").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FinishError, match="symlink"):
        archive_task(root, tasks, source, "T-A")
    assert source.is_dir()


def test_relation_findings_block_requirement_closeout(tmp_path: Path) -> None:
    """M244：关联/缺陷报告缺失不再阻断收口时，本用例必须红。"""
    from _support.workflow_finish import requirement_closeout

    root = make_clean_project(tmp_path)
    make_requirement_root(root, slug="bug", kind="缺陷", status="已拆")
    task = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-A"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({
        "id": "T-A", "title": "T-A", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "created_at": "2026-11-01",
        "requirement_root": "product/requirements/bug",
    }), encoding="utf-8")
    _write_claims(task, ["R-01", "R-02"], root_rel="product/requirements/bug")
    assert any("推进为「已收口」" in f for f in requirement_root_findings(root)) is False
    closeout = requirement_closeout(root, "product/requirements/bug")
    assert closeout["requirement_status_target"] is None
    assert closeout["findings"]


def test_requirement_pointer_text_mentions_authority_order() -> None:
    text = requirement_pointer_text("product/requirements/x")
    assert "唯一住址" in text
    assert "需求原文 > 需求 PRD > 任务 PRD" in text


# ── 机制文档机器面（RFC-20261122-04 提示族残部 + RFC-20261123-01 申报判决门）──

from _support.workflow_verify import (  # noqa: E402
    MECHANISM_WARN_CAP, _mech_glob_regex, _mech_glob_wellformed,
    discover_mechanism_docs, mechanism_dead_declare_findings,
    mechanism_declaration_verdict, mechanism_doc_findings, parse_mech_declares
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


def test_mechanism_verdict_undeclared_template_and_pass_paths(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/trace.md", ["backend/**"])
    (root / "backend" / "svc.py").parent.mkdir(parents=True)
    (root / "backend" / "svc.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    tasks_root = root / ".atlas" / "tasks"

    v = mechanism_declaration_verdict(root, ["backend/svc.py", "other.py"],
                                      tasks_root, "T-1")
    assert len(v) == 1 and v[0]["kind"] == "undeclared", v
    assert v[0]["doc"] == "docs/architecture/trace.md"
    assert v[0]["hits"] == ["backend/svc.py"]
    assert v[0]["template"] == "- docs/architecture/trace.md: not-involved: <理由>"
    assert "T-1" in v[0]["declare_path"] and "mech-declares.md" in v[0]["declare_path"]
    # D4 隐式 updated：篇 ∈ 暂存 ⇒ PASS（触及提示「文档跟改了照样出声」的病根在此修掉）
    assert mechanism_declaration_verdict(
        root, ["backend/svc.py", "docs/architecture/trace.md"],
        tasks_root, "T-1") == []
    # 已申报（理由非空）⇒ PASS
    d = tasks_root / "T-1"
    d.mkdir(parents=True)
    (d / "mech-declares.md").write_text(
        "- docs/architecture/trace.md: not-involved: 部署态服务不在本仓\n",
        encoding="utf-8")
    assert mechanism_declaration_verdict(
        root, ["backend/svc.py"], tasks_root, "T-1") == []
    # 无触及 ⇒ 沉默
    assert mechanism_declaration_verdict(root, ["other.py"], tasks_root, "T-1") == []


def test_mechanism_doc_dead_paths_warn_and_alive_silent(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/old.md", ["gone/**"])
    _mech_doc(root, "docs/architecture/live.md", ["backend/**"])
    (root / "backend" / "a.py").parent.mkdir(parents=True)
    (root / "backend" / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root)
    dead = [f for f in findings if "疑似死 paths" in f]
    assert len(dead) == 1 and "docs/architecture/old.md" in dead[0]
    assert not any("live.md" in f and "疑似死" in f for f in findings)


def test_mechanism_doc_pending_skips_all(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/new.md", ["pending"])
    findings = mechanism_doc_findings(root)
    assert findings == []  # 冷启动豁免（评审 s1）：零命中判据不红、触及不判


def test_mechanism_doc_invalid_glob_named_not_matched(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/wide.md", ["src/*.py", "backend/**"])
    (root / "src" / "a.py").parent.mkdir(parents=True)
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    (root / "backend" / "b.py").parent.mkdir(parents=True)
    (root / "backend" / "b.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    findings = mechanism_doc_findings(root)
    assert any("非法 glob" in f and "'src/*.py'" in f for f in findings)
    assert not any("疑似死 paths" in f for f in findings)  # backend/** 仍活


def test_mechanism_verdict_no_cap_lists_all(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    changed = []
    for n in range(MECHANISM_WARN_CAP + 2):
        _mech_doc(root, f"docs/architecture/m{n}.md", [f"svc{n}/**"])
        (root / f"svc{n}" / "x.py").parent.mkdir(parents=True)
        (root / f"svc{n}" / "x.py").write_text("x\n", encoding="utf-8")
        changed.append(f"svc{n}/x.py")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    v = mechanism_declaration_verdict(root, changed, root / ".atlas" / "tasks", "T-1")
    undeclared = [x for x in v if x["kind"] == "undeclared"]
    assert len(undeclared) == MECHANISM_WARN_CAP + 2  # 判决 FAIL 面无 CAP（评审 Minor-1）


def test_mechanism_wordlist_two_tiers() -> None:
    good = ["docs/x.md", "backend/**", "dir/", "a/b/c.py"]
    bad = ["**", "**/x", "a/**/b", "src/*.py", "a/*/b", "a?.py", "a*/**"]
    for g in good:
        assert _mech_glob_wellformed(g), g
    for g in bad:
        assert not _mech_glob_wellformed(g), g


def test_mechanism_declares_grammar(tmp_path: Path) -> None:
    root = tmp_path
    tasks_root = root / ".atlas" / "tasks"
    # 缺文件 ⇒ 空且可解析
    assert parse_mech_declares(root, tasks_root, "T-1") == ({}, None)
    d = tasks_root / "T-1"
    d.mkdir(parents=True)
    p = d / "mech-declares.md"
    p.write_text(
        "# 注释行\n\n- docs/a.md: not-involved: 不涉及\n"
        "- ./docs/b.md: not-involved:   前缀与尾空白归一化  \n", encoding="utf-8")
    declares, bad = parse_mech_declares(root, tasks_root, "T-1")
    assert bad is None
    assert declares == {"docs/a.md": "不涉及", "docs/b.md": "前缀与尾空白归一化"}
    # 垃圾行 ⇒ fail-closed 带行号原文（RFC-20261123-01 §2.2）
    p.write_text("- docs/a.md: not-involved: x\ngarbage line\n", encoding="utf-8")
    declares, bad = parse_mech_declares(root, tasks_root, "T-1")
    assert declares == {} and bad is not None and "第 2 行" in bad and "garbage" in bad
    # 缺理由 ⇒ fail-closed 点名
    p.write_text("- docs/a.md: not-involved:\n", encoding="utf-8")
    _declares, bad = parse_mech_declares(root, tasks_root, "T-1")
    assert bad is not None and "缺理由" in bad


def test_mechanism_verdict_unparsable_short_circuits(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/a.md", ["backend/**"])
    (root / "backend" / "x.py").parent.mkdir(parents=True)
    (root / "backend" / "x.py").write_text("x\n", encoding="utf-8")
    d = root / ".atlas" / "tasks" / "T-1"
    d.mkdir(parents=True)
    (d / "mech-declares.md").write_text("garbage\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    v = mechanism_declaration_verdict(root, ["backend/x.py"],
                                      root / ".atlas" / "tasks", "T-1")
    assert len(v) == 1 and v[0]["kind"] == "unparsable_declares", v
    assert "garbage" in v[0]["hits"][0]


def test_mechanism_verdict_excludes_atlas_staging(tmp_path: Path) -> None:
    """**M206**：摘判决面 `.atlas/` 前缀过滤 ⇒ 本测试红（负断言，门册 C-15）。

    卡产物自身（含 mech-declares.md）入暂存不得触发触及——无过滤时 `.atlas/**`
    类 glob 永久命中申报文件 ⇒ 每轮必红的卡死循环（首轮评审 Blocker-1 场景）。"""
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/ledger.md", [".atlas/**"])
    d = root / ".atlas" / "tasks" / "T-1"
    d.mkdir(parents=True)
    (d / "mech-declares.md").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    # 卡产物自身入暂存不得触发触及（首轮 Blocker-1①）：
    # 无 .atlas 过滤时 .atlas/** 会永久命中申报文件自身 ⇒ 卡死循环
    v = mechanism_declaration_verdict(root, [".atlas/tasks/T-1/mech-declares.md"],
                                      root / ".atlas" / "tasks", "T-1")
    assert v == []


def test_mechanism_verdict_pending_exempt_but_bad_glob_not(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/new.md", ["pending"])
    _mech_doc(root, "docs/architecture/wide.md", ["src/**", "src/*.py"])
    (root / "src" / "a.py").parent.mkdir(parents=True)
    (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)

    v = mechanism_declaration_verdict(root, ["src/a.py"], root / ".atlas" / "tasks", "T-1")
    assert any(x["kind"] == "invalid_paths" and x["doc"] == "docs/architecture/wide.md"
               for x in v)  # 词表非法不豁免（pending 豁免的是覆盖判定非词形，Major-3）
    assert not any(x["kind"] == "undeclared" and x["doc"] == "docs/architecture/new.md"
                   for x in v)  # pending 覆盖判定豁免不变
    assert any(x["kind"] == "undeclared" and x["doc"] == "docs/architecture/wide.md"
               for x in v)


def test_mechanism_dead_declare_warn(tmp_path: Path) -> None:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/a.md", ["backend/**"])
    d = root / ".atlas" / "tasks" / "T-1"
    d.mkdir(parents=True)
    (d / "mech-declares.md").write_text(
        "- docs/architecture/a.md: not-involved: ok\n"
        "- docs/architecture/gone.md: not-involved: 篇已改名\n", encoding="utf-8")

    w = mechanism_dead_declare_findings(root, root / ".atlas" / "tasks", "T-1")
    assert len(w) == 1 and "gone.md" in w[0] and "申报死行" in w[0]
    # 不可解析 ⇒ 沉默（判决位已 fail-closed 出红，不重复出声）
    (d / "mech-declares.md").write_text("garbage\n", encoding="utf-8")
    assert mechanism_dead_declare_findings(root, root / ".atlas" / "tasks", "T-1") == []


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


def _mech_gate_project(tmp_path: Path) -> Path:
    root = _git_repo(tmp_path)
    _mech_doc(root, "docs/architecture/trace.md", ["backend/**"])
    (root / "backend" / "svc.py").parent.mkdir(parents=True)
    (root / "backend" / "svc.py").write_text("x = 1\n", encoding="utf-8")
    # 只暂存代码文件：机制篇自身不入暂存（入了就是 D4 隐式 updated，判 PASS）
    subprocess.run(["git", "add", "backend/svc.py"], cwd=root,
                   check=True, capture_output=True)
    return root


def test_verify_mechanism_gate_blocks_before_review(tmp_path: Path) -> None:
    """**M205**：摘 `cmd_verify` 前置带的 `mechanism_declaration_verdict` 调用 ⇒ 本测试红
    （负断言，门册 C-15）。门拦截 rc1 + stderr 申报模板/落点 + attempts 记账 charged。"""
    root = _mech_gate_project(tmp_path)
    p = run(root, "verify", "--unit", "T-1")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "FAIL（机制文档）" in p.stderr
    assert "not-involved" in p.stderr and "mech-declares.md" in p.stderr  # 申报模板 + 落点（Major-2）
    rows, _bad = load_attempts(root / ".atlas" / "tasks", "T-1")
    assert rows and rows[-1]["cause"] == "mechanism_undeclared"
    assert rows[-1]["charged"] is True  # D2：扣预算（词表定义 = 需实现侧动作）


def test_verify_mechanism_gate_json_shape(tmp_path: Path) -> None:
    root = _mech_gate_project(tmp_path)
    p = run(root, "verify", "--unit", "T-1", "--json")
    assert p.returncode == 1, p.stdout + p.stderr
    payload = json.loads(p.stdout)
    assert payload["status"] == "gate_fail"
    assert payload["cause"] == "mechanism_undeclared"
    assert payload["violations"][0]["doc"] == "docs/architecture/trace.md"
    assert payload["violations"][0]["kind"] == "undeclared"


def test_verify_dry_run_skips_mechanism_verdict(tmp_path: Path) -> None:
    root = _mech_gate_project(tmp_path)
    p = run(root, "verify", "--unit", "T-1", "--dry-run")
    assert "FAIL（机制文档）" not in p.stderr
    rows, _bad = load_attempts(root / ".atlas" / "tasks", "T-1")
    assert rows == []  # dry-run 不判决不记账（与前置带同契）


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


# ── workflow 回收面（RFC-20261122-07：双轨失败分类学 + 尝试预算 + 退出码封闭）────

import argparse  # noqa: E402

from _support.workflow_causes import (  # noqa: E402
    CAUSES, DEFAULT_MAX_VERIFY_ATTEMPTS, EXIT_BUDGET, EXIT_GATE_FAIL, EXIT_INTERRUPTED,
    EXIT_OK, EXIT_USAGE, attempts_path, charged_count, exit_code_for, load_attempts,
    max_verify_attempts, record_attempt,
)


def _verify_args(unit: str) -> argparse.Namespace:
    return argparse.Namespace(unit=unit, dry_run=False, json=False, check_cmd=None,
                              resolves=None, round=None, staged=True)


def _wf_mod():
    """进程内加载调度器模块（预算/记账断言用；e2e 面仍走 run() 子进程）。"""
    spec = importlib.util.spec_from_file_location("atlas_workflow_recycle_mod", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _staged_impl(root: Path, name: str = "a.ts") -> None:
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / name).write_text("export const a = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", f"src/{name}"], cwd=str(root), check=True,
                   capture_output=True)


def test_verify_charged_failure_counts_and_budget_refuses(tmp_path, monkeypatch,
                                                          capsys) -> None:
    """M197：摘 cmd_verify 预算门调用 ⇒ 本测试超限段变绿（负断言）。
    M198：摘 budget_exceeded 的不计数语义（词表改扣）⇒ 末段 charged==2 断言红。

    verify rc==1（报告未过）⇒ blocking_critical 扣预算；charged 达缺省上限 2 ⇒
    第三次拒绝 rc==3 + budget_exceeded 留痕行（不计数、cmd 写死 'verify'）。"""
    root = make_clean_project(_git_repo(tmp_path))
    _plan_and_dispatch(root, "T-B1")
    _staged_impl(root)
    mod = _wf_mod()
    real_run = subprocess.run
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda argv, *a, **k: fake if any("atlas_review.py" in str(x) for x in argv)
        else real_run(argv, *a, **k))
    ns = _verify_args("T-B1")
    assert mod.cmd_verify(ns, root) == 1
    assert mod.cmd_verify(_verify_args("T-B1"), root) == 1
    rc = mod.cmd_verify(_verify_args("T-B1"), root)
    assert rc == EXIT_BUDGET
    assert "预算超限" in capsys.readouterr().err
    tasks_root = root / ".atlas" / "tasks"
    rows, _ = load_attempts(tasks_root, "T-B1")
    charged = [r for r in rows if r.get("charged") is True]
    assert len(charged) == 2 and all(r["cause"] == "blocking_critical" for r in charged)
    last = rows[-1]
    assert (last["cause"], last["charged"], last["cmd"]) == ("budget_exceeded", False, "verify")
    assert all(r.get("unit") == "T-B1" for r in rows)


def test_verify_uncharged_staged_empty_never_blocks(tmp_path) -> None:
    """不扣轨：staged_empty 入记账不计数——反复撞前置不触发预算拒绝（真 e2e）。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-B2")
    for _ in range(5):
        p = run(root, "verify", "--unit", "T-B2")
        assert p.returncode == EXIT_USAGE and "暂存区为空" in p.stderr
    rows, _ = load_attempts(root / ".atlas" / "tasks", "T-B2")
    assert len(rows) == 5
    assert all(r["cause"] == "staged_empty" and r["charged"] is False for r in rows)
    assert charged_count(root / ".atlas" / "tasks", "T-B2") == 0


def test_verify_pending_records_uncharged(tmp_path) -> None:
    """会话待审（rc==2 PENDING）⇒ no_review_report 不扣预算（真 e2e，无 mock）。"""
    root = make_clean_project(_git_repo(tmp_path))
    _plan_and_dispatch(root, "T-B3")
    _staged_impl(root)
    p = run(root, "verify", "--unit", "T-B3")
    assert p.returncode == EXIT_USAGE and "PENDING" in p.stdout
    rows, _ = load_attempts(root / ".atlas" / "tasks", "T-B3")
    assert len(rows) == 1
    assert (rows[0]["cause"], rows[0]["charged"]) == ("no_review_report", False)


def test_verify_json_pause_reason_on_budget(tmp_path, monkeypatch, capsys) -> None:
    """--json 暂停面：预算超限输出 {"status":"paused","paused_reason":...}。"""
    root = make_clean_project(_git_repo(tmp_path))
    _plan_and_dispatch(root, "T-B4")
    _staged_impl(root)
    mod = _wf_mod()
    real_run = subprocess.run
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda argv, *a, **k: fake if any("atlas_review.py" in str(x) for x in argv)
        else real_run(argv, *a, **k))
    record_attempt(root / ".atlas" / "tasks", "T-B4", cmd="verify", cause="blocking_critical")
    record_attempt(root / ".atlas" / "tasks", "T-B4", cmd="verify", cause="blocking_critical")
    ns = argparse.Namespace(unit="T-B4", dry_run=False, json=True, check_cmd=None,
                            resolves=None, round=None, staged=True)
    rc = mod.cmd_verify(ns, root)
    assert rc == EXIT_BUDGET
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"unit": "T-B4", "status": "paused",
                       "paused_reason": "budget_exceeded"}


def test_exit_code_allocation_closed() -> None:
    """M199：摘退出码分配 budget 分支 ⇒ 本测试红（负断言）。

    封闭分配 0/1/2/3/130；扣预算 ⇒ 1；budget_exceeded ⇒ 3；不扣 ⇒ 2；
    fallback unclassified 保守扣 ⇒ 1；同位点不同 cause 不同码（no_review_report 2
    vs review_not_passed 1）。"""
    assert (EXIT_OK, EXIT_GATE_FAIL, EXIT_USAGE, EXIT_BUDGET, EXIT_INTERRUPTED) == (0, 1, 2, 3, 130)
    for cause, charged in CAUSES.items():
        if cause == "budget_exceeded":
            assert exit_code_for(cause) == EXIT_BUDGET
        else:
            assert exit_code_for(cause) == (EXIT_GATE_FAIL if charged else EXIT_USAGE)
    assert exit_code_for("unclassified") == EXIT_GATE_FAIL  # fallback 保守扣
    assert exit_code_for("no_review_report") == EXIT_USAGE
    assert exit_code_for("review_not_passed") == EXIT_GATE_FAIL


def test_config_max_attempts_fail_soft(tmp_path) -> None:
    """config fail-soft：无文件/无键/坏值/非正值（写 0 关预算）⇒ 缺省 2；显式值生效。"""
    root = tmp_path
    assert max_verify_attempts(root) == DEFAULT_MAX_VERIFY_ATTEMPTS == 2
    cfg = root / ".atlas" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("workflow:\n  max_verify_attempts: 5\n", encoding="utf-8")
    assert max_verify_attempts(root) == 5
    cfg.write_text("other:\n  key: 1\n", encoding="utf-8")
    assert max_verify_attempts(root) == DEFAULT_MAX_VERIFY_ATTEMPTS
    cfg.write_text("workflow:\n  max_verify_attempts: 0\n", encoding="utf-8")
    assert max_verify_attempts(root) == DEFAULT_MAX_VERIFY_ATTEMPTS  # N2：0 = 放行 ⇒ 回缺省
    cfg.write_text("workflow:\n  max_verify_attempts: abc\n", encoding="utf-8")
    assert max_verify_attempts(root) == DEFAULT_MAX_VERIFY_ATTEMPTS


def test_attempts_bad_lines_skipped_fail_soft(tmp_path) -> None:
    """读侧 fail-soft：半行 JSON 跳过计数；status 人读面出坏行数，不炸。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-B5")
    record_attempt(root / ".atlas" / "tasks", "T-B5", cmd="verify",
                   cause="blocking_critical")
    p = attempts_path(root / ".atlas" / "tasks", "T-B5")
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "x", "unit": "T-B5", "cmd": "verify", "cause": "blo\n')  # 半行
    rows, bad = load_attempts(root / ".atlas" / "tasks", "T-B5")
    assert len(rows) == 1 and bad == 1
    assert charged_count(root / ".atlas" / "tasks", "T-B5") == 1
    out = run(root, "status", "--unit", "T-B5")
    assert out.returncode == 0 and "坏行 1" in out.stdout


# ── deferred 台账通道（RFC-20261122-07 §3.1.3）────────────────────────────────

_DEFERRED_REPORT_CHECKS = [
    {"id": "P1", "level": "Critical", "check": "legacy_bug", "target": "src/old.py:10",
     "detail": "存量空指针", "pre_existing": True, "disposition": "open",
     "fingerprint": "fp-legacy-001"},
    {"id": "N1", "level": "Minor", "check": "nit", "target": "src/nit.py:2",
     "detail": "存量命名", "pre_existing": True, "disposition": "open"},
    {"id": "F1", "level": "Major", "check": "fixed_one", "target": "src/a.py:1",
     "detail": "已修存量", "pre_existing": True, "disposition": "fixed",
     "disposition_by": "维护者", "disposition_evidence": "diff"},
    {"id": "C1", "level": "Major", "check": "fresh_bug", "target": "src/new.py:5",
     "detail": "本次改动引入", "pre_existing": False, "disposition": "open"},
]


def _write_warn_report(root: Path, unit: str, *, checks: list, round_no: int = 1) -> None:
    r_dir = root / "product" / "reviews" / f"2026-11-22-impl-review-{unit}"
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / "review.json").write_text(json.dumps({
        "schema_version": 4, "ok": True, "status": "WARN", "round": round_no,
        "checks": checks,
    }), encoding="utf-8")


def test_deferred_registered_even_when_blocked(tmp_path) -> None:
    """M201：摘 extract_deferred_findings 调用 ⇒ 本测试 deferred.md 断言红（负断言）。

    open pre_existing Critical 以 WARN 下限阻断收口（收口需 PASS）——即便如此
    deferred.md 也要落账（提取在门判定之前）；本次改动引入的（pre_existing=False）
    与已关闭的不登记。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-D1")
    _write_warn_report(root, "T-D1", checks=_DEFERRED_REPORT_CHECKS)
    p = run(root, "finish", "--unit", "T-D1")
    assert p.returncode == EXIT_GATE_FAIL and "WARN" in p.stderr  # 仍阻断
    dw = (root / ".atlas" / "tasks" / "T-D1" / "deferred.md").read_text(encoding="utf-8")
    assert "DW-1" in dw and "存量空指针" in dw and "族:Critical" in dw
    assert "fp=fp-legacy-001" in dw and "r1" in dw
    assert "DW-2" in dw and "存量命名" in dw and "族:Minor" in dw  # 无 fingerprint ⇒ 回退键
    assert "k=" in dw
    assert "已修存量" not in dw  # disposition 关闭 ⇒ 不登记
    assert "本次改动引入" not in dw  # pre_existing=False ⇒ 不登记
    assert "阻断中 1 条" in p.stdout and "登记：2 条" in p.stdout


def test_deferred_fingerprint_idempotent_on_rerun(tmp_path) -> None:
    """fingerprint 幂等：同报告复跑 finish 不产生重复 DW 条目（第二次零新登记不出声）。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-D2")
    _write_warn_report(root, "T-D2", checks=_DEFERRED_REPORT_CHECKS)
    assert run(root, "finish", "--unit", "T-D2").returncode == EXIT_GATE_FAIL
    assert run(root, "finish", "--unit", "T-D2").returncode == EXIT_GATE_FAIL
    dw = (root / ".atlas" / "tasks" / "T-D2" / "deferred.md").read_text(encoding="utf-8")
    assert "DW-1" in dw and "DW-2" in dw and "DW-3" not in dw


def test_status_aggregates_attempts_and_deferred(tmp_path) -> None:
    """status 双聚合（含 --json 逐卡字段）：attempts charged/坏行 + deferred 开放数。

    先跑一次被阻断的 finish（触发 deferred 提取 + finish 失败记账），再查 status。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-D3")
    _write_warn_report(root, "T-D3", checks=_DEFERRED_REPORT_CHECKS)
    assert run(root, "finish", "--unit", "T-D3").returncode == EXIT_GATE_FAIL
    out = run(root, "status", "--unit", "T-D3")
    assert out.returncode == 0
    assert "charged 1/2" in out.stdout and "deferred 开放 2" in out.stdout
    pj = run(root, "status", "--unit", "T-D3", "--json")
    assert pj.returncode == 0
    data = json.loads(pj.stdout)
    task = next(t for t in data["tasks"] if t["id"] == "T-D3")
    assert task["attempts"] == {"charged": 1, "uncharged": 0, "limit": 2, "bad_lines": 0}
    assert task["deferred_open"] == 2


def test_finish_charged_row_written_on_warn_block(tmp_path) -> None:
    """finish 阻断按 cause 入记账：WARN 报告 ⇒ review_not_passed（扣）⇒ rc 1。"""
    root = make_clean_project(tmp_path)
    _plan_and_dispatch(root, "T-D4")
    _write_warn_report(root, "T-D4", checks=[])
    p = run(root, "finish", "--unit", "T-D4")
    assert p.returncode == EXIT_GATE_FAIL  # 语义钉保持：review_not_passed 门红 rc==1
    rows, _ = load_attempts(root / ".atlas" / "tasks", "T-D4")
    assert len(rows) == 1
    assert (rows[0]["cause"], rows[0]["charged"], rows[0]["cmd"]) == \
        ("review_not_passed", True, "finish")


# ── 机制文档判据行测试锚（RFC-20261122-07 §3.2.2，可选但存活）─────────────────

def _mech_doc_with_anchors(root: Path, rel: str, globs: list[str],
                           anchors: list[str]) -> None:
    _mech_doc(root, rel, globs)
    p = root / rel
    body = p.read_text(encoding="utf-8") + "\n" + "".join(
        f"行为陈述行〔测:{a}〕\n" for a in anchors)
    p.write_text(body, encoding="utf-8")


def test_mechanism_doc_dead_test_anchor_warns(tmp_path) -> None:
    """M202：摘 _dead_anchor_findings 调用 ⇒ 本测试红（负断言）。

    锚指向不存在的 tests 文件 ⇒ 死锚 WARN；存在的 ⇒ 沉默；非 tests/ 前缀 ⇒ 形态
    WARN；节点级存在性不机器判（文件在即不 WARN）。"""
    root = _git_repo(tmp_path)
    (root / "backend" / "a.py").parent.mkdir(parents=True)
    (root / "backend" / "a.py").write_text("x\n", encoding="utf-8")
    # 夹具仓内造一个真实存在的 tests 文件（锚检查对夹具仓根，非 atlas 仓）
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_local.py").write_text("def test_x():\n    pass\n",
                                                  encoding="utf-8")
    _mech_doc_with_anchors(root, "docs/architecture/x.md", ["backend/**"], [
        "tests/test_gone.py::test_a",      # 死锚：文件不存在
        "tests/test_local.py::test_x",     # 文件在（节点级不判）⇒ 沉默
        "scripts/foo.py",                  # 形态非法：非 tests/ 前缀
    ])
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    findings = mechanism_doc_findings(root)
    assert any("死锚" in f and "tests/test_gone.py" in f for f in findings)
    assert not any("test_local.py" in f and "死锚" in f for f in findings)
    assert any("形态非法" in f and "scripts/foo.py" in f for f in findings)


def test_mechanism_doc_pending_still_checks_anchor(tmp_path) -> None:
    """pending 篇（paths 冷启动豁免）的死锚仍判——锚存活与 paths 无关。"""
    root = _git_repo(tmp_path)
    _mech_doc_with_anchors(root, "docs/architecture/new.md", ["pending"],
                           ["tests/test_missing.py"])
    findings = mechanism_doc_findings(root)
    assert any("死锚" in f and "tests/test_missing.py" in f for f in findings)
    assert not any("触及" in f or "疑似死 paths" in f for f in findings)  # paths 面豁免不变


def test_mechanism_doc_anchor_free_lines_stay_silent(tmp_path) -> None:
    """未写锚的行零出声（棘轮起点 = 可选，不强推）：无锚机制篇行为与 RFC-04 一致。"""
    root = _git_repo(tmp_path)
    (root / "backend" / "a.py").parent.mkdir(parents=True)
    (root / "backend" / "a.py").write_text("x\n", encoding="utf-8")
    _mech_doc(root, "docs/architecture/plain.md", ["backend/**"])
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    assert mechanism_doc_findings(root) == []
