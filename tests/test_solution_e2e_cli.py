#!/usr/bin/env python3
"""RFC-20261108-02 一期：`atlas solution e2e status / verify / init` 入口。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_solution.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_atlas_solution_cli_core", "_support/solution.py")


def req(rid: str, member: str, **extra) -> dict:
    out = {"id": rid, "acs": "AC-SOLUTION-001", "member": member,
           "task_slug": f"{member}-task", "scope": "演示"}
    out.update(extra)
    return out


def make_solution(tmp_path: Path, requirements: list[dict]) -> None:
    for name in ("web", "api"):
        (tmp_path / name).mkdir()
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False, requirements=requirements,
    )


def run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "e2e", *args],
        capture_output=True, text=True, cwd=str(tmp_path),
    )


def test_cli_init_creates_skeleton(tmp_path: Path) -> None:
    make_solution(tmp_path, [])
    res = run(tmp_path, "init", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["created"] is True
    assert Path(payload["index"]).is_file()


def test_cli_status_single_member_none_is_na(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web", cross_repo_e2e="none")])
    run(tmp_path, "init", "--json")
    res = run(tmp_path, "status", "--requirement", "REQ-001", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["verdict"] == "N/A"
    assert payload["requirements"][0]["state"] == "na"


def test_cli_status_multi_member_none_is_blocked(tmp_path: Path) -> None:
    make_solution(tmp_path, [
        req("REQ-001", "web"),
        req("REQ-001", "api", cross_repo_e2e="none"),
    ])
    run(tmp_path, "init", "--json")
    res = run(tmp_path, "status", "--requirement", "REQ-001", "--json")
    assert res.returncode == 3, res.stderr
    assert json.loads(res.stdout)["verdict"] == "BLOCKED"


def test_cli_verify_fails_on_missing_selector(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web")])
    run(tmp_path, "init", "--json")
    res = run(tmp_path, "verify", "--json")
    assert res.returncode == 1, res.stderr
    payload = json.loads(res.stdout)
    assert payload["verdict"] == "FAIL"
    assert any(c["status"] == "FAIL" for c in payload["checks"])


def test_cli_verify_clean_parent_passes(tmp_path: Path) -> None:
    make_solution(tmp_path, [])
    run(tmp_path, "init", "--json")
    res = run(tmp_path, "verify", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["verdict"] == "PASS"


def test_cli_migrate_reports_affected_cases(tmp_path: Path) -> None:
    make_solution(tmp_path, [])
    run(tmp_path, "init", "--json")
    cases = tmp_path / "product" / "e2e" / "cases"
    (cases / "solution-flow.md").write_text(
        "# solution-flow\n\n```atlas-case\nid: E2E-SOLUTION-001\n"
        "intent: 跨仓下单\npages: solution-flow\nstep: goto /\n"
        "expected: 成功\n```\n", encoding="utf-8")
    res = run(tmp_path, "init", "--migrate", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["migrated"] == [{"file": "solution-flow.md",
                                    "case": "E2E-SOLUTION-001"}]


def test_cli_rejects_non_solution_root(tmp_path: Path) -> None:
    res = run(tmp_path, "status", "--json")
    assert res.returncode == 2
    assert "不是父仓" in res.stderr
