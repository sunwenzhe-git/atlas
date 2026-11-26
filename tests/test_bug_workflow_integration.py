#!/usr/bin/env python3
"""Issue #75/#76 regression coverage: defect backflow through review and finish.

Fixtures are real Git repositories.  The happy path stages an implementation,
a confirmed backflow document, and record.json, then seals a v4 review against
the index.  Negative cases mutate one finish precondition at a time.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import review_scope_core as scope_core
from _support.bug_backflow import (
    artifact_paths, required_staged_paths, review_anchor, source_snapshot,
    validate_backflow,
)
from _support.bug_record import (
    RECORD_FILE, append_history, canonical_bytes, new_record, read_record,
    refresh_hashes, sha256_bytes, write_record,
)
from _support.workflow_causes import load_attempts
from _support.workflow_finish import FinishError, check_task_review_passed, finish_task
from _support.workflow_plan import load_tasks
from scripts import atlas_workflow as workflow
from scripts.atlas_review import seal_bug_anchor
from test_atlas_workflow import (
    _make_claim_card, make_clean_project, make_requirement_root,
    run as workflow_run,
)
from test_review_scope import git, init_repo

ATLAS_BIN = PKG_ROOT / "bin" / "atlas.js"
BUG = "bug-75"
UNIT = "T-BUG-75"
IMPL = "src/app.py"
PRD = "product/prd/home-prd.md"
BUG_REL = f"product/requirements/{BUG}"
RECORD_REL = f"{BUG_REL}/{RECORD_FILE}"
BUG_ARTIFACTS = {RECORD_REL, PRD, f"{BUG_REL}/requirement.md", f"{BUG_REL}/items.md",
                 f"{BUG_REL}/work/缺陷报告.md"}
REVIEW_REL = f"product/reviews/2026-11-26-impl-review-{UNIT}"


@dataclass
class BugFixture:
    root: Path
    req_root: Path
    record: dict
    artifacts: set[str]

    @property
    def task(self) -> dict:
        return next(t for t in load_tasks(self.root / ".atlas" / "tasks")
                    if t["id"] == UNIT)

    @property
    def review_file(self) -> Path:
        return self.root / REVIEW_REL / "review.json"


def _git_text(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, text=True, timeout=30,
    ).stdout


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _make_bug_fixture(tmp_path: Path, *, delete_impl: bool = False,
                      kind: str = "缺陷", slug: str = BUG) -> BugFixture:
    root = tmp_path
    init_repo(root)
    # Keep this downstream fixture schema-valid on Git versions whose default
    # raw-diff abbreviation is seven hex digits.  The unconfigured case is
    # covered separately by test_staged_source_snapshot_has_full_object_ids.
    git(root, "config", "core.abbrev", "40")
    make_clean_project(root)
    (root / "product" / "stack-profile.yaml").write_text("origin: adopt\n", encoding="utf-8")
    make_requirement_root(root)
    (root / "src").mkdir()
    (root / IMPL).write_text("print('before')\n", encoding="utf-8")
    req_root = make_requirement_root(
        root, slug=slug, item_ids=("R-01",), kind=kind,
        related="demo-req#R-01")
    req_rel = req_root.relative_to(root).as_posix()
    record_rel = f"{req_rel}/{RECORD_FILE}"
    report_rel = "work/缺陷报告.md" if kind == "缺陷" else "work/变更请求.md"
    report_bytes = (req_root / report_rel).read_bytes()
    write_record(req_root, new_record(
        slug, "demo-req#R-01", "prod", sha256_bytes(report_bytes), report_path=report_rel))
    git(root, "add", "-A")
    git(root, "commit", "-qm", f"bootstrap {kind}")

    _make_claim_card(root, UNIT, req_rel, ["R-01"])
    if delete_impl:
        git(root, "rm", "--", IMPL)
    else:
        (root / IMPL).write_text("AC_ID = 'AC-HOME-001'\nprint(AC_ID)\n", encoding="utf-8")
        git(root, "add", "--", IMPL)

    prd_path = root / PRD
    before_prd = _git_text(root, "show", f"HEAD:{PRD}").encode("utf-8")
    with prd_path.open("a", encoding="utf-8") as handle:
        handle.write("\n回推确认：AC-HOME-001 的实现语义保持不变。\n")
    after_prd = prd_path.read_bytes()
    git(root, "add", "--", PRD)

    record = read_record(req_root)
    assert record is not None
    source = source_snapshot(root, "staged", None, artifact_paths(root, req_root, record) | {PRD})
    record["source"] = source
    record["root_cause"] = "实现与既有验收契约的映射需要独立确认。"
    record["backflow_status"] = "applied"
    record["impact"] = [{
        "id": "impact-home-001", "conflict_id": None, "kind": "ac",
        "target": f"{PRD}#L3", "evidence": f"{PRD}:3", "action": "confirmed",
    }]
    record["documents"] = [{
        "path": PRD, "action": "confirmed",
        "version": {"supported": False, "before": None, "after": None},
        "change_ref": None,
        "before_sha256": sha256_bytes(before_prd),
        "after_sha256": sha256_bytes(after_prd),
    }]
    refresh_hashes(record)
    append_history(record, "validated", source_sha256=source["sha256"],
                   document_sha256={PRD: sha256_bytes(after_prd)})
    write_record(req_root, record)

    git(root, "add", "--", PRD, record_rel)
    artifacts = artifact_paths(root, req_root, record)
    fixture = BugFixture(root, req_root, record, artifacts)
    checked = validate_backflow(root, fixture.task)
    assert checked == {
        "applicable": True, "findings": [], "cause": "",
        "artifacts": checked["artifacts"],
    }
    assert set(checked["artifacts"]) == artifacts
    return fixture


def _make_change_intake_fixture(tmp_path: Path) -> BugFixture:
    root = tmp_path
    init_repo(root)
    git(root, "config", "core.abbrev", "40")
    make_clean_project(root)
    (root / "product" / "stack-profile.yaml").write_text("origin: adopt\n", encoding="utf-8")
    make_requirement_root(root)
    (root / "src").mkdir()
    (root / IMPL).write_text("print('before')\n", encoding="utf-8")
    req_root = make_requirement_root(
        root, slug="change-75", item_ids=("R-01",), kind="需求变更",
        related="demo-req#R-01")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "bootstrap requirement change")
    _make_claim_card(root, UNIT, "product/requirements/change-75", ["R-01"])
    (root / IMPL).write_text("print('before')\n# AC-HOME-001\n", encoding="utf-8")
    git(root, "add", "--", IMPL)
    return BugFixture(root, req_root, {}, set())


def _write_review(fixture: BugFixture, *, with_anchor: bool = True,
                  anchor: dict | None = None) -> dict:
    root = fixture.root
    manifest = scope_core.build_manifest(
        root, [IMPL], base="HEAD", head="INDEX", hash_source="index")
    data = {
        "schema_version": 4, "unit": UNIT, "round": 1,
        "ok": True, "status": "PASS", "checks": [], "other": [],
        "review_scope": {
            "sha256": manifest["scope_sha256"], "files": manifest["files"],
            "hash_source": "index", "base": "HEAD", "head": "INDEX",
        },
    }
    if with_anchor:
        data["change_backflow"] = (copy.deepcopy(anchor) if anchor is not None
                                   else review_anchor(root, fixture.req_root, fixture.record))
    _write_json(fixture.review_file, data)
    return data


def _finish(fixture: BugFixture, *extra: str) -> subprocess.CompletedProcess:
    return workflow_run(fixture.root, "finish", "--unit", UNIT, "--json", *extra)


def _assert_blocked(result: subprocess.CompletedProcess, cause: str, text: str) -> None:
    assert result.returncode == (1 if cause in {
        "bug_backflow_stale", "bug_backflow_invalid", "scope_stale"
    } else 2), result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "paused"
    assert payload["paused_reason"] == cause
    assert text in result.stderr


def test_staged_source_snapshot_has_full_object_ids(tmp_path: Path) -> None:
    init_repo(tmp_path)
    path = tmp_path / IMPL
    path.parent.mkdir()
    path.write_text("before\n", encoding="utf-8")
    git(tmp_path, "add", "--", IMPL)
    git(tmp_path, "commit", "-qm", "init")
    path.write_text("after\n", encoding="utf-8")
    git(tmp_path, "add", "--", IMPL)

    source = source_snapshot(tmp_path, "staged", None, set())
    item = source["implementation_files"][0]
    assert len(item["old_oid"]) in (40, 64)
    assert len(item["new_oid"]) in (40, 64)


def test_node_atlas_bug_help_and_route_to_project_script(tmp_path: Path) -> None:
    root = tmp_path
    init_repo(root)
    make_clean_project(root)
    make_requirement_root(root)

    top = subprocess.run(["node", str(ATLAS_BIN), "--help"], cwd=root,
                         capture_output=True, text=True, timeout=60)
    assert top.returncode == 0, top.stderr
    assert "change" in top.stdout and "bug" in top.stdout and "缺陷" in top.stdout

    help_result = subprocess.run(["node", str(ATLAS_BIN), "bug", "--help"], cwd=root,
                                 capture_output=True, text=True, timeout=60)
    assert help_result.returncode == 0, help_result.stderr
    assert "canonical requirement-change/defect" in help_result.stdout
    assert "--decision-file" in help_result.stdout

    routed = subprocess.run(["node", str(ATLAS_BIN), "bug", "list", "--json"], cwd=root,
                            capture_output=True, text=True, timeout=60)
    assert routed.returncode == 0, routed.stdout + routed.stderr
    assert json.loads(routed.stdout) == {"status": "ok", "changes": [], "bugs": []}
    change_help = subprocess.run(["node", str(ATLAS_BIN), "change", "--help"], cwd=root,
                                 capture_output=True, text=True, timeout=60)
    assert change_help.returncode == 0, change_help.stderr
    assert "--auto-stage" in change_help.stdout

    old_workflow = root / ".atlas" / "scripts" / "atlas_workflow.py"
    old_workflow.parent.mkdir(parents=True)
    old_workflow.write_text("print('LOCAL_OLD_WORKFLOW')\n", encoding="utf-8")
    workflow_help = subprocess.run(["node", str(ATLAS_BIN), "workflow", "--help"], cwd=root,
                                   capture_output=True, text=True, timeout=60)
    assert workflow_help.returncode == 0, workflow_help.stderr
    assert "LOCAL_OLD_WORKFLOW" not in workflow_help.stdout

    partial_change = root / ".atlas" / "scripts" / "atlas_change.py"
    partial_change.write_text("# ATLAS_CHANGE_AUTO_V1\nprint('PARTIAL_CHANGE')\n",
                              encoding="utf-8")
    old_bug = root / ".atlas" / "scripts" / "atlas_bug.py"
    old_bug.write_text("def main():\n    pass\n", encoding="utf-8")
    change_help = subprocess.run(["node", str(ATLAS_BIN), "change", "--help"], cwd=root,
                                 capture_output=True, text=True, timeout=60)
    assert change_help.returncode == 0, change_help.stderr
    assert "PARTIAL_CHANGE" not in change_help.stdout


def test_finish_accepts_index_scope_and_exact_bug_artifact_extras(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    _write_review(fixture)

    # The reviewed set contains only implementation.  The other staged paths are
    # exact registered backflow artifacts, not blanket product/** exemptions.
    assert set(_git_text(fixture.root, "diff", "--cached", "--name-only").splitlines()) == {
        IMPL, PRD, RECORD_REL,
    }
    result = _finish(fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["requirement_closeout"]["product_fact_writeback"] == "conditional"
    assert payload["bug_backflow"]["applicable"] is True
    assert payload["bug_backflow"]["artifacts"] == sorted(BUG_ARTIFACTS)


def test_finish_accepts_unchanged_confirmed_document_and_existing_stub(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    root = fixture.root
    git(root, "checkout", "HEAD", "--", PRD)
    stub = root / ".atlas/spec/conventions/testid.md"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("# pre-existing testid stub\n", encoding="utf-8")
    git(root, "add", "--", stub.relative_to(root).as_posix())
    git(root, "commit", "-qm", "track testid stub", "--", stub.relative_to(root).as_posix())
    prd_bytes = (root / PRD).read_bytes()
    record = read_record(fixture.req_root)
    record["source"] = source_snapshot(
        root, "staged", None, artifact_paths(root, fixture.req_root, record) | {PRD})
    record["documents"][0]["before_sha256"] = sha256_bytes(prd_bytes)
    record["documents"][0]["after_sha256"] = sha256_bytes(prd_bytes)
    refresh_hashes(record)
    write_record(fixture.req_root, record)
    fixture.record = record
    git(root, "add", "--", RECORD_REL)
    checked = validate_backflow(root, fixture.task)
    assert checked["findings"] == []
    assert set(checked["artifacts"]) == BUG_ARTIFACTS
    _write_review(fixture)
    result = _finish(fixture)
    assert result.returncode == 0, result.stdout + result.stderr


def test_unregistered_review_scope_extra_blocks_finish(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    _write_review(fixture)
    extra = fixture.root / "product" / "requirements" / BUG / "record.json.bak"
    extra.write_text("not a registered artifact\n", encoding="utf-8")
    git(fixture.root, "add", "--", extra.relative_to(fixture.root).as_posix())

    artifacts = artifact_paths(fixture.root, fixture.req_root, fixture.record)
    passed, reason, cause = check_task_review_passed(
        fixture.root, UNIT, bug_artifacts=artifacts)
    assert not passed
    assert cause == "scope_stale"
    assert "record.json.bak" in reason and "实审集之外" in reason
    result = _finish(fixture)
    assert result.returncode != 0
    meta = json.loads((fixture.root / ".atlas" / "tasks" / UNIT / "task.json")
                      .read_text(encoding="utf-8"))
    assert meta["status"] == "in_progress"


@pytest.mark.parametrize("force", [False, True], ids=["normal", "force"])
@pytest.mark.parametrize("case", ["missing", "pending", "stale", "unstaged", "diverged", "range"])
def test_finish_blocks_invalid_backflow_even_with_force(
        tmp_path: Path, case: str, force: bool) -> None:
    """M253：摘除 finish 的缺陷回推门后，本组阻断用例必须变绿。"""
    fixture = _make_bug_fixture(tmp_path)
    _write_review(fixture)
    root = fixture.root
    record = read_record(fixture.req_root)
    assert record is not None

    if case == "missing":
        (root / RECORD_REL).unlink()
        cause, text = "bug_backflow_missing", "缺 record.json"
    elif case == "pending":
        record["backflow_status"] = "pending"
        refresh_hashes(record)
        write_record(fixture.req_root, record)
        git(root, "add", "--", RECORD_REL)
        cause, text = "bug_backflow_pending", "待完成"
    elif case == "stale":
        (root / IMPL).write_text("print('changed after backflow')\n", encoding="utf-8")
        git(root, "add", "--", IMPL)
        cause, text = "bug_backflow_stale", "过期"
    elif case == "unstaged":
        # Commit the artifact itself while leaving implementation staged.  The
        # artifact is then absent from the staged set but index == worktree,
        # isolating the missing-staged gate from index/worktree divergence.
        git(root, "commit", "-qm", "record and confirmed document", "--", PRD, RECORD_REL)
        cause, text = "bug_backflow_unstaged", "未暂存"
    elif case == "diverged":
        (root / IMPL).write_text("print('unstaged divergence')\n", encoding="utf-8")
        cause, text = "bug_backflow_worktree_diverged", "index/worktree 不一致"
    else:
        record["source"]["mode"] = "range"
        record["source"]["base"] = "HEAD"
        record["source"]["head"] = "HEAD"
        payload = {k: v for k, v in record["source"].items() if k != "sha256"}
        record["source"]["sha256"] = sha256_bytes(canonical_bytes(payload))
        refresh_hashes(record)
        write_record(fixture.req_root, record)
        git(root, "add", "--", RECORD_REL)
        cause, text = "bug_backflow_mode_not_finish_ready", "range 回推记录"

    with pytest.raises(FinishError) as raised:
        finish_task(root, fixture.task, force=force)
    assert getattr(raised.value, "cause", None) == cause
    assert text in str(raised.value)
    meta = json.loads((root / ".atlas" / "tasks" / UNIT / "task.json").read_text(encoding="utf-8"))
    assert meta["status"] == "in_progress"
    assert not (root / ".atlas" / "tasks" / "archive").exists()


def test_review_verify_seals_and_rechecks_bug_backflow_anchor(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    expected = review_anchor(fixture.root, fixture.req_root, fixture.record)
    review_file = fixture.review_file
    _write_review(fixture, with_anchor=False)
    seal_bug_anchor(fixture.root, UNIT, review_file.parent)

    sealed = json.loads(review_file.read_text(encoding="utf-8"))
    assert sealed["change_backflow"] == expected
    assert validate_backflow(fixture.root, fixture.task, sealed)["findings"] == []

    mutations = []
    missing = copy.deepcopy(sealed)
    del missing["change_backflow"]
    mutations.append(missing)
    for field in ("record_sha256", "artifacts", "history"):
        changed = copy.deepcopy(sealed)
        if field == "record_sha256":
            changed["change_backflow"][field] = "0" * 64
        elif field == "artifacts":
            changed["change_backflow"][field][0]["sha256"] = "0" * 64
        else:
            changed["change_backflow"][field][0]["event_sha256"] = "0" * 64
        mutations.append(changed)

    for data in mutations:
        findings = validate_backflow(fixture.root, fixture.task, data)["findings"]
        assert any("change_backflow" in finding for finding in findings), findings

    result = _finish(fixture)
    assert result.returncode == 0, result.stdout + result.stderr


def test_deleted_implementation_is_captured_in_bug_backflow_anchor(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path, delete_impl=True)
    deleted = fixture.record["source"]["implementation_files"]
    assert len(deleted) == 1 and deleted[0]["path"] == IMPL
    assert deleted[0]["new_oid"] == "0" * len(deleted[0]["old_oid"])

    anchor = review_anchor(fixture.root, fixture.req_root, fixture.record)
    assert anchor["deleted_files"] == [{"path": IMPL, "old_oid": deleted[0]["old_oid"]}]
    _write_review(fixture, with_anchor=False)
    seal_bug_anchor(fixture.root, UNIT, fixture.review_file.parent)
    sealed = json.loads(fixture.review_file.read_text(encoding="utf-8"))
    assert sealed["change_backflow"]["deleted_files"] == anchor["deleted_files"]
    assert validate_backflow(fixture.root, fixture.task, sealed)["findings"] == []

    tampered = copy.deepcopy(sealed)
    tampered["change_backflow"]["deleted_files"] = []
    assert any("删除锚" in finding for finding in validate_backflow(
        fixture.root, fixture.task, tampered)["findings"])


def test_bug_finish_requires_v4_scope_sha(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    data = _write_review(fixture)
    del data["review_scope"]["sha256"]
    _write_json(fixture.review_file, data)
    result = _finish(fixture)
    _assert_blocked(result, "scope_stale", "v4 review_scope")


def test_non_defect_finish_is_unaffected_and_needs_no_bug_anchor(tmp_path: Path) -> None:
    root = tmp_path
    init_repo(root)
    make_clean_project(root)
    (root / "src").mkdir()
    (root / IMPL).write_text("print('base')\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    (root / IMPL).write_text("print('feature')\n", encoding="utf-8")
    git(root, "add", "--", IMPL)
    _make_claim_card(root, "T-NORMAL", "", [])

    manifest = scope_core.build_manifest(
        root, [IMPL], base="HEAD", head="INDEX", hash_source="index")
    _write_json(root / "product/reviews/2026-11-26-impl-review-T-NORMAL/review.json", {
        "schema_version": 4, "ok": True, "status": "PASS", "checks": [],
        "review_scope": {
            "sha256": manifest["scope_sha256"], "files": manifest["files"],
            "hash_source": "index",
        },
    })
    task = load_tasks(root / ".atlas/tasks")[0]
    assert validate_backflow(root, task) == {
        "applicable": False, "findings": [], "cause": "", "artifacts": {},
    }
    result = workflow_run(root, "finish", "--unit", "T-NORMAL", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["bug_backflow"]["applicable"] is False


def test_verify_automatically_backflows_requirement_change(tmp_path: Path) -> None:
    fixture = _make_change_intake_fixture(tmp_path)
    args = argparse.Namespace(unit=UNIT, dry_run=False, json=True)
    task = fixture.task

    assert workflow._verify_change_backflow(args, fixture.root, task) is None

    record = read_record(fixture.req_root)
    assert record is not None
    assert record["backflow_status"] == "applied"
    assert record["report"]["path"] == "work/变更请求.md"
    assert record["root_cause"] == "验收范围调整。"
    assert record["stage"] == "prod"
    assert [item["path"] for item in record["source"]["implementation_files"]] == [IMPL]
    staged = set(_git_text(fixture.root, "diff", "--cached", "--name-only").splitlines())
    assert required_staged_paths(fixture.root, fixture.req_root, record) <= staged
    assert validate_backflow(fixture.root, task)["findings"] == []


def test_cmd_verify_runs_change_backflow_before_review(tmp_path: Path, monkeypatch) -> None:
    """M255：摘除 verify 自动回推调用后，本用例必须红。"""
    fixture = _make_change_intake_fixture(tmp_path)
    real_run = subprocess.run
    reviewed = []

    def fake_review(argv, *args, **kwargs):
        if any("atlas_review.py" in str(item) for item in argv):
            reviewed.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(workflow.subprocess, "run", fake_review)
    monkeypatch.setattr(workflow, "check_task_review_passed",
                        lambda root, unit, **kwargs: (True, str(root / "product/reviews/fake"), ""))
    monkeypatch.setattr(workflow, "create_workflow_origin", lambda *args, **kwargs: None)
    args = argparse.Namespace(unit=UNIT, dry_run=False, json=True, check_cmd=None,
                              resolves=None, round=None, staged=True)
    assert workflow.cmd_verify(args, fixture.root) == 0
    assert reviewed and read_record(fixture.req_root)["backflow_status"] == "applied"


def test_verify_pending_backflow_is_uncharged(tmp_path: Path, monkeypatch,
                                               capsys) -> None:
    fixture = _make_change_intake_fixture(tmp_path)
    report = fixture.req_root / "work" / "变更请求.md"
    write_record(fixture.req_root, new_record(
        "change-75", "demo-req#R-01", "prod", sha256_bytes(report.read_bytes()),
        report_path="work/变更请求.md"))
    git(fixture.root, "add", "--", "product/requirements/change-75/record.json")
    monkeypatch.setattr(workflow, "_run_change_backflow",
                        lambda root, task: (0, {"status": "ok"}, ""))
    args = argparse.Namespace(unit=UNIT, dry_run=False, json=True)

    assert workflow._verify_change_backflow(args, fixture.root, fixture.task) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["paused_reason"] == "bug_backflow_pending"
    rows, bad = load_attempts(fixture.root / ".atlas" / "tasks", UNIT)
    assert bad == 0 and rows[-1]["cause"] == "bug_backflow_pending"
    assert rows[-1]["charged"] is False


def test_finish_auto_backflow_requires_fresh_review(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path, kind="需求变更", slug="change-75")
    _write_review(fixture)
    old_review = json.loads(fixture.review_file.read_text(encoding="utf-8"))
    git(fixture.root, "commit", "-qm", "implementation", "--", IMPL)
    (fixture.root / IMPL).write_text(
        "AC_ID = 'AC-HOME-001'\nprint(AC_ID)\n# AC-HOME-001\n",
        encoding="utf-8")
    git(fixture.root, "add", "--", IMPL)
    args = argparse.Namespace(unit=UNIT, dry_run=False, json=True)

    rc = workflow._finish_change_backflow(args, fixture.root, fixture.task)

    assert rc == 2
    record = read_record(fixture.req_root)
    assert record is not None and record["backflow_status"] == "applied"
    assert record["source"]["sha256"] != fixture.record["source"]["sha256"]
    assert validate_backflow(fixture.root, fixture.task, old_review)["findings"]
    rows, _ = load_attempts(fixture.root / ".atlas" / "tasks", UNIT)
    assert rows[-1]["cause"] == "change_backflow_reverify_required"
    assert rows[-1]["charged"] is False


def test_legacy_anchor_is_readable_and_ambiguous_anchors_fail(tmp_path: Path) -> None:
    fixture = _make_bug_fixture(tmp_path)
    data = _write_review(fixture, with_anchor=False)
    data["bug_backflow"] = review_anchor(
        fixture.root, fixture.req_root, fixture.record, legacy=True)
    assert validate_backflow(fixture.root, fixture.task, data)["findings"] == []

    ambiguous = copy.deepcopy(data)
    ambiguous["change_backflow"] = review_anchor(
        fixture.root, fixture.req_root, fixture.record)
    assert any("同时含" in finding for finding in validate_backflow(
        fixture.root, fixture.task, ambiguous)["findings"])

    unversioned = _write_review(fixture)
    del unversioned["change_backflow"]["anchor_version"]
    assert any("anchor_version=2" in finding for finding in validate_backflow(
        fixture.root, fixture.task, unversioned)["findings"])


def test_legacy_source_fingerprint_and_anchor_cannot_hide_root_change(tmp_path: Path) -> None:
    """M256：放宽 legacy 锚的 canonical 产物守卫后，本用例必须红。"""
    fixture = _make_bug_fixture(tmp_path)
    root = fixture.root
    req_rel = fixture.req_root.relative_to(root).as_posix()
    requirement_rel = f"{req_rel}/requirement.md"
    requirement = root / requirement_rel
    requirement.write_text(requirement.read_text(encoding="utf-8") + "\nchanged root\n",
                           encoding="utf-8")
    git(root, "add", "--", requirement_rel)
    record = read_record(fixture.req_root)
    record["source"] = source_snapshot(root, "staged", None, {RECORD_REL, PRD})
    refresh_hashes(record)
    write_record(fixture.req_root, record)
    git(root, "add", "--", RECORD_REL)
    fixture.record = record

    assert validate_backflow(root, fixture.task)["findings"] == []
    data = _write_review(fixture, with_anchor=False)
    data["bug_backflow"] = review_anchor(root, fixture.req_root, record, legacy=True)
    data["review_scope"]["files"].append({"path": requirement_rel})
    findings = validate_backflow(root, fixture.task, data)["findings"]
    assert any("legacy bug_backflow 未覆盖 canonical 产物" in finding for finding in findings)
