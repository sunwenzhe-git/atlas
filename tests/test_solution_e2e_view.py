#!/usr/bin/env python3
"""RFC-20261108-02 二期：父仓只读聚合视图（`atlas solution e2e status`）。

反面包全部用真实目录 + 真实 git 仓 + 真实账本落盘，不 monkeypatch；
「只读」用文件内容哈希前后对比取证，不以声明代替。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_solution.py"
MAIN_COLUMNS = ("用例ID", "页面", "中文标题", "类型", "关联AC", "需求",
                "状态", "状态原因", "分片")
_HEADER = "| " + " | ".join(MAIN_COLUMNS) + " |"
_SEP = "|---" * len(MAIN_COLUMNS) + "|"
_TS = "2026-11-08T10:00:00"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_atlas_solution_view_core", "_support/solution.py")
e2e = _load("_atlas_solution_view_kernel", "_support/solution_e2e.py")
cons = _load("_atlas_solution_view_console", "scripts/e2e_console.py")


def req(rid: str, member: str, **extra) -> dict:
    out = {"id": rid, "acs": "AC-SOLUTION-001", "member": member,
           "task_slug": f"{member}-task", "scope": "演示"}
    out.update(extra)
    return out


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def init_repo(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "view@test")
    git(repo, "config", "user.name", "view")
    (repo / "app.txt").write_text("v1\n", encoding="utf-8")
    git(repo, "add", "app.txt")
    git(repo, "commit", "-qm", "init")


def member_index(repo: Path, cid: str) -> None:
    e2e_dir = repo / "product" / "e2e"
    (e2e_dir / "cases").mkdir(parents=True)
    (e2e_dir / "scripts").mkdir(parents=True)
    (e2e_dir / "scripts" / "local.spec.ts").write_text(
        f"test('{cid} 本地流', async () => {{}});\n", encoding="utf-8")
    (e2e_dir / "e2e-index.md").write_text(
        "# E2E 索引\n\n" + _HEADER + "\n" + _SEP + "\n"
        f"| {cid} | home | 本地流 | 功能 | AC-WEB-001 | | green | | cases/local.md |\n",
        encoding="utf-8")
    (e2e_dir / "cases" / "local.md").write_text(
        f"# home\n\n## {cid} 本地流\n\n```atlas-case\nid: {cid}\n```\n",
        encoding="utf-8")
    git(repo, "add", "product")
    git(repo, "commit", "-qm", "e2e")


def seed_member_submit(repo: Path, cid: str) -> None:
    prov = cons.run_provenance(repo)
    snap = cons._compact(
        {"ok": True, "ts": _TS, "prov": prov, "reviewed": {"pass": True}},
        prov=prov, cid=cid)
    cons.Ledger(repo, "member").append({
        "kind": "submit", "source": "app", "ts": _TS, "actor": "member",
        "cases": {cid: snap}, "reviewed_scope": [cid], "prov": prov, "changed": 0,
    })


def make_parent(tmp_path: Path, requirements: list[dict]) -> None:
    init_repo(tmp_path / "web")
    init_repo(tmp_path / "api")
    member_index(tmp_path / "web", "E2E-WEB-001")
    member_index(tmp_path / "api", "E2E-API-001")
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "view@test")
    git(tmp_path, "config", "user.name", "view")
    git(tmp_path, "commit", "-qm", "empty", "--allow-empty")
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False, requirements=requirements,
    )


def parent_index(tmp_path: Path, cids: list[str]) -> None:
    e2e.init(tmp_path)
    path = e2e.index_path(tmp_path)
    text = path.read_text(encoding="utf-8")
    injected = _HEADER + "\n" + _SEP + "\n"
    injected += "".join(
        f"| {cid} | solution-flow | 跨仓流 | 功能 | AC-SOLUTION-001 | | green | | cases/solution-flow.md |\n"
        for cid in cids)
    assert _HEADER + "\n" + _SEP in text
    text = text.replace(_HEADER + "\n" + _SEP, injected, 1)
    path.write_text(text, encoding="utf-8")
    (tmp_path / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    blocks = ""
    for i, cid in enumerate(cids, start=1):
        deps = "web" if i == 1 else "api"
        blocks += (
            f"## {cid} 跨仓流{i}\n\n```atlas-case\nid: {cid}\nintent: 跨仓验收\n"
            "pages:\n  - solution-flow\nstep:\n  - goto /\nexpected:\n  - 可见\n"
            f"成员依赖: {deps}\n```\n\n")
    (tmp_path / "product" / "e2e" / "cases" / "solution-flow.md").write_text(
        "# solution-flow\n\n" + blocks, encoding="utf-8")


def seed_parent_submit(tmp_path: Path, cids: list[str]) -> None:
    prov = cons.run_provenance(tmp_path)
    cases = {cid: cons._compact(
        {"ok": True, "ts": _TS, "prov": prov, "reviewed": {"pass": True}},
        prov=prov, cid=cid) for cid in cids}
    cons.Ledger(tmp_path, "parent").append({
        "kind": "submit", "source": "app", "ts": _TS, "actor": "parent",
        "cases": cases, "reviewed_scope": cids, "prov": prov, "changed": 0,
    })


def hashes(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in rel or "__pycache__" in rel:
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def view(tmp_path: Path, requirement: str | None = None, snapshot: bool = False) -> dict:
    data = core.load_manifest(tmp_path)
    return e2e.status(data, e2e.read_index(tmp_path), requirement,
                      root=tmp_path, snapshot=snapshot)


def test_view_schema_member_summary_and_parent_cases(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001,E2E-SOLUTION-002")])
    parent_index(tmp_path, ["E2E-SOLUTION-001", "E2E-SOLUTION-002"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")

    result = view(tmp_path)
    assert result["kind"] == "solution-e2e-readonly-view"
    assert result["readonly"] is True
    assert result["parent"]["index"].endswith("e2e-index.md")
    members = {m["name"]: m for m in result["members"]}
    assert members["web"]["state"] == "ok"
    assert members["web"]["counts"] == {"total": 1, "green": 1, "red": 0,
                                        "blocked": 0, "skipped": 0}
    assert members["web"]["review"]["fresh"] == 1
    assert members["web"]["latest_seq"] == 1
    assert members["api"]["state"] == "ok"
    cases = {c["id"]: c for c in result["parent"]["cases"]}
    assert cases["E2E-SOLUTION-001"]["members"] == ["web"]
    assert cases["E2E-SOLUTION-002"]["members"] == ["api"]
    # 父仓账本为空：父仓用例没有快照 ⇒ unreviewed（有快照但无 run-time prov 才是 stale）。
    assert {c["review_state"] for c in result["parent"]["cases"]} == {"unreviewed"}
    assert result["verdict"] == "INCOMPLETE"


def test_view_is_read_only_member_files_untouched(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")
    before = hashes(tmp_path)
    view(tmp_path)
    assert hashes(tmp_path) == before
    assert not (tmp_path / "product" / "e2e" / "reviews" / "aggregate").exists()


def test_member_review_state_recomputed_at_member_root_h5(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001,E2E-SOLUTION-002")])
    parent_index(tmp_path, ["E2E-SOLUTION-001", "E2E-SOLUTION-002"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")
    seed_member_submit(tmp_path / "api", "E2E-API-001")
    seed_parent_submit(tmp_path, ["E2E-SOLUTION-001", "E2E-SOLUTION-002"])
    assert {c["review_state"] for c in view(tmp_path)["parent"]["cases"]} == {"fresh"}

    # 只改成员 B（api）的应用内容：父仓全部用例 stale；成员 A 本地仍 fresh。
    (tmp_path / "api" / "app.txt").write_text("v2\n", encoding="utf-8")
    before = hashes(tmp_path / "web") | hashes(tmp_path / "api")
    result = view(tmp_path)
    # stale 重算不得回写成员账本/索引（RFC §5.8）。
    assert hashes(tmp_path / "web") | hashes(tmp_path / "api") == before
    members = {m["name"]: m for m in result["members"]}
    assert members["web"]["review"]["fresh"] == 1
    assert members["api"]["review"]["stale"] == 1
    assert {c["review_state"] for c in result["parent"]["cases"]} == {"stale"}
    # 不依赖 api 的 E2E-SOLUTION-001 也不豁免（RFC §4.5.2 H5）。
    assert next(c for c in result["parent"]["cases"]
                if c["id"] == "E2E-SOLUTION-001")["review_state"] == "stale"


def test_missing_member_blocks_dependent_parent_case(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001,E2E-SOLUTION-002")])
    parent_index(tmp_path, ["E2E-SOLUTION-001", "E2E-SOLUTION-002"])
    import shutil
    shutil.rmtree(tmp_path / "api")

    result = view(tmp_path)
    members = {m["name"]: m for m in result["members"]}
    assert members["api"]["state"] == "missing"
    cases = {c["id"]: c for c in result["parent"]["cases"]}
    assert cases["E2E-SOLUTION-001"]["status"] == "green"
    assert cases["E2E-SOLUTION-002"]["status"] == "blocked"
    assert cases["E2E-SOLUTION-002"]["blocked_by_members"] == ["api"]
    assert result["verdict"] == "BLOCKED"
    assert result["exit"] == 3


def test_snapshot_writes_only_parent_aggregate(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")
    before = hashes(tmp_path)
    result = view(tmp_path, snapshot=True)
    path = Path(result["snapshot"])
    assert path.parent == tmp_path / "product" / "e2e" / "reviews" / "aggregate"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "solution-e2e-readonly-view"
    assert payload["readonly"] is True
    assert "不是任何成员状态的第二份账本" in payload["note"]
    after = hashes(tmp_path)
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == set()
    assert set(after) - set(before) == {path.relative_to(tmp_path).as_posix()}


def test_cli_status_snapshot_flag(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path),
         "e2e", "status", "--json", "--snapshot"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert Path(payload["snapshot"]).is_file()
    assert payload["parent"]["cases"][0]["members"] == ["web"]


def test_app_js_draft_key_is_member_namespaced() -> None:
    text = (PKG_ROOT / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    assert "const DRAFT_KEY = (src, member)" in text
    assert "atlas-console-draft:v3:${member ? `${member}/` : ''}${src}" in text
    assert "DRAFT_KEY(S.source)" not in text
    assert "draftKey = () => DRAFT_KEY(S.source, S.member)" in text


def test_aggregate_is_reserved_reviews_name() -> None:
    text = (PKG_ROOT / "rings" / "e2e" / "reference.md").read_text(encoding="utf-8")
    assert "`aggregate/`" in text
    assert "保留名" in text
