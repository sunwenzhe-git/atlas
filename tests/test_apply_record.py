#!/usr/bin/env python3
"""封条（apply record）C 批夹具：upstream / 路径宇宙 / 状态机 / 续签链 / 写侧。"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
SEAL_SCRIPT = PKG / "scripts" / "atlas_apply_seal.py"
SOLUTION_SCRIPT = PKG / "scripts" / "atlas_solution.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_c_record", "_support/solution.py")
seal = _load("_s_record", "_support/solution_seal.py")
validator = _load("_v_record", "validators/validate_apply_record.py")

CASE_ID = "E2E-LOGIN-001"
SEAL_REL = "product/reviews/apply/web/T-001.seal.json"
CARD = ".trellis/tasks/01-x/prd.md"


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=check)


def commit(root: Path, *paths: str, message: str = "c") -> str:
    git(root, "add", *paths)
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def commit_all(root: Path, message: str = "c") -> str:
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def last_seal_commit(root: Path, path: str = SEAL_REL) -> str:
    return git(root, "log", "-1", "--format=%H", "--", path).stdout.strip()


def read_doc(root: Path, path: str = SEAL_REL) -> dict:
    return json.loads((root / path).read_text(encoding="utf-8"))


def write_doc(root: Path, doc: dict, path: str = SEAL_REL) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def init_repo(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    git(tmp, "init", "-q")
    (tmp / ".atlas").mkdir()
    (tmp / ".atlas" / "package.json").write_text('{"version": "0.4.0"}',
                                                 encoding="utf-8")
    web = tmp / "web"
    web.mkdir()
    git(web, "init", "-q")
    (web / "a.txt").write_text("a\n", encoding="utf-8")
    git(web, "add", "-A")
    git(web, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    core.init_solution(
        tmp, "demo", [("web", "web", "frontend")], install=False,
        requirements=[{"id": "R1", "member": "web", "acs": ["AC-SOLUTION-001"],
                       "case_ids": [CASE_ID], "task_slug": "r1",
                       "scope": ["AC-SOLUTION-001"]}])
    (tmp / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    (tmp / "product" / "e2e" / "cases" / f"{CASE_ID}.md").write_text(
        "## E2E-LOGIN-001\n\n```atlas-case\nid: E2E-LOGIN-001\n```\n",
        encoding="utf-8")
    (tmp / "product" / "e2e" / "e2e-index.md").write_text(
        "# index\n\n## E2E-LOGIN-001\n\n| ID | 需求 |\n|---|---|\n"
        "| E2E-LOGIN-001 | R1 |\n", encoding="utf-8")
    card = tmp / "web" / CARD
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("atlas-acceptance: AC-SOLUTION-001\n", encoding="utf-8")
    (card.parent / "atlas-apply.md").write_text("# apply\n", encoding="utf-8")
    # 卡必须在**成员仓**里被跟踪（父仓判 `card_untracked` 时会 `git -C web ls-files`）
    git(tmp / "web", "add", "-A")
    git(tmp / "web", "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "card")
    commit(tmp, ".", message="assets")
    data = core.load_manifest(tmp)
    payload = seal.build_seal_payload(
        tmp, data, SEAL_REL, assets_root="product", kind="binding",
        card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID], owner="@a")
    write_doc(tmp, payload)
    commit(tmp, SEAL_REL, message="seal")
    core.write_lock(tmp, core.load_manifest(tmp), require_clean=True)
    commit(tmp, core.LOCK_NAME, message="lock")
    return tmp


def renew(root: Path, **overrides) -> dict:
    return renew_path(root, SEAL_REL, **overrides)


def renew_path(root: Path, path: str, **overrides) -> dict:
    payload = seal.build_seal_payload(
        root, core.load_manifest(root), path, assets_root="product",
        kind="binding", card_path=CARD,
        acceptance_acs=["AC-SOLUTION-001"], e2e_status="ready",
        case_ids=[CASE_ID], owner="@a")
    payload.update(overrides)
    write_doc(root, payload, path)
    commit(root, path, message="renew")
    return payload


def renew_mutate(root: Path, mutate) -> dict:
    payload = seal.build_seal_payload(
        root, core.load_manifest(root), SEAL_REL, assets_root="product",
        kind="binding", card_path=CARD,
        acceptance_acs=["AC-SOLUTION-001"], e2e_status="ready",
        case_ids=[CASE_ID], owner="@a")
    mutate(payload)
    write_doc(root, payload)
    commit(root, SEAL_REL, message="renew mutated")
    return payload


def findings(root: Path) -> list[dict]:
    data = core.load_manifest(root)
    lock = core.read_lock(root)
    roots, _ = core.historical_roots(root)
    return seal.analyze(root, data, lock, roots,
                        bind_from=core.SEAL_UPSTREAM_BIND_FROM)


def codes(root: Path) -> list[str]:
    return [item["code"] for item in findings(root)]


def _error_codes(root: Path) -> list[str]:
    return [item["code"] for item in findings(root)
            if item["severity"] == "error"]


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


def test_c_first_sign_is_clean(repo: Path) -> None:
    assert codes(repo) == []


def test_c_renewal_appends_chain(repo: Path) -> None:
    first = last_seal_commit(repo)
    payload = renew(repo)
    assert payload["renewal_seq"] == 2
    assert payload["previous_seal_commit"] == first
    assert payload["previous_seal_sha256"]
    assert codes(repo) == []


def test_c_renewal_seq_mismatch_is_broken(repo: Path) -> None:
    renew(repo, renewal_seq=5)
    assert "renewal_chain_broken" in codes(repo)


def test_c_previous_seal_commit_must_be_last_event(repo: Path) -> None:
    renew_mutate(repo, lambda p: p.update(previous_seal_commit="0" * 40))
    assert "renewal_chain_broken" in codes(repo)


def test_c_upstream_stale_after_bytes_change(repo: Path) -> None:
    (repo / "product" / "e2e" / "e2e-index.md").write_text(
        "# index\n\n| ID | 需求 |\n|---|---|\n| E2E-LOGIN-001 | R1 |\n| E2E-X-002 | R1 |\n",
        encoding="utf-8")
    commit(repo, "product/e2e/e2e-index.md", message="upstream")
    assert "upstream_stale" in codes(repo)


def test_c_upstream_missing_after_delete(repo: Path) -> None:
    (repo / "product" / "stack-profile.yaml").unlink()
    commit(repo, "product/stack-profile.yaml", message="delete upstream")
    assert "upstream_missing" in codes(repo)


def test_c_upstream_role_unknown(repo: Path) -> None:
    renew_mutate(repo, lambda p: p["upstream"].append(
        {"role": "bogus", "path": "x", "sha256": "0" * 64}))
    assert "upstream_role_unknown" in codes(repo)


def test_c_upstream_path_unresolved(repo: Path) -> None:
    renew_mutate(repo, lambda p: p["upstream"][0].update(path="not/manifest.yaml"))
    assert "upstream_path_unresolved" in codes(repo)


def test_c_seal_upstream_unbound_window_and_frozen(tmp_path: Path) -> None:
    """期内 WARN；过「D 批首版 + 90d」转 error；frozen 永久 WARN（§2.5）。"""
    from datetime import date
    root = init_repo(tmp_path)
    doc = read_doc(root)
    doc["upstream"] = [u for u in doc["upstream"] if u["role"] != "stack-profile"]
    write_doc(root, doc)
    commit(root, SEAL_REL, message="unbound")
    data = core.load_manifest(root)
    warn = seal.upstream_findings(root, data, doc, SEAL_REL, "product",
                                  bind_from=None,
                                  today=date(2030, 1, 1))
    assert [f["severity"] for f in warn if f["code"] == "seal_upstream_unbound"] == ["warning"]
    late = seal.upstream_findings(root, data, doc, SEAL_REL, "product",
                                  bind_from="2026-01-01",
                                  today=date(2030, 1, 1))
    assert "error" in [f["severity"] for f in late if f["code"] == "seal_upstream_unbound"]
    frozen_doc = {**doc, "__state": "frozen"}
    frozen = seal.upstream_findings(root, data, frozen_doc, SEAL_REL, "product",
                                    bind_from="2026-01-01",
                                    today=date(2030, 1, 1))
    assert [f["severity"] for f in frozen
            if f["code"] == "seal_upstream_unbound"] == ["warning"]


def test_c_history_reset_when_delete_then_recreate(repo: Path) -> None:
    doc = read_doc(repo)
    git(repo, "rm", "-q", SEAL_REL)
    commit_all(repo, message="delete")
    write_doc(repo, doc)
    commit_all(repo, message="recreate")
    assert "seal_history_reset" in codes(repo)


def test_c_merge_conflict_manual_bytes(repo: Path) -> None:
    git(repo, "checkout", "-qb", "side")
    side = read_doc(repo)
    side["owner"] = "@side"
    write_doc(repo, side)
    commit(repo, SEAL_REL, message="side")
    git(repo, "checkout", "-q", "-")
    main = read_doc(repo)
    main["owner"] = "@main"
    write_doc(repo, main)
    commit(repo, SEAL_REL, message="main")
    git(repo, "merge", "--no-commit", "side", check=False)
    merged = dict(main)
    merged["owner"] = "@merged"
    write_doc(repo, merged)
    commit_all(repo, message="merge manual")
    assert "seal_merge_conflict" in codes(repo)


def test_c_worktree_dirty_blocks_chain(repo: Path) -> None:
    doc = read_doc(repo)
    doc["owner"] = "@dirty"
    write_doc(repo, doc)
    assert "seal_worktree_dirty" in codes(repo)


def test_c_signed_at_must_be_canonical(repo: Path) -> None:
    renew_mutate(repo, lambda p: p.update(signed_at="2026-01-01 00:00:00"))
    assert "signed_at_not_canonical" in codes(repo)


def test_c_freeze_then_modify(repo: Path) -> None:
    head = last_seal_commit(repo)
    result = core.freeze_seal(repo, SEAL_REL, head)
    assert result["state"] == "frozen"
    commit(repo, core.LOCK_NAME, message="freeze")
    assert codes(repo) == []
    payload = read_doc(repo)
    payload["owner"] = "@changed"
    write_doc(repo, payload)
    commit(repo, SEAL_REL, message="modify frozen")
    assert "seal_frozen_modified" in codes(repo)


def test_c_multi_seal_requires_explicit_choice(repo: Path) -> None:
    other = "product/reviews/apply/web/T-002.seal.json"
    payload = seal.build_seal_payload(
        repo, core.load_manifest(repo), other, assets_root="product",
        kind="binding", e2e_status="ready", case_ids=[CASE_ID])
    write_doc(repo, payload, other)
    commit(repo, other, message="second seal")
    with pytest.raises(core.SolutionError, match="多枚封条"):
        core.write_lock(repo, core.load_manifest(repo), require_clean=True)
    core.write_lock(repo, core.load_manifest(repo), require_clean=True,
                    seal=other)
    anchors = core.read_lock(repo)["seal_anchors"]
    assert {SEAL_REL, other} <= set(anchors)


def test_c_assets_root_history_rewritten_is_fail(repo: Path) -> None:
    lock = core.read_lock(repo)
    lock["assets_root_history"] = [lock["assets_root_history"][-1]]
    lock["assets_root_history"][0]["root"] = "product"
    lock["layout_assets_root"] = "product"
    # 先制造一个历史根，再从当前锁删掉 ⇒ 历史版本有、当前锁无
    extra = dict(lock["assets_root_history"][0])
    extra["root"] = "oldroot"
    first = dict(lock)
    first["assets_root_history"] = [extra, lock["assets_root_history"][0]]
    (repo / core.LOCK_NAME).write_text(
        json.dumps(first, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="history with oldroot")
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="drop oldroot")
    report = core.check_solution(repo)
    assert any(e["code"] == "assets_root_history_rewritten"
               for e in report["errors"])


def test_c_unsupported_seal_key(repo: Path) -> None:
    lock = core.read_lock(repo)
    lock["seal_anchors"]["other/reviews/apply/web/T-009.seal.json"] = \
        dict(lock["seal_anchors"][SEAL_REL])
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="unsupported key")
    assert "seal_path_unsupported" in codes(repo)


def test_c_reanchor_writer_advances_epoch(tmp_path: Path) -> None:
    """S-18/S-21：重写历史后 fresh clone 先 lock --update（红），再 reanchor。"""
    original = init_repo(tmp_path / "orig")
    renew(original)                     # seq=2, N=2
    old_a = git(original, "log", "--diff-filter=A", "--format=%H",
                "--reverse", "--", SEAL_REL).stdout.split()[0]
    rewritten = tmp_path / "rewritten"
    subprocess.run(["git", "clone", "-q", str(original), str(rewritten)],
                   check=True)
    git(rewritten, "checkout", "-q", "--orphan", "rewritten")
    git(rewritten, "add", "-A")
    git(rewritten, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "rewritten root")
    git(rewritten, "branch", "-M", "main")
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", "file://" + str(rewritten), str(fresh)],
                   check=True)
    assert git(fresh, "cat-file", "-e", old_a, check=False).returncode != 0
    card = fresh / "web" / CARD
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("atlas-acceptance: AC-SOLUTION-001\n", encoding="utf-8")
    (card.parent / "atlas-apply.md").write_text("# apply\n", encoding="utf-8")
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="lock after rewrite")
    result = core.reanchor_seal(fresh, SEAL_REL, "REVIEW-20261112-01", old_a)
    assert result["renewal_seq"] == 3
    assert result["reanchor"]["from_a"] == old_a
    doc = read_doc(fresh)
    assert doc["previous_seal_sha256"] is None
    assert doc["previous_seal_commit"] == old_a
    assert doc["reanchor"]["base_n"] == 1
    lock_doc = core.read_lock(fresh)
    assert lock_doc["seal_anchors"][SEAL_REL]["exemption_start_history"]
    commit(fresh, SEAL_REL, core.LOCK_NAME, message="reanchor R")
    record = git(fresh, "rev-parse", "HEAD").stdout.strip()
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="R2")
    anchor = core.read_lock(fresh)["seal_anchors"][SEAL_REL]
    assert anchor["epoch_origin"] == record
    assert anchor["anchor_review"] == "REVIEW-20261112-01"
    # fresh clone 里成员树未 checkout：卡判据只出 WARN，错误面必须为空
    assert _error_codes(fresh) == []
    # B4：reanchor 后的正常续签必须仍绿
    renew(fresh)
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="renew after reanchor")
    assert _error_codes(fresh) == []
    # B2：删 reanchor + 回退 renewal_seq 必须红（epoch_origin=R0 守卫）
    doc = read_doc(fresh)
    doc.pop("reanchor")
    doc["renewal_seq"] = seal.seal_history(fresh, SEAL_REL)["N"] + 1
    write_doc(fresh, doc)
    commit(fresh, SEAL_REL, message="tamper reanchor")
    assert "reanchor_record_missing" in codes(fresh)


def test_c_reanchor_rejects_reachable_from_a(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(core.SolutionError, match="reanchor_not_allowed"):
        core.reanchor_seal(repo, SEAL_REL, "REVIEW-20261112-01", head)


def test_c_reanchor_requires_synced_anchor(repo: Path) -> None:
    renew(repo)
    with pytest.raises(core.SolutionError, match="seal_anchor_stale"):
        core.reanchor_seal(repo, SEAL_REL, "REVIEW-20261112-01", "a" * 40)


def test_c_moved_from_first_sign(repo: Path) -> None:
    old = SEAL_REL
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    old_anchor = core.read_lock(repo)["seal_anchors"][old]
    doc = read_doc(repo)
    moved = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID], moved_from={"path": old})
    assert moved["renewal_seq"] == 1
    assert moved["previous_seal_commit"] is None
    assert moved["signed_at"] == doc["signed_at"]
    assert moved["moved_from"]["sha256"]
    write_doc(repo, moved, new)
    git(repo, "rm", "-q", old)
    commit_all(repo, message="move seal")
    core.write_lock(repo, core.load_manifest(repo), require_clean=True,
                    seal=new)
    commit(repo, core.LOCK_NAME, message="lock moved")
    anchors = core.read_lock(repo)["seal_anchors"]
    assert anchors[old]["state"] == "retired"
    assert anchors[old]["moved_to"] == new
    assert anchors[new]["state"] == "active"
    # B5：新键继承链首豁免起点，不得重置窗口
    assert anchors[new]["exemption_start_origin"] == \
        old_anchor["exemption_start_origin"]
    assert anchors[new]["exemption_start_history"] == \
        old_anchor["exemption_start_history"]
    assert anchors[new]["first_seen_origin"] == old_anchor["first_seen_origin"]
    assert codes(repo) == []
    # B4：迁出后的正常续签必须继续携带 moved_from 且仍绿
    renew_path(repo, new)
    core.write_lock(repo, core.load_manifest(repo), require_clean=True,
                    seal=new)
    commit(repo, core.LOCK_NAME, message="renew moved")
    assert "moved_from" in read_doc(repo, new)
    assert codes(repo) == []


def test_c_moved_from_sha_mismatch(repo: Path) -> None:
    old = SEAL_REL
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    moved = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", e2e_status="ready", case_ids=[CASE_ID],
        moved_from={"path": old, "sha256": "0" * 64})
    write_doc(repo, moved, new)
    git(repo, "rm", "-q", old)
    commit_all(repo, message="move seal")
    core.write_lock(repo, core.load_manifest(repo), require_clean=True,
                    seal=new)
    commit(repo, core.LOCK_NAME, message="lock moved")
    assert "seal_path_history_lost" in codes(repo)


def test_c_retired_write_is_detected(repo: Path) -> None:
    old = SEAL_REL
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    moved = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", e2e_status="ready", case_ids=[CASE_ID],
        moved_from={"path": old})
    write_doc(repo, moved, new)
    git(repo, "rm", "-q", old)
    commit_all(repo, message="move seal")
    core.write_lock(repo, core.load_manifest(repo), require_clean=True,
                    seal=new)
    commit(repo, core.LOCK_NAME, message="lock moved")
    doc = read_doc(repo, new)
    doc["owner"] = "@late"
    write_doc(repo, doc, old)
    commit_all(repo, message="write old retired path")
    assert "seal_path_retired_write" in codes(repo)


def test_c_validator_cli_reports_and_n_a(repo: Path) -> None:
    errors, warnings, paths, count, _ = validator.collect_errors(repo)
    assert count == 1 and not errors
    empty = repo / "empty"
    empty.mkdir()
    assert validator.collect_errors(empty)[3] == 0


def test_c_apply_seal_cli_writes_seconds_signature(repo: Path) -> None:
    new = "product/reviews/apply/web/T-003.seal.json"
    before = datetime.now(timezone.utc)
    res = subprocess.run(
        [sys.executable, str(SEAL_SCRIPT), "--root", str(repo), "--seal", new,
         "--acceptance-acs", "AC-SOLUTION-001", "--e2e-status", "ready",
         "--case", CASE_ID, "--json"],
        capture_output=True, text=True)
    after = datetime.now(timezone.utc)
    assert res.returncode == 0, res.stderr
    doc = json.loads((repo / new).read_text(encoding="utf-8"))
    assert seal.SIGNED_AT_RE.match(doc["signed_at"])
    signed = datetime.strptime(doc["signed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    assert before - timedelta(seconds=5) <= signed <= after + timedelta(seconds=5)
    assert doc["renewal_seq"] == 1
    assert {u["role"] for u in doc["upstream"]} >= {"manifest", "prd-global"}


def test_c_seal_cli_exit_codes(repo: Path) -> None:
    head = last_seal_commit(repo)
    res = subprocess.run(
        [sys.executable, str(SOLUTION_SCRIPT), "--root", str(repo), "seal",
         "freeze", "--at", "0" * 40], capture_output=True, text=True)
    assert res.returncode == 2
    res = subprocess.run(
        [sys.executable, str(SOLUTION_SCRIPT), "--root", str(repo), "seal",
         "freeze", "--seal", SEAL_REL, "--at", head, "--json"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _validator_codes(root: Path) -> list[str]:
    errors, _, _, _, _ = validator.collect_errors(root)
    return [e["code"] for e in errors]


def test_b1_deleted_anchor_key_fails_at_delivery_gate(repo: Path) -> None:
    lock = core.read_lock(repo)
    lock["seal_anchors"] = {}
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="drop anchor key")
    assert "seal_anchor_path_unmapped" in _validator_codes(repo)
    res = subprocess.run(
        [sys.executable, str(PKG / "validators" / "validate_apply_record.py"),
         "--root", str(repo)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "seal_anchor_path_unmapped" in res.stdout


def test_b1_missing_lock_with_seal_is_not_n_a(repo: Path) -> None:
    (repo / core.LOCK_NAME).unlink()
    commit_all(repo, message="drop lock")
    errors, _, paths, count, _ = validator.collect_errors(repo)
    assert count == 1 and paths
    assert "seal_anchor_path_unmapped" in [e["code"] for e in errors]


def test_i3_missing_apply_record_fails(repo: Path) -> None:
    (repo / "web" / CARD).parent.joinpath("atlas-apply.md").unlink()
    assert "apply_record_missing" in _validator_codes(repo)


def test_k14_missing_card_file_fails(repo: Path) -> None:
    """父仓：封条在、卡缺失 ⇒ `card_absent` FAIL（成员侧同一形态只 WARN）。"""
    (repo / "web" / CARD).unlink()
    assert "card_absent" in _validator_codes(repo)


def test_i2_e2e_changed_cases_are_diffed(repo: Path) -> None:
    case_file = repo / "product" / "e2e" / "cases" / f"{CASE_ID}.md"
    case_file.write_text(
        "## E2E-LOGIN-001\n\n```atlas-case\nid: E2E-LOGIN-001\nstep: 2\n```\n",
        encoding="utf-8")
    commit(repo, f"product/e2e/cases/{CASE_ID}.md", message="case change")
    payload = renew(repo)
    assert payload["e2e"]["changed_case_ids"] == [CASE_ID]
    assert payload["e2e"]["previous_cases"][0]["id"] == CASE_ID
    assert payload["e2e"]["previous_cases"][0]["sha256"]
    core.write_lock(repo, core.load_manifest(repo), require_clean=True)
    commit(repo, core.LOCK_NAME, message="lock")
    assert codes(repo) == []


def test_i2_changed_case_ids_tamper_fails(repo: Path) -> None:
    renew_mutate(repo, lambda p: p["e2e"].update(changed_case_ids=["bogus"]))
    assert "seal_e2e_changed_case_ids_mismatch" in codes(repo)


def test_i2_ready_requires_case_block_in_index(repo: Path) -> None:
    (repo / "product" / "e2e" / "e2e-index.md").write_text(
        "# index\n", encoding="utf-8")
    commit(repo, "product/e2e/e2e-index.md", message="drop block")
    assert "seal_e2e_case_missing" in codes(repo)


def test_i1_frozen_after_delete_is_history_reset(repo: Path) -> None:
    doc = read_doc(repo)
    git(repo, "rm", "-q", SEAL_REL)
    commit_all(repo, message="delete")
    write_doc(repo, doc)
    commit_all(repo, message="recreate")
    head = last_seal_commit(repo)
    core.freeze_seal(repo, SEAL_REL, head)
    commit(repo, core.LOCK_NAME, message="freeze after reset")
    assert "seal_history_reset" in codes(repo)


def test_i7_origin_rewritten_is_detected(repo: Path) -> None:
    lock = core.read_lock(repo)
    anchor = lock["seal_anchors"][SEAL_REL]
    anchor["exemption_start_origin"] = "2020-01-01T00:00:00Z"
    anchor["exemption_started_at"] = anchor["exemption_start_origin"]
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="rewrite origin")
    assert "exemption_start_origin_rewritten" in codes(repo)


def test_r4_archived_card_is_not_card_absent(repo: Path) -> None:
    """卡归档后封条 `card.path` 不改写：双解析到 archive 仍须绿；两处都缺才红。"""
    member = repo / "web"
    archived = member / ".trellis/tasks/archive/2026-11/01-x/prd.md"
    archived.parent.mkdir(parents=True)
    card = member / CARD
    card.rename(archived)
    (card.parent / "atlas-apply.md").rename(archived.parent / "atlas-apply.md")
    git(member, "add", "-A")
    git(member, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "archive card")
    assert codes(repo) == []
    archived.unlink()
    git(member, "add", "-A")
    git(member, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "drop archived card")
    assert "card_absent" in codes(repo)


def test_r4_allow_card_absent_downgrades_with_record(repo: Path) -> None:
    """`--allow-card-absent`：默认 FAIL；开开关降 WARN 并写入 `downgrades[]`。"""
    (repo / "web" / CARD).unlink()
    errors, _, _, _, downgrades = validator.collect_errors(repo)
    assert "card_absent" in [e["code"] for e in errors]
    assert downgrades == []
    errors, warnings, _, _, downgrades = validator.collect_errors(
        repo, allow_card_absent=True)
    assert "card_absent" not in [e["code"] for e in errors]
    assert "card_absent" in [w["code"] for w in warnings]
    assert downgrades == [{
        "code": "card_absent",
        "flag": "--allow-card-absent",
        "scope": "card_absent",
        "path": CARD,
        "detail": downgrades[0]["detail"],
    }]
    res = subprocess.run(
        [sys.executable, str(PKG / "validators" / "validate_apply_record.py"),
         "--root", str(repo), "--allow-card-absent", "--json"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stdout
    payload = json.loads(
        res.stdout[res.stdout.index("{"):res.stdout.rindex("}") + 1])
    assert payload["downgrades"][0]["code"] == "card_absent"
    assert payload["ok"] is True


def test_r4_squashed_external_anchor_is_chain_unverifiable(tmp_path: Path) -> None:
    """锁与封条压进同一个 orphan 根并同改 origin/started ⇒ 锚自指，必须 fail-closed。"""
    root = init_repo(tmp_path)
    git(root, "checkout", "-q", "--orphan", "squashed")
    doc = read_doc(root)
    doc["signed_at"] = "2020-01-01T00:00:00Z"
    doc["first_seen_at"] = "2020-01-01T00:00:00Z"
    write_doc(root, doc)
    lock = core.read_lock(root)
    anchor = lock["seal_anchors"][SEAL_REL]
    anchor["exemption_start_origin"] = "2020-01-01T00:00:00Z"
    anchor["exemption_started_at"] = "2020-01-01T00:00:00Z"
    anchor["first_seen_origin"] = "2020-01-01T00:00:00Z"
    (root / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit_all(root, message="squashed root")
    assert "chain_unverifiable" in codes(root)


def _single_commit_first_sign(tmp_path: Path, *, repoint: bool) -> Path:
    """单提交仓：封条与锁同在一个根提交，`epoch_origin == L[0]`（首签基线）。"""
    root = init_repo(tmp_path / "orig")
    head_tree = git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    r0 = subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b", "-c", "user.name=a",
         "commit-tree", head_tree, "-m", "imported root"],
        check=True, capture_output=True, text=True).stdout.strip()
    git(root, "reset", "-q", "--hard", r0)
    lock = core.read_lock(root)
    seal_doc = read_doc(root)
    anchor = lock["seal_anchors"][SEAL_REL]
    anchor["epoch_origin"] = r0
    anchor["epoch_origin_history"] = [r0]
    anchor["renewal_seq"] = 1
    anchor["n"] = 1
    anchor["exemption_start_origin"] = seal_doc["signed_at"]
    anchor["exemption_started_at"] = seal_doc["signed_at"]
    if repoint:
        # v49/项 3 认可的「重指痕迹」之一：`anchor_review != null`（不再是豁免链，
        # 链长度不再算重指痕迹）。
        anchor["anchor_review"] = "REVIEW-20261112-01"
    (root / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(root, core.LOCK_NAME, message="single commit lock")
    return root


def test_r4_single_commit_first_sign_is_tofu_green(tmp_path: Path) -> None:
    """TOFU：单提交仓首签、无重指痕迹 ⇒ 锚同源是事实，不判红。"""
    root = _single_commit_first_sign(tmp_path, repoint=False)
    assert codes(root) == []


def test_r4_single_commit_with_repoint_is_chain_unverifiable(
        tmp_path: Path) -> None:
    """单提交仓 + 重指痕迹 ⇒ 锚自指不再可信，必须 fail-closed。"""
    root = _single_commit_first_sign(tmp_path, repoint=True)
    assert "chain_unverifiable" in codes(root)


def test_r4_pure_rename_with_reason_is_green(tmp_path: Path) -> None:
    """纯改名带 `--reason`：`reasons` 不计载荷，不得判 `seal_move_payload_mismatch`。"""
    root = init_repo(tmp_path)
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    _move_seal(root, new, reasons=["renamed"])
    assert codes(root) == []


def test_r4_two_missing_cases_are_both_reported(tmp_path: Path) -> None:
    """同码同路径的并列成因（两条用例同时缺失）不得被去重压成一条。"""
    root = init_repo(tmp_path)
    renew_mutate(root, lambda p: p["e2e"].update(cases=[
        {"id": CASE_ID, "sha256": "0" * 64},
        {"id": "E2E-MISSING-002", "sha256": "1" * 64},
    ]))
    core.write_lock(root, core.load_manifest(root), require_clean=True)
    commit(root, core.LOCK_NAME, message="lock")
    (root / "product" / "e2e" / "cases" / f"{CASE_ID}.md").unlink()
    commit_all(root, message="drop case")
    codes_ = _validator_codes(root)
    assert codes_.count("seal_e2e_case_missing") == 2


def test_r4_parent_reports_untracked_card(repo: Path) -> None:
    """父仓判跟踪：卡在盘上但成员仓未跟踪 ⇒ `card_untracked` FAIL。"""
    member = repo / "web"
    git(member, "rm", "-q", "--cached", CARD)
    assert (member / CARD).is_file()
    assert "card_untracked" in codes(repo)


def test_r4_non_anchor_path_cannot_bypass_chain_checks(repo: Path) -> None:
    """未进 `by_path` 的封条仍由 `analyze` 的 unmapped 支报红，不绕过 chain 判据。"""
    lock = core.read_lock(repo)
    lock["seal_anchors"] = {}
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="drop anchors")
    errors, _, paths, count, _ = validator.collect_errors(repo)
    assert count == 1 and paths
    assert "seal_anchor_path_unmapped" in [e["code"] for e in errors]


def _rewrite_keeping_old_path_tree(tmp_path: Path) -> tuple[Path, str]:
    """`commit-tree` 重写：新根树同时保住**旧路径**封条与迁移后封条，旧提交不进克隆。

    这样旧 `epoch_origin` 对象在 fresh clone 里不存在（`seal reanchor` 允许），
    而 `moved_from` 需要的旧路径 `L_pre[-1]` 仍可读——即「move 与 reanchor 组合」。
    """
    original = init_repo(tmp_path / "orig")
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    _move_seal(original, new, reasons=["renamed"])
    from_a = core.read_lock(original)["seal_anchors"][new]["epoch_origin"]
    old_blob = git(original, "rev-parse", f"HEAD~2:{SEAL_REL}").stdout.strip()
    base_tree = git(original, "rev-parse", "HEAD^{tree}").stdout.strip()
    env = dict(os.environ, GIT_INDEX_FILE=str(tmp_path / "rewritten.index"))
    subprocess.run(["git", "-C", str(original), "read-tree", base_tree],
                   check=True, env=env)
    subprocess.run(["git", "-C", str(original), "update-index", "--add",
                    "--cacheinfo", f"100644,{old_blob},{SEAL_REL}"],
                   check=True, env=env)
    tree = subprocess.run(["git", "-C", str(original), "write-tree"],
                          check=True, capture_output=True, text=True,
                          env=env).stdout.strip()
    root = subprocess.run(
        ["git", "-C", str(original), "-c", "user.email=a@b",
         "-c", "user.name=a", "commit-tree", tree, "-m", "rewritten root"],
        check=True, capture_output=True, text=True).stdout.strip()
    git(original, "branch", "-f", "rewritten", root)
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", "--single-branch", "--branch",
                    "rewritten", "file://" + str(original), str(fresh)],
                   check=True)
    assert git(fresh, "cat-file", "-e", from_a, check=False).returncode != 0
    return fresh, new


def test_r4_v49_moved_from_with_own_reanchor_is_green(tmp_path: Path) -> None:
    """v49/项 1：新封条可同时带 `moved_from` 与**自己的** `reanchor` ⇒ 绿。

    构造 = move → 在新路径上 reanchor（旧路径树用 `commit-tree` 保住，使
    `moved_from` 依赖的 `L_pre[-1]` 仍可读）。旧（retired）键按 v49/项 2 固化：
    `epoch_origin` 保持原值、读侧不判锚可达性、不报 `reanchor_record_missing`。
    这条替代上一轮的「move → reanchor 不得静默放过」临时钉子——v49 已定稿。
    """
    fresh, new = _rewrite_keeping_old_path_tree(tmp_path)
    old_epoch = core.read_lock(fresh)["seal_anchors"][SEAL_REL]["epoch_origin"]
    core.reanchor_seal(fresh, new, "REVIEW-20261112-01",
                       core.read_lock(fresh)["seal_anchors"][new]["epoch_origin"])
    commit_all(fresh, message="reanchor R")
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True, seal=new)
    commit(fresh, core.LOCK_NAME, message="R2")
    doc = read_doc(fresh, new)
    assert doc["moved_from"]["path"] == SEAL_REL
    assert doc["reanchor"]["review"] == "REVIEW-20261112-01"
    assert "seal_move_reanchor_conflict" not in codes(fresh)
    assert _error_codes(fresh) == []
    # retired 键的锚固化：不随重指改写
    assert core.read_lock(fresh)["seal_anchors"][SEAL_REL]["epoch_origin"] == old_epoch


def test_r4_v49_moved_to_with_reanchor_is_conflict(tmp_path: Path) -> None:
    """v49/项 1：旧（retired）封条同时带 `moved_to` 与 `reanchor` ⇒ 写侧 exit 2、读侧红。

    `moved_to` 与 `moved_from` 是两回事：本夹具只让**旧**封条带 `reanchor`，
    新封条只带 `moved_from`（上一条夹具钉它的绿侧）。
    """
    root = init_repo(tmp_path)
    # 旧路径封条先带上 reanchor（合法历史里 reanchor 只出现在 active 期）
    old_doc = read_doc(root)
    old_doc["reanchor"] = {"from_a": "0" * 40,
                           "review": "REVIEW-20261112-01",
                           "signed_at": "2027-01-01T00:00:00Z",
                           "base_seq": 2, "base_n": 1}
    write_doc(root, old_doc)
    commit(root, SEAL_REL, message="reanchor on old path")
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    moved = seal.build_seal_payload(
        root, core.load_manifest(root), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID], moved_from={"path": SEAL_REL})
    moved.pop("reanchor", None)  # 新封条只留 moved_from，冲突只落在旧封条上
    write_doc(root, moved, new)
    git(root, "rm", "-q", SEAL_REL)
    commit_all(root, message="move seal")
    lock_file = root / core.LOCK_NAME
    before = lock_file.read_bytes()
    # 写侧：旧封条带 reanchor ⇒ 拒绝写 moved_to，exit 2 且不写任何文件
    with pytest.raises(core.SolutionError, match="seal_move_reanchor_conflict"):
        core.write_lock(root, core.load_manifest(root), require_clean=True, seal=new)
    assert lock_file.read_bytes() == before
    # 读侧：模拟已落盘的坏状态（旧键 retired + moved_to），必须报互斥
    lock = core.read_lock(root)
    anchors = lock["seal_anchors"]
    old_anchor = dict(anchors[SEAL_REL])
    old_anchor.update(state="retired", moved_to=new)
    anchors[SEAL_REL] = old_anchor
    anchors[new] = seal.compute_anchor(root, new, None, read_doc(root, new),
                                       None, all_prior=anchors)
    lock_file.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    commit(root, core.LOCK_NAME, message="bad lock")
    assert "seal_move_reanchor_conflict" in codes(root)


def test_i9_anchor_review_format_is_enforced(repo: Path) -> None:
    (repo / "other").mkdir()
    with pytest.raises(core.SolutionError, match="REVIEW"):
        core.lock_payload(repo, core.load_manifest(repo),
                          assets_root="other", anchor_review="not-a-review")


def _move_seal(root: Path, new: str, patch: dict | None = None,
               **kwargs) -> dict:
    """换路径首签：写新封条 + 删旧路径 + 写锁（返回新键）。"""
    moved = seal.build_seal_payload(
        root, core.load_manifest(root), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID], moved_from={"path": SEAL_REL},
        **kwargs)
    if patch:
        moved.update(patch)
    write_doc(root, moved, new)
    git(root, "rm", "-q", SEAL_REL)
    commit_all(root, message="move seal")
    core.write_lock(root, core.load_manifest(root), require_clean=True, seal=new)
    commit(root, core.LOCK_NAME, message="lock moved")
    return moved


def test_c_moved_from_after_renewal_keeps_exemption_window(tmp_path: Path) -> None:
    """先续签一次再 move：`exemption_started_at` 必须随键继承，不得按新 L[0] 重算。"""
    root = init_repo(tmp_path)
    first = core.read_lock(root)["seal_anchors"][SEAL_REL]["exemption_start_origin"]
    # 续签时重签一个**不同**的 signed_at：move 会逐字节沿用它，成为新路径的 L[0].signed_at
    renew_mutate(root, lambda p: p.update(signed_at="2027-01-01T00:00:00Z"))
    core.write_lock(root, core.load_manifest(root), require_clean=True)
    commit(root, core.LOCK_NAME, message="lock renewed")
    assert codes(root) == []
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    _move_seal(root, new)
    anchor = core.read_lock(root)["seal_anchors"][new]
    assert anchor["exemption_started_at"] == first
    assert codes(root) == []
    # 换路径后的正常续签仍绿
    renew_path(root, new)
    core.write_lock(root, core.load_manifest(root), require_clean=True, seal=new)
    commit(root, core.LOCK_NAME, message="renew moved")
    assert codes(root) == []


def test_i2_case_change_then_move_recomputes_from_old_path(tmp_path: Path) -> None:
    """用例变化后 move：按旧路径 `L_pre[-1]` 复算 changed，声明齐备 ⇒ 绿。"""
    root = init_repo(tmp_path)
    old_sha = next(c["sha256"] for c in read_doc(root)["e2e"]["cases"]
                   if c["id"] == CASE_ID)
    case = root / "product" / "e2e" / "cases" / f"{CASE_ID}.md"
    case.write_text("## E2E-LOGIN-001\n\n```atlas-case\nid: E2E-LOGIN-001\n"
                    "step: 2\n```\n", encoding="utf-8")
    commit(root, f"product/e2e/cases/{CASE_ID}.md", message="case change")
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    moved = seal.build_seal_payload(
        root, core.load_manifest(root), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID],
        moved_from={"path": SEAL_REL}, reasons=["case-change"])
    # 写侧按当前树复算：changed / previous / upstream 不得整段沿用旧载荷
    assert moved["e2e"]["changed_case_ids"] == [CASE_ID]
    assert moved["e2e"]["previous_cases"] == [{"id": CASE_ID, "sha256": old_sha}]
    assert {u["role"] for u in moved["upstream"]} >= {"e2e-case"}
    write_doc(root, moved, new)
    git(root, "rm", "-q", SEAL_REL)
    commit_all(root, message="move with case change")
    core.write_lock(root, core.load_manifest(root), require_clean=True, seal=new)
    commit(root, core.LOCK_NAME, message="lock moved")
    assert codes(root) == []


def test_i7_payload_inherits_reanchor_alongside_moved_from(repo: Path) -> None:
    """写侧：`reanchor` 与 `moved_from` 必须同时保留（链路未覆盖，见 gates）。"""
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    reanchor = {"from_a": "0" * 40, "from_b": "1" * 40,
                "review": "REVIEW-20261112-01",
                "signed_at": "2027-01-01T00:00:00Z"}
    _move_seal(repo, new, patch={"reanchor": reanchor})
    payload = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID])
    assert payload["reanchor"] == reanchor
    assert payload["moved_from"]["path"] == SEAL_REL
    assert payload["renewal_seq"] == 2


def test_i2_case_change_then_move_without_reasons_is_rejected(
        tmp_path: Path) -> None:
    """用例变了却把旧载荷原样搬过去（不写 reasons）⇒ 分片 sha 必红。"""
    root = init_repo(tmp_path)
    case = root / "product" / "e2e" / "cases" / f"{CASE_ID}.md"
    case.write_text("## E2E-LOGIN-001\n\n```atlas-case\nid: E2E-LOGIN-001\n"
                    "step: 2\n```\n", encoding="utf-8")
    commit(root, f"product/e2e/cases/{CASE_ID}.md", message="case change")
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    _move_seal(root, new)
    assert "seal_e2e_case_sha_mismatch" in codes(root)


def _rewrite_first_sign(tmp_path: Path) -> Path:
    """首签 rebase：新孤立历史 + 重签首签；旧历史留在本地但不可达（rc=1）。"""
    original = init_repo(tmp_path / "orig")
    old_first = git(original, "log", "--diff-filter=A", "--format=%H",
                    "--reverse", "--", SEAL_REL).stdout.split()[0]
    # 保留旧历史为一条 ref，供 fresh 拉取**对象**（不合并进 HEAD）
    git(original, "branch", "old-history", "HEAD")
    git(original, "checkout", "-q", "--orphan", "rewritten")
    doc = read_doc(original)
    doc["signed_at"] = "2027-01-01T00:00:00Z"
    write_doc(original, doc)
    git(original, "add", "-A")
    # 锁单独成一次提交：外部锚必须与 L[0] 异源（R4-3），压进同一次提交会被
    # 判 `chain_unverifiable`（那正是 squashed 篡改的形态）。
    git(original, "rm", "-q", "--cached", core.LOCK_NAME)
    git(original, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "rewritten root")
    git(original, "add", core.LOCK_NAME)
    git(original, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "rewritten lock")
    git(original, "branch", "-M", "main")
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", "file://" + str(original), str(fresh)],
                   check=True)
    git(fresh, "fetch", "-q", "origin", "old-history")
    assert git(fresh, "cat-file", "-e", old_first, check=False).returncode == 0
    assert git(fresh, "merge-base", "--is-ancestor", old_first, "HEAD",
               check=False).returncode == 1
    return fresh


def test_i3_first_sign_rebase_with_unreachable_origin_can_reanchor(
        tmp_path: Path) -> None:
    """旧对象仍在本地但已不可达（rc=1）⇒ 受控重指放行，且重指后重签仍绿。"""
    fresh = _rewrite_first_sign(tmp_path)
    before = core.read_lock(fresh)["seal_anchors"][SEAL_REL]
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="controlled reanchor")
    after = core.read_lock(fresh)["seal_anchors"][SEAL_REL]
    assert after["epoch_origin"] != before["epoch_origin"]
    assert after["exemption_start_origin"] == before["exemption_start_origin"]
    assert after["exemption_started_at"] == "2027-01-01T00:00:00Z"
    assert after["exemption_start_history"] == [{
        "from": before["exemption_started_at"],
        "to": "2027-01-01T00:00:00Z",
        "commit": git(fresh, "rev-parse", "HEAD~1").stdout.strip()}]
    assert _error_codes(fresh) == []
    # 重指后重签（普通续签）：不得回落到「origin != L[0].signed_at」的永久红
    renew(fresh)
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="re-sign after reanchor")
    assert _error_codes(fresh) == []


def test_i3_first_sign_rebase_with_reachable_origin_is_rejected(repo: Path) -> None:
    """旧根仍可达（rc=0）⇒ 不得受控重指，`reanchor_record_missing` 保留。"""
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    lock = core.read_lock(repo)
    lock["seal_anchors"][SEAL_REL]["epoch_origin"] = head
    lock["seal_anchors"][SEAL_REL]["epoch_origin_history"] = [head]
    (repo / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    commit(repo, core.LOCK_NAME, message="origin at head")
    core.write_lock(repo, core.load_manifest(repo), require_clean=True)
    commit(repo, core.LOCK_NAME, message="lock again")
    assert core.read_lock(repo)["seal_anchors"][SEAL_REL]["epoch_origin"] == head
    assert "reanchor_record_missing" in codes(repo)


def test_k14_legacy_seal_skips_card_checks(repo: Path) -> None:
    """legacy 不走卡 / apply record 判据（白名单期）。"""
    renew_mutate(repo, lambda p: p.update(kind="legacy"))
    core.write_lock(repo, core.load_manifest(repo), require_clean=True)
    commit(repo, core.LOCK_NAME, message="lock legacy")
    (repo / "web" / CARD).unlink()
    (repo / "web" / CARD).parent.joinpath("atlas-apply.md").unlink()
    assert codes(repo) == []


def test_i3_apply_record_unverifiable_when_member_not_checked_out(
        repo: Path) -> None:
    """成员子树未 checkout ⇒ 不可验证（WARN），不得误判 `card_absent` FAIL。"""
    (repo / "web").rename(repo / "web-not-checked-out")
    errors, warnings, _, _, _ = validator.collect_errors(repo)
    assert "apply_record_missing" in [w["code"] for w in warnings]
    assert "apply_record_missing" not in [e["code"] for e in errors]
    assert "card_absent" not in [e["code"] for e in errors]


def test_b1_atlas_check_dispatcher_does_not_skip_apply_record(repo: Path) -> None:
    """真跑 `scripts/atlas_check.py`：删锁但保留封条不得被前置 SKIP 掉。"""
    validators = repo / ".atlas" / "validators"
    if validators.exists():
        shutil.rmtree(validators)
    validators.symlink_to(PKG / "validators", target_is_directory=True)
    check = PKG / "scripts" / "atlas_check.py"

    def row_of() -> dict:
        res = subprocess.run(
            [sys.executable, str(check), "--root", ".", "--fast", "--json"],
            cwd=str(repo), capture_output=True, text=True)
        rows = json.loads(res.stdout)["rows"]
        return next(r for r in rows if r["name"] == "validate_apply_record")

    assert row_of()["status"] == "ok"
    (repo / core.LOCK_NAME).unlink()
    commit_all(repo, message="drop lock")
    row = row_of()
    assert row["status"] == "FAIL", row
    assert "seal_anchor_path_unmapped" in row["detail"]
