#!/usr/bin/env python3
"""D 批：`_support/ac_crosswalk.py` 的解析、C-01…C-11 与父仓接线（RFC-20261111-03 §2.1 / §7）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import ac_crosswalk as ac  # noqa: E402
from _support import solution  # noqa: E402

HEADER = ("| 方案AC | 成员 | 成员PRD | 成员域 | 成员AC | 依据 |\n"
          "|---|---|---|---|---|---|\n")
PRD = "backend/product/prd/auth-prd.md"
ROW = ("| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | auth "
       "| `AC-AUTH-012` | C1 |")


def cw(*rows: str) -> str:
    return HEADER + "\n".join(rows) + "\n"


# ---------------------------------------------------------------- parse（纯词法）

def test_parse_six_columns_and_line_numbers() -> None:
    table = ac.parse_crosswalk(cw(
        "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | `auth` "
        "| `AC-AUTH-012` | 契约 C1 |"))
    assert len(table.rows) == 1
    row = table.rows[0]
    assert (row.solution_ac, row.member, row.prd, row.member_domain,
            row.member_ac, row.basis) == (
        "AC-SOLUTION-001", "backend", "product/prd/auth-prd.md", "auth",
        "AC-AUTH-012", "契约 C1")
    assert row.line == 3


def test_parse_duplicate_key_is_not_a_parse_error() -> None:
    table = ac.parse_crosswalk(cw(ROW, ROW))
    assert len(table.rows) == 2


def test_parse_header_missing() -> None:
    with pytest.raises(ac.CrosswalkParseError) as exc:
        ac.parse_crosswalk("| 方案AC | 成员 |\n|---|---|\n| AC-SOLUTION-001 | backend |\n")
    assert exc.value.code == "header_missing"


def test_parse_column_count() -> None:
    with pytest.raises(ac.CrosswalkParseError) as exc:
        ac.parse_crosswalk(cw("| `AC-SOLUTION-001` | backend |"))
    assert exc.value.code == "column_count"


def test_parse_ac_format_rejects_contract_and_malformed_member_ac() -> None:
    with pytest.raises(ac.CrosswalkParseError) as exc:
        ac.parse_crosswalk(cw(
            "| `AC-CONTRACT-001` | backend | `product/prd/auth-prd.md` | auth "
            "| `AC-AUTH-012` | C1 |"))
    assert exc.value.code == "ac_format"
    with pytest.raises(ac.CrosswalkParseError) as exc:
        ac.parse_crosswalk(cw(
            "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | auth "
            "| `AC-AUTH-1` | C1 |"))
    assert exc.value.code == "ac_format"


def test_parse_prd_path() -> None:
    for bad in ("/abs/auth-prd.md", "../auth-prd.md", "product/prd/auth.md",
                "product//auth-prd.md"):
        with pytest.raises(ac.CrosswalkParseError) as exc:
            ac.parse_crosswalk(cw(
                f"| `AC-SOLUTION-001` | backend | `{bad}` | auth "
                "| `AC-AUTH-012` | C1 |"))
        assert exc.value.code == "prd_path", bad


def test_parse_member_field_empty() -> None:
    with pytest.raises(ac.CrosswalkParseError) as exc:
        ac.parse_crosswalk(cw(
            "| `AC-SOLUTION-001` |  | `product/prd/auth-prd.md` | auth "
            "| `AC-AUTH-012` | C1 |"))
    assert exc.value.code == "member_field_empty"


def test_parse_error_code_closed_set() -> None:
    with pytest.raises(ValueError):
        ac.CrosswalkParseError("member_unknown", 1)


# ---------------------------------------------------------------- findings

class FakeReader:
    """成员 PRD 读取面；`ac_ids` 由 `ac_links` 派生（v47 不变式）。"""

    def __init__(self, prds: dict[str, dict]) -> None:
        self.prds = prds
        self.waivers: list[dict] = []

    def paths(self, member: str) -> list[str]:
        return sorted(p for p in self.prds if p.startswith(f"{member}/"))

    def exists(self, path: str) -> bool:
        return path in self.prds

    def front_matter(self, path: str) -> dict:
        item = self.prds[path]
        return {"domain": item.get("domain", ""), "prd_schema": "2"}

    def ac_links(self, path: str) -> list[dict]:
        item = self.prds[path]
        links = item.get("links") or {}
        return [{"member_ac": ac, "linked_solution_ac": links.get(ac)}
                for ac in sorted(item.get("acs", ()))]

    def ac_ids(self, path: str) -> set[str]:
        return {item["member_ac"] for item in self.ac_links(path)}


def manifest(*reqs: dict, cutover: str = "2027-03-31") -> dict:
    return {"members": [{"name": "backend", "path": "backend"}],
            "requirements": list(reqs), "acceptance_cutover": cutover}


def req(ac_ids: list[str], member: str = "backend") -> dict:
    return {"id": "REQ-001", "member": member, "acs": ac_ids}


def codes(findings: list[ac.Finding]) -> list[str]:
    return [f.code for f in findings]


def test_c01_unmapped_requirement_and_contract_excluded() -> None:
    table = ac.parse_crosswalk(cw(
        "| `AC-SOLUTION-002` | backend | `product/prd/auth-prd.md` | auth "
        "| `AC-AUTH-012` | C1 |"))
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        table, manifest(req(["AC-SOLUTION-001", "AC-SOLUTION-002",
                             "AC-CONTRACT-001"])), reader)
    assert codes(found) == ["crosswalk_ac_unmapped"]
    assert "AC-CONTRACT-001" not in found[0].message


def test_c02_member_prd_missing_and_multi_prd() -> None:
    table = ac.parse_crosswalk(cw(ROW))
    assert codes(ac.crosswalk_findings(
        table, manifest(req(["AC-SOLUTION-001"])), FakeReader({}))) == [
        "crosswalk_member_prd_unresolved"]
    reader = FakeReader({
        "backend/product/prd/a-prd.md": {"domain": "auth", "acs": {"AC-AUTH-012"}},
        "backend/product/prd/b-prd.md": {"domain": "auth", "acs": {"AC-AUTH-013"}},
    })
    found = ac.crosswalk_findings(table, manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["crosswalk_member_prd_unresolved"]
    assert "多 PRD" in found[0].message


def test_c03_member_ac_missing() -> None:
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-999"}}})
    assert codes(ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])),
        reader)) == ["crosswalk_member_ac_missing"]


def test_c03_hit_row_skips_c09() -> None:
    """C-03 命中行不再判 C-09（同一行只出一个码，v47）。"""
    reader = FakeReader({PRD: {
        "domain": "auth", "acs": {"AC-AUTH-999"},
        "links": {"AC-AUTH-999": ["AC-SOLUTION-002"]}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["crosswalk_member_ac_missing"]


def test_c04_pair_without_requirement_row() -> None:
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(
            "| `AC-SOLUTION-002` | backend | `product/prd/auth-prd.md` | auth "
            "| `AC-AUTH-012` | C1 |")),
        manifest(req(["AC-SOLUTION-001"])), reader)
    assert "crosswalk_requirement_missing" in codes(found)


def test_c05_duplicate_key() -> None:
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW, ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found).count("crosswalk_duplicate_row") == 1


def test_c06_not_judged_in_crosswalk() -> None:
    """C-06 已并入 `waiver_baseline_drift`（v46/项 2）：后加需求豁免不产码。"""
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    reader.waivers = [{"requirement": "REQ-002", "owner": "a",
                       "due": "2027-01-01", "review": "REVIEW-20261112-01"}]
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert found == []


def test_c07_waiver_due_beyond_cutover_and_malformed() -> None:
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    reader.waivers = [
        {"requirement": "REQ-001", "owner": "a", "due": "2027-04-01"},
        {"requirement": "REQ-001", "owner": "a", "due": "2027-13-01"},
    ]
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["crosswalk_waiver_due_exceeded"] * 2
    assert {f.detail["kind"] for f in found} == {"beyond_cutover", "malformed"}


def test_c08_one_member_ac_two_solution_acs_is_pass() -> None:
    rows = (
        "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | auth "
        "| `AC-AUTH-012` | C1 |",
        "| `AC-SOLUTION-002` | backend | `product/prd/auth-prd.md` | auth "
        "| `AC-AUTH-012` | C2 |",
    )
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(*rows)),
        manifest(req(["AC-SOLUTION-001", "AC-SOLUTION-002"])), reader)
    assert found == []


def test_c09_wrong_mapping_against_prd_link() -> None:
    reader = FakeReader({PRD: {
        "domain": "auth", "acs": {"AC-AUTH-012"},
        "links": {"AC-AUTH-012": ["AC-SOLUTION-002"]}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["crosswalk_ac_link_mismatch"]


def test_c09_null_link_is_not_judged() -> None:
    reader = FakeReader({PRD: {
        "domain": "auth", "acs": {"AC-AUTH-012"},
        "links": {"AC-AUTH-012": None}}})
    assert ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])),
        reader) == []


def test_c09_multi_table_links_prefer_non_null() -> None:
    """同一成员 AC 出现在多张表时，空的 `linked_solution_ac` 不得擦掉真关联。"""
    class DupReader(FakeReader):
        def ac_links(self, path: str) -> list[dict]:
            return [
                {"member_ac": "AC-AUTH-012",
                 "linked_solution_ac": ["AC-SOLUTION-002"]},
                {"member_ac": "AC-AUTH-012", "linked_solution_ac": None},
            ]

    reader = DupReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["crosswalk_ac_link_mismatch"]


def test_c10_orphan_member_ac_default_silent() -> None:
    reader = FakeReader({PRD: {"domain": "auth",
                               "acs": {"AC-AUTH-012", "AC-AUTH-013"}}})
    data = manifest(req(["AC-SOLUTION-001"]))
    table = ac.parse_crosswalk(cw(ROW))
    assert "crosswalk_orphan_member_ac" not in codes(
        ac.crosswalk_findings(table, data, reader))
    found = ac.crosswalk_findings(table, data, reader, orphan_warn=True)
    assert [(f.code, f.severity) for f in found] == [
        ("crosswalk_orphan_member_ac", "warning")]


def test_c11_member_unknown() -> None:
    data = {"members": [{"name": "backend", "path": "backend"}],
            "requirements": [{"id": "REQ-001", "member": "web",
                              "acs": ["AC-SOLUTION-001"]}],
            "acceptance_cutover": "2027-03-31"}
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(
            "| `AC-SOLUTION-001` | web | `product/prd/auth-prd.md` | auth "
            "| `AC-AUTH-012` | C1 |")), data, FakeReader({}))
    assert codes(found) == ["member_domain_mismatch"]
    assert found[0].detail["kind"] == "member_unknown"


def test_c11_domain_mismatch_prefix_and_front_matter() -> None:
    reader = FakeReader({PRD: {"domain": "billing", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    kinds = {f.detail["kind"] for f in found if f.code == "member_domain_mismatch"}
    assert kinds == {"front_matter"}
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(
            "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | billing "
            "| `AC-AUTH-012` | C1 |")),
        manifest(req(["AC-SOLUTION-001"])), reader)
    kinds = {f.detail["kind"] for f in found if f.code == "member_domain_mismatch"}
    assert kinds == {"ac_prefix", "front_matter"}


def test_contract_ac_in_member_slot_both_forms() -> None:
    table = ac.parse_crosswalk(cw(
        "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | auth "
        "| `AC-CONTRACT-001` | C1 |"))
    reader = FakeReader({PRD: {"domain": "auth", "acs": {"AC-AUTH-012"}}})
    found = ac.crosswalk_findings(table, manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["contract_ac_in_member_slot"]

    reader = FakeReader({PRD: {"domain": "auth",
                               "acs": {"AC-AUTH-012", "AC-CONTRACT-001"}}})
    found = ac.crosswalk_findings(
        ac.parse_crosswalk(cw(ROW)), manifest(req(["AC-SOLUTION-001"])), reader)
    assert codes(found) == ["contract_ac_in_member_slot"]


# ---------------------------------------------------------------- 父仓接线（D-45 / D-46 / D-47 / 证据列）

PRD_OK = """---
domain: auth
prd_schema: 2
---

## 五、验收标准

| AC ID | 场景（Given / When / Then） | 回指规则 |
|---|---|---|
| `AC-AUTH-012` | Given / When / Then | `AUTH-R-001` |
"""


def data(*, acs: tuple[str, ...] = ("AC-SOLUTION-001",),
         definition: str | None = None) -> dict:
    out = {"members": [{"name": "backend", "path": "backend"}],
           "requirements": [{"id": "REQ-001", "member": "backend",
                             "acs": list(acs)}],
           "acceptance_cutover": "2027-03-31"}
    if definition:
        out["definition"] = {"path": definition}
    return out


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def check(root: Path, manifest_data: dict) -> list[dict]:
    return solution._crosswalk_and_contract_checks(root, manifest_data)


def test_d45_missing_crosswalk_suppresses_c_family(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK)
    got = check(tmp_path, data())
    assert [f["code"] for f in got] == [
        "crosswalk_unresolvable", "evidence_columns_unbound"]


def test_no_solution_ac_requirement_does_not_require_crosswalk(tmp_path: Path) -> None:
    """按需求判：零需求 / 只引用契约 AC 的清单不因缺 crosswalk 被红（`init` 后可跑）。"""
    write(tmp_path, PRD, PRD_OK)
    assert check(tmp_path, data(acs=("AC-CONTRACT-001",))) == []
    assert check(tmp_path, {**data(), "requirements": []}) == []


def test_d45_unreadable_crosswalk_is_unresolvable(tmp_path: Path) -> None:
    """D-45 的「不可读」分支：文件在但 UTF-8 解码失败 ⇒ 同 `crosswalk_unresolvable`，不落 parse_error。"""
    write(tmp_path, PRD, PRD_OK)
    path = tmp_path / "product" / "prd" / "ac-crosswalk.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00\x81")
    got = check(tmp_path, data())
    assert [f["code"] for f in got] == [
        "crosswalk_unresolvable", "evidence_columns_unbound"]


@pytest.mark.parametrize("body,kind", [
    ("| 方案AC | 成员 |\n|---|---|\n| AC-SOLUTION-001 | backend |\n",
     "header_missing"),
    (HEADER + "| `AC-SOLUTION-001` | backend |\n", "column_count"),
    (HEADER + "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` "
              "| auth | `AC-AUTH-1` | C1 |\n", "ac_format"),
    (HEADER + "| `AC-SOLUTION-001` | backend | `/abs/auth-prd.md` "
              "| auth | `AC-AUTH-012` | C1 |\n", "prd_path"),
    (HEADER + "| `AC-SOLUTION-001` |  | `product/prd/auth-prd.md` "
              "| auth | `AC-AUTH-012` | C1 |\n", "member_field_empty"),
])
def test_d47_parse_error_suppresses_c_family(tmp_path: Path, body: str,
                                             kind: str) -> None:
    write(tmp_path, PRD, PRD_OK)
    write(tmp_path, "product/prd/ac-crosswalk.md", body)
    got = check(tmp_path, data())
    assert [f["code"] for f in got] == [
        "crosswalk_parse_error", "evidence_columns_unbound"]
    assert got[0]["detail"]["kind"] == kind


def test_happy_path_no_findings(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK)
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    assert check(tmp_path, data()) == []


def test_d46_contract_ac_in_member_slot(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK)
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(
        "| `AC-SOLUTION-001` | backend | `product/prd/auth-prd.md` | auth "
        "| `AC-CONTRACT-001` | C1 |"))
    assert [f["code"] for f in check(tmp_path, data())] == [
        "contract_ac_in_member_slot"]


def test_d46_contract_ac_in_member_prd_table(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK.replace(
        "| `AC-AUTH-012` | Given / When / Then | `AUTH-R-001` |",
        "| `AC-AUTH-012` | Given / When / Then | `AUTH-R-001` |\n"
        "| `AC-CONTRACT-001` | Given / When / Then | `AUTH-R-001` |"))
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    assert [f["code"] for f in check(tmp_path, data())] == [
        "contract_ac_in_member_slot"]


def test_evidence_columns_missing(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK + """
## 六、Assumptions & Defaults

| 假设内容 | 采用的默认值 |
|---|---|
| 默认值待定 | — |
""")
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    assert [f["code"] for f in check(tmp_path, data())] == [
        "evidence_columns_missing"]


def test_contract_ac_positive_via_definition(tmp_path: Path) -> None:
    write(tmp_path, PRD, PRD_OK)
    write(tmp_path, "product/prd/solution-prd.md", """---
domain: solution
prd_schema: 2
---

## 五、验收标准

| AC ID | 场景（Given / When / Then） | 回指规则 |
|---|---|---|
| `AC-SOLUTION-001` | Given / When / Then | `SOL-R-001` |

### §五-b 字段契约 AC

| 契约AC | 字段 | 类型 | 必填 | 异常码 | 关联AC |
|---|---|---|---|---|---|
| `AC-CONTRACT-001` | email | string | 是 | ERR-EMAIL | `AC-SOLUTION-001` |
""")
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    assert check(tmp_path, data(
        acs=("AC-SOLUTION-001", "AC-CONTRACT-001"),
        definition="product/prd/solution-prd.md")) == []


def test_parent_side_does_not_judge_confirmed_state(tmp_path: Path) -> None:
    """E-12：父仓只验封条投影、不读卡正文 ⇒ 任务卡里坏的 Confirmed 表不产 `confirmed_*`。

    证据状态由成员 `validate_task_card` 判（C 批）；父仓端 N/A `confirmed_parent_only`。
    """
    write(tmp_path, PRD, PRD_OK)
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    write(tmp_path, "backend/.trellis/tasks/T-1/prd.md",
          "## Confirmed\n\n| 确认项 | 口径 | 证据状态 | 证据指针 |\n"
          "|---|---|---|---|\n| 认证方式 | JWT | unverified | — |\n")
    got = check(tmp_path, data())
    assert [f["code"] for f in got
            if f["code"].startswith("confirmed_")] == []
    assert got == []


def test_e06_member_na_exit_and_parent_e02_still_red(tmp_path: Path) -> None:
    """E-06：成员侧给显式 N/A 出口（`evidence_columns_parent_only`）；父仓缺列仍 E-02 FAIL。"""
    spec = importlib.util.spec_from_file_location(
        "atlas_check_e06", PKG_ROOT / "scripts" / "atlas_check.py")
    check_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_mod)
    (tmp_path / "product" / "prd").mkdir(parents=True)

    rows = check_mod.Row()
    check_mod.check_validators(tmp_path, rows, sys.executable)
    row = next(r for r in rows.rows if r["name"] == "证据列（被引用域）")
    assert row["status"] == "N/A"
    assert "evidence_columns_parent_only" in row["detail"]

    # 父仓根（有清单）不再出成员侧 N/A，归父仓 `atlas solution check` 判。
    (tmp_path / "atlas.solution.yaml").write_text("solution: x\n", encoding="utf-8")
    rows = check_mod.Row()
    check_mod.check_validators(tmp_path, rows, sys.executable)
    assert not [r for r in rows.rows if r["name"] == "证据列（被引用域）"]

    # 父仓侧 E-02 照旧红：被引用成员 PRD 缺证据两列。
    write(tmp_path, PRD, PRD_OK + """
## 六、Assumptions & Defaults

| 假设内容 | 采用的默认值 |
|---|---|
| 默认值待定 | — |
""")
    write(tmp_path, "product/prd/ac-crosswalk.md", cw(ROW))
    assert [f["code"] for f in check(tmp_path, data())] == [
        "evidence_columns_missing"]
