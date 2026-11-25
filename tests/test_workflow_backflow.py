#!/usr/bin/env python3
"""活需求文档的变更/缺陷 diff 回推回归。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PKG_ROOT / "scripts" / "atlas_workflow.py"
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backflow = _load("workflow_backflow", PKG_ROOT / "_support" / "workflow_backflow.py")
atlas_bug = _load("atlas_bug", PKG_ROOT / "scripts" / "atlas_bug.py")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def project(root: Path) -> Path:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "product" / "prd").mkdir(parents=True)
    (root / "product" / "prd" / "prd.md").write_text(
        "---\nversion: 1.0.0\ndate: 2026-11-25\n---\n\n# PRD\n\ntestid: search-result\n", encoding="utf-8")
    (root / "product" / "e2e" / "cases").mkdir(parents=True)
    (root / "product" / "e2e" / "cases" / "home.md").write_text(
        "# 首页\n\n- testid: search-result\n", encoding="utf-8")
    (root / "code.js").write_text(
        'const x = <div data-testid="search-result" />;\nconst y = { status: "ready" };\n',
        encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def plan(root: Path, unit: str, text: str, *extra: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(WORKFLOW), "--root", str(root), "plan", "--unit", unit,
         "--requirement", text, *extra], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((root / ".atlas" / "tasks" / unit / "task.json").read_text(encoding="utf-8"))


def args_for(unit: str, kind: str = "bug", **kwargs) -> argparse.Namespace:
    values = {
        "root": ".", "unit": unit, "kind": kind, "from_": None, "stage": None,
        "decision": None, "decision_by": None, "clause_text": None, "pr": None,
        "commit": None, "dry_run": False, "json": True,
    }
    values.update(kwargs)
    return argparse.Namespace(**values)


def passing_validators(root: Path, feature_root: Path, request_path: Path, *,
                       include_structure: bool) -> list[dict]:
    return [{"validator": "fixture", "status": "PASS", "returncode": 0, "output": ""}]


def feature(root: Path) -> dict:
    return plan(root, "T-INIT", "新增搜索结果详情功能，testid 为 search-result，接口字段 status 为 ready")


def bug_meta(root: Path, unit: str = "T-BUG") -> dict:
    initial = feature(root)
    return plan(root, unit, "搜索结果偶尔打不开", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")


def test_bug_testid_backflow_updates_e2e_and_is_idempotent(tmp_path: Path, monkeypatch, capsys) -> None:
    root = project(tmp_path)
    initial = feature(root)
    meta = plan(root, "T-BUG", "搜索结果偶尔打不开", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    request_path = root / meta["request_path"]
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    assert "search-result-old" in (root / "product/e2e/cases/home.md").read_text(encoding="utf-8")
    assert "version: 1.0.1" in (root / "product/prd/prd.md").read_text(encoding="utf-8")
    record = backflow.parse_record(request_path)
    assert record["status"] == "ok"
    assert backflow.backflow_findings(root, meta) == []
    before = request_path.read_bytes()
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    assert request_path.read_bytes() == before
    assert backflow.backflow_findings(root, meta) == []
    from _support.workflow_finish import finish_task
    meta["_dir"] = str(root / ".atlas" / "tasks" / "T-BUG")
    result = finish_task(root, meta, force=True)
    assert result["status"] == "completed"


def test_change_backflow_updates_clause_and_identifier(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    initial = feature(root)
    meta = plan(root, "T-CHANGE", "搜索结果增加排序，testid 改为 search-result-new",
                "--related", f"{Path(initial['requirement_root']).name}#R-01")
    (root / "code.js").write_text('const x = <div data-testid="search-result-new" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"], "change"), root) == 0
    requirement = (root / meta["requirement_root"] / "requirement.md").read_text(encoding="utf-8")
    assert "search-result-new" in requirement
    assert "search-result-new" in (root / "product/e2e/cases/home.md").read_text(encoding="utf-8")
    assert "version: 1.1.0" in (root / "product/prd/prd.md").read_text(encoding="utf-8")
    assert backflow.parse_record(root / meta["request_path"])["status"] == "ok"


def test_bug_business_identifier_conflict_does_not_rewrite_contract(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    initial = feature(root)
    meta = plan(root, "T-BUG", "搜索结果偶尔打不开", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    request_path = root / meta["request_path"]
    (root / "code.js").write_text('const x = <div data-testid="search-result" />;\nconst y = { status: "failed" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 2
    requirement = (root / meta["requirement_root"] / "requirement.md").read_text(encoding="utf-8")
    assert "status 为 ready" in requirement
    assert backflow.parse_record(request_path)["status"] == "conflict"
    assert backflow.backflow_findings(root, meta)
    assert atlas_bug.run(args_for(meta["id"], decision="确认契约改为 failed",
                                  decision_by="maintainer"), root) == 0
    assert "status 为 failed" in (root / meta["requirement_root"] / "requirement.md").read_text(encoding="utf-8")


def test_finish_blocks_when_backflow_missing(tmp_path: Path) -> None:
    """M246：摘除 finish 的回推门调用后，本用例必须红。"""
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text("x = 1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(WORKFLOW), "--root", str(root), "finish", "--unit", "T-BUG", "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "回推" in result.stderr
    attempts = (root / ".atlas/tasks/T-BUG/attempts.jsonl").read_text(encoding="utf-8")
    assert "backflow_missing" in attempts


def test_backflow_becomes_stale_after_code_change(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    (root / "code.js").write_text('const x = <div data-testid="search-result-newer" />;\n', encoding="utf-8")
    findings = backflow.backflow_findings(root, meta)
    assert findings and "过期" in findings[0]


def test_dry_run_does_not_write_documents(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    before = (root / "product/e2e/cases/home.md").read_bytes()
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"], dry_run=True), root) == 0
    assert (root / "product/e2e/cases/home.md").read_bytes() == before
    assert backflow.parse_record(root / meta["request_path"]) is None


def test_spec_path_and_identifier_are_backfilled(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    spec = root / ".atlas" / "spec" / "conventions" / "search.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("---\npaths:\n  - code.js\n---\n\n# 检索规范\n\ntestid: search-result\n", encoding="utf-8")
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    assert "search-result-old" in spec.read_text(encoding="utf-8")
    assert any(i["type"] == "spec" for i in backflow.parse_record(root / meta["request_path"])["impacts"])


def test_multiline_pipe_request_keeps_change_record_intact(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    initial = feature(root)
    request = "搜索结果增加排序|导出\n仅管理员可导出"
    meta = plan(root, "T-CHANGE", request, "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    (root / "code.js").write_text('const x = <div data-testid="search-result-new" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"], "change"), root) == 0
    doc = (root / meta["requirement_root"] / "requirement.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith(f"| {meta['request_id']} |"))
    assert "排序\\|导出<br>仅管理员" in row
    assert row.endswith("| 已实现并校验 |")


def test_rerun_with_metadata_does_not_double_replace_or_bump(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    prd = root / "product/prd/prd.md"
    version = next(line for line in prd.read_text(encoding="utf-8").splitlines() if line.startswith("version:"))
    assert atlas_bug.run(args_for(meta["id"], stage="prod", pr="42"), root) == 0
    assert next(line for line in prd.read_text(encoding="utf-8").splitlines() if line.startswith("version:")) == version
    assert "old-old" not in (root / "product/e2e/cases/home.md").read_text(encoding="utf-8")
    assert backflow.backflow_findings(root, meta) == []


def test_decision_without_signer_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result" />;\nconst y = { status: "failed" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    before = (root / meta["requirement_root"] / "requirement.md").read_bytes()
    assert atlas_bug.run(args_for(meta["id"], decision="改为 failed"), root) == 2
    assert (root / meta["requirement_root"] / "requirement.md").read_bytes() == before


def test_unrelated_field_change_is_not_paired_as_rename(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    initial = feature(root)
    meta = plan(root, "T-CHANGE", "首页字段调整", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    current = backflow.clause_text(root / meta["requirement_root"], "R-01")
    (root / "code.js").write_text('const x = { theme: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"], "change", clause_text=current), root) == 2
    assert backflow.clause_text(root / meta["requirement_root"], "R-01") == current
    assert backflow.parse_record(root / meta["request_path"])["status"] == "conflict"


def test_second_request_does_not_stale_first_receipt(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    first = bug_meta(root, "T-BUG-1")
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(first["id"]), root) == 0
    second = plan(root, "T-BUG-2", "搜索结果偶尔 loading", "--related",
                  f"{Path(first['requirement_root']).name}#R-01")
    assert second["request_id"] != first["request_id"]
    assert backflow.backflow_findings(root, first) == []


def test_request_metadata_tamper_invalidates_receipt(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    path = root / meta["request_path"]
    path.write_text(path.read_text(encoding="utf-8").replace("status: implemented", "status: confirmed"), encoding="utf-8")
    assert backflow.backflow_findings(root, meta)


def test_missing_living_document_returns_one_with_receipt(tmp_path: Path) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / meta["requirement_root"] / "items.md").unlink()
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    assert atlas_bug.run(args_for(meta["id"]), root) == 1
    record = backflow.parse_record(root / meta["request_path"])
    assert record["status"] == "fail"
    assert any(v["validator"] == "validate_living_requirement" and v["returncode"] == 1
               for v in record["validators"])


def test_partial_bad_utf8_returns_one_with_receipt(tmp_path: Path) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    requirement = root / meta["requirement_root"] / "requirement.md"
    requirement.write_bytes(requirement.read_bytes() + b"\xff")
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    assert atlas_bug.run(args_for(meta["id"]), root) == 1
    assert backflow.parse_record(root / meta["request_path"])["status"] == "fail"


def test_missing_requirement_on_change_returns_one_with_receipt(tmp_path: Path) -> None:
    root = project(tmp_path)
    initial = feature(root)
    meta = plan(root, "T-CHANGE", "搜索结果增加排序", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    (root / meta["requirement_root"] / "requirement.md").unlink()
    assert atlas_bug.run(args_for(meta["id"], "change"), root) == 1
    assert backflow.parse_record(root / meta["request_path"])["status"] == "fail"


def test_corruption_after_success_replaces_ok_receipt_with_fail(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    requirement = root / meta["requirement_root"] / "requirement.md"
    requirement.write_bytes(requirement.read_bytes() + b"\xff")
    assert atlas_bug.run(args_for(meta["id"]), root) == 1
    assert backflow.parse_record(root / meta["request_path"])["status"] == "fail"


def test_truncated_item_row_after_success_replaces_ok_receipt_with_fail(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    items = root / meta["requirement_root"] / "items.md"
    lines = items.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("| R-01 |"))
    lines[index] = "| R-01 |"
    items.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert backflow.backflow_findings(root, meta)
    assert atlas_bug.run(args_for(meta["id"]), root) == 1
    assert backflow.parse_record(root / meta["request_path"])["status"] == "fail"


def test_missing_recent_request_after_success_blocks_finish(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    items = root / meta["requirement_root"] / "items.md"
    lines = items.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("| R-01 |"))
    lines[index] = "| R-01 | requirement.md#R-01 | active |  |"
    items.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert backflow.backflow_findings(root, meta)
    from _support.workflow_finish import FinishError, finish_task
    meta["_dir"] = str(root / ".atlas" / "tasks" / "T-BUG")
    with pytest.raises(FinishError) as error:
        finish_task(root, meta, force=True)
    assert error.value.cause == "backflow_stale"


@pytest.mark.parametrize("recent_kind", ["older", "missing"])
def test_invalid_recent_request_after_success_blocks_backflow(tmp_path: Path, monkeypatch, recent_kind: str) -> None:
    root = project(tmp_path)
    first = bug_meta(root, "T-BUG-1")
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(first["id"]), root) == 0
    plan(root, "T-BUG-2", "搜索结果偶尔 loading", "--related",
         f"{Path(first['requirement_root']).name}#R-01")
    items = root / first["requirement_root"] / "items.md"
    lines = items.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("| R-01 |"))
    recent = first["request_id"] if recent_kind == "older" else "BUG-19990101-001"
    lines[index] = f"| R-01 | requirement.md#R-01 | active | {recent} |"
    items.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert backflow.backflow_findings(root, first)
    assert atlas_bug.run(args_for(first["id"]), root) == 1
    assert backflow.parse_record(root / first["request_path"])["status"] == "fail"


@pytest.mark.parametrize("corruption", ["orphan_row", "deleted_request"])
def test_orphan_change_record_blocks_backflow(tmp_path: Path, monkeypatch, corruption: str) -> None:
    root = project(tmp_path)
    first = bug_meta(root, "T-BUG-1")
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(first["id"]), root) == 0
    second = plan(root, "T-BUG-2", "搜索结果偶尔 loading", "--related",
                  f"{Path(first['requirement_root']).name}#R-01")
    requirement = root / first["requirement_root"] / "requirement.md"
    if corruption == "deleted_request":
        (root / second["request_path"]).unlink()
        items = root / first["requirement_root"] / "items.md"
        lines = items.read_text(encoding="utf-8").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("| R-01 |"))
        lines[index] = f"| R-01 | requirement.md#R-01 | active | {first['request_id']} |"
        items.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        requirement.write_text(requirement.read_text(encoding="utf-8") +
                               "| BUG-19990101-777 | 缺陷 | 2026-11-25 | 伪造 | R-01 | 已修复 |\n",
                               encoding="utf-8")
    assert backflow.backflow_findings(root, first)
    assert atlas_bug.run(args_for(first["id"]), root) == 1
    assert backflow.parse_record(root / first["request_path"])["status"] == "fail"


def test_bad_utf8_external_document_records_conflict(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    prd = root / "product/prd/prd.md"
    prd.write_bytes(prd.read_bytes() + b"\xff")
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 2
    record = backflow.parse_record(root / meta["request_path"])
    assert record["status"] == "conflict"
    assert any("UTF-8" in c["reason"] for c in record["conflicts"])


def test_bad_utf8_request_blocks_finish_without_traceback(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", passing_validators)
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    request = root / meta["request_path"]
    request.write_bytes(request.read_bytes() + b"\xff")
    result = subprocess.run(
        [sys.executable, str(WORKFLOW), "--root", str(root), "finish", "--unit", "T-BUG", "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "回推" in result.stderr
    assert "Traceback" not in result.stderr
    assert json.loads((root / ".atlas/tasks/T-BUG/task.json").read_text(encoding="utf-8"))["status"] == "todo"
    assert not (root / ".atlas/tasks/archive").exists()


def test_real_validators_pass_after_testid_backflow(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("fixture_validators", PKG_ROOT / "tests/test_validators.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    root = tmp_path
    fixture.mk_prototype(root)
    fixture.mk_cases(root)
    fixture.mk_index(root)
    fixture.mk_prd(root)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    initial = plan(root, "T-INIT", "新增首页测试功能")
    meta = plan(root, "T-BUG", "首页按钮偶尔打不开", "--related",
                f"{Path(initial['requirement_root']).name}#R-01")
    (root / "web/src/home.html").write_text(
        '<!doctype html><html><body><button data-testid="home-cta-btn-new">开始</button>'
        '<h1 data-testid="home-title">首页</h1></body></html>', encoding="utf-8")
    assert atlas_bug.run(args_for(meta["id"]), root) == 0
    record = backflow.parse_record(root / meta["request_path"])
    assert all(v["returncode"] == 0 for v in record["validators"])
    assert any(v["validator"] == "validate_living_requirement" for v in record["validators"])


def test_living_document_validator_failure_is_recorded(tmp_path: Path) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / meta["requirement_root"] / "items.md").unlink()
    results = backflow.run_validators(root, root / meta["requirement_root"],
                                      root / meta["request_path"], include_structure=False)
    living = next(v for v in results if v["validator"] == "validate_living_requirement")
    assert living["returncode"] == 1 and living["status"] == "FAIL"


def test_docs_only_change_is_not_code_impact(tmp_path: Path) -> None:
    root = project(tmp_path)
    docs = root / "docs" / "guide.md"
    docs.parent.mkdir()
    docs.write_text('data-testid: "search-result"\n', encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "docs")
    meta = bug_meta(root)
    docs.write_text('data-testid: "search-result-new"\n', encoding="utf-8")
    assert backflow.changed_code_files(root, meta["base_commit"]) == []


def test_multiple_changes_increment_feature_version(tmp_path: Path) -> None:
    root = project(tmp_path)
    initial = feature(root)
    related = f"{Path(initial['requirement_root']).name}#R-01"
    plan(root, "T-C1", "搜索结果增加排序", "--related", related)
    plan(root, "T-C2", "搜索结果增加筛选", "--related", related)
    doc = (root / initial["requirement_root"] / "requirement.md").read_text(encoding="utf-8")
    assert "**版本**：1.2.0" in doc


def test_validator_failure_returns_one_and_records_fail(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    meta = bug_meta(root)
    (root / "code.js").write_text('const x = <div data-testid="search-result-old" />;\nconst y = { status: "ready" };\n', encoding="utf-8")
    monkeypatch.setattr(atlas_bug, "run_validators", lambda root, feature_root, request_path, include_structure: [
        {"validator": "fixture", "status": "FAIL", "returncode": 1, "output": "bad"}])
    assert atlas_bug.run(args_for(meta["id"]), root) == 1
    assert backflow.parse_record(root / meta["request_path"])["status"] == "fail"
