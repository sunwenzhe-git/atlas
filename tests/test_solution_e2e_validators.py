#!/usr/bin/env python3
"""RFC-20261108-02 一期：父仓模式校验器（E2E 索引 / testid）反面包。

全部用真实目录 + 真实清单/索引/分片，不 monkeypatch：校验器必须真的报 FAIL / WARN / N/A。
"""
from __future__ import annotations

import importlib.util
import re
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

def make_v2(root: Path) -> None:
    """把 init 产出的 v1 清单升到 v2（版本门：0.4.0 读者只收 v2）。

    只做文本层面的最小补充，不重排既有块——本文件测的是 #54 的第二落点，不是迁移。
    """
    path = root / core.MANIFEST_NAME
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^version:\s*1\s*$", text, re.M):
        return
    text = re.sub(r"^version:\s*1\s*$", "version: 2", text, count=1, flags=re.M)
    text = text.replace(
        "mode: federated\n",
        "mode: federated\ndefinition:\n  domain: solution\n"
        "  path: product/prd/solution-prd.md\nacceptance_cutover: 2027-03-31\n", 1)
    path.write_text(text, encoding="utf-8")


def set_reader_version(root: Path, version: str) -> None:
    """RFC §5.3：`reader_version` 读 `<root>/.atlas/VERSION`（B-0 的 semver 注入点）。

    reader ≥0.4.0 时清单必须是 v2，否则 `load_manifest` 会被版本门硬拒（清单门）。
    """
    (root / ".atlas").mkdir(exist_ok=True)
    (root / ".atlas" / "VERSION").write_text(version + "\n", encoding="utf-8")
    if version and not core.semver_lt(version, (0, 4, 0)):
        make_v2(root)


def test_parent_second_landing_fails_for_task_dir_case_outside_index(tmp_path: Path) -> None:
    """RFC-20261111-03 §2.4：成员 `.trellis/tasks/**/cases.md` 出现索引外用例 ID ⇒ FAIL。"""
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    set_reader_version(tmp_path, "0.4.0")
    task_dir = tmp_path / "web" / ".trellis" / "tasks" / "T-1"
    task_dir.mkdir(parents=True)
    (task_dir / "cases.md").write_text(
        "# 任务用例\n\n用例 E2E-SOLUTION-777 写在任务目录里。\n", encoding="utf-8")
    result = v_index.validate(tmp_path)
    assert levels(result)["用例第二落点"] == "FAIL", result
    assert "E2E-SOLUTION-777" in details(result, "用例第二落点")


def test_m06_any_case_row_is_second_landing_regardless_of_id_prefix(tmp_path: Path) -> None:
    """M-06：不看 ID 是否 `E2E-*`；0.3.x WARN、0.4.0 起 FAIL；含 archive 任务目录。"""
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    active = tmp_path / "web" / ".trellis" / "tasks" / "T-9"
    active.mkdir(parents=True)
    (active / "cases.md").write_text(
        "# 任务用例\n\n| 用例ID | 场景 |\n|---|---|\n| BE-SYNC-001 | 同步重试成功 |\n",
        encoding="utf-8")
    archived = tmp_path / "web" / ".trellis" / "tasks" / "archive" / "2026-10" / "T-8"
    archived.mkdir(parents=True)
    (archived / "cases.md").write_text(
        "# 归档用例\n\n| HC-RECORD-001 | 记录回放 |\n|---|---|\n", encoding="utf-8")

    set_reader_version(tmp_path, "0.3.0")
    warn = v_index.validate(tmp_path)
    assert levels(warn)["用例第二落点"] == "WARN", warn
    assert "BE-SYNC-001" in details(warn, "用例第二落点")

    set_reader_version(tmp_path, "0.4.0")
    fail = v_index.validate(tmp_path)
    assert levels(fail)["用例第二落点"] == "FAIL", fail
    detail = details(fail, "用例第二落点")
    assert "task_dir_case_duplicate" in detail
    assert ".trellis/tasks/T-9/cases.md" in detail
    assert ".trellis/tasks/archive/2026-10/T-8/cases.md" in detail


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


def _task_case_fixture(tmp_path: Path) -> None:
    """父仓 + 一张索引外用例行的成员任务目录（#54 必红的最小现场）。"""
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    task_dir = tmp_path / "web" / ".trellis" / "tasks" / "T-9"
    task_dir.mkdir(parents=True)
    (task_dir / "cases.md").write_text(
        "# 任务用例\n\n| 用例ID | 场景 |\n|---|---|\n| BE-SYNC-001 | 同步重试成功 |\n",
        encoding="utf-8")


def test_reader_version_ignores_checked_repo_package_json(tmp_path: Path,
                                                         monkeypatch) -> None:
    """评审阻断 1：`reader_version` 只认工具自身来源，被检查仓 `package.json` 不参与分级。

    现场刻意让「被检查仓版本 ≠ 工具版本」：被检查仓写 `0.4.0`、工具包写 `0.3.0`
    ⇒ #54 仍判 WARN；判据跟着**工具**走，不跟着被检查仓走。
    """
    _task_case_fixture(tmp_path)
    tool = tmp_path / "toolroot"
    (tool / "validators").mkdir(parents=True)
    (tool / "package.json").write_text('{"version": "0.3.0"}', encoding="utf-8")
    monkeypatch.setattr(v_index, "__file__",
                        str(tool / "validators" / "validate_e2e_index.py"))
    (tmp_path / "package.json").write_text('{"version": "0.4.0"}', encoding="utf-8")
    assert not (tmp_path / ".atlas").exists()

    warn = v_index.validate(tmp_path)
    assert levels(warn)["用例第二落点"] == "WARN", warn
    assert "BE-SYNC-001" in details(warn, "用例第二落点")

    # 第二级是装配副本自带的 `.atlas/package.json`（工具自身），0.4.0 ⇒ 升 FAIL
    (tmp_path / ".atlas").mkdir()
    (tmp_path / ".atlas" / "package.json").write_text(
        '{"version": "0.4.0"}', encoding="utf-8")
    make_v2(tmp_path)  # reader 0.4.0 ⇒ 清单必须是 v2，否则清单门先红
    fail = v_index.validate(tmp_path)
    assert levels(fail)["用例第二落点"] == "FAIL", fail

    # 第一级 `.atlas/VERSION` 优先于第二级
    (tmp_path / ".atlas" / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    assert levels(v_index.validate(tmp_path))["用例第二落点"] == "WARN"


@pytest.mark.parametrize("header", ["编号", "ID", "序号", "用例"])
def test_task_case_rows_under_generic_header(tmp_path: Path, header: str) -> None:
    """复核：表头写 `编号` / `ID` / `序号` / `用例` 时，**索引内** ID 也必须被认成用例行。

    刻意用索引已声明的 `E2E-SOLUTION-001`：`索引外 ID` 判据恒空，红只可能来自
    「用例行」本身（否则把表头门加回去这四条照样绿，是假钉）。
    """
    make_parent(tmp_path, [req("REQ-001", "web", case_ids=["E2E-SOLUTION-001"])])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    task = tmp_path / "web" / ".trellis" / "tasks" / "T-HDR"
    task.mkdir(parents=True)
    (task / "cases.md").write_text(
        f"| {header} | 场景 |\n|---|---|\n| E2E-SOLUTION-001 | 登录成功 |\n",
        encoding="utf-8")

    set_reader_version(tmp_path, "0.3.0")
    warn = v_index.validate(tmp_path)
    assert levels(warn)["用例第二落点"] == "WARN", warn
    warn_detail = details(warn, "用例第二落点")
    assert "用例行=" in warn_detail
    assert "E2E-SOLUTION-001" in warn_detail
    assert "索引外 ID" not in warn_detail

    set_reader_version(tmp_path, "0.4.0")
    fail = v_index.validate(tmp_path)
    assert levels(fail)["用例第二落点"] == "FAIL", fail
    fail_detail = details(fail, "用例第二落点")
    assert "用例行=" in fail_detail
    assert "E2E-SOLUTION-001" in fail_detail
    assert "索引外 ID" not in fail_detail


def test_ac_trace_table_is_not_a_case_row(tmp_path: Path) -> None:
    """复核 2：追溯表放进**成员** `web/`、四类前缀都在首列 ⇒ 仍不得判成用例行。"""
    _task_case_fixture(tmp_path)  # web/.trellis/tasks/T-9/cases.md：一条真用例行
    trace = tmp_path / "web" / ".trellis" / "tasks" / "T-10"
    trace.mkdir(parents=True)
    (trace / "cases.md").write_text(
        "# 验收追溯\n\n"
        "| AC | 场景 | 回指规则 |\n|---|---|---|\n"
        "| AC-DEMO-001 | 下单成功 | REQ-001 |\n\n"
        "| 需求 | 标题 |\n|---|---|\n"
        "| REQ-001 | 需求条目 |\n\n"
        "| 任务 | 标题 |\n|---|---|\n"
        "| T-001 | 任务卡 |\n\n"
        "| 优先级 | 说明 |\n|---|---|\n"
        "| P0-1 | 优先级 |\n"
        "| P-1 | 优先级 |\n\n"
        "| 决策 | 说明 |\n|---|---|\n"
        "| D-1 | 决策记录 |\n",
        encoding="utf-8")
    set_reader_version(tmp_path, "0.4.0")
    # 扫描面钉子：T-10 确实存在且被扫到，但一行都不认；只有 T-9 那条真用例行
    assert (trace / "cases.md").is_file()
    assert v_index._task_case_lines(tmp_path / "web") == [
        ".trellis/tasks/T-9/cases.md:5=BE-SYNC-001"], "扫描面或判定不符"
    result = v_index.validate(tmp_path)
    assert levels(result)["用例第二落点"] == "FAIL", result
    detail = details(result, "用例第二落点")
    assert "BE-SYNC-001" in detail
    assert "AC-DEMO-001" not in detail
    assert "REQ-001" not in detail
    assert "T-001" not in detail
    assert "P0-1" not in detail
    assert "P-1" not in detail
    assert "D-1" not in detail

    # 去掉那条唯一用例行 ⇒ PASS（追溯表本身不得触发任何判定）
    (tmp_path / "web" / ".trellis" / "tasks" / "T-9" / "cases.md").write_text(
        "| AC-DEMO-001 | 仅追溯表 |\n", encoding="utf-8")
    assert levels(v_index.validate(tmp_path))["用例第二落点"] == "PASS"


def test_reader_version_unknown_reports_fixed_hint(tmp_path: Path, monkeypatch) -> None:
    """评审重要 4：三级全缺 ⇒ 按 0.3.x 判 WARN，并在 detail 里留固定提示。"""
    _task_case_fixture(tmp_path)
    monkeypatch.setattr(v_index, "_reader_version", lambda root: "")
    result = v_index.validate(tmp_path)
    assert levels(result)["用例第二落点"] == "WARN", result
    assert "reader_version_unknown" in details(result, "用例第二落点")


def test_parent_without_case_ids_marks_second_landing_na(tmp_path: Path) -> None:
    """评审次要 11：父仓清单未声明 `case_ids` ⇒ N/A 且带原因，不静默跳过。"""
    make_parent(tmp_path, [])
    write_prd(tmp_path)
    write_index(tmp_path, [main_row()])
    write_shard(tmp_path, case_block())
    result = v_index.validate(tmp_path)
    assert levels(result)["用例第二落点"] == "N/A", result
    assert "未声明 case_ids" in details(result, "用例第二落点")


# ---------------------------------------------------------------- testid N/A

def test_testids_parent_mode_is_na(tmp_path: Path) -> None:
    make_parent(tmp_path, [])
    result = v_testids.validate(tmp_path)
    assert result.status == "N/A"
    assert "成员仓隔离" in details(result, "门控态")
