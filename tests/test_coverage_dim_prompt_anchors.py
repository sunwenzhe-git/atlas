#!/usr/bin/env python3
"""RFC-20261106-01 契约文本锚钉（D184）。

钉的是「生成纪律提示在位」，不是门——本批零新门、零新字段、零校验器改动（RFC §5）：

  * 锚 1  e2e §6.1「逐维自检」块在位，且块内 C 记号集合 == §5.2 闭集行**现解析**集合
          （等值断言：既防杜撰（多出 C15）也防收窄漂移（静默删行）——闭集单一来源）；
  * 锚 2  e2e §6.1「数据构造」块在位且含「不新增字段」
          （边界/异常值必须生成期给具体值，料不足回 prd 环）；
  * 锚 3  apply §5「PRD AC 表第 4 列默认声明」块结构前缀在位 + 表头词
          （政策语句不进钉面，防合法政策演化造成无谓红灯——REVIEW Minor-3）。

证明 = GREEN-RED-GREEN：删除任一块 ⇒ 对应锚红；逐字恢复 ⇒ 绿（变异记录见 RFC §5）。
"""
from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]

E2E_REF = PKG_ROOT / "rings" / "e2e" / "reference.md"
APPLY_REF = PKG_ROOT / "apply" / "reference.md"

C_TOKEN = re.compile(r"C\d{2}")


def _e2e_text() -> str:
    return E2E_REF.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """截取 `heading` 起到下一个同级 `### `（或文件尾）的文本。"""
    start = text.index(heading)
    nxt = text.find("\n### ", start + len(heading))
    return text[start:] if nxt == -1 else text[start:nxt]


def _closed_dim_set() -> set[str]:
    """从 §5.2 `覆盖维度` 闭集表现场解析成员——单一来源，本测试不复制词表。"""
    rows = [
        ln
        for ln in _e2e_text().splitlines()
        if ln.startswith("| `覆盖维度` |")
    ]
    assert len(rows) == 1, f"§5.2 覆盖维度闭集行应恰有一条，实得 {len(rows)} 条"
    return set(C_TOKEN.findall(rows[0]))


def test_anchor1_dim_checklist_block_equals_closed_set() -> None:
    text = _e2e_text()
    assert "逐维自检" in text, "§6.1 逐维自检块缺失（改动点①被删除或漂移）"
    sec = _section(text, "### 6.1")
    block_tokens = set(C_TOKEN.findall(sec))
    closed = _closed_dim_set()
    assert block_tokens == closed, (
        "§6.1 维度记号集合与 §5.2 闭集不等值："
        f"多出 {sorted(block_tokens - closed)}（枚举杜撰），"
        f"缺失 {sorted(closed - block_tokens)}（收窄漂移）"
    )


def test_anchor2_data_construction_block_present() -> None:
    sec = _section(_e2e_text(), "### 6.1")
    assert "数据构造" in sec, "§6.1 数据构造提示块缺失（改动点②被删除或漂移）"
    assert "不新增字段" in sec, "数据构造块的「不新增字段」承诺行缺失"


def test_anchor3_apply_default_declaration_block_prefix() -> None:
    text = APPLY_REF.read_text(encoding="utf-8")
    assert (
        "**PRD AC 表第 4 列默认声明（apply 默认动作" in text
    ), "apply §5 第 4 列默认声明块缺失或结构前缀漂移（改动点③被删除）"
    assert "适用覆盖维度" in text, "第 4 列表头词「适用覆盖维度」在 apply §5 缺失"
