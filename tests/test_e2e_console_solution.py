#!/usr/bin/env python3
"""RFC-20261108-02 一期：控制台评审新鲜度按父仓模式分支 + run-time provenance。

单仓路径必须逐字节等价（无 `solution_root` 标记时仍走 D128 / D174 旧路）；
父仓路径无 run-time `prov`（或 prov 无 `fp`）⇒ `stale`（fail-closed）。
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cons = _load("_atlas_console_solution_test", "scripts/e2e_console.py")
solution = _load("_atlas_console_solution_manifest", "_support/solution.py")

RUN_PROV = {
    "head_sha": "11111112222222",
    "scripts_hash": "aaaa1111",
    "git_dirty": False,
    "actor_type": "human",
    "app_hash": "app-old",
    "shared_hash": "sh111",
    "cases": {"E2E-001": {"script": "scripts/demo.spec.ts", "block": "b1", "rest": "r1"}},
}


def current(app_hash: str = "app-old") -> dict:
    return dict(RUN_PROV, app_hash=app_hash, solution_root=True)


# ---------------------------------------------------------------- 单仓等价

def test_single_repo_without_prov_is_still_legacy() -> None:
    """无 `solution_root` 标记 ⇒ 旧语义（legacy），逐字节不变。"""
    state = cons.case_review_state("E2E-001", {"reviewed": {"pass": True}}, {})
    assert state["state"] == "legacy"
    assert "历史快照无提交指纹" in state["reason"]


def test_single_repo_legacy_snapshot_without_head_is_legacy() -> None:
    snap = {"reviewed": {"pass": True}, "prov": {"actor_type": "human"}}
    assert cons.case_review_state("E2E-001", snap, {})["state"] == "legacy"


# ---------------------------------------------------------------- 父仓 fail-closed

def test_parent_without_prov_is_stale() -> None:
    state = cons.case_review_state("E2E-001", {"reviewed": {"pass": True}}, current())
    assert state["state"] == "stale"
    assert "run-time provenance" in state["reason"]


def test_parent_runtime_prov_without_fp_is_stale() -> None:
    snap = {"reviewed": {"pass": True},
            "prov": {"head_sha": RUN_PROV["head_sha"], "scripts_hash": "aaaa1111"}}
    assert cons.case_review_state("E2E-001", snap, current())["state"] == "stale"


# ---------------------------------------------------------------- 提交当前值不得补 fp.app

def test_submit_current_values_do_not_create_fp() -> None:
    """`_compact` 只认 entry 自带的运行期 prov；提交时的当前值不得补 fp。"""
    snap = cons._compact({"ok": True, "reviewed": {"pass": True}},
                         prov=current("app-new"), cid="E2E-001")
    assert "fp" not in snap["prov"]
    state = cons.case_review_state("E2E-001", snap, current("app-new"))
    assert state["state"] == "stale"


def test_runtime_prov_fresh_then_app_change_stale() -> None:
    snap = cons._compact({"ok": True, "prov": RUN_PROV,
                          "reviewed": {"pass": True}}, prov=current(), cid="E2E-001")
    assert snap["prov"]["fp"]["app"] == "app-old"
    assert cons.case_review_state("E2E-001", snap, current("app-old"))["state"] == "fresh"
    stale = cons.case_review_state("E2E-001", snap, current("app-new"))
    assert stale["state"] == "stale"
    assert "应用代码变动" in stale["reason"]


def test_re_sign_without_rerun_is_still_stale() -> None:
    """跑完（app-old）后应用改成 new，只重签不重跑 ⇒ fp.app 仍是 old ⇒ stale。"""
    run_prov = dict(RUN_PROV, app_hash="app-old")
    draft = {"ok": True, "prov": run_prov, "reviewed": {"pass": True}}
    snap = cons._compact(draft, prov=current("app-new"), cid="E2E-001")
    # 提交时即使把当前 app_hash 传给 _compact，也不能覆盖运行期的 app-old。
    assert snap["prov"]["fp"]["app"] == "app-old"
    assert cons.case_review_state("E2E-001", snap, current("app-new"))["state"] == "stale"


# ---------------------------------------------------------------- 运行期 prov 回传 / 父仓识别

def test_run_provenance_carries_fp_surface() -> None:
    prov = cons.run_provenance(Path("."))
    assert {"head_sha", "scripts_hash", "app_hash", "shared_hash", "cases"} <= set(prov)


def test_is_solution_root_detects_federated_manifest(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    solution.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    assert cons._is_solution_root(tmp_path) is True
    (tmp_path / "atlas.solution.yaml").unlink()
    assert cons._is_solution_root(tmp_path) is False


# ---------------------------------------------------------------- H3 / H5：成员内容变化

def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   capture_output=True, text=True)


def make_parent_with_members(tmp_path: Path) -> None:
    for name in ("web", "api"):
        repo = tmp_path / name
        repo.mkdir()
        _git(repo, "init")
        (repo / "app.txt").write_text("v1\n", encoding="utf-8")
        _git(repo, "add", "app.txt")
        _git(repo, "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-m", "init")
    solution.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False,
    )


def test_parent_app_hash_aggregates_all_members(tmp_path: Path) -> None:
    make_parent_with_members(tmp_path)
    before = cons.app_fingerprint(tmp_path)
    web_before = cons.app_fingerprint(tmp_path / "web")
    assert before and web_before
    (tmp_path / "api" / "app.txt").write_text("v2\n", encoding="utf-8")
    after = cons.app_fingerprint(tmp_path)
    assert after and after != before
    # 成员 A 自己的根指纹不受成员 B 改动影响。
    assert cons.app_fingerprint(tmp_path / "web") == web_before


def test_member_change_makes_all_parent_cases_stale(tmp_path: Path) -> None:
    make_parent_with_members(tmp_path)
    old = cons.app_fingerprint(tmp_path)
    run_prov = {"head_sha": "h", "scripts_hash": "s", "git_dirty": False,
                "actor_type": "human", "app_hash": old, "shared_hash": "sh",
                "cases": {"E2E-A": {"script": "a.ts", "block": "b1", "rest": "r1"},
                          "E2E-B": {"script": "b.ts", "block": "b2", "rest": "r2"}}}
    (tmp_path / "api" / "app.txt").write_text("v2\n", encoding="utf-8")
    new = cons.app_fingerprint(tmp_path)
    assert new != old
    current = dict(run_prov, app_hash=new, solution_root=True)
    for cid in ("E2E-A", "E2E-B"):
        snap = cons._compact({"ok": True, "prov": run_prov,
                              "reviewed": {"pass": True}}, prov=run_prov, cid=cid)
        # 依赖 B 的与不依赖 B 的父仓用例都不豁免。
        assert cons.case_review_state(cid, snap, current)["state"] == "stale"


def test_member_a_local_case_stays_fresh_when_member_b_changes(tmp_path: Path) -> None:
    make_parent_with_members(tmp_path)
    web_hash = cons.app_fingerprint(tmp_path / "web")
    run_prov = {"head_sha": "hw", "scripts_hash": "sw", "git_dirty": False,
                "actor_type": "human", "app_hash": web_hash, "shared_hash": "sh",
                "cases": {"E2E-LOCAL": {"script": "l.ts", "block": "b", "rest": "r"}}}
    snap = cons._compact({"ok": True, "prov": run_prov,
                          "reviewed": {"pass": True}}, prov=run_prov, cid="E2E-LOCAL")
    (tmp_path / "api" / "app.txt").write_text("v2\n", encoding="utf-8")
    # 成员 A 根算 current（无 solution_root 标记）：它自己的应用没变 ⇒ 仍 fresh。
    assert cons.case_review_state("E2E-LOCAL", snap,
                                  dict(run_prov))["state"] == "fresh"
