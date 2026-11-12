#!/usr/bin/env python3
"""#52①：`atlas solution task acceptance --backfill` 夹具（K-11 / §1.3.7）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
SCRIPT = PKG / "scripts" / "atlas_solution.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_c_backfill", "_support/solution.py")
card = _load("_v_backfill", "validators/validate_task_card.py")

CARD_REL = ".trellis/tasks/01-r1/prd.md"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def commit(cwd: Path, message: str) -> None:
    git(cwd, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", message)


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root),
                           *args], capture_output=True, text=True)


def new_repo(tmp: Path) -> Path:
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
    commit(web, "init")
    core.init_solution(
        tmp, "demo", [("web", "web", "frontend")], install=False,
        requirements=[{"id": "R1", "member": "web",
                       "acs": ["AC-SOLUTION-001"], "case_ids": [],
                       "task_slug": "r1", "scope": ["AC-SOLUTION-001"]}])
    task = web / ".trellis" / "tasks" / "01-r1"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({"meta": {
        "solution": "demo", "requirement": "R1", "member": "web"}}),
        encoding="utf-8")
    (task / "solution.md").write_text("# 指针\n\n- acs: AC-SOLUTION-001\n",
                                      encoding="utf-8")
    (task / "prd.md").write_text("# 任务卡\n\n正文。\n", encoding="utf-8")
    git(web, "add", "-A")
    commit(web, "task card")
    git(tmp, "add", "-A")
    commit(tmp, "assets")
    return tmp


def test_k11_backfill_appends_from_pointer(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    res = run(root, "task", "acceptance", "--backfill", "--apply", "--json")
    assert res.returncode == 0, res.stderr
    text = (root / "web" / CARD_REL).read_text(encoding="utf-8")
    assert text == "# 任务卡\n\n正文。\natlas-acceptance: AC-SOLUTION-001\n"
    # 该绿的还绿：成员侧卡门不再报专用行缺失
    errors, _ = card.validate(root / "web")
    assert "card_acceptance_missing" not in [e["code"] for e in errors]


def test_k11_backfill_refuses_existing_line(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    assert run(root, "task", "acceptance", "--backfill", "--apply").returncode == 0
    before = (root / "web" / CARD_REL).read_bytes()
    again = run(root, "task", "acceptance", "--backfill", "--apply")
    assert again.returncode == 2
    assert (root / "web" / CARD_REL).read_bytes() == before


def test_k11_backfill_ignores_fenced_and_commented_lines(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    prd = root / "web" / CARD_REL
    original = ("# 任务卡\n\n```text\natlas-acceptance: AC-SOLUTION-001\n```\n\n"
                "<!--\natlas-acceptance: AC-SOLUTION-001\n-->\n")
    prd.write_text(original, encoding="utf-8")
    git(root / "web", "add", "-A")
    commit(root / "web", "fenced only")
    res = run(root, "task", "acceptance", "--backfill", "--apply")
    assert res.returncode == 0, res.stderr
    assert prd.read_text(encoding="utf-8") == (
        original + "atlas-acceptance: AC-SOLUTION-001\n")


def test_k11_backfill_dry_run_does_not_write(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    before = (root / "web" / CARD_REL).read_bytes()
    res = run(root, "task", "acceptance", "--backfill")
    assert res.returncode == 0
    assert "[DRY-RUN]" in res.stdout
    assert (root / "web" / CARD_REL).read_bytes() == before
