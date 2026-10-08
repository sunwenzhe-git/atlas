#!/usr/bin/env python3
"""`adapters/_graph.py`（图谱后端隔离层）的「喂坏输入必红」判据（2026-10-05 图谱批 1）。

为什么要它：_graph.py 是全线**唯一**接触图谱后端的模块，确定性契约（ORDER BY /
标记字节一致 / 响亮超时）只在这里实现一次；它若静默坏，上层对账门全数失明。

四侧（全部经 fake `cgc` 可执行，不依赖真后端）：
  1. 探测：版本解析 + pin 失配显式 WARN + 缺失 ⇒ None；
  2. 用前现刷：新鲜度键（HEAD + 脏文件集）驱动 marker fresh/indexed 两态；
  3. 查询解析：横幅剥离 + 后端 error 对象响亮 die + 无 JSON 响亮 die；
  4. profile 声明：graph 段解析 / `graph: null` / 非法 backend 必红。

变异：摘掉 query 的 error 对象检查 ⇒ 第 3 侧红；摘掉 ensure_index 的键比对 ⇒ 第 2 侧红。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT / "adapters"))
import _graph  # noqa: E402

FAKE_CGC = r'''#!/usr/bin/env python3
import json, os, sys
state = os.environ["FAKE_CGC_STATE"]
with open(os.path.join(state, "calls.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print(os.environ.get("FAKE_CGC_VERSION", "CodeGraphContext 0.9.9"))
    sys.exit(0)
if args[:1] == ["index"]:
    sys.exit(3 if os.environ.get("FAKE_CGC_INDEX_FAIL") else 0)
if args[:1] == ["query"]:
    body = open(os.environ["FAKE_CGC_QUERY_FILE"], encoding="utf-8").read() \
        if os.environ.get("FAKE_CGC_QUERY_FILE") else "[]"
    print("Loaded configuration from: /fake/.env")
    print("Using database: falkordb (source: auto-detect)")
    print("Services initialized.")
    print(body)
    sys.exit(0)
sys.exit(2)
'''


@pytest.fixture()
def fake_cgc(tmp_path: Path, monkeypatch):
    """装一个 fake cgc 进 PATH；返回 state 目录。"""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    exe = bin_dir / "cgc"
    exe.write_text(FAKE_CGC, encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_CGC_STATE", str(state))
    return state


@pytest.fixture()
def git_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    # fakebin/ state/ 是本测试夹具的运行时目录；.adapter-out/ 是图谱层运行时目录——
    # 与真实项目一致：运行时目录 gitignore，不进代码态指纹。
    (tmp_path / ".gitignore").write_text("fakebin/\nstate/\n.adapter-out/\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    return tmp_path


# ---------------------------------------------------------------- 1. 探测

def test_detect_parses_version(fake_cgc) -> None:
    det = _graph.detect(Path("."), {"backend": "cgc", "pinned": "0.9.9"})
    assert det is not None and det["version"] == "0.9.9"


def test_detect_pin_mismatch_warns_loudly(fake_cgc, capsys) -> None:
    _graph.detect(Path("."), {"backend": "cgc", "pinned": "0.6.13"})
    assert "版本失配" in capsys.readouterr().err


def test_detect_missing_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-graph-path")
    assert _graph.detect(Path(".")) is None


# ---------------------------------------------------------------- 2. 用前现刷

def test_ensure_index_fresh_then_reindex_on_change(fake_cgc, git_repo) -> None:
    cfg = {"backend": "cgc"}
    r1 = _graph.ensure_index(git_repo, cfg, version="0.9.9")
    assert r1["status"] == "indexed"
    marker = json.loads((git_repo / ".adapter-out" / "_graph_index.json").read_text(encoding="utf-8"))
    assert marker["backend"] == "cgc" and marker["backend_version"] == "0.9.9"

    r2 = _graph.ensure_index(git_repo, cfg, version="0.9.9")
    assert r2["status"] == "fresh"

    # 脏工作区（未提交改动）⇒ 键变化 ⇒ 必须重建，不许拿旧索引装新鲜
    (git_repo / "a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    r3 = _graph.ensure_index(git_repo, cfg, version="0.9.9")
    assert r3["status"] == "indexed"

    calls = (fake_cgc / "calls.log").read_text(encoding="utf-8").splitlines()
    index_calls = [c for c in calls if json.loads(c)[:1] == ["index"]]
    assert len(index_calls) == 2, index_calls


def test_ensure_index_backend_failure_is_loud(fake_cgc, git_repo, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FAKE_CGC_INDEX_FAIL", "1")
    with pytest.raises(SystemExit):
        _graph.ensure_index(git_repo, {"backend": "cgc"}, version="0.9.9")
    assert "cgc index 失败" in capsys.readouterr().err
    assert not (git_repo / ".adapter-out" / "_graph_index.json").exists()


# ---------------------------------------------------------------- 3. 查询解析

def test_query_strips_banner_and_parses(fake_cgc, tmp_path, monkeypatch) -> None:
    qf = tmp_path / "resp.json"
    qf.write_text(json.dumps(
        [{"name": "create_user", "path": "backend/app/api/routes/users.py"},
         {"name": "recover_password", "path": "backend/app/api/routes/login.py"}]) + "\n",
        encoding="utf-8")
    monkeypatch.setenv("FAKE_CGC_QUERY_FILE", str(qf))
    rows = _graph.query(Path("."), "MATCH (c)-[:CALLS]->(t) RETURN c.name AS name ORDER BY name")
    assert [r["name"] for r in rows] == ["create_user", "recover_password"]


def test_query_backend_error_dies_loudly(fake_cgc, tmp_path, monkeypatch, capsys) -> None:
    qf = tmp_path / "resp.json"
    qf.write_text(json.dumps({"error": "Binder exception: ..."}) + "\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_CGC_QUERY_FILE", str(qf))
    with pytest.raises(SystemExit):
        _graph.query(Path("."), "MATCH (x) RETURN x")
    assert "后端查询错误" in capsys.readouterr().err


def test_query_without_json_dies_loudly(fake_cgc, tmp_path, monkeypatch, capsys) -> None:
    qf = tmp_path / "resp.txt"
    qf.write_text("Services initialized.\n（没有任何 JSON）\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_CGC_QUERY_FILE", str(qf))
    with pytest.raises(SystemExit):
        _graph.query(Path("."), "MATCH (x) RETURN x")
    assert "没有 JSON" in capsys.readouterr().err


def test_callers_dedupes_and_sorts(fake_cgc, tmp_path, monkeypatch) -> None:
    qf = tmp_path / "resp.json"
    qf.write_text(json.dumps([
        {"name": "z_caller", "path": "b.py"},
        {"name": "a_caller", "path": "b.py"},
        {"name": "a_caller", "path": "b.py"},
        {"name": "a_caller", "path": "a.py"},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_CGC_QUERY_FILE", str(qf))
    out = _graph.callers(Path("."), "send_email")
    assert out == [
        {"name": "a_caller", "path": "a.py"},
        {"name": "a_caller", "path": "b.py"},
        {"name": "z_caller", "path": "b.py"},
    ]


# ---------------------------------------------------------------- 4. profile 声明

def _write_profile(root: Path, body: str) -> Path:
    (root / "product").mkdir(parents=True, exist_ok=True)
    p = root / "product" / "stack-profile.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_graph_config_declared_and_comment_stripped(tmp_path) -> None:
    _write_profile(tmp_path, 'product: 夹具\ngraph:\n  backend: cgc   # 唯一合法后端\n  pinned: "0.6.13"\n')
    cfg = _graph.load_graph_config(tmp_path)
    assert cfg == {"backend": "cgc", "pinned": "0.6.13"}


def test_graph_config_survives_following_sections(tmp_path) -> None:
    """graph 段不是文件末段时不得丢配置（2026-10-05 Polyvoice 真栈咬出）。"""
    _write_profile(tmp_path, 'product: 夹具\n'
                             'graph:\n  backend: cgc   # 注释\n  pinned: "0.6.13"\n'
                             'e2e:\n  runner: node-playwright\n')
    cfg = _graph.load_graph_config(tmp_path)
    assert cfg == {"backend": "cgc", "pinned": "0.6.13"}, cfg


def test_graph_config_null_and_absent(tmp_path) -> None:
    _write_profile(tmp_path, "product: 夹具\ngraph: null\n")
    assert _graph.load_graph_config(tmp_path) is None
    _write_profile(tmp_path, "product: 夹具\norigin: adopt\n")
    assert _graph.load_graph_config(tmp_path) is None


def test_graph_config_bad_backend_dies_loudly(tmp_path, capsys) -> None:
    _write_profile(tmp_path, "product: 夹具\ngraph:\n  backend: gitnexus\n")
    with pytest.raises(SystemExit):
        _graph.load_graph_config(tmp_path)
    assert "graph.backend 非法" in capsys.readouterr().err


def test_graph_config_scalar_form_dies_loudly(tmp_path, capsys) -> None:
    _write_profile(tmp_path, "product: 夹具\ngraph: cgc\n")
    with pytest.raises(SystemExit):
        _graph.load_graph_config(tmp_path)
    assert "形态非法" in capsys.readouterr().err
