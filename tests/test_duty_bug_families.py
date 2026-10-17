#!/usr/bin/env python3
"""DR4 **口径 B** 单源模块（`duty-review/families.py`）的形状钉 + 判定真值表。

**为什么钉它**：口径 B 的输入是**人工写的** `bugs.md`。解析形状一漂，最坏结果是**静默归零**
（每段都数成 0 ⇒ 永不升室）——那恰好让本机制要治的「复发靠撞见」原样回来，而且**没有任何声息**。
故本测断言的是「解析**真的看得见**」，不是「跑得出表格」。

**副本态**：`duty-review/` 不随包分发（`.atlas/tests` 里没有它）⇒ 显式 skip，不是通过。

变异证明 **M91**：把计数正则从段内全文 (`re.findall(r"#(\\d+)", line)`) 退回行首
(`r"^#(\\d+)"`) ⇒ 「案数上界」塌成 ≤1 ⇒ 本测红（真实库里的族再也数不到 3）。
"""
from __future__ import annotations

import datetime
import importlib.util
import re
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = PKG_ROOT / "duty-review" / "families.py"
BUGS = PKG_ROOT / "duty-review" / "bugs.md"

pytestmark = pytest.mark.skipif(
    not FAMILIES.is_file() or not BUGS.is_file(),
    reason="duty-review/ 不随包分发（副本态）：口径 B 的载体不在场 —— 不是通过")


def _load():
    spec = importlib.util.spec_from_file_location("duty_bug_families", FAMILIES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_parses_every_section_of_real_bugs_md() -> None:
    """形状钉：`## ` 段的**解析面必须等于文件面**（少一段 = 那一段永远不可见）。"""
    fam = _load()
    text = BUGS.read_text(encoding="utf-8")
    headers = re.findall(r"^##\s+\S", text, re.M)
    got = fam.parse_sections(text)
    assert len(got) == len(headers), f"解析 {len(got)} 段 ≠ 文件 {len(headers)} 段"
    assert any(s["has_root"] for s in got), "真实库里至少有一段带「同根归纳」锚行"
    assert sum(len(s["ids"]) for s in got) > 0, "段内 `#NN` 一个都没解析到 = 静默归零"


def test_real_library_reaches_family_scale() -> None:
    """真实库必须**数得出族规模**（≥3 案）——否则口径 B 等于没接线。

    （这不是「数据断言」而是接线断言：库只会增长，若这里塌了，多半是解析面坏了。）
    """
    fam = _load()
    rows = fam.families(BUGS.read_text(encoding="utf-8"))
    assert max(r["count"] for r in rows) >= 3, rows
    assert any(r["verdict"] == "升室候选" for r in rows), [
        (r["name"], r["count"], r["last_date"], r["verdict"]) for r in rows]


def test_verdict_truth_table_and_boundary() -> None:
    """判定真值表（四项）+ 活跃窗边界（日期**正好** = cutoff ⇒ 仍算活跃）。"""
    fam = _load()
    today = datetime.date(2026, 10, 17)
    cutoff = (today - datetime.timedelta(days=fam.WINDOW_DAYS)).isoformat()   # 2026-09-17
    text = (
        "## 甲段（同根归案 + 3 案 + 今天）\n"
        "- 同根归纳：同属一族\n"
        "- #1 案甲\n- #2 案乙\n- #3 案丙\n"
        f"- 现场取证 {today.isoformat()}\n"
        "## 乙段（3 案但只有旧日期）\n"
        "- 同根归纳：同属一族\n"
        "- #4 案甲\n- #5 案乙\n- #6 案丙\n"
        "- 现场取证 2026-01-01\n"
        "## 丙段（案数不足）\n"
        "- 同根归纳：同属一族\n"
        "- #7 案甲\n- #8 案乙\n"
        f"- 现场取证 {today.isoformat()}\n"
        "## 丁段（无同根归纳锚）\n"
        "- #9 案甲\n- #10 案乙\n- #11 案丙\n"
        f"- 现场取证 {today.isoformat()}\n"
        "## 戊段（边界：日期正好 = cutoff）\n"
        "- 同根归纳：同属一族\n"
        "- #12 案甲\n- #13 案乙\n- #14 案丙\n"
        f"- 现场取证 {cutoff}\n"
    )
    verdicts = {r["name"][:2]: r["verdict"] for r in fam.families(text, today=today)}
    assert verdicts == {"甲段": "升室候选", "乙段": "族已静默", "丙段": "案数不足",
                        "丁段": "无同根归纳", "戊段": "升室候选"}, verdicts


def test_read_only_and_empty_input_is_not_a_crash() -> None:
    """无 `bugs.md`（副本态 / 首次运行）⇒ 空表 + 明确一行，不炸也不假装有数据。"""
    fam = _load()
    assert fam.families("") == []
    assert fam.render([]) == ["(无 duty-review/bugs.md，跳过)"]
