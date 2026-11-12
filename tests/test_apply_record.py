#!/usr/bin/env python3
"""封条（apply record）C 批夹具：upstream / 路径宇宙 / 状态机 / 续签链 / 写侧。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
        "```atlas-case\nid: E2E-LOGIN-001\n```\n", encoding="utf-8")
    (tmp / "product" / "e2e" / "e2e-index.md").write_text(
        "# index\n\n| ID | 需求 |\n|---|---|\n| E2E-LOGIN-001 | R1 |\n",
        encoding="utf-8")
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
    payload = seal.build_seal_payload(
        root, core.load_manifest(root), SEAL_REL, assets_root="product",
        kind="binding", card_path=CARD,
        acceptance_acs=["AC-SOLUTION-001"], e2e_status="ready",
        case_ids=[CASE_ID], owner="@a")
    payload.update(overrides)
    write_doc(root, payload)
    commit(root, SEAL_REL, message="renew")
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
    core.write_lock(fresh, core.load_manifest(fresh), require_clean=True)
    commit(fresh, core.LOCK_NAME, message="R2")
    anchor = core.read_lock(fresh)["seal_anchors"][SEAL_REL]
    assert anchor["epoch_origin"] == git(fresh, "rev-list", "--max-parents=0",
                                         "HEAD").stdout.split()[0]
    assert anchor["anchor_review"] == "REVIEW-20261112-01"
    assert codes(fresh) == []


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
    doc = read_doc(repo)
    moved = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", card_path=CARD, acceptance_acs=["AC-SOLUTION-001"],
        e2e_status="ready", case_ids=[CASE_ID], moved_from={"path": old},
        reasons=["task-renamed"], previous_cases=[{"id": CASE_ID}])
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
    assert codes(repo) == []


def test_c_moved_from_sha_mismatch(repo: Path) -> None:
    old = SEAL_REL
    new = "product/reviews/apply/web/T-001-moved.seal.json"
    moved = seal.build_seal_payload(
        repo, core.load_manifest(repo), new, assets_root="product",
        kind="binding", e2e_status="ready", case_ids=[CASE_ID],
        moved_from={"path": old, "sha256": "0" * 64},
        reasons=["task-renamed"], previous_cases=[{"id": CASE_ID}])
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
        moved_from={"path": old}, reasons=["task-renamed"],
        previous_cases=[{"id": CASE_ID}])
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
    errors, warnings, paths, count = validator.collect_errors(repo)
    assert count == 1 and not errors
    empty = repo / "empty"
    empty.mkdir()
    assert validator.collect_errors(empty)[3] == 0


def test_c_apply_seal_cli_writes_seconds_signature(repo: Path) -> None:
    new = "product/reviews/apply/web/T-003.seal.json"
    res = subprocess.run(
        [sys.executable, str(SEAL_SCRIPT), "--root", str(repo), "--seal", new,
         "--acceptance-acs", "AC-SOLUTION-001", "--e2e-status", "ready",
         "--case", CASE_ID, "--json"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    doc = json.loads((repo / new).read_text(encoding="utf-8"))
    assert seal.SIGNED_AT_RE.match(doc["signed_at"])
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
