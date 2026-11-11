#!/usr/bin/env python3
"""RFC-20261108-02 一期：父仓模式校验器（E2E 索引 / testid）反面包。

全部用真实目录 + 真实清单/索引/分片，不 monkeypatch：校验器必须真的报 FAIL / WARN / N/A。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

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


core = _load("_atlas_solution_validator_core", "_support/solution.py")
e2e = _load("_atlas_solution_validator_kernel", "_support/solution_e2e.py")
v_index = _load("_atlas_validate_e2e_index_test", "validators/validate_e2e_index.py")
v_testids = _load("_atlas_validate_testids_test", "validators/validate_testids.py")


def req(rid: str, member: str, **extra) -> dict:
    out = {"id": rid, "acs": "AC-SOLUTION-001", "member": member,
           "task_slug": f"{member}-task", "scope": "演示"}
    out.update(extra)
    return out


def make_parent(tmp_path: Path, requirements: list[dict]) -> None:
    for name in ("web", "api"):
        (tmp_path / name).mkdir()
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False, requirements=requirements,
    )


def write_prd(tmp_path: Path, extra_prose: str = "") -> None:
    (tmp_path / "product" / "prd" / "solution-prd.md").write_text(
        "---\ndomain: \"solution\"\n---\n\n# solution\n\n"
        "| AC ID | 描述 |\n|---|---|\n| AC-SOLUTION-001 | 跨仓下单 |\n\n"
        + extra_prose,
        encoding="utf-8",
    )


def case_block(cid: str = "E2E-SOLUTION-001",
               deps: str | None = "web") -> str:
    text = (
        f"```atlas-case\nid: {cid}\nintent: 证明跨仓下单成功\n"
        "pages:\n  - solution-flow\nprecondition:\n  - 已进入跨仓流\n"
        "step:\n  - goto /\nexpected:\n  - 可见文案「下单成功」\n"
        f"testid:\n  - solution-flow-x\n"
    )
    if deps is not None:
        text += f"成员依赖: {deps}\n" if deps else "成员依赖:\n"
    return text + "```\n"


def write_index(tmp_path: Path, rows: list[tuple[str, ...]],
                reverse: str = "| solution-flow | E2E-SOLUTION-001 | |") -> None:
    e2e.init(tmp_path)
    path = e2e.index_path(tmp_path)
    text = path.read_text(encoding="utf-8")
    injected = _HEADER + "\n" + _SEP + "\n"
    injected += "".join("| " + " | ".join(r) + " |\n" for r in rows)
    text = text.replace(_HEADER + "\n" + _SEP, injected, 1)
    text = text.replace("| solution-flow | | |", reverse, 1)
    path.write_text(text, encoding="utf-8")


def write_shard(tmp_path: Path, body: str) -> None:
    (tmp_path / "product" / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    (tmp_path / "product" / "e2e" / "cases" / "solution-flow.md").write_text(
        "# solution-flow\n\n## E2E-SOLUTION-001 跨仓流\n\n" + body, encoding="utf-8")


def main_row(cid: str = "E2E-SOLUTION-001", demand: str = "",
             ac: str = "AC-SOLUTION-001") -> tuple[str, ...]:
    return (cid, "solution-flow", "跨仓流", "acceptance", ac, demand,
            "red", "", "cases/solution-flow.md#e2e-solution-001")


def levels(result) -> dict[str, str]:
    return {c["check"]: c["level"] for c in result.checks}


def details(result, check: str) -> str:
    return next(c["detail"] for c in result.checks if c["check"] == check)


# ---------------------------------------------------------------- 父仓门控态

def test_parent_no_index_without_case_ids_warns(tmp_path: Path) -> None:
    make_parent(tmp_path, [])
    result = v_index.validate(tmp_path)
    assert levels(result)["门控态"] == "WARN"
    assert "未初始化" in details(result, "门控态")


def test_parent_no_index_with_case_ids_fails(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    result = v_index.validate(tmp_path)
    assert levels(result)["门控态"] == "FAIL"


def test_single_repo_without_index_still_na(tmp_path: Path) -> None:
    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: product\n", encoding="utf-8")
    (tmp_path / "product").mkdir()
    result = v_index.validate(tmp_path)
    assert levels(result)["门控态"] == "N/A"


# ---------------------------------------------------------------- 成员依赖

def _run_with_deps(tmp_path: Path, deps: str | None, body=None) -> dict:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, body if body is not None else case_block(deps=deps))
    return levels(v_index.validate(tmp_path))


def test_member_dependency_missing_fails(tmp_path: Path) -> None:
    lv = _run_with_deps(tmp_path, deps=None)
    assert lv["成员依赖必填"] == "FAIL"


def test_member_dependency_empty_is_ok(tmp_path: Path) -> None:
    lv = _run_with_deps(tmp_path, deps="")
    assert lv["成员依赖必填"] == "PASS"


def test_member_dependency_literal_empty_list_is_ok(tmp_path: Path) -> None:
    lv = _run_with_deps(tmp_path, deps="[]")
    assert lv["成员依赖必填"] == "PASS"


def test_member_dependency_unknown_member_fails(tmp_path: Path) -> None:
    lv = _run_with_deps(tmp_path, deps="ghost")
    assert lv["成员依赖成员存在"] == "FAIL"


def test_member_dependency_shared_union_mismatch_fails(tmp_path: Path) -> None:
    make_parent(tmp_path, [
        req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"]),
        req("REQ-002", "api", case_ids=["E2E-SOLUTION-001"]),
    ])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row(demand="REQ-001,REQ-002")])
    write_shard(tmp_path, case_block(deps="web"))
    lv = levels(v_index.validate(tmp_path))
    assert lv["成员依赖共享并集"] == "FAIL"


def test_member_dependency_shared_union_matches(tmp_path: Path) -> None:
    make_parent(tmp_path, [
        req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"]),
        req("REQ-002", "api", case_ids=["E2E-SOLUTION-001"]),
    ])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row(demand="REQ-001,REQ-002")])
    write_shard(tmp_path, (
        "```atlas-case\nid: E2E-SOLUTION-001\nintent: 证明跨仓下单成功\n"
        "pages:\n  - solution-flow\nprecondition:\n  - 已进入跨仓流\n"
        "step:\n  - goto /\nexpected:\n  - 可见文案「下单成功」\n"
        "testid:\n  - solution-flow-x\n成员依赖:\n  - web\n  - api\n```\n"
    ))
    assert levels(v_index.validate(tmp_path))["成员依赖共享并集"] == "PASS"


# ---------------------------------------------------------------- AC / 反向视图

def test_parent_ac_requires_definition_row(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    # AC 只出现在散文里，不是 AC 表定义行。
    write_prd(tmp_path, "\n补充说明：AC-SOLUTION-009 只在这里被提到。\n")
    write_index(tmp_path, [main_row(ac="AC-SOLUTION-009")])
    write_shard(tmp_path, case_block())
    result = v_index.validate(tmp_path)
    assert levels(result)["关联AC 可达"] == "FAIL"
    assert "E2E-SOLUTION-001" in details(result, "关联AC 可达")


def test_parent_reverse_view_requires_empty_cells(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()], reverse="| solution-flow | — | — |")
    write_shard(tmp_path, case_block(deps=""))
    result = v_index.validate(tmp_path)
    assert levels(result)["反向视图一致"] == "FAIL"


def test_parent_multi_value_ac_counts_each_token(tmp_path: Path) -> None:
    """RFC-20261111-03 §1.6：父仓 `关联AC` 多值逐 token 可达，父仓挂靠统计同源拆分。"""
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    (tmp_path / "product" / "prd" / "solution-prd.md").write_text(
        "---\ndomain: \"solution\"\n---\n\n# solution\n\n"
        "| AC ID | 描述 |\n|---|---|\n"
        "| AC-SOLUTION-001 | 跨仓下单 |\n| AC-SOLUTION-002 | 跨仓退款 |\n",
        encoding="utf-8")
    write_index(tmp_path, [main_row(ac="AC-SOLUTION-001、AC-SOLUTION-002")])
    write_shard(tmp_path, case_block())
    result = v_index.validate(tmp_path)
    assert levels(result)["关联AC 格式"] == "PASS"
    assert levels(result)["关联AC 可达"] == "PASS"
    cov = e2e._ac_coverage(tmp_path, {
        "present": True, "ok": True,
        "rows": [{"关联AC": "AC-SOLUTION-001、AC-SOLUTION-002"}],
    })
    assert cov["attached"] == 2, cov
    assert cov["zero_attached"] == [], cov


def test_parent_multi_value_ac_illegal_token_fails(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row(ac="AC-SOLUTION-001、AC-SOLUTION-1")])
    write_shard(tmp_path, case_block())
    assert levels(v_index.validate(tmp_path))["关联AC 格式"] == "FAIL"


# ---------------------------------------------------------------- 用例第二落点（#54）

def test_parent_second_landing_fails_for_task_dir_case_outside_index(tmp_path: Path) -> None:
    """RFC-20261111-03 §2.4：成员 `.trellis/tasks/**/cases.md` 出现索引外用例 ID ⇒ FAIL。"""
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    task_dir = tmp_path / "web" / ".trellis" / "tasks" / "T-1"
    task_dir.mkdir(parents=True)
    (task_dir / "cases.md").write_text(
        "# 任务用例\n\n用例 E2E-SOLUTION-777 写在任务目录里。\n", encoding="utf-8")
    result = v_index.validate(tmp_path)
    assert levels(result)["用例第二落点"] == "FAIL", result
    assert "E2E-SOLUTION-777" in details(result, "用例第二落点")


def test_parent_second_landing_passes_when_task_dir_ids_are_in_index(tmp_path: Path) -> None:
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    task_dir = tmp_path / "api" / ".trellis" / "tasks" / "T-2"
    task_dir.mkdir(parents=True)
    (task_dir / "cases.md").write_text(
        "已迁入索引：E2E-SOLUTION-001。\n", encoding="utf-8")
    assert levels(v_index.validate(tmp_path))["用例第二落点"] == "PASS"


# ---------------------------------------------------------------- testid N/A

def test_testids_parent_mode_is_na(tmp_path: Path) -> None:
    make_parent(tmp_path, [])
    result = v_testids.validate(tmp_path)
    assert result.status == "N/A"
    assert "成员仓隔离" in details(result, "门控态")
