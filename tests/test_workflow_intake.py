#!/usr/bin/env python3
"""自然语言需求归类、落盘与实现前置门回归。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_workflow.py"
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


def run(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        input=stdin, capture_output=True, text=True, timeout=60,
    )


def project(root: Path) -> Path:
    (root / "product" / "prd").mkdir(parents=True, exist_ok=True)
    return root


def parent(root: Path, slug: str = "v3-knowledge", title: str = "V3 个人知识检索") -> Path:
    req = root / "product" / "requirements" / slug
    req.mkdir(parents=True)
    (req / "requirement.md").write_text(
        f"# {title}\n\n**类型**：初始需求  \n**状态**：已确认\n", encoding="utf-8")
    (req / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | 对话 | 原始请求 | 搜索结果可打开详情 |\n"
        "条目总数：1\n", encoding="utf-8")
    return req


def task_meta(root: Path, unit: str) -> dict:
    return json.loads((root / ".atlas" / "tasks" / unit / "task.json").read_text(encoding="utf-8"))


def test_change_words_win_over_incidental_bug_words(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-DRILL", "--requirement",
            "V3 个人知识检索新增回归测试套件与偶尔故障演练")
    assert p.returncode == 0, p.stdout + p.stderr
    landed = root / task_meta(root, "T-DRILL")["requirement_root"]
    assert "**类型**：初始需求" in (landed / "requirement.md").read_text(encoding="utf-8")
    meta = task_meta(root, "T-DRILL")
    assert meta["intake_type"] == "需求变更"
    assert "kind: 需求变更" in (root / meta["request_path"]).read_text(encoding="utf-8")


def test_short_title_substring_does_not_claim_parent(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root, "login", "登录")
    p = run(root, "plan", "--unit", "T-LOGIN", "--requirement", "新增登录日志导出功能")
    assert p.returncode == 2
    assert "--related" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_replan_with_plain_file_keeps_intake_binding(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    assert run(root, "plan", "--unit", "T-FILE", "--requirement",
               "V3 个人知识检索详情打不开").returncode == 0
    request = root / "request.txt"
    request.write_text("V3 个人知识检索新增导出功能", encoding="utf-8")
    p = run(root, "plan", "--unit", "T-FILE", "--requirement", str(request), "--replan")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-FILE")
    assert "活文档模式" in p.stdout
    assert f"本次请求 = {meta['request_path']}" in p.stdout
    assert "条目正文唯一住址" not in p.stdout
    prd = (root / ".atlas" / "tasks" / "T-FILE" / "prd.md").read_text(encoding="utf-8")
    assert "当前需求正文唯一住址" in prd
    assert f"本次请求原文：`{meta['request_path']}`" in prd
    claims = (root / ".atlas" / "tasks" / "T-FILE" / "requirement-items.md").read_text(encoding="utf-8")
    assert "活文档模式" in claims and "requirement.md" in claims
    assert meta["intake_version"] == 2
    assert meta["intake_type"] == "需求变更"
    assert "新增导出功能" in (root / meta["request_path"]).read_text(encoding="utf-8")


def test_replan_without_requirement_preserves_v2_binding(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-INIT", "--requirement", "新增个人知识检索功能").returncode == 0
    initial = task_meta(root, "T-INIT")
    request = "个人知识检索详情偶尔打不开"
    assert run(root, "plan", "--unit", "T-BUG", "--requirement", request,
               "--related", f"{Path(initial['requirement_root']).name}#R-01").returncode == 0
    before = task_meta(root, "T-BUG")
    for extra in ((), ("--requirement", request)):
        p = run(root, "plan", "--unit", "T-BUG", *extra)
        assert p.returncode == 0, p.stdout + p.stderr
        after = task_meta(root, "T-BUG")
        for key in ("intake_version", "intake_type", "request_id", "request_path", "base_commit"):
            assert after[key] == before[key]
        assert after["intake_version"] == 2
        assert "条目正文唯一住址" not in p.stdout
        prd = (root / ".atlas/tasks/T-BUG/prd.md").read_text(encoding="utf-8")
        assert "当前需求正文唯一住址" in prd
        assert f"本次请求原文：`{before['request_path']}`" in prd


def test_multitask_v2_replan_uses_request_text(tmp_path: Path) -> None:
    root = project(tmp_path)
    request = "### 第一步\n完成检索入口\n\n### 第二步\n完成结果详情"
    p = run(root, "plan", "--unit", "T-MULTI", "--requirement", request)
    assert p.returncode == 0, p.stdout + p.stderr
    before = {task_id: task_meta(root, task_id) for task_id in ("T-MULTI-01", "T-MULTI-02")}
    for extra in ((), ("--requirement", request)):
        p = run(root, "plan", "--unit", "T-MULTI", *extra)
        assert p.returncode == 0, p.stdout + p.stderr
        assert not (root / ".atlas/tasks/T-MULTI-03").exists()
        for task_id, meta in before.items():
            after = task_meta(root, task_id)
            for key in ("intake_version", "request_id", "request_path", "base_commit"):
                assert after[key] == meta[key]


@pytest.mark.parametrize("kind", ["change", "bug"])
def test_v2_replan_preserves_request_with_same_named_heading(tmp_path: Path, kind: str) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-INIT", "--requirement", "新增个人知识检索功能").returncode == 0
    initial = task_meta(root, "T-INIT")
    heading = "## 缺陷证据" if kind == "bug" else "## 变更口径"
    request = f"个人知识检索{'详情偶尔打不开' if kind == 'bug' else '增加排序'}\n{heading}\n用户补充说明"
    p = run(root, "plan", "--unit", "T-HEADING", "--requirement", request,
            "--related", f"{Path(initial['requirement_root']).name}#R-01")
    assert p.returncode == 0, p.stdout + p.stderr
    before = task_meta(root, "T-HEADING")
    for extra in ((), ("--requirement", request)):
        p = run(root, "plan", "--unit", "T-HEADING", *extra)
        assert p.returncode == 0, p.stdout + p.stderr
        after = task_meta(root, "T-HEADING")
        assert after["request_path"] == before["request_path"]
        assert after["intake_version"] == 2


@pytest.mark.parametrize("corruption", ["missing", "bad_utf8"])
def test_v2_replan_unreadable_request_fails_cleanly(tmp_path: Path, corruption: str) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-INIT", "--requirement", "新增个人知识检索功能").returncode == 0
    initial = task_meta(root, "T-INIT")
    assert run(root, "plan", "--unit", "T-BUG", "--requirement", "个人知识检索详情偶尔打不开",
               "--related", f"{Path(initial['requirement_root']).name}#R-01").returncode == 0
    request_path = root / task_meta(root, "T-BUG")["request_path"]
    if corruption == "missing":
        request_path.unlink()
    else:
        request_path.write_bytes(request_path.read_bytes() + b"\xff")
    p = run(root, "plan", "--unit", "T-BUG")
    assert p.returncode == 2
    assert "请求记录不可读" in p.stderr
    assert "Traceback" not in p.stderr


def test_plan_bad_utf8_requirement_file_fails_cleanly(tmp_path: Path) -> None:
    root = project(tmp_path)
    requirement = root / "requirement.txt"
    requirement.write_bytes(b"new requirement\n\xff")
    p = run(root, "plan", "--unit", "T-BAD", "--requirement", str(requirement))
    assert p.returncode == 2
    assert "需求文件不可读" in p.stderr
    assert "Traceback" not in p.stderr


def test_plan_bad_utf8_stdin_fails_cleanly(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "plan", "--unit", "T-BAD-STDIN",
         "--requirement", "-"], input=b"new requirement\n\xff", capture_output=True,
    )
    assert p.returncode == 2
    stderr = p.stderr.decode("utf-8", "replace")
    assert "stdin 需求输入不是合法 UTF-8" in stderr
    assert "Traceback" not in stderr


def test_explicit_path_switch_requires_replan(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root, "one", "需求一")
    parent(root, "two", "需求二")
    assert run(root, "plan", "--unit", "T-SWITCH", "--requirement",
               "新增收藏", "--related", "one#R-01").returncode == 0
    p = run(root, "plan", "--unit", "T-SWITCH", "--requirement",
            "product/requirements/two")
    assert p.returncode == 2
    assert "--replan" in p.stderr
    p2 = run(root, "plan", "--unit", "T-SWITCH", "--requirement",
             "product/requirements/two", "--replan")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert task_meta(root, "T-SWITCH")["requirement_root"] == "product/requirements/two"


def test_claim_source_accepts_items_md_suffix(tmp_path: Path) -> None:
    from _support.workflow_verify import requirement_root_findings
    root = project(tmp_path)
    parent(root)
    card = root / ".atlas" / "tasks" / "T-SUFFIX"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-SUFFIX", "title": "来源", "status": "todo", "depends_on": [],
        "affected_domains": [], "acs": [], "requirement_root": "product/requirements/v3-knowledge",
    }), encoding="utf-8")
    (card / "requirement-items.md").write_text(
        "| ID | 来源 |\n|---|---|\n"
        "| R-01 | product/requirements/v3-knowledge/items.md#R-01 |\n",
        encoding="utf-8")
    findings = requirement_root_findings(root)
    assert not any("冒领" in finding for finding in findings)


def test_legacy_card_replan_does_not_gain_intake_gate(tmp_path: Path) -> None:
    root = project(tmp_path)
    req = parent(root)
    card = root / ".atlas" / "tasks" / "T-LEGACY"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-LEGACY", "title": "旧任务", "status": "todo", "depends_on": [],
        "affected_domains": [], "acs": [], "requirement_root": "product/requirements/v3-knowledge",
    }), encoding="utf-8")
    (card / "requirement-items.md").write_text(
        "| ID | 来源 |\n|---|---|\n| ITEM-1 | product/requirements/v3-knowledge#ITEM-1 |\n",
        encoding="utf-8")
    p = run(root, "plan", "--unit", "T-LEGACY")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "intake_version" not in task_meta(root, "T-LEGACY")
    assert run(root, "dispatch", "--unit", "T-LEGACY").returncode == 0
    assert req.is_dir()


def test_closed_requirement_requires_new_unit_or_replan(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-CLOSED", "--requirement", "新增收藏").returncode == 0
    req = root / task_meta(root, "T-CLOSED")["requirement_root"]
    doc = req / "requirement.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("**状态**：已拆", "**状态**：已收口"),
                   encoding="utf-8")
    p = run(root, "plan", "--unit", "T-CLOSED", "--requirement", "新增收藏")
    assert p.returncode == 2 and "已收口" in p.stderr
    p2 = run(root, "plan", "--unit", "T-CLOSED", "--requirement", "新增收藏", "--replan")
    assert p2.returncode == 2 and "已收口" in p2.stderr


def test_reserved_archive_slug_is_rejected_without_pollution(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-RESERVED", "--requirement", "新增收藏", "--slug", "archive")
    assert p.returncode == 2
    assert "保留名" in p.stderr
    assert not (root / "product" / "requirements" / "archive" / "requirement.md").exists()


def test_archived_completed_task_allows_closed_requirement(tmp_path: Path) -> None:
    from _support.workflow_intake import intake_task_findings
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-ARCH", "--requirement", "新增收藏").returncode == 0
    ref = task_meta(root, "T-ARCH")["requirement_root"]
    req = root / ref
    doc = req / "requirement.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("**状态**：已拆", "**状态**：已收口"),
                   encoding="utf-8")
    meta = task_meta(root, "T-ARCH")
    assert intake_task_findings(root, {
        **meta, "status": "completed", "_archived": True,
    }) == []


def test_mark_split_ignores_fenced_status_example(tmp_path: Path) -> None:
    from _support.workflow_intake import mark_requirement_split
    req = parent(tmp_path)
    doc = req / "requirement.md"
    original = "**状态**：已确认  \n\n```md\n**状态**：已确认\n```\n"
    doc.write_text(original, encoding="utf-8")
    mark_requirement_split(req)
    updated = doc.read_text(encoding="utf-8")
    assert updated.startswith("**状态**：已拆  \n")
    assert "```md\n**状态**：已确认\n```" in updated


def test_index_symlink_is_rejected(tmp_path: Path) -> None:
    from _support.workflow_intake import refresh_requirement_index
    root = project(tmp_path)
    parent(root)
    outside = tmp_path.parent / f"{tmp_path.name}-index"
    outside.write_text("outside\n", encoding="utf-8")
    (root / "product" / "requirements" / "_index.md").symlink_to(outside)
    try:
        refresh_requirement_index(root)
    except Exception as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("index symlink was followed")
    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_dynamic_workflow_plan_load_without_package_path(tmp_path: Path) -> None:
    script = (
        "import importlib.util,pathlib;"
        f"p=pathlib.Path({str(PKG_ROOT / '_support/workflow_plan.py')!r});"
        "s=importlib.util.spec_from_file_location('standalone_plan',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.PlanError.__name__)"
    )
    p = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip() == "PlanError"


def test_missing_explicit_clause_does_not_fall_back_to_first(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-CLAUSE", "--requirement",
            "V3 个人知识检索R-99 页面打不开")
    assert p.returncode == 2
    assert "R-99" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_closed_landing_cannot_be_used_as_new_task_entry(tmp_path: Path) -> None:
    root = project(tmp_path)
    req = parent(root)
    doc = req / "requirement.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("**状态**：已确认", "**状态**：已收口"),
                   encoding="utf-8")
    p = run(root, "plan", "--unit", "T-CLOSED-PATH", "--requirement", str(req))
    assert p.returncode == 2
    assert "已收口" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_replan_to_other_landing_rebuilds_claim_table(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root, "one", "需求一")
    parent(root, "two", "需求二")
    assert run(root, "plan", "--unit", "T-RECLAIM", "--requirement",
               "新增收藏", "--related", "one#R-01").returncode == 0
    p = run(root, "plan", "--unit", "T-RECLAIM", "--requirement",
            "product/requirements/two", "--replan")
    assert p.returncode == 0, p.stdout + p.stderr
    claims = (root / ".atlas" / "tasks" / "T-RECLAIM" / "requirement-items.md").read_text(encoding="utf-8")
    assert "product/requirements/one#R-01" not in claims
    assert "product/requirements/two/items.md" in claims


def test_duplicate_active_and_archived_task_id_is_rejected(tmp_path: Path) -> None:
    from _support.workflow_plan import PlanError, load_tasks
    root = project(tmp_path)
    tasks = root / ".atlas" / "tasks"
    active = tasks / "T-DUP"
    archived = tasks / "archive" / "2026-11" / "T-DUP"
    active.mkdir(parents=True)
    archived.mkdir(parents=True)
    for card in (active, archived):
        (card / "task.json").write_text(json.dumps({
            "id": "T-DUP", "title": "重复", "status": "todo", "depends_on": [],
            "affected_domains": [], "acs": [],
        }), encoding="utf-8")
    try:
        load_tasks(tasks, include_archived=True)
    except PlanError as exc:
        assert "重复" in str(exc)
    else:
        raise AssertionError("duplicate task id was silently overwritten")


def test_chinese_slash_text_is_not_treated_as_path(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-SLASH", "--requirement", "新增A/B测试支持")
    assert p.returncode == 0, p.stdout + p.stderr
    assert task_meta(root, "T-SLASH")["intake_version"] == 2


@pytest.mark.parametrize("claim_mode", ["missing", "partial", "invalid", "no_source", "ghost", "swapped"])
def test_closeout_requires_complete_intake_claims(tmp_path: Path, claim_mode: str) -> None:
    from _support.workflow_finish import requirement_closeout
    root = project(tmp_path)
    req = root / "product" / "requirements" / "claims"
    req.mkdir(parents=True)
    (req / "requirement.md").write_text("**类型**：初始需求  \n**状态**：已拆\n", encoding="utf-8")
    (req / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | p1 | §1 | 一 |\n| R-02 | p2 | §2 | 二 |\n", encoding="utf-8")
    card = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-CLAIMS"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-CLAIMS", "title": "领取", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "intake_version": 1,
        "requirement_root": "product/requirements/claims",
    }), encoding="utf-8")
    if claim_mode == "partial":
        (card / "requirement-items.md").write_text(
            "| ID | 来源 |\n|---|---|\n"
            "| R-01 | product/requirements/claims#R-01 |\n", encoding="utf-8")
    elif claim_mode == "invalid":
        (card / "requirement-items.md").write_text(
            "| ID | 来源 |\n|---|---|\n| R-01 | 复制的正文 |\n", encoding="utf-8")
    elif claim_mode == "no_source":
        (card / "requirement-items.md").write_text(
            "| ID | 来源说明 |\n|---|---|\n| R-01 | 说明 |\n", encoding="utf-8")
    elif claim_mode == "ghost":
        (card / "requirement-items.md").write_text(
            "| ID | 来源 |\n|---|---|\n"
            "| R-01 | product/requirements/claims#R-01 |\n"
            "| R-02 | product/requirements/claims#R-02 |\n"
            "| R-99 | product/requirements/claims#R-99 |\n", encoding="utf-8")
    elif claim_mode == "swapped":
        (card / "requirement-items.md").write_text(
            "| ID | 来源 |\n|---|---|\n"
            "| R-01 | product/requirements/claims#R-02 |\n"
            "| R-02 | product/requirements/claims#R-01 |\n", encoding="utf-8")
    result = requirement_closeout(root, "product/requirements/claims")
    assert result["all_cards_closed"] is False
    assert result["requirement_status_target"] is None
    assert result["findings"]


def test_closeout_combines_legacy_and_intake_claims(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout
    root = project(tmp_path)
    req = root / "product" / "requirements" / "mixed"
    req.mkdir(parents=True)
    (req / "requirement.md").write_text("**类型**：初始需求  \n**状态**：已拆\n", encoding="utf-8")
    (req / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | p1 | §1 | 一 |\n| R-02 | p2 | §2 | 二 |\n", encoding="utf-8")
    for task_id, item_id, intake in (("T-OLD", "R-01", False), ("T-NEW", "R-02", True)):
        card = root / ".atlas" / "tasks" / "archive" / "2026-11" / task_id
        card.mkdir(parents=True)
        meta = {
            "id": task_id, "title": task_id, "status": "completed", "depends_on": [],
            "affected_domains": [], "acs": [], "requirement_root": "product/requirements/mixed",
        }
        if intake:
            meta["intake_version"] = 1
        (card / "task.json").write_text(json.dumps(meta), encoding="utf-8")
        if intake:
            (card / "requirement-items.md").write_text(
                "| ID | 来源 |\n|---|---|\n"
                f"| {item_id} | product/requirements/mixed#{item_id} |\n", encoding="utf-8")
        else:
            (card / "requirement-items.md").write_text(
                "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
                f"| {item_id} | p1 | §1 | 旧卡条目 来源说明 |\n", encoding="utf-8")
    result = requirement_closeout(root, "product/requirements/mixed")
    assert result["all_cards_closed"] is True
    assert result["requirement_status_target"] == "已收口"


def test_verify_blocks_legacy_card_without_claim_table(tmp_path: Path) -> None:
    from _support.workflow_verify import requirement_root_findings
    root = project(tmp_path)
    parent(root)
    card = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-NO-CLAIMS"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-NO-CLAIMS", "title": "旧卡", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "requirement_root": "product/requirements/v3-knowledge",
    }), encoding="utf-8")
    findings = requirement_root_findings(root)
    assert any("缺 requirement-items.md" in finding for finding in findings)
    assert not any("推进为「已收口」" in finding for finding in findings)


def test_closeout_rejects_legacy_ghost_claim(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout
    root = project(tmp_path)
    req = root / "product" / "requirements" / "legacy"
    req.mkdir(parents=True)
    (req / "requirement.md").write_text("**类型**：初始需求  \n**状态**：已拆\n", encoding="utf-8")
    (req / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | p1 | §1 | 一 |\n", encoding="utf-8")
    card = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-LEGACY-GHOST"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-LEGACY-GHOST", "title": "旧卡", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "requirement_root": "product/requirements/legacy",
    }), encoding="utf-8")
    (card / "requirement-items.md").write_text(
        "| ID | 来源 |\n|---|---|\n"
        "| R-99 | product/requirements/legacy#R-99 |\n", encoding="utf-8")
    result = requirement_closeout(root, "product/requirements/legacy")
    assert result["all_cards_closed"] is False
    assert any("幽灵" in finding for finding in result["findings"])


def test_verify_does_not_prompt_closeout_with_partial_claims(tmp_path: Path) -> None:
    from _support.workflow_verify import requirement_root_findings
    root = project(tmp_path)
    req = root / "product" / "requirements" / "claims"
    req.mkdir(parents=True)
    (req / "requirement.md").write_text("**类型**：初始需求  \n**状态**：已拆\n", encoding="utf-8")
    (req / "items.md").write_text(
        "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
        "| R-01 | p1 | §1 | 一 |\n| R-02 | p2 | §2 | 二 |\n", encoding="utf-8")
    card = root / ".atlas" / "tasks" / "archive" / "2026-11" / "T-CLAIMS"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-CLAIMS", "title": "领取", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "intake_version": 1,
        "requirement_root": "product/requirements/claims",
    }), encoding="utf-8")
    (card / "requirement-items.md").write_text(
        "| ID | 来源 |\n|---|---|\n"
        "| R-01 | product/requirements/claims#R-01 |\n", encoding="utf-8")
    findings = requirement_root_findings(root)
    assert any("漏领" in finding for finding in findings)
    assert not any("推进为「已收口」" in finding for finding in findings)


def test_plan_auto_creates_initial_requirement_before_task(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-INIT", "--requirement", "新增个人知识收藏功能")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-INIT")
    req = root / meta["requirement_root"]
    assert (req / "requirement.md").is_file()
    assert (req / "items.md").is_file()
    assert "**类型**：初始需求" in (req / "requirement.md").read_text(encoding="utf-8")
    assert "新增个人知识收藏功能" in (req / "requirement.md").read_text(encoding="utf-8")
    assert meta["intake_version"] == 2
    assert (req / "changes" / "CHG-000-initial" / "requirement.md").is_file()
    assert "新增个人知识收藏功能" in (root / meta["request_path"]).read_text(encoding="utf-8")
    assert "| ID | 锚 | 状态 | 最近请求 |" in (req / "items.md").read_text(encoding="utf-8")
    doc = (req / "requirement.md").read_text(encoding="utf-8")
    assert "**状态**：已拆  \n**版本**：1.0.0  \n**输入摘要**：" in doc
    index = (root / "product" / "requirements" / "_index.md").read_text(encoding="utf-8")
    assert "| slug | 类型 | 关联需求 |" in index
    assert "状态" not in index and "关联卡" not in index
    claims = (root / ".atlas" / "tasks" / "T-INIT" / "requirement-items.md").read_text(encoding="utf-8")
    assert f"| R-01 | {meta['requirement_root']}#R-01 |" in claims


def test_plan_auto_classifies_bug_and_links_mentioned_parent(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-BUG", "--requirement",
            "V3 个人知识检索的搜索结果偶尔打不开详情，请修复")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-BUG")
    req = root / meta["requirement_root"]
    fields = (req / "requirement.md").read_text(encoding="utf-8")
    assert "**类型**：初始需求" in fields
    assert meta["intake_type"] == "缺陷"
    report = (root / meta["request_path"]).read_text(encoding="utf-8")
    assert "kind: 缺陷" in report and "items: R-01" in report
    for key in ("现象", "期望", "实际", "复现", "环境"):
        assert key in report
    assert not (root / ".atlas" / "bugs").exists()
    assert "v3-knowledge#R-01" in report
    assert "搜索结果偶尔打不开详情" in report
    assert len(list((req / "bugs").glob("BUG-*.md"))) == 1


def test_change_preserves_full_multiline_request(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    request = "搜索结果增加按时间排序\n第二行：导出PDF\n仅管理员可导出"
    p = run(root, "plan", "--unit", "T-BODY", "--requirement", request,
            "--related", "v3-knowledge#R-01")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-BODY")
    request_text = (root / meta["request_path"]).read_text(encoding="utf-8")
    diff = (root / meta["requirement_root"] / "changes" / meta["request_id"] / "diff.md").read_text(encoding="utf-8")
    assert "第二行：导出PDF" in request_text and "仅管理员可导出" in request_text
    assert "第二行：导出PDF" in diff and "仅管理员可导出" in diff


def test_unrelated_single_parent_is_not_silently_claimed(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root, "login", "登录")
    p = run(root, "plan", "--unit", "T-BUG", "--requirement", "报表导出偶尔崩溃")
    assert p.returncode == 2
    assert "--related" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_new_capability_with_only_archived_requirements_is_initial(tmp_path: Path) -> None:
    root = project(tmp_path)
    req = parent(root)
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    req.rename(archive / req.name)
    p = run(root, "plan", "--unit", "T-NEW", "--requirement", "新增导出全部收藏功能")
    assert p.returncode == 0, p.stdout + p.stderr
    landed = root / task_meta(root, "T-NEW")["requirement_root"]
    assert "**类型**：初始需求" in (landed / "requirement.md").read_text(encoding="utf-8")


def test_repeated_bug_reuses_landing_across_units(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    request = "V3 个人知识检索的搜索结果偶尔打不开详情，请修复"
    assert run(root, "plan", "--unit", "T-BUG-A", "--requirement", request).returncode == 0
    first = task_meta(root, "T-BUG-A")["requirement_root"]
    p = run(root, "plan", "--unit", "T-BUG-B", "--requirement", request)
    assert p.returncode == 0, p.stdout + p.stderr
    assert task_meta(root, "T-BUG-B")["requirement_root"] == first
    assert task_meta(root, "T-BUG-B")["request_id"] == task_meta(root, "T-BUG-A")["request_id"]


def test_same_unit_rejects_different_request_without_orphan(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-SAME", "--requirement", "新增收藏").returncode == 0
    before = set((root / "product" / "requirements").glob("*/requirement.md"))
    p = run(root, "plan", "--unit", "T-SAME", "--requirement", "搜索结果偶尔打不开")
    assert p.returncode == 2
    assert "新的 --unit" in p.stderr
    assert set((root / "product" / "requirements").glob("*/requirement.md")) == before


def test_failure_retry_feature_is_change_not_bug(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-RETRY", "--requirement", "V3 个人知识检索新增失败重试机制")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-RETRY")
    assert meta["intake_type"] == "需求变更"
    assert "kind: 需求变更" in (root / meta["request_path"]).read_text(encoding="utf-8")


def test_missing_requirement_path_is_not_treated_as_request(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-PATH", "--requirement", "product/requirements/missing")
    assert p.returncode == 2
    assert "无法解析" in p.stderr
    assert not (root / "product" / "requirements").exists()


def test_outside_requirement_path_is_rejected_at_plan(tmp_path: Path) -> None:
    root = project(tmp_path / "repo")
    outside = parent(tmp_path / "outside")
    p = run(root, "plan", "--unit", "T-OUT", "--requirement", str(outside))
    assert p.returncode == 2
    assert "项目根内" in p.stderr or "路径非法" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_plan_auto_classifies_change_with_explicit_baseline(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-CHANGE", "--requirement",
            "搜索结果增加按时间排序", "--related", "v3-knowledge#R-01")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-CHANGE")
    assert meta["intake_type"] == "需求变更"
    assert (root / meta["requirement_root"] / "changes" / meta["request_id"] / "diff.md").is_file()


def test_explicit_baseline_makes_neutral_request_a_change(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-NEUTRAL", "--requirement", "收藏列表每页二十条",
            "--related", "v3-knowledge#R-01")
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-NEUTRAL")
    assert meta["intake_type"] == "需求变更"
    assert "kind: 需求变更" in (root / meta["request_path"]).read_text(encoding="utf-8")


def test_explicit_initial_type_rejects_baseline(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root)
    p = run(root, "plan", "--unit", "T-BAD", "--requirement", "新增收藏",
            "--type", "initial", "--related", "v3-knowledge#R-01")
    assert p.returncode == 2
    assert "初始需求" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_plan_rejects_bug_without_behavior_baseline(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-BUG", "--requirement", "修复页面打不开的问题", "--type", "bug")
    assert p.returncode == 2
    assert "基线" in p.stderr or "关联需求" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_plan_rejects_ambiguous_parent_without_writing(tmp_path: Path) -> None:
    root = project(tmp_path)
    parent(root, "knowledge-a", "个人知识检索")
    parent(root, "knowledge-b", "个人知识检索")
    p = run(root, "plan", "--unit", "T-BUG", "--requirement", "个人知识检索页面打不开")
    assert p.returncode == 2
    assert "knowledge-a" in p.stderr and "knowledge-b" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_plan_rejects_new_request_on_archived_parent(tmp_path: Path) -> None:
    root = project(tmp_path)
    req = parent(root)
    archive = root / "product" / "requirements" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    req.rename(archive / req.name)
    p = run(root, "plan", "--unit", "T-BUG", "--requirement", "V3 个人知识检索详情打不开")
    assert p.returncode == 2
    assert "归档" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_repeated_initial_request_keeps_version_two_binding(tmp_path: Path) -> None:
    root = project(tmp_path)
    first = run(root, "plan", "--unit", "T-FIRST", "--requirement", "新增知识标签筛选")
    assert first.returncode == 0, first.stdout + first.stderr
    second = run(root, "plan", "--unit", "T-SECOND", "--requirement", "新增知识标签筛选")
    assert second.returncode == 0, second.stdout + second.stderr
    first_meta = task_meta(root, "T-FIRST")
    second_meta = task_meta(root, "T-SECOND")
    assert second_meta["intake_version"] == 2
    assert second_meta["request_id"] == first_meta["request_id"] == "CHG-000-initial"
    assert second_meta["request_path"] == first_meta["request_path"]


def test_repeated_plan_reuses_requirement_and_is_idempotent(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-SAME", "--requirement", "新增知识标签筛选")
    assert p.returncode == 0, p.stdout + p.stderr
    req_rel = task_meta(root, "T-SAME")["requirement_root"]
    before = (root / req_rel / "items.md").read_bytes()
    p2 = run(root, "plan", "--unit", "T-SAME", "--requirement", "新增知识标签筛选")
    assert p2.returncode == 0, p2.stdout + p.stderr
    assert task_meta(root, "T-SAME")["requirement_root"] == req_rel
    assert (root / req_rel / "items.md").read_bytes() == before
    assert len(list((root / "product" / "requirements").glob("*/requirement.md"))) == 1
    assert len(list((root / req_rel / "changes").glob("CHG-*/request.md"))) == 1


def test_plan_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-DRY", "--requirement", "新增知识标签", "--dry-run")
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (root / ".atlas").exists()
    assert not (root / "product" / "requirements").exists()


def test_plan_without_input_blocks_new_task(tmp_path: Path) -> None:
    root = project(tmp_path)
    p = run(root, "plan", "--unit", "T-EMPTY")
    assert p.returncode == 2
    assert "需求" in p.stderr
    assert not (root / ".atlas" / "tasks").exists()


def test_dispatch_blocks_missing_intake_record(tmp_path: Path) -> None:
    """M245：摘除 dispatch 的 intake 前置调用后，本用例必须红。"""
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-GATE", "--requirement", "新增知识标签").returncode == 0
    meta_path = root / ".atlas" / "tasks" / "T-GATE" / "task.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["requirement_root"] = "product/requirements/missing"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    p = run(root, "dispatch", "--unit", "T-GATE")
    assert p.returncode == 2
    assert "归类" in p.stderr or "落点" in p.stderr
    assert not (root / ".atlas" / "tasks" / "T-GATE" / "dispatch.md").exists()


@pytest.mark.parametrize("kind", ["需求变更", "缺陷"])
def test_dispatch_blocks_missing_type_evidence(tmp_path: Path, kind: str) -> None:
    root = project(tmp_path)
    parent(root)
    request = "V3 个人知识检索详情打不开" if kind == "缺陷" else "搜索结果增加排序"
    extra = ("--related", "v3-knowledge#R-01") if kind == "需求变更" else ()
    p = run(root, "plan", "--unit", "T-EVIDENCE", "--requirement", request, *extra)
    assert p.returncode == 0, p.stdout + p.stderr
    meta = task_meta(root, "T-EVIDENCE")
    request_path = root / meta["request_path"]
    request_path.unlink()
    blocked = run(root, "dispatch", "--unit", "T-EVIDENCE")
    assert blocked.returncode == 2
    assert "请求记录不可解析" in blocked.stderr


def test_dispatch_blocks_candidate_requirement(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-CANDIDATE", "--requirement", "新增收藏").returncode == 0
    req = root / task_meta(root, "T-CANDIDATE")["requirement_root"]
    doc = req / "requirement.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("**状态**：已拆", "**状态**：候选"),
                   encoding="utf-8")
    p = run(root, "dispatch", "--unit", "T-CANDIDATE")
    assert p.returncode == 2
    assert "候选" in p.stderr


def test_finish_force_does_not_bypass_missing_intake(tmp_path: Path) -> None:
    root = project(tmp_path)
    assert run(root, "plan", "--unit", "T-FINISH", "--requirement", "新增知识标签").returncode == 0
    meta_path = root / ".atlas" / "tasks" / "T-FINISH" / "task.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["requirement_root"] = "product/requirements/missing"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    p = run(root, "finish", "--unit", "T-FINISH", "--force")
    assert p.returncode == 2
    assert "intake_missing" in (root / ".atlas" / "tasks" / "T-FINISH" / "attempts.jsonl").read_text(encoding="utf-8")


def test_dispatch_allows_legacy_card_without_intake_version(tmp_path: Path) -> None:
    root = project(tmp_path)
    card = root / ".atlas" / "tasks" / "T-OLD"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-OLD", "title": "旧任务", "status": "todo", "depends_on": [],
        "affected_domains": [], "acs": [],
    }), encoding="utf-8")
    p = run(root, "dispatch", "--unit", "T-OLD")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (card / "dispatch.md").is_file()


def test_verify_blocks_missing_intake_before_review(tmp_path: Path) -> None:
    root = project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    assert run(root, "plan", "--unit", "T-VERIFY", "--requirement", "新增知识标签").returncode == 0
    meta_path = root / ".atlas" / "tasks" / "T-VERIFY" / "task.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["requirement_root"] = "product/requirements/missing"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (root / "code.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "code.py"], cwd=root, check=True)
    p = run(root, "verify", "--unit", "T-VERIFY")
    assert p.returncode == 2
    assert "归类" in p.stderr or "落点" in p.stderr
    attempts = (root / ".atlas" / "tasks" / "T-VERIFY" / "attempts.jsonl").read_text(encoding="utf-8")
    assert "intake_missing" in attempts


def test_closeout_matches_equivalent_absolute_requirement_path(tmp_path: Path) -> None:
    from _support.workflow_finish import requirement_closeout
    root = project(tmp_path)
    req = parent(root)
    card = root / ".atlas" / "tasks" / "T-CLOSE"
    card.mkdir(parents=True)
    (card / "task.json").write_text(json.dumps({
        "id": "T-CLOSE", "title": "收口", "status": "completed", "depends_on": [],
        "affected_domains": [], "acs": [], "requirement_root": str(req),
    }), encoding="utf-8")
    archive = root / ".atlas" / "tasks" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    shutil.move(str(card), str(archive / "T-CLOSE"))
    (archive / "T-CLOSE" / "requirement-items.md").write_text(
        "| ID | 来源 |\n|---|---|\n"
        "| R-01 | product/requirements/v3-knowledge#R-01 |\n", encoding="utf-8")
    result = requirement_closeout(root, "product/requirements/v3-knowledge")
    assert result["all_cards_closed"] is True


def test_plan_uses_custom_assets_root(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "atlas.config.yaml").write_text("version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    p = run(root, "plan", "--unit", "T-DOCS", "--requirement", "新增知识标签")
    assert p.returncode == 0, p.stdout + p.stderr
    assert task_meta(root, "T-DOCS")["requirement_root"].startswith("docs/requirements/")


def test_plan_accepts_quoted_stdin_request(tmp_path: Path) -> None:
    root = project(tmp_path)
    request = "新增收藏；$(touch SHOULD_NOT_EXIST)"
    p = run(root, "plan", "--unit", "T-STDIN", "--requirement", "-", stdin=request)
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (root / "SHOULD_NOT_EXIST").exists()
    meta = task_meta(root, "T-STDIN")
    assert request in (root / meta["request_path"]).read_text(encoding="utf-8")
