#!/usr/bin/env python3
"""DR4 **口径 B** 单源模块（`duty-review/families.py`）的形状钉 + 判定真值表 + 条目字段制式钉。

**为什么钉它**：口径 B 的输入是**人工写的** `bugs.md`。解析形状一漂，最坏结果是**静默归零**
（每段都数成 0 ⇒ 永不升室）——那恰好让本机制要治的「复发靠撞见」原样回来，而且**没有任何声息**。
故本测断言的是「解析**真的看得见**」，不是「跑得出表格」。

**副本态**：`duty-review/` 不随包分发（`.atlas/tests` 里没有它）⇒ 显式 skip，不是通过。

变异证明：
* **M91**：把计数正则从段内全文 (`re.findall(r"#(\\d+)", line)`) 退回行首 (`r"^#(\\d+)"`)
  ⇒ 「案数上界」塌成 ≤1 ⇒ 本测红（真实库里的族再也数不到 3）。
* **M157a**（D154）：摘分层日期来源（回退段内全行散文日期）⇒「陈旧说明不抬窗」正向钉红。
* **M157b**（D154）：摘坏形状 WARN ⇒ 字段形状钉坏形状组红（静默回退从另一门归来）。

判据零变更对照基线（D154 落刀日 2026-10-26，证据 = `proposals/REVIEW-20261026-07` §3 试跑）：
五段 verdict/案数/最近日期冻结在
`test_current_real_file_baseline_frozen`——字段制式对现行全文（零条目带尾缀）**零扰动**。
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

TODAY = datetime.date(2026, 10, 26)          # D154 落刀日；冻结基线与字段钉都用它，不随时钟漂
FROZEN_BASELINE = {                          # (案数上界, 最近日期, verdict) —— 现行 bugs.md 五段
    "structure 逆向（适配器 / 事实区渲染 / 结构环）": (3, "", "族已静默"),
    "E2E（契约用例 / 生成器 / 校验器）": (16, "2026-10-25", "升室候选"),
    "安装与装配（install.sh / adopt 守卫 / 包自检）": (3, "2026-10-17", "升室候选"),
    "图谱通道（已知边界，非缺陷——防误重报）": (0, "", "无同根归纳"),
    "自感知上报（§15 缺陷族）": (8, "2026-10-17", "升室候选"),
}

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


# ---------------------------------------------------------------------------
# D154 条目字段制式（2026-10-26）——六钉
# ---------------------------------------------------------------------------

def test_fielded_entry_date_drives_window_and_excludes_own_prose() -> None:
    """带字段条目：字段日期是唯一活跃窗来源；本行散文旧日期与段尾收尾说明**不再抬窗**。"""
    fam = _load()
    text = (
        "## 字段激活段\n"
        "- 同根归纳：同属一族\n"
        f"- #51 案甲 2026-01-01〔日期 {TODAY.isoformat()}〕\n"
        "- #52 案乙\n"
        "- #53 案丙\n"
        "（段尾收尾说明 2026-01-01 全量绿——非条目行，不是日期来源）\n"
    )
    rows = fam.families(text, today=TODAY)
    row = rows[0]
    assert row["last_date"] == TODAY.isoformat(), (
        "带字段条目的本行散文旧日期 / 段尾说明不应参与活跃窗取数")
    assert row["active"] is True
    assert row["verdict"] == "升室候选"
    assert row["exact"] == 1, row            # 精确病案数 = 带字段条目的 #51


def test_stale_tail_note_and_fieldless_entries_do_not_lift_window() -> None:
    """仅陈旧收尾说明日期、全段无字段条目 ⇒ 判「族已静默」（M157a 的正向钉 ②）。"""
    fam = _load()
    text = (
        "## 静默段\n"
        "- 同根归纳：同属一族\n"
        "- #61 案甲\n"
        "- #62 案乙\n"
        "- #63 案丙\n"
        "（收尾说明：2026-01-01 已修全量绿——非条目行）\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert row["last_date"] == "", "非条目行的日期不是取数源，不得抬窗"
    assert row["active"] is False
    assert row["verdict"] == "族已静默"


def test_bad_shape_warns_and_falls_back() -> None:
    """坏形状（重复键 / 日期形态非法 / 未知键 / 值域外 / 缺必填）⇒ WARN + 按无字段回退，不静默。"""
    fam = _load()
    text = (
        "## 坏形状段\n"
        "- 同根归纳：同属一族\n"
        "- #71 案甲〔日期 2026-10-26｜日期 2026-10-25〕\n"
        "- #72 案乙〔日期 2026/10/26〕\n"
        "- #73 案丙〔时间 2026-10-26〕\n"
        "- #74 案丁〔状态 已废除〕\n"
        "- #75 案戊〔状态 开放〕\n"
        "- #76 案己 2026-10-20\n"
    )
    rows = fam.families(text, today=TODAY)
    row = rows[0]
    assert len(row["warns"]) == 5, row["warns"]   # #71–#75 各一条，缺「日期」同算坏
    for w in row["warns"]:
        assert "已按无字段回退" in w
    assert row["count"] == 6                      # 上界计数不受字段状态影响
    assert row["last_date"] == "2026-10-20", "坏形状条目回退后，日期来源只剩 #76 的行内散文日期"
    assert row["active"] is True and row["verdict"] == "升室候选"
    assert row["exact"] is None, "段内零个合法带字段条目 ⇒ 无精确病案数列"
    assert any("WARN 条目字段形状" in ln for ln in fam.render(rows))


def test_half_field_is_legal_shape() -> None:
    """半字段（只带「日期」）合法：字段直接进活跃窗，不 WARN。"""
    fam = _load()
    text = (
        "## 半字段段\n"
        "- #81 案甲〔日期 2026-10-25〕\n"
        "- #82 案乙\n- #83 案丙\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert row["warns"] == []
    assert row["last_date"] == "2026-10-25"
    assert row["exact"] == 1


def test_mixed_segment_aggregates_by_max_date() -> None:
    """混合段：带字段新条目 ∪ 无字段旧条目行内日期，段活跃窗 = 并集最大（按条目级回退）。"""
    fam = _load()
    text = (
        "## 混合段\n"
        "- 同根归纳：同属一族\n"
        "- #91 新案〔日期 2026-10-25｜状态 开放〕\n"
        "- #92 旧案 自 2026-10-20 起（无字段，散文日期）\n"
        "- #93 旧案无日期\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert row["last_date"] == "2026-10-25"
    assert row["active"] is True and row["verdict"] == "升室候选"
    assert row["exact"] == 1


def test_render_exact_column_only_when_present() -> None:
    """显示列钉：带字段段出「精确病案数=M」；无字段段不出该列（RFC v2 §2.1）。"""
    fam = _load()
    mixed = "## 混合段\n- 同根归纳：同属一族\n- #91 新案〔日期 2026-10-25〕\n- #92 旧案\n- #93 旧案\n"
    plain = "## 无字段段\n- #94 案甲\n- #95 案乙\n- #96 案丙\n"
    out = fam.render(fam.families(mixed, today=TODAY) + fam.families(plain, today=TODAY))
    mixed_line = [ln for ln in out if "混合段" in ln][0]
    plain_line = [ln for ln in out if "无字段段" in ln][0]
    assert "精确病案数=1" in mixed_line
    assert "精确病案数" not in plain_line


def test_current_real_file_baseline_frozen() -> None:
    """判据零变更对照钉（D154）：对现行 `bugs.md` 全文（零条目带尾缀），判据三输出逐段冻结
    = D154 落刀日基线（REVIEW-20261026-07 §3 试跑）——字段制式对旧库**零扰动**且无 WARN。"""
    fam = _load()
    rows = fam.families(BUGS.read_text(encoding="utf-8"), today=TODAY)
    got = {r["name"]: (r["count"], r["last_date"], r["verdict"]) for r in rows}
    assert got == FROZEN_BASELINE, got
    assert all(r["warns"] == [] for r in rows), "现行全文零尾缀 ⇒ 不应有任何形状 WARN"
    assert all(r["exact"] is None for r in rows), "现行全文零尾缀 ⇒ 不应出精确病案数列"
