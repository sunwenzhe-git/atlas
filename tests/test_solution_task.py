#!/usr/bin/env python3
"""solution task：requirements 解析、dry-run、幂等、status 的回归测试。"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]

FAKE_TASK = r'''#!/usr/bin/env python3
import datetime, json, pathlib, sys

root = pathlib.Path(__file__).resolve().parents[2]
tasks = root / ".trellis" / "tasks"
args = sys.argv[1:]

if args and args[0] == "create":
    if "--help" in args:
        print("--slug --assignee --description --meta --no-start")
        sys.exit(0)
    title = args[0]
    opts = {"meta": {}}
    i = 1
    while i < len(args):
        a = args[i]
        if a in ("--slug", "--assignee", "--description"):
            opts[a] = args[i + 1]
            i += 2
        elif a == "--meta":
            k, v = args[i + 1].split("=", 1)
            opts["meta"][k] = v
            i += 2
        elif a == "--no-start":
            opts["no_start"] = True
            i += 1
        else:
            i += 1
    name = datetime.datetime.now().strftime("%m-%d") + "-" + opts["--slug"]
    d = tasks / name
    d.mkdir(parents=True, exist_ok=False)
    (d / "task.json").write_text(json.dumps({
        "title": title, "description": opts.get("--description", ""),
        "assignee": opts.get("--assignee"), "meta": opts["meta"],
    }), encoding="utf-8")
    (d / "prd.md").write_text("# PRD\n\n" + opts.get("--description", "") + "\n", encoding="utf-8")
    (d / "implement.jsonl").write_text("", encoding="utf-8")
    (d / "check.jsonl").write_text("", encoding="utf-8")
    if not opts.get("no_start"):
        (root / ".trellis" / "active").write_text(name, encoding="utf-8")
    print("Created task: " + name, file=sys.stderr)
    sys.exit(0)

if args and args[0] == "add-context":
    if "--help" in args:
        print("task.py add-context dir implement|check path reason")
        sys.exit(0)
    d, kind, path, reason = args[1:5]
    target = root / d / (kind + ".jsonl")
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"file": path, "reason": reason}) + "\n")
    sys.exit(0)

sys.exit(2)
'''


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load("_solution_task_test_core", "_support/solution.py")
task_core = load("_solution_task_test_tasks", "_support/solution_task.py")


def make_member(root: Path, name: str, with_task_py: bool = True) -> Path:
    member = root / name
    (member / ".trellis" / "scripts").mkdir(parents=True, exist_ok=True)
    (member / ".trellis" / ".developer").write_text(
        "name=agent_learning\ninitialized_at=2026-11-05T00:00:00\n", encoding="utf-8")
    if with_task_py:
        (member / ".trellis" / "scripts" / "task.py").write_text(FAKE_TASK, encoding="utf-8")
    return member


def make_solution(root: Path, members=("a", "b"), requirements=None,
                  with_task_py: bool = True) -> dict:
    for name in members:
        make_member(root, name, with_task_py=with_task_py)
    reqs = requirements or [
        {"id": "REQ-001", "acs": ["AC-SOLUTION-001"], "member": "a",
         "task_slug": "req-001-api", "scope": "实现同步 API"},
        {"id": "REQ-001", "acs": ["AC-SOLUTION-001"], "member": "b",
         "task_slug": "req-001-ui", "scope": "接入同步入口"},
    ]
    core.init_solution(root, "demo", [(n, n, "fullstack") for n in members],
                       install=False, requirements=reqs)
    prd = root / "product" / "prd" / "solution-prd.md"
    prd.write_text(
        "# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n"
        "| AC-SOLUTION-001 | Given / When / Then | SOLUTION-R-001 |\n",
        encoding="utf-8",
    )
    return core.load_manifest(root)


def test_dry_run_zero_write(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    result = task_core.create_tasks(tmp_path, data, "REQ-001", apply=False)
    assert result["apply"] is False
    assert len(result["plans"]) == 2
    assert not list((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json"))


def test_apply_creates_tasks_without_start_and_with_context(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    result = task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    assert len(result["done"]) == 2
    expected = {"a": "实现同步 API", "b": "接入同步入口"}
    for name in ("a", "b"):
        task_dirs = [p for p in (tmp_path / name / ".trellis" / "tasks").iterdir()
                     if (p / "task.json").is_file()]
        assert len(task_dirs) == 1
        task = task_dirs[0]
        payload = __import__("json").loads((task / "task.json").read_text(encoding="utf-8"))
        assert payload["meta"]["solution"] == "demo"
        assert payload["meta"]["requirement"] == "REQ-001"
        assert payload["meta"]["member"] == name
        assert payload["assignee"] == "agent_learning"
        assert (task / "solution.md").is_file()
        assert expected[name] in (task / "solution.md").read_text(encoding="utf-8")
        assert (task / "implement.jsonl").read_text(encoding="utf-8").strip()
        assert (task / "check.jsonl").read_text(encoding="utf-8").strip()
        assert not (tmp_path / name / ".trellis" / "active").exists()
        assert expected[name] not in (task / "prd.md").read_text(encoding="utf-8")


def test_missing_task_py_preflight_writes_nothing(tmp_path: Path) -> None:
    make_member(tmp_path, "a")
    make_member(tmp_path, "b", with_task_py=False)
    data = make_solution(tmp_path, members=("a", "b"), with_task_py=False)
    # make_solution re-created a/b; ensure b lacks task.py
    (tmp_path / "b" / ".trellis" / "scripts" / "task.py").unlink(missing_ok=True)
    with pytest.raises(task_core.TaskError, match="task.py"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    assert not list((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json"))


def test_missing_ac_preflight(tmp_path: Path) -> None:
    data = make_solution(tmp_path, requirements=[
        {"id": "REQ-001", "acs": ["AC-SOLUTION-999"], "member": "a",
         "task_slug": "req-001-api", "scope": "实现同步 API"},
    ], members=("a",))
    with pytest.raises(task_core.TaskError, match="AC 定义行"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)


def test_resume_and_update(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    with pytest.raises(task_core.TaskError, match="已存在"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    resumed = task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, resume=True)
    assert all(p["action"] == "skip" for p in resumed["done"])
    before = [p.read_text(encoding="utf-8") for p in
              (tmp_path / "a" / ".trellis" / "tasks").glob("*/prd.md")]
    updated = task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, update=True)
    assert all(p["action"] == "update" for p in updated["done"])
    after = [p.read_text(encoding="utf-8") for p in
             (tmp_path / "a" / ".trellis" / "tasks").glob("*/prd.md")]
    assert before == after


def test_status_live_and_check_warns(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    task = next((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json")).parent
    __import__("shutil").rmtree(task)
    status = task_core.task_status(tmp_path, data, "REQ-001")
    assert not status["ok"]
    assert any("缺失" in w for w in status["warnings"])
    checked = core.check_solution(tmp_path)
    assert any("跨仓任务" in c["check"] for c in checked["checks"])


REAL_TASK = Path(os.environ.get("ATLAS_REAL_TRELLIS_TASK", ""))


@pytest.mark.skipif(not REAL_TASK.is_file(), reason="未提供 ATLAS_REAL_TRELLIS_TASK")
def test_real_trellis_cli_supports_required_flags() -> None:
    text = subprocess.run([sys.executable, str(REAL_TASK), "create", "--help"],
                          capture_output=True, text=True)
    out = text.stdout + text.stderr
    for flag in ("--slug", "--assignee", "--description", "--meta", "--no-start"):
        assert flag in out
    ctx = subprocess.run([sys.executable, str(REAL_TASK), "add-context", "--help"],
                         capture_output=True, text=True)
    assert "add-context" in (ctx.stdout + ctx.stderr)


def test_archive_layout_is_found_and_idempotent(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    task = next((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json")).parent
    archive = tmp_path / "a" / ".trellis" / "tasks" / "archive" / "2026-11"
    archive.mkdir(parents=True)
    task.rename(archive / task.name)

    status = task_core.task_status(tmp_path, data, "REQ-001")
    assert status["ok"] is True
    assert any(row["member"] == "a" and row["task"] for row in status["requirements"])
    with pytest.raises(task_core.TaskError, match="已存在"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    resumed = task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, resume=True)
    assert any(item["action"] in ("skip", "repair") for item in resumed["done"])
    updated = task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, update=True)
    assert any(item["action"] == "update" for item in updated["done"])


def test_resume_repairs_missing_context(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)
    task = next((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json")).parent
    (task / "check.jsonl").write_text("", encoding="utf-8")
    assert any("context" in w for w in task_core.task_status(tmp_path, data)["warnings"])
    task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, resume=True)
    assert (task / "check.jsonl").read_text(encoding="utf-8").strip()


def test_cross_day_slug_collision(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    d = tmp_path / "a" / ".trellis" / "tasks" / "01-01-req-001-api"
    d.mkdir(parents=True)
    (d / "task.json").write_text(
        json.dumps({"meta": {"solution": "other", "requirement": "X", "member": "a"}}),
        encoding="utf-8",
    )
    with pytest.raises(task_core.TaskError, match="task_slug 冲突"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True)


def test_cli_dry_run_flag(tmp_path: Path) -> None:
    make_solution(tmp_path)
    script = PKG_ROOT / "scripts" / "atlas_solution.py"
    res = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path),
         "task", "create", "--requirement", "REQ-001", "--dry-run"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "DRY-RUN" in res.stdout
    assert not list((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json"))


def test_assignee_env_overrides_developer(tmp_path: Path, monkeypatch) -> None:
    data = make_solution(tmp_path)
    monkeypatch.setenv("TRELLIS_DEVELOPER", "alice")
    task_core.create_tasks(tmp_path, data, "REQ-001", members=["a"], apply=True)
    task = next((tmp_path / "a" / ".trellis" / "tasks").glob("*/task.json")).parent
    payload = __import__("json").loads((task / "task.json").read_text(encoding="utf-8"))
    assert payload["assignee"] == "alice"


def test_update_without_existing_errors(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    with pytest.raises(task_core.TaskError, match="--update"):
        task_core.create_tasks(tmp_path, data, "REQ-001", apply=True, update=True)


def test_status_unknown_requirement(tmp_path: Path) -> None:
    data = make_solution(tmp_path)
    result = task_core.task_status(tmp_path, data, "REQ-999")
    assert result["ok"] is False
    assert any("requirement 不存在" in w for w in result["warnings"])


def test_cli_task_dry_run_json(tmp_path: Path) -> None:
    make_solution(tmp_path)
    script = PKG_ROOT / "scripts" / "atlas_solution.py"
    res = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path),
         "task", "create", "--requirement", "REQ-001", "--json"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    payload = __import__("json").loads(res.stdout)
    assert payload["apply"] is False
    assert len(payload["plans"]) == 2


def test_scope_hash_is_round_tripped(tmp_path: Path) -> None:
    data = make_solution(tmp_path, requirements=[
        {"id": "REQ-001", "acs": ["AC-SOLUTION-001"], "member": "a",
         "task_slug": "req-001-api", "scope": "同步 # 备注"},
    ], members=("a",))
    loaded = core.load_manifest(tmp_path)
    assert loaded["requirements"][0]["scope"] == "同步 # 备注"
