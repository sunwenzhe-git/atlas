#!/usr/bin/env python3
"""RFC-20261108-02 一期：父仓跨仓 E2E 清单解析 / 选择器 / solution check 专项。

反面包（RFC §4.5.4）在这里逐条咬红：不是 monkeypatch 自证，而是构造真实清单 + 索引，
断言 `solution check` / 选择器真的给出 FAIL / BLOCKED。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]

MAIN_COLUMNS = ("用例ID", "页面", "中文标题", "类型", "关联AC", "需求",
                "状态", "状态原因", "分片")
_HEADER = "| " + " | ".join(MAIN_COLUMNS) + " |"
_SEP = "|---" * len(MAIN_COLUMNS) + "|"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_atlas_solution_e2e_test_core", "_support/solution.py")
e2e = _load("_atlas_solution_e2e_test_kernel", "_support/solution_e2e.py")
case_block = _load("_atlas_solution_e2e_test_block", "_support/case_block.py")


# ---------------------------------------------------------------- fixtures

def make_solution(tmp_path: Path, requirements: list[dict]) -> dict:
    for name in ("web", "api"):
        (tmp_path / name).mkdir()
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False, requirements=requirements,
    )
    return core.load_manifest(tmp_path)


def req(rid: str, member: str, **extra) -> dict:
    out = {"id": rid, "acs": "AC-SOLUTION-001", "member": member,
           "task_slug": f"{member}-task", "scope": "演示"}
    out.update(extra)
    return out


def write_rows(root: Path, rows: list[tuple[str, ...]]) -> None:
    e2e.init(root)
    path = e2e.index_path(root)
    text = path.read_text(encoding="utf-8")
    injected = _HEADER + "\n" + _SEP + "\n"
    injected += "".join("| " + " | ".join(r) + " |\n" for r in rows)
    assert _HEADER + "\n" + _SEP in text
    path.write_text(text.replace(_HEADER + "\n" + _SEP, injected, 1), encoding="utf-8")


def row(cid: str, demand: str = "", page: str = "solution-flow") -> tuple[str, ...]:
    return (cid, page, "跨仓流", "功能", "AC-SOLUTION-001", demand, "待测", "", "cases/x.md")


def e2e_checks(root: Path) -> dict[str, dict]:
    report = core.check_solution(root)
    return {c["check"]: c for c in report["checks"] if c["check"].startswith("父仓 E2E")}


# ---------------------------------------------------------------- 清单解析

def test_manifest_parses_case_ids_and_cross_repo_e2e(tmp_path: Path) -> None:
    text = (
        "version: 1\nsolution: demo\nmode: federated\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n"
        "requirements:\n"
        "  - id: REQ-001\n    member: web\n    acs: AC-SOLUTION-001\n"
        "    task_slug: web-task\n    scope: 演示\n"
        "    case_ids: E2E-SOLUTION-001, E2E-SOLUTION-002\n"
    )
    data = core.validate_manifest(core.parse_manifest_text(text), tmp_path)
    req = data["requirements"][0]
    assert req["case_ids"] == ["E2E-SOLUTION-001", "E2E-SOLUTION-002"]
    assert req["case_ids_present"] is True
    assert req["cross_repo_e2e"] is None


def test_manifest_rejects_bad_case_id(tmp_path: Path) -> None:
    text = (
        "version: 1\nsolution: demo\nmode: federated\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n"
        "requirements:\n"
        "  - id: REQ-001\n    member: web\n    acs: AC-SOLUTION-001\n"
        "    task_slug: web-task\n    scope: 演示\n    case_ids: CASE-1\n"
    )
    with pytest.raises(core.SolutionError, match="case_id 文法非法"):
        core.validate_manifest(core.parse_manifest_text(text), tmp_path)


def test_manifest_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    text = (
        "version: 1\nsolution: demo\nmode: federated\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n"
        "requirements:\n"
        "  - id: REQ-001\n    member: web\n    acs: AC-SOLUTION-001\n"
        "    task_slug: web-task\n    scope: 演示\n"
        "    case_ids: E2E-SOLUTION-001,E2E-SOLUTION-001\n"
    )
    with pytest.raises(core.SolutionError, match="case_ids 重复"):
        core.validate_manifest(core.parse_manifest_text(text), tmp_path)


def test_manifest_rejects_selector_mutual_exclusion(tmp_path: Path) -> None:
    text = (
        "version: 1\nsolution: demo\nmode: federated\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n"
        "requirements:\n"
        "  - id: REQ-001\n    member: web\n    acs: AC-SOLUTION-001\n"
        "    task_slug: web-task\n    scope: 演示\n"
        "    case_ids: E2E-SOLUTION-001\n    cross_repo_e2e: none\n"
    )
    with pytest.raises(core.SolutionError, match="同时出现"):
        core.validate_manifest(core.parse_manifest_text(text), tmp_path)


def test_manifest_rejects_non_none_cross_repo_e2e(tmp_path: Path) -> None:
    text = (
        "version: 1\nsolution: demo\nmode: federated\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n"
        "requirements:\n"
        "  - id: REQ-001\n    member: web\n    acs: AC-SOLUTION-001\n"
        "    task_slug: web-task\n    scope: 演示\n    cross_repo_e2e: partial\n"
    )
    with pytest.raises(core.SolutionError, match="只能是 none"):
        core.validate_manifest(core.parse_manifest_text(text), tmp_path)


# ---------------------------------------------------------------- solution check 选择器

def test_multi_member_none_fails(tmp_path: Path) -> None:
    make_solution(tmp_path, [
        req("REQ-001", "web"),
        req("REQ-001", "api", cross_repo_e2e="none"),
    ])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 选择器"]["status"] == "FAIL"
    assert "禁止 cross_repo_e2e: none" in checks["父仓 E2E 选择器"]["detail"]
    report = core.check_solution(tmp_path)
    assert report["e2e"]["requirements_without_case_ids"] == ["REQ-001"]
    assert report["overall"] == "FAIL"


def test_multi_member_without_selector_fails(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web"), req("REQ-001", "api")])
    assert e2e_checks(tmp_path)["父仓 E2E 选择器"]["status"] == "FAIL"


def test_single_member_none_is_na(tmp_path: Path) -> None:
    data = make_solution(tmp_path, [req("REQ-001", "web", cross_repo_e2e="none")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 选择器"]["status"] == "PASS"
    assert "N/A" in checks["父仓 E2E 选择器"]["detail"]
    # 单成员 none 是事实陈述：不要求索引存在，索引缺失只 WARN。
    assert checks["父仓 E2E 索引"]["status"] == "WARN"
    result = e2e.status(data, e2e.read_index(tmp_path), "REQ-001")
    assert result["verdict"] == "N/A"
    assert result["exit"] == 0


def test_single_member_without_selector_fails(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 选择器"]["status"] == "FAIL"
    assert "二选一" in checks["父仓 E2E 选择器"]["detail"]


def test_declared_case_ids_without_index_fails(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 索引"]["status"] == "FAIL"
    assert "case_ids" in checks["父仓 E2E 索引"]["detail"]


def test_case_ids_missing_from_index_fails(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_rows(tmp_path, [row("E2E-SOLUTION-002")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E case_ids 引用"]["status"] == "FAIL"
    assert "E2E-SOLUTION-001" in checks["父仓 E2E case_ids 引用"]["detail"]


def test_selector_hits_existing_case(tmp_path: Path) -> None:
    data = make_solution(tmp_path, [
        req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"]),
    ])
    write_rows(tmp_path, [row("E2E-SOLUTION-001")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 选择器接线"]["status"] == "PASS"
    grid = e2e.read_index(tmp_path)
    assert e2e.select(data, "REQ-001", grid)["selected"] == ["E2E-SOLUTION-001"]
    assert e2e.status(data, grid, "REQ-001")["verdict"] == "OK"


def test_shared_case_demand_column_must_list_all_consumers(tmp_path: Path) -> None:
    make_solution(tmp_path, [
        req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"]),
        req("REQ-002", "api", case_ids=["E2E-SOLUTION-001"]),
    ])
    write_rows(tmp_path, [row("E2E-SOLUTION-001", demand="REQ-001")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 需求列一致"]["status"] == "FAIL"
    assert "REQ-002" in checks["父仓 E2E 需求列一致"]["detail"]

    write_rows(tmp_path, [row("E2E-SOLUTION-001", demand="REQ-001,REQ-002")])
    assert e2e_checks(tmp_path)["父仓 E2E 需求列一致"]["status"] == "PASS"


def test_single_consumer_demand_column_may_be_empty(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_rows(tmp_path, [row("E2E-SOLUTION-001")])
    assert e2e_checks(tmp_path)["父仓 E2E 需求列一致"]["status"] == "PASS"


def test_orphan_case_is_warned_not_deleted(tmp_path: Path) -> None:
    make_solution(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_rows(tmp_path, [row("E2E-SOLUTION-001"), row("E2E-SOLUTION-009")])
    checks = e2e_checks(tmp_path)
    assert checks["父仓 E2E 孤儿用例"]["status"] == "WARN"
    assert "E2E-SOLUTION-009" in checks["父仓 E2E 孤儿用例"]["detail"]
    assert core.check_solution(tmp_path)["e2e"]["orphan_cases"] == ["E2E-SOLUTION-009"]


# ---------------------------------------------------------------- init / migrate

def test_e2e_init_is_idempotent(tmp_path: Path) -> None:
    make_solution(tmp_path, [])
    first = e2e.init(tmp_path)
    assert first["created"] is True
    assert e2e.index_path(tmp_path).is_file()
    assert e2e.read_index(tmp_path)["ok"] is True
    snapshot = e2e.index_path(tmp_path).read_text(encoding="utf-8")
    second = e2e.init(tmp_path)
    assert second["created"] is False
    assert e2e.index_path(tmp_path).read_text(encoding="utf-8") == snapshot


def test_migrate_fills_member_dependency(tmp_path: Path) -> None:
    make_solution(tmp_path, [])
    e2e.init(tmp_path)
    cases = tmp_path / "product" / "e2e" / "cases"
    shard = cases / "solution-flow.md"
    shard.write_text(
        "# 跨仓流\n\n```atlas-case\nid: E2E-SOLUTION-001\n"
        "intent: 跨仓下单\npages: solution-flow\nstep: goto /\n"
        "expected: 成功\n```\n",
        encoding="utf-8",
    )
    result = e2e.init(tmp_path, migrate=True)
    assert result["migrated"] == [{"file": "solution-flow.md",
                                   "case": "E2E-SOLUTION-001"}]
    text = shard.read_text(encoding="utf-8")
    assert "成员依赖:\n" in text
    parsed = case_block.parse_block(text.split("```atlas-case\n", 1)[1].split("```", 1)[0])
    assert parsed["成员依赖"] == []
    # 幂等：再跑一次不再改。
    assert e2e.init(tmp_path, migrate=True)["migrated"] == []


def test_case_block_normalizes_member_dependency(tmp_path: Path) -> None:
    assert case_block.parse_block("成员依赖:\n")["成员依赖"] == []
    assert case_block.parse_block("成员依赖: []\n")["成员依赖"] == []
    parsed = case_block.parse_block("成员依赖: api\n")
    assert parsed["成员依赖"] == ["api"]
    assert "成员依赖" in case_block.block_keys("成员依赖:\n")
    assert "成员依赖" not in case_block.block_keys("id: E2E-SOLUTION-001\n")
