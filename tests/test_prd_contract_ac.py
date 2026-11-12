#!/usr/bin/env python3
"""D 批：§五-b 契约 AC（`AC-CONTRACT-*`）的纯判据（RFC-20261111-03 §1.5 第 7 条）。

判据本体在 `_support/ac_crosswalk.py::_contract_ac_findings`（纯函数，零 Git / 零 FS），
`check_solution` 接线在 C 批返工落地后另行接入；本文件只测判据。
"""
from __future__ import annotations

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import ac_crosswalk as ac  # noqa: E402

REL = "product/prd/solution-prd.md"

CONTRACT_OK = """---
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
"""


def manifest(*ac_ids: str) -> dict:
    return {"requirements": [{"id": "REQ-001", "member": "backend",
                              "acs": list(ac_ids)}]}


def findings(text: str, data: dict) -> list[ac.Finding]:
    return ac._contract_ac_findings(text, data, REL)


def codes(items: list[ac.Finding]) -> list[str]:
    return [f.code for f in items]


def test_contract_table_positive() -> None:
    assert findings(CONTRACT_OK, manifest("AC-SOLUTION-001",
                                          "AC-CONTRACT-001")) == []


def test_contract_table_missing_when_schema2_and_referenced() -> None:
    prd = CONTRACT_OK.split("### §五-b")[0]
    got = findings(prd, manifest("AC-CONTRACT-001"))
    assert codes(got) == ["contract_ac_table_missing"]


def test_contract_table_not_required_for_schema1() -> None:
    prd = CONTRACT_OK.split("### §五-b")[0].replace("prd_schema: 2", "prd_schema: 1")
    assert findings(prd, manifest("AC-CONTRACT-001")) == []


def test_contract_ac_undefined_reference() -> None:
    prd = CONTRACT_OK.replace("`AC-CONTRACT-001`", "`AC-CONTRACT-002`", 1)
    got = findings(prd, manifest("AC-CONTRACT-001"))
    assert "contract_ac_undefined" in codes(got)


def test_contract_ac_orphan_related_ac() -> None:
    prd = CONTRACT_OK.replace(
        "| `AC-CONTRACT-001` | email | string | 是 | ERR-EMAIL | `AC-SOLUTION-001` |",
        "| `AC-CONTRACT-001` | email | string | 是 | ERR-EMAIL | `AC-SOLUTION-999` |")
    got = findings(prd, manifest("AC-SOLUTION-001", "AC-CONTRACT-001"))
    assert codes(got) == ["contract_ac_orphan"]
    assert got[0].detail["related"] == "AC-SOLUTION-999"


def test_contract_ac_duplicate() -> None:
    row = ("| `AC-CONTRACT-001` | email | string | 是 | ERR-EMAIL | "
           "`AC-SOLUTION-001` |")
    prd = CONTRACT_OK.replace(row + "\n", row + "\n" + row + "\n")
    got = findings(prd, manifest("AC-CONTRACT-001"))
    assert [f.detail["kind"] for f in got] == ["duplicate"]


def test_contract_ac_bad_numbering_is_contract_ac_format() -> None:
    """§五-b 编号形态错归 `contract_ac_format`，不经 crosswalk parser（v46/项 4）。"""
    prd = CONTRACT_OK.replace("`AC-CONTRACT-001`", "`AC-CONTRACT-1`")
    got = findings(prd, manifest("AC-CONTRACT-1"))
    assert got[0].code == "contract_ac_format"
    assert got[0].detail["kind"] == "ac_contract_format"


def test_contract_table_header_must_be_six_columns() -> None:
    prd = CONTRACT_OK.replace(
        "| 契约AC | 字段 | 类型 | 必填 | 异常码 | 关联AC |",
        "| 契约AC | 字段 | 类型 | 必填 | 异常码 | 备注 |")
    got = findings(prd, manifest("AC-CONTRACT-001"))
    assert got[0].code == "contract_ac_table_missing"
    assert got[0].detail["kind"] == "header"
