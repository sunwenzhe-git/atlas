#!/usr/bin/env python3
"""RFC-20261108-02 二期：父仓只读聚合视图（`atlas solution e2e status`）。

反面包全部用真实目录 + 真实 git 仓 + 真实账本落盘，不 monkeypatch；
「只读」用文件内容哈希前后对比取证，不以声明代替。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shlex
import socket
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    # D198 起评审只认用例内容：只改成员 B（api）的应用代码不再作废已审
    # （成员本地与父仓一视同仁），重算也不得回写成员账本/索引（RFC §5.8）。
    (tmp_path / "api" / "app.txt").write_text("v2\n", encoding="utf-8")
    before = hashes(tmp_path / "web") | hashes(tmp_path / "api")
    result = view(tmp_path)
    assert hashes(tmp_path / "web") | hashes(tmp_path / "api") == before
    members = {m["name"]: m for m in result["members"]}
    assert members["web"]["review"]["fresh"] == 1
    assert members["api"]["review"]["fresh"] == 1
    assert {c["review_state"] for c in result["parent"]["cases"]} == {"fresh"}

    # 只改父仓用例内容（两条都改）：父仓全部用例 stale，成员 A/B 本地仍 fresh
    # —— 根隔离：成员用例没有拿父仓根算 current。
    shard = tmp_path / "product" / "e2e" / "cases" / "solution-flow.md"
    shard.write_text(shard.read_text(encoding="utf-8").replace("  - 可见", "  - 可见且已刷新"),
                     encoding="utf-8")
    result = view(tmp_path)
    members = {m["name"]: m for m in result["members"]}
    assert members["web"]["review"]["fresh"] == 1
    assert members["api"]["review"]["fresh"] == 1
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


# ---------------------------------------------------------------- 控制台逐条只读聚合
# 契约 `rings/e2e/reference.md §10.1.2` 第 6 条：父仓只看不跑，复合键区分同名用例。

def test_console_member_cases_grouped_with_composite_key(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")

    payload = cons.member_snapshots(tmp_path)
    assert payload["scope"] == "solution"
    assert [m["name"] for m in payload["members"]] == ["web", "api"]
    web = next(m for m in payload["members"] if m["name"] == "web")
    assert web["state"] == "ok"
    assert web["readonly"] is True
    assert web["run_blocked_reason"] == cons.MEMBER_READONLY_REASON
    assert web["counts"] == {"total": 1, "green": 1, "red": 0,
                             "blocked": 0, "skipped": 0}
    assert web["review"]["fresh"] == 1
    row = web["cases"][0]
    assert row["uid"] == "web:E2E-WEB-001"
    assert row["id"] == "E2E-WEB-001"          # 本地 ID 不被改写
    assert row["member"] == "web"
    assert row["scope"] == "member"
    assert row["review_state"]["state"] == "fresh"
    assert payload["conflicts"] == []


def test_console_member_id_conflict_keeps_both_rows(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    # 真实场景：两个成员各自独立编号，撞号合法——不得合并、不得覆盖。
    for p in (tmp_path / "api" / "product" / "e2e").rglob("*.md"):
        p.write_text(p.read_text(encoding="utf-8").replace("E2E-API-001", "E2E-WEB-001"),
                     encoding="utf-8")

    payload = cons.member_snapshots(tmp_path)
    assert payload["conflicts"] == [{"case_id": "E2E-WEB-001", "members": ["web", "api"]}]
    uids = sorted(c["uid"] for m in payload["members"] for c in m["cases"])
    assert uids == ["api:E2E-WEB-001", "web:E2E-WEB-001"]
    assert "E2E-WEB-001" in (tmp_path / "api" / "product" / "e2e" / "e2e-index.md").read_text(
        encoding="utf-8")


def test_console_member_missing_is_disclosed(tmp_path: Path) -> None:
    import shutil
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    shutil.rmtree(tmp_path / "api")

    api = next(m for m in cons.member_snapshots(tmp_path)["members"] if m["name"] == "api")
    assert api["state"] == "missing"
    assert "api" in (api["reason"] or "")
    assert api["cases"] == []


def test_console_member_without_local_e2e_is_not_red(tmp_path: Path) -> None:
    import shutil
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    shutil.rmtree(tmp_path / "api" / "product" / "e2e")

    api = next(m for m in cons.member_snapshots(tmp_path)["members"] if m["name"] == "api")
    assert api["state"] == "no_local_e2e"
    assert api["counts"] == {"total": 0, "green": 0, "red": 0,
                             "blocked": 0, "skipped": 0}
    assert api["cases"] == []


def test_console_single_root_has_no_member_section(tmp_path: Path) -> None:
    root = tmp_path / "single"
    init_repo(root)
    assert cons.member_snapshots(root) == {
        "scope": "single", "members": [], "conflicts": []}


def test_console_member_view_is_read_only(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    seed_member_submit(tmp_path / "web", "E2E-WEB-001")
    before = hashes(tmp_path)
    cons.member_snapshots(tmp_path)
    assert hashes(tmp_path) == before


# ---------------------------------------------------------------- 成员控制台入口（深链 + 启动命令）
# 契约 `rings/e2e/reference.md §10.1.2` 第 6 条：父仓只给入口，执行/评审/账本仍归成员进程。

def test_console_member_exposes_console_entry_and_command(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])

    payload = cons.member_snapshots(tmp_path, 4200)
    web = next(m for m in payload["members"] if m["name"] == "web")
    api = next(m for m in payload["members"] if m["name"] == "api")
    # 端口 = 父仓端口 + 1 + 清单序号（web 在前 ⇒ 4201，api 次之 ⇒ 4202）。
    assert web["console_url"] == "http://127.0.0.1:4201/"
    assert api["console_url"] == "http://127.0.0.1:4202/"
    assert web["root"] == str((tmp_path / "web").resolve())
    assert f"--root {web['root']}" in web["console_cmd"]
    assert "--port 4201 --host 127.0.0.1" in web["console_cmd"]
    # 入口链接/命令是纯读字段：只读口径与拒绝原因不变。
    assert web["readonly"] is True
    assert web["run_blocked_reason"] == cons.MEMBER_READONLY_REASON


def test_member_console_cmd_is_shell_copyable() -> None:
    """路径含空格/中文时按 shell 规则转义，粘进终端可原样执行。"""
    cmd = cons.member_console_cmd(Path("/tmp/有 空格/member"), 4191)
    assert shlex.split(cmd)[-6:] == [
        "--root", "/tmp/有 空格/member", "--port", "4191", "--host", "127.0.0.1"]


def test_member_run_and_submit_guards_are_still_409(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    parent_index(tmp_path, ["E2E-SOLUTION-001"])
    before = hashes(tmp_path)

    class Stub:
        def __init__(self) -> None:
            self.got: list[tuple[int, dict]] = []

        def _json(self, obj: dict, code: int = 200) -> None:
            self.got.append((code, obj))

    stub = Stub()
    cons.Handler._run(stub, {"id": "web:E2E-WEB-001", "member": True})
    cons.Handler._submit(stub, {"draft": {"web:E2E-WEB-001": {"ok": True}}, "apply": True})

    assert [code for code, _ in stub.got] == [409, 409]
    assert all(body["readonly"] is True for _, body in stub.got)
    assert hashes(tmp_path) == before       # 守卫在任何写盘之前返回


def test_app_js_member_block_has_console_entry() -> None:
    text = (PKG_ROOT / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    assert "打开成员控制台" in text
    assert 'target="_blank" rel="noopener"' in text
    assert "m.console_cmd" in text and "data-copy" in text
    # 只加导航，不加执行/评审控件：成员行仍不接 run()/api/run。
    assert "data-run" not in text.split("function memberBlock")[1].split("function rowHTML")[0]



# ---------------------------------------------------------------- 父仓自动拉起成员控制台
# 2026-11-10（方案 B）：父仓按「父仓端口 + 1 + 清单序号」自动拉起成员控制台，
# 只起进程、不新增路由、不接管执行；端口被占则复用或跳过，退出只回收自己拉起的。

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class FakeConsole:
    """假控制台：只实现 `/api/cases`（不带真服务/真依赖），用于验证端口判别。"""

    def __init__(self, scope: str = "single", port: int = 0) -> None:
        self.scope = scope
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *args):  # 安静
                pass

            def do_GET(self):  # noqa: N802
                body = json.dumps({"scope": outer.scope}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = int(self.httpd.server_address[1])
        self._th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._th.start()

    def alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/cases", timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def test_member_targets_ports_follow_manifest_order(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids="E2E-SOLUTION-001")])
    tgts = cons.member_targets(tmp_path, 4290)
    assert [(t["name"], t["path"], t["port"]) for t in tgts] == [
        ("web", "web", 4291), ("api", "api", 4292)]
    assert Path(tgts[0]["root"]) == (tmp_path / "web").resolve()
    assert cons.member_targets(tmp_path / "web", 4290) == []   # 单根不拉起


def test_no_spawn_flag_disables_auto_start(tmp_path: Path) -> None:
    parser = cons.build_parser()
    assert parser.parse_args([]).no_spawn is False
    assert parser.parse_args(["--no-spawn"]).no_spawn is True

    mc = cons.MemberConsoles(tmp_path, 4290, enabled=False)
    mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path), "port": free_port()}])
    snap = mc.snapshot("web")
    assert snap["console_state"] == "disabled"
    assert "--no-spawn" in snap["console_note"]
    assert mc._threads == []          # 一个子进程都没起


def test_port_with_member_console_is_reused_and_never_killed(tmp_path: Path) -> None:
    fake = FakeConsole()
    try:
        mc = cons.MemberConsoles(tmp_path, 4290)
        mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path), "port": fake.port}])
        mc._threads[-1].join(5)
        snap = mc.snapshot("web")
        assert snap["console_state"] == "reused"
        assert "退出不回收" in snap["console_note"]
        assert mc._handles == {}
        mc.stop()
        assert fake.alive() is True   # 复用的外部实例一根手指都不碰
    finally:
        fake.close()


def test_port_occupied_by_other_process_is_skipped(tmp_path: Path) -> None:
    fake = FakeConsole(scope="solution")   # 有响应但不是成员控制台（例如另一个父仓）
    try:
        mc = cons.MemberConsoles(tmp_path, 4290)
        mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path), "port": fake.port}])
        mc._threads[-1].join(5)
        snap = mc.snapshot("web")
        assert snap["console_state"] == "skipped"
        assert "已被占用" in snap["console_note"]
        mc.stop()
        assert fake.alive() is True   # 不抢占、不杀
    finally:
        fake.close()


def test_spawn_command_targets_terminal_with_member_root(tmp_path: Path) -> None:
    log = tmp_path / "web.log"
    pidfile = tmp_path / "web.pid"
    cmd = cons.member_console_shell_command(tmp_path, 4299, log, pidfile)
    assert cmd.startswith("cd ")
    assert "echo $$ > " in cmd and str(pidfile).split("/")[-1] in cmd
    assert "exec " in cmd
    assert f"--port 4299" in cmd                 # 端口按清单序号推导
    assert "--host 127.0.0.1" in cmd
    assert "--no-spawn" in cmd                   # 被拉起的成员不再递归拉起
    assert "--root " in cmd and tmp_path.name in cmd
    assert str(log).split("/")[-1] in cmd and "2>&1" in cmd

    script = cons.terminal_spawn_command(cmd)
    assert script.startswith('tell application "Terminal" to do script "')
    assert script.endswith('"')
    # AppleScript 字符串内的双引号必须转义，否则 do script 会被截断
    assert '\\"' in cons.terminal_spawn_command('echo "hi"')


def test_spawn_failure_reports_readable_reason(tmp_path: Path) -> None:
    def spawner(name, mroot, port):
        raise cons.SpawnError(
            "osascript 调用失败（exit=1）：Not authorized to send Apple events")

    mc = cons.MemberConsoles(tmp_path, 4290, spawner=spawner)
    mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path),
                   "port": free_port()}])
    mc._threads[-1].join(5)
    snap = mc.snapshot("web")
    assert snap["console_state"] == "failed"
    assert "拉起失败" in snap["console_note"]
    assert "Not authorized" in snap["console_note"]   # 原始错误行不吞掉


def test_free_port_is_spawned_and_survives_parent_stop(tmp_path: Path) -> None:
    port = free_port()
    spawned: dict = {}

    def spawner(name, mroot, port):
        spawned["console"] = FakeConsole(port=port)
        return {"via": "terminal", "pid": None, "log": str(tmp_path / "web.log"),
                "pidfile": str(tmp_path / "web.pid"), "shell_cmd": "stub"}

    mc = cons.MemberConsoles(tmp_path, 4290, spawner=spawner)
    try:
        mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path),
                       "port": port}])
        mc._threads[-1].join(5)
        snap = mc.snapshot("web")
        assert snap["console_state"] == "ready"
        assert "Terminal.app" in snap["console_note"]
        assert "父会话退出不影响" in snap["console_note"]
        mc.stop()
        assert spawned["console"].alive() is True   # 父退出不回收（硬要求）
    finally:
        if "console" in spawned:
            spawned["console"].close()


def test_ensure_reuses_listening_console_without_spawning(tmp_path: Path) -> None:
    fake = FakeConsole()
    calls: list = []

    def spawner(name, mroot, port):
        calls.append(name)
        raise AssertionError("已有监听时不得再拉起")

    mc = cons.MemberConsoles(tmp_path, 4290, spawner=spawner)
    try:
        mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path),
                       "port": fake.port}])
        mc._threads[-1].join(5)
        snap = mc.ensure("web", wait=True)
        assert snap["console_state"] == "reused"
        assert calls == []
        assert fake.alive() is True
    finally:
        fake.close()


def test_member_open_returns_child_url_and_rejects_unknown() -> None:
    class _Stub:
        targets = [{"name": "web", "port": 4301}]
        host = "127.0.0.1"
        members = None

    code, payload = cons.App.open_member_console(_Stub(), "web")
    assert code == 200 and payload["url"] == "http://127.0.0.1:4301/"
    code, payload = cons.App.open_member_console(_Stub(), "nope")
    assert code == 404 and "未知成员" in payload["error"]


def test_no_local_e2e_member_is_not_spawned(tmp_path: Path) -> None:
    spawned: list = []

    def spawner(name, mroot, port):
        spawned.append(name)
        raise AssertionError("无本地 E2E 索引的成员不应起进程")

    mc = cons.MemberConsoles(tmp_path, 4290, spawner=spawner)
    mc.start_all([{"name": "web", "path": "web", "root": str(tmp_path), "port": free_port()}],
                 {"web": "no_local_e2e"})
    snap = mc.snapshot("web")
    assert spawned == []                      # 一个子进程都没起
    assert mc._threads == []
    assert snap["console_state"] == "no_index"
    assert snap["console_state"] != "ready"
    assert "未启动控制台" in snap["console_note"]


def test_app_js_console_entry_has_parent_to_child_route() -> None:
    text = (PKG_ROOT / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    block = text.split("function memberBlock")[1].split("function rowHTML")[0]
    assert "console_state" in block
    # 已就绪 ⇒ 直连子控制台地址（host/port 来自后端 console_url）；否则走父仓兜底路由
    assert "const entryHref = (live && m.console_url)" in block
    assert "api/member-open?name=${encodeURIComponent(m.name)}" in block
    assert "const entry = ok" in block          # 无索引成员不渲染入口链接
    assert 'target="_blank" rel="noopener"' in block


def test_app_js_hides_console_entry_for_members_without_index() -> None:
    text = (PKG_ROOT / "templates" / "e2e" / "console" / "app.js").read_text(encoding="utf-8")
    block = text.split("function memberBlock")[1].split("function rowHTML")[0]
    assert "no_index: '无本地 E2E 索引 · 未启动控制台'" in block
    assert "(ok && m.console_cmd)" in block   # 无索引成员不展示启动命令/端口/日志
    assert "const entry = ok" in block        # 入口链接同样以 ok 为门
    assert "m.path !== m.name" in block       # 成员名不重复展示
