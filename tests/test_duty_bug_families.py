#!/usr/bin/env python3
"""DR4 **口径 B** 单源模块（`duty-review/families.py`）的形状钉 + 判定真值表 + 条目字段制式钉。

**套件计数**：19 条 = 既有形状/真值表 4 + D154 字段制式 7 + **D155 日期越界 7** + **D156 指针行 1**
（`duty-review/README.md` §2 的钉数与本文件一致；改任一钉同步改这里）。
D156 的 1 条 = 留出验证指针行形状钉（正向：合规指针不改三值；反向：带日期改 `last_date`、带 `#NN` 改 `count`——反向用例即其反面包，不另配 M）。
D155 的 7 条 = 越界两钉（日历非法 / 未来日期）+ 合法边界反面包 + 判别性补强 + **轮 2 复核补的三钉**：
**判据级留出 = 归零路径**（全坏字段 + 零散文日期 ⇒ `last_date=""`，既有钉无一走到；pre 红 = verdict/`last_date`/`exact` 三层翻转）；
**紧边界判别钉 = `T` / `T+1` 对**（红在判据层，但属 G2 同夹具日期串变体，按 RFC-03 §2.1.4 计判别性补强——轮 3 年粒度变异实测：G2 绿、唯它与 CLI 钉红）；
**送达钉 = CLI 巡检轨**（`main()` 的 stdout——既有钉全在进程内，把 `print` 改成 `stderr.write` 时 15 条钉曾全绿而告警消失）。
**三条在 D154 版上实测全红；留出资格只归归零路径——「pre 红」不自动等于「留出」（轮 3 判词）。**

**为什么钉它**：口径 B 的输入是**人工写的** `bugs.md`。解析形状一漂，最坏结果是**静默归零**
（每段都数成 0 ⇒ 永不升室）——那恰好让本机制要治的「复发靠撞见」原样回来，而且**没有任何声息**。
故本测断言的是「解析**真的看得见**」，不是「跑得出表格」。

**副本态**：`duty-review/` 不随包分发（`.atlas/tests` 里没有它）⇒ 显式 skip，不是通过。

变异证明：
* **M91**：把计数正则从段内全文 (`re.findall(r"#(\\d+)", line)`) 退回行首 (`r"^#(\\d+)"`)
  ⇒ 「案数上界」塌成 ≤1 ⇒ 本测红（真实库里的族再也数不到 3）。
* **M157a**（D154）：摘分层日期来源（回退段内全行散文日期）⇒「陈旧说明不抬窗」正向钉红。
* **M157b**（D154）：摘坏形状 WARN ⇒ 字段形状钉坏形状组红（静默回退从另一门归来）。
* **M158a**（D155）：摘日历关（`date.fromisoformat` 失败仍当合法）⇒ **2 红**（日历非法钉 + 归零路径钉）。
* **M158b**（D155）：摘未来关（晚于当日的字段日期不拦）⇒ **4 红**（未来钉 + 归零钉 + `T+1` 边界钉 + CLI 轨钉）。
* **M158c**（D155）：把 `main()` 的 `print` 换成 `sys.stderr.write` ⇒ **恰 1 红 = 只有 CLI 轨钉**，17 条判据面全绿
  —— 这正说明该钉咬的是「告警有没有送达巡检消费者」，与两关算得对不对无关（轮 2 复实用它证伪了「换通道=换留出」的第一版说法，也据此把 CLI 轨从「留出」降为「送达钉」，判据级留出改由归零路径与 `T+1` 边界承担）。
* 三枚的红因集合 = **恰好是依赖被摘那一关的钉**，无一条无关钉被牵连 ⇒ 注入面与红因一致（不是「一处崩了冒充全局红」）。

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
    "安装与装配（install.sh / adopt 守卫 / 包自检 / 发版口径）": (3, "2026-10-27", "升室候选"),
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
# D154 条目字段制式（2026-10-26）——七钉（含末尾的现行库基线冻结对照钉）
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


# ---------------------------------------------------------------------------
# D155 字段日期越界校验（2026-10-26，RFC-20261026-05）——四钉
# ---------------------------------------------------------------------------

def test_calendar_invalid_field_date_warns_and_falls_back() -> None:
    """越界之一：形态过正则但**日历非法**（13 月 40 日）⇒ WARN + 按无字段回退。

    「判据可被形态满足」族的新实例：`^20\\d\\d-\\d\\d-\\d\\d$` 满足 ≠ 是一个可用日期。
    """
    fam = _load()
    text = (
        "## 日历非法段\n"
        "- 同根归纳：同属一族\n"
        "- #301 案甲 2026-01-01〔日期 2026-13-40〕\n"
        "- #302 案乙\n"
        "- #303 案丙\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert len(row["warns"]) == 1, row["warns"]
    assert "日历非法" in row["warns"][0], row["warns"]
    assert "已按无字段回退" in row["warns"][0], row["warns"]
    assert row["last_date"] == "2026-01-01", "越界字段日期不得抬活跃窗——须回退行内散文日期"
    assert row["verdict"] == "族已静默"


def test_future_field_date_warns_and_falls_back() -> None:
    """越界之二：**晚于当日**的字段日期 ⇒ WARN + 回退，否则该段被永久判「升室候选」。"""
    fam = _load()
    text = (
        "## 未来日期段\n"
        "- 同根归纳：同属一族\n"
        "- #311 案甲 2026-01-01〔日期 2027-01-01〕\n"
        "- #312 案乙\n"
        "- #313 案丙\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert len(row["warns"]) == 1, row["warns"]
    assert "晚于当日" in row["warns"][0], row["warns"]
    assert row["last_date"] == "2026-01-01", "未来日期不是活跃窗来源——须回退行内散文日期"
    assert row["verdict"] == "族已静默"


def test_legal_field_date_still_accepted_after_tightening() -> None:
    """反面包：收紧只挡越界，**合法边界值不得被误伤**。

    正好 = cutoff（`TODAY - WINDOW_DAYS` = 2026-09-26）且行内散文日期更旧 ⇒ 字段日期生效、无 WARN。
    """
    fam = _load()
    cutoff = (TODAY - datetime.timedelta(days=fam.WINDOW_DAYS)).isoformat()
    text = (
        "## 合法边界段\n"
        "- 同根归纳：同属一族\n"
        f"- #331 案甲 2026-01-01〔日期 {cutoff}〕\n"
        "- #332 案乙\n"
        "- #333 案丙\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert row["warns"] == [], f"合法日期被误拦：{row['warns']}"
    assert row["last_date"] == cutoff
    assert row["verdict"] == "升室候选"


def test_tail_note_newer_than_field_date_does_not_lift_window() -> None:
    """判别性补强：收尾说明日期**晚于**字段日期时，活跃窗仍只认字段日期。

    既有钉 #1 的尾注日期（2026-01-01）比字段日期更早，pre/post 同结论 ⇒ 咬不住「其余行不抬窗」；
    本条把尾注改成**更新**，M157a 类退化才会被抓住。**不替换既有钉**——新增。
    """
    fam = _load()
    text = (
        "## 尾注更新段\n"
        "- 同根归纳：同属一族\n"
        "- #321 案甲〔日期 2026-01-01〕\n"
        "- #322 案乙\n"
        "- #323 案丙\n"
        "（收尾说明 2026-10-26 已修全量绿——非条目行，不是日期来源）\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert row["last_date"] == "2026-01-01", "收尾说明即使更新也不得抬窗"
    assert row["verdict"] == "族已静默"


def test_all_bad_field_dates_zero_out_window_and_exact() -> None:
    """归零路径（轮 2 复核指出：现钉无一覆盖）：段内字段日期**全部越界**且无散文日期。

    这是 `last_date = ""` 那条「无日期 ⇒ 已静默」分支在**坏字段**下的唯一来路——既有坏形状钉
    （`test_bad_shape_warns_and_falls_back`）总留一条带散文日期的 #76，所以从没走到这里。
    pre（D154）实测：`last=2027-06-01 / 升室候选 / warns=0 / exact=2`（越界值被当合法，
    且抬窗 + 虚计精确病案数）；post（D155）：全拒 ⇒ 归零静默。
    """
    fam = _load()
    text = (
        "## 全坏字段段\n"
        "- 同根归纳：同属一族\n"
        "- #501 案甲〔日期 2026-13-40〕\n"
        "- #502 案乙〔日期 2027-06-01〕\n"
        "- #503 案丙\n"
    )
    row = fam.families(text, today=TODAY)[0]
    assert len(row["warns"]) == 2, row["warns"]
    assert row["last_date"] == "", "两个越界字段都不许充当日期源"
    assert row["verdict"] == "族已静默", "越界字段不得把段抬进活跃窗"
    assert row["exact"] is None, "坏字段条目不得计入精确病案数"


def test_tomorrow_field_date_rejected_but_today_accepted() -> None:
    """紧边界对（轮 2 复核指出：G2 用 2027 远日期，测不出「只按年比较」的偷懒实现）。

    `当日` ⇒ 合法、无 WARN、字段日期生效；`当日 + 1 天` ⇒ 越界 WARN + 回退行内散文日期。
    """
    fam = _load()
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()

    def seg(date_str: str):
        text = (
            f"## 边界 {date_str}\n"
            "- 同根归纳：同属一族\n"
            f"- #701 案甲 2026-01-01〔日期 {date_str}〕\n"
            "- #702 案乙\n"
            "- #703 案丙\n"
        )
        return fam.families(text, today=TODAY)[0]

    legal = seg(TODAY.isoformat())
    assert legal["warns"] == [], f"当日不许被误拦：{legal['warns']}"
    assert legal["last_date"] == TODAY.isoformat() and legal["verdict"] == "升室候选"

    boundary = seg(tomorrow)
    assert len(boundary["warns"]) == 1, boundary["warns"]
    assert "晚于当日" in boundary["warns"][0], boundary["warns"]
    assert boundary["last_date"] == "2026-01-01", "T+1 必须回退行内散文日期，而不是继续抬窗"
    assert boundary["verdict"] == "族已静默"


def test_cli_channel_delivers_shape_warn_on_stdout(tmp_path, capsys) -> None:
    """CLI 巡检轨（`duty_signals.sh:30` 的真实消费面）：WARN 必须**到达 stdout**。

    既有钉全部在进程内调 `families()` / `render()`，无一触达 `main()` 的 argv / 读文件 /
    `print` 分支——把 `print` 改成 `sys.stderr.write` 时 15 条钉全绿而巡检输出里的 WARN 消失
    （轮 2 复核实测）。本钉把「告警送达消费者」钉住。日期用**真实当日**推导 ⇒ 不绑死某天，可长期复算。
    """
    fam = _load()
    today = datetime.date.today()
    bad = (today + datetime.timedelta(days=1)).isoformat()
    legal = today.isoformat()

    def run_cli(body: str) -> str:
        path = tmp_path / "ledger.md"
        path.write_text(body, encoding="utf-8")
        capsys.readouterr()                      # 清屏，避免上一条残留
        rc = fam.main([str(path)])
        out = capsys.readouterr().out
        assert rc == 0, f"CLI 退出码非 0：{rc}"
        return out

    warn_out = run_cli(
        f"## 巡检轨越界\n- 同根归纳：同属一族\n- #801 案甲 2026-01-01〔日期 {bad}〕\n"
        "- #802 案乙\n- #803 案丙\n"
    )
    assert "WARN 条目字段形状" in warn_out, "越字段日期的告警没送达 stdout（巡检看不见 = 等于没报）"
    assert "族已静默" in warn_out and "升室候选" not in warn_out

    quiet_out = run_cli(
        f"## 巡检轨合法\n- 同根归纳：同属一族\n- #811 案甲〔日期 {legal}〕\n"
        "- #812 案乙\n- #813 案丙\n"
    )
    assert "WARN 条目字段形状" not in quiet_out, "合法日期在 CLI 轨上被误报"
    assert "升室候选" in quiet_out


def test_current_real_file_baseline_frozen() -> None:
    """判据零变更对照钉（D154）：对现行 `bugs.md` 全文（零条目带尾缀），判据三输出逐段冻结
    = D154 落刀日基线（REVIEW-20261026-07 §3 试跑）——字段制式对旧库**零扰动**且无 WARN。"""
    fam = _load()
    rows = fam.families(BUGS.read_text(encoding="utf-8"), today=TODAY)
    got = {r["name"]: (r["count"], r["last_date"], r["verdict"]) for r in rows}
    assert got == FROZEN_BASELINE, got
    assert all(r["warns"] == [] for r in rows), "现行全文零尾缀 ⇒ 不应有任何形状 WARN"
    assert all(r["exact"] is None for r in rows), "现行全文零尾缀 ⇒ 不应出精确病案数列"


# ---------------------------------------------------------------------------
# D156 留出验证指针行形状钉（2026-10-26，RFC-20261026-03 Phase 1）——一钉
# ---------------------------------------------------------------------------

def test_holdout_pointer_line_is_judgment_neutral() -> None:
    """指针行 `- 留出验证：RFC-… / REVIEW-…` 的格式禁令的机器面（D156 / `RFC-03` §4.4）。

    正向：合规指针行（无日期 / 无 `#NN`）⇒ `count` / `last_date` / `verdict` 三值不变；
    反向：带日期 ⇒ `last_date` 被抬到指针行日期；带 `#NN` ⇒ `count` +1——这就是为什么
    格式禁日期与病案号（指针必须中性，不得污染段级信号；`duty-review/README.md` §2/§3）。
    """
    fam = _load()
    base = (
        "## 指针段\n"
        "- 同根归纳：同属一族\n"
        "- #601 案甲 2026-10-01\n"
        "- #602 案乙\n"
        "- #603 案丙\n"
    )
    legal = base + "- 留出验证：RFC-20261026-03 / REVIEW-20261026-06\n"
    dirty_date = base + "- 留出验证：RFC-20261026-03（2026-10-26）\n"
    dirty_id = base + "- 留出验证：RFC-20261026-03 / REVIEW-20261026-06 / #99\n"
    b, l, d, i = (fam.families(t, today=TODAY)[0] for t in (base, legal, dirty_date, dirty_id))
    assert (b["count"], b["last_date"], b["verdict"]) == (3, "2026-10-01", "升室候选"), b
    assert (l["count"], l["last_date"], l["verdict"]) == (b["count"], b["last_date"], b["verdict"]), \
        "合规指针行不得改变三值"
    assert d["last_date"] == "2026-10-26" and d["last_date"] != b["last_date"], \
        "反向：带日期的指针行会把最近日期抬到指针行——故格式禁日期"
    assert i["count"] == b["count"] + 1, "反向：带 #NN 的指针行会虚增案数——故格式禁 #NN"
