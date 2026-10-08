#!/usr/bin/env python3
"""`validators/validate_ledger.py` 回归测试（`3509 §97` / `§B94` / `§B96` / `§B113`）。

夹具 = 一个假 vault（两个台账卷 + 一份纪要卷）+ 一份 `product/prd/*-prd.md`。
三件事各测两侧（**正例必须绿**，否则后面的红说明不了任何事）：

  1. **撞号**：跨卷 B 号 / 纪要卷节号 / AC 号**定义**（含「2 列的结构类清单行不算定义」这一侧 ——
     它是实测踩到的假阳性：正则 `[^|]*` 会跨行吃掉后续内容）；
  2. **疑似已落地**：只列**包内路径**命中（项目侧路径只计数不列名）；
  3. **未启用知识库** ⇒ 台账项 `SKIP`（响亮原则），但项目侧 AC 项照跑。

变异证明：
  * M1 摘掉跨卷撞号判据 ⇒ `test_ledger_cross_volume_id_collision_fails` 红；
  * M2 把 `AC_DEF_ROW` 的 `[^|\\n]` 退回 `[^|]`（跨行）⇒ 2 列清单那一侧红；
  * M3 台账卷改回「含 B 行即算卷」⇒ `test_ledger_journal_is_not_a_volume` 红。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
VL = PKG_ROOT / "validators" / "validate_ledger.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_ledger_under_test", VL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vl = _load()

PROFILE = """product: 夹具
knowledge:
  tool: open-zk-bk
  vault: {vault}   # 行内注释必须被剥掉（实测踩到：注释被当成路径的一部分）
  dir: atlas
"""

OPEN = """---
title: "夹具未决清单"
---

# 夹具未决清单（未决卷）

> 卷角色：未决

| # | 问题 | 影响 | 建议动作 |
|---|---|---|---|
| B1 | 夹具问题一 | — | — |
| B2 | 夹具问题二 | — | — |
"""

ARCH = """---
title: "夹具已决归档"
---

# 夹具已决归档（已决归档）

> 卷角色：已决归档

| # | 问题 | 解决方式 |
|---|---|---|
| B3 | 夹具问题三 | 已解决 |
"""

JOURNAL = """---
title: "夹具讨论纪要"
---

# 夹具讨论纪要

| §1 | 2026-01-01 | gist |
| §2 | 2026-01-01 | gist |

## 1. 第一节

正文里引用台账（**行首即 `| B…`** ⇒ 会被 `LEDGER_ROW` 扫到，但它没声明卷角色 ⇒ 不算台账卷）：

| B9 | 引用台账条目（只是引用） | — |

## 2. 第二节
"""


def mk(root: Path, *, open_text: str = OPEN, arch_text: str = ARCH,
       journal_text: str = JOURNAL, prd_text: str = "") -> None:
    vault = root / "vault" / "atlas"
    vault.mkdir(parents=True, exist_ok=True)
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(
        PROFILE.format(vault=root / "vault"), encoding="utf-8")
    (vault / "2026010100000001-open.md").write_text(open_text, encoding="utf-8")
    (vault / "2026010100000002-arch.md").write_text(arch_text, encoding="utf-8")
    (vault / "2026010100000003-journal.md").write_text(journal_text, encoding="utf-8")
    prd = root / "product" / "prd"
    prd.mkdir(parents=True, exist_ok=True)
    (prd / "demo-prd.md").write_text(prd_text or AC_OK, encoding="utf-8")


AC_OK = """# demo 域 PRD

## 五、验收标准

| AC ID | 场景（Given / When / Then） | 回指规则 |
|---|---|---|
| `AC-DEMO-001` | Given 已登录，When 打开，Then 渲染 1 行 | `DEMO-R-001` |
| `AC-DEMO-002` | Given 已登录，When 打开，Then 首屏有容器 | `DEMO-R-001` |

#### 结构类 AC 清单

| AC ID | 为什么只能在初始态观测 |
|---|---|
| `AC-DEMO-002` | 骨架属性，只能初始态观测 |
| `AC-DEMO-003` | 另一条骨架属性（**它必须存在**：否则 2 列行是文件末行，
跨行假阳性复现不出来 —— M2 第一次没咬就是这个原因） |
"""


def _levels(res) -> dict:
    return {c["check"]: c["level"] for c in res.checks}


def _detail(res, name: str) -> str:
    return [c for c in res.checks if c["check"] == name][0]["detail"]


def test_ledger_baseline_passes() -> None:
    """正例必须先绿：两个台账卷 + 一份纪要卷 + 无撞号的 AC ⇒ 无 FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        res = vl.validate(root)
        levels = _levels(res)
        assert "FAIL" not in levels.values(), levels
        assert levels["知识库已启用"] == "PASS", levels
        assert levels["台账 B 号跨卷唯一"] == "PASS", levels
        assert levels["纪要卷编号唯一"] == "PASS", levels
        assert levels["AC 号跨文件唯一"] == "PASS", levels


def test_ledger_journal_is_not_a_volume() -> None:
    """纪要卷里引用 `| B9 |` **不算台账卷**（否则跨卷撞号会成片假阳性）。

    变异 M3：台账卷改回「含 B 行即算卷」⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        res = vl.validate(root)
        detail = _detail(res, "台账卷可定位")
        assert "open.md" in detail and "arch.md" in detail, detail
        assert "journal.md" not in detail, detail


def test_ledger_cross_volume_id_collision_fails() -> None:
    """同一 B 号出现在两卷 ⇒ FAIL（`3509 §B94`：`max+1` 只管本卷 ⇒ 跨卷必撞）。

    变异 M1：摘掉跨卷判据 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, arch_text=ARCH.replace("| B3 | 夹具问题三 | 已解决 |",
                                        "| B2 | 夹具问题二（重复取号） | 已解决 |"))
        res = vl.validate(root)
        assert _levels(res)["台账 B 号跨卷唯一"] == "FAIL", _levels(res)
        assert "B2" in _detail(res, "台账 B 号跨卷唯一"), _detail(res, "台账 B 号跨卷唯一")
        assert res.status == "FAIL"


def test_ledger_round_prefix_id_collision_fails() -> None:
    """轮次前缀形态 `B<轮次>-<序号>` 两卷同串 ⇒ FAIL（`§B94` 发号侧：撞号按整串唯一）。

    变异 M28：把 `LEDGER_ROW` 退回 `B\d+`（前缀被截断成 B139）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root,
           arch_text=ARCH.replace("| B3 | 夹具问题三 | 已解决 |",
                                  "| B139-1 | 夹具问题（轮次前缀重复取号） | 已解决 |"),
           open_text=OPEN.replace("| B2 | 夹具问题二 | — | — |",
                                  "| B2 | 夹具问题二 | — | — |\n| B139-1 | 夹具问题（轮次前缀） | — | — |"))
        res = vl.validate(root)
        assert _levels(res)["台账 B 号跨卷唯一"] == "FAIL", _levels(res)
        assert "B139-1" in _detail(res, "台账 B 号跨卷唯一"), _detail(res, "台账 B 号跨卷唯一")
        assert res.status == "FAIL"


def test_ledger_round_prefix_and_legacy_same_number_do_not_collide() -> None:
    """`B139-1`（轮次前缀）与遗留 `B139` 是**不同条号** ⇒ 不得误报撞号（`§B94`）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root,
           arch_text=ARCH.replace("| B3 | 夹具问题三 | 已解决 |",
                                  "| B139 | 遗留形态条目 | 已解决 |"),
           open_text=OPEN.replace("| B2 | 夹具问题二 | — | — |",
                                  "| B2 | 夹具问题二 | — | — |\n| B139-1 | 轮次前缀条目 | — | — |"))
        res = vl.validate(root)
        assert _levels(res)["台账 B 号跨卷唯一"] == "PASS", _levels(res)
        assert res.status != "FAIL"


def test_ledger_journal_duplicate_section_fails() -> None:
    """纪要卷内 `## <N>.` 撞号 ⇒ FAIL（实测：本卷曾有两个 §92 指两件事）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, journal_text=JOURNAL.replace("## 2. 第二节", "## 1. 第二节（撞号）"))
        res = vl.validate(root)
        assert _levels(res)["纪要卷编号唯一"] == "FAIL", _levels(res)
        assert "§1" in _detail(res, "纪要卷编号唯一"), _detail(res, "纪要卷编号唯一")


def test_ledger_ac_definition_collision_detected() -> None:
    """AC 号**定义**重复（同文件 / 跨文件）⇒ FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, prd_text=AC_OK.replace("| `AC-DEMO-002` | Given 已登录，When 打开，Then 首屏有容器 | `DEMO-R-001` |",
                                        "| `AC-DEMO-001` | Given 已登录，When 打开，Then 重复定义 | `DEMO-R-001` |"))
        res = vl.validate(root)
        assert _levels(res)["AC 号跨文件唯一"] == "FAIL", _levels(res)
        assert "AC-DEMO-001" in _detail(res, "AC 号跨文件唯一")


def test_ledger_two_column_listing_row_is_not_a_definition() -> None:
    """**结构类 AC 清单**（2 列）里的同一 ID 不算「重复定义」——实测的假阳性源。

    变异 M2：`AC_DEF_ROW` 的 `[^|\\n]` 退回 `[^|]`（可跨行）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)                                   # 基线：清单里 AC-DEMO-002 与主表同 ID
        res = vl.validate(root)
        assert _levels(res)["AC 号跨文件唯一"] == "PASS", _detail(res, "AC 号跨文件唯一")
        # 直接钉住正则本身：2 列行不得被当成定义行。**必须用多行文本**：
        # 单行字符串无法复现「`[^|]` 跨行吃掉后续行」这个假阳性（M2 第一次没咬的原因）。
        row2 = ("| `AC-DEMO-002` | 骨架属性，只能初始态观测 |\n"
                "| `AC-DEMO-003` | 另一条骨架属性 |\n")
        row3 = "| `AC-DEMO-002` | Given 已登录，When 打开，Then 渲染 | `DEMO-R-001` |"
        assert not vl.AC_DEF_ROW.search(row2), row2
        assert vl.AC_DEF_ROW.search(row3), row3


def test_ledger_skips_vault_items_when_knowledge_disabled() -> None:
    """`knowledge.vault: null` ⇒ 台账项 `SKIP`（不是通过），AC 项照跑，整体不 FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        (root / "product" / "stack-profile.yaml").write_text(
            "product: 夹具\nknowledge:\n  vault: null\n", encoding="utf-8")
        res = vl.validate(root)
        levels = _levels(res)
        assert levels["知识库已启用"] == "SKIP", levels
        assert "台账 B 号跨卷唯一" not in levels, levels        # vault 项整体跳过
        assert levels["AC 号跨文件唯一"] == "PASS", levels       # 项目侧照跑
        assert res.status != "FAIL", levels


def test_ledger_suspected_landed_lists_package_paths_only() -> None:
    """「疑似已落地」只列**包内路径**命中；项目侧路径只计数不列名（低信号）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas" / "shared").mkdir(parents=True, exist_ok=True)
        (root / ".atlas" / "shared" / "gates.md").write_text("x", encoding="utf-8")
        mk(root, open_text=OPEN.replace(
            "| B2 | 夹具问题二 | — | — |",
            "| B2 | 夹具问题二：契约 `shared/gates.md` 不存在 | — | — |\n"
            "| B4 | 夹具问题四：产物 `product/prd/prd.md` 待补 | — | — |"))
        res = vl.validate(root)
        assert _levels(res)["疑似已落地"] == "WARN", _levels(res)
        detail = _detail(res, "疑似已落地")
        assert "B2" in detail and "shared/gates.md" in detail, detail
        assert "B4" not in detail, detail                      # 项目侧路径不列名
        assert "跳过" in detail, detail


def test_ledger_open_entry_unresolved_refs_are_narrowed() -> None:
    """未决条目引用一个**不存在**的 `.atlas/` 路径 ⇒ WARN + 列名（缩围，不判 FAIL：待建 or 已删分不开）。

    变异 M10：摘掉 `unresolved_refs` 这一项 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, open_text=OPEN.replace(
            "| B2 | 夹具问题二 | — | — |",
            "| B2 | 夹具问题二：见 `.atlas/scripts/ghost-tool.py` | — | — |"))
        res = vl.validate(root)
        assert _levels(res)["未决条目引用可达"] == "WARN", _levels(res)
        detail = _detail(res, "未决条目引用可达")
        assert ".atlas/scripts/ghost-tool.py" in detail, detail


def test_ledger_cli_exit_code_is_one_on_fail() -> None:
    """CLI：FAIL ⇒ 退出码 1（响亮原则：坏输入必须显式失败）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, arch_text=ARCH.replace("| B3 | 夹具问题三 | 已解决 |",
                                        "| B1 | 夹具问题一（撞号） | 已解决 |"))
        p = subprocess.run([sys.executable, str(VL), "--root", str(root)],
                           capture_output=True, text=True, timeout=120)
        assert p.returncode == 1, p.stdout + p.stderr
        assert "FAIL" in p.stdout, p.stdout


# ---- 纪要卷滚动阈值（`closeout.md` 步骤 4；`3509 §B188-1`）----

def _mk_journal(d: Path, name: str, rounds: int, pad: int = 0) -> None:
    """造一份纪要卷：`## 0.` 常驻节 + `rounds` 个全文轮次节（每节可填 `pad` 字符）。"""
    body = "".join(f"\n## {i}. 轮次 {i}\n\n" + ("x" * pad) + "\n" for i in range(1, rounds + 1))
    (d / name).write_text(
        "---\nid: 1\ntitle: 纪要\n---\n\n# 纪要\n\n## 0. 常驻节\n" + body, encoding="utf-8")


def test_ledger_journal_overflow_by_round_count() -> None:
    """全文轮次 31（> 阈值 30）⇒ 指名命中；29 ⇒ 不命中。

    变异证明：删掉轮数判据 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _mk_journal(d, "2026010100000001-atlas-discussion-log.md", 31)
        out = vl.journal_volume_overflow(d)
        assert out and "31 轮" in out[0], out
        _mk_journal(d, "2026010100000001-atlas-discussion-log.md", 29)
        assert vl.journal_volume_overflow(d) == [], vl.journal_volume_overflow(d)


def test_ledger_journal_overflow_by_chars_and_ignores_archive() -> None:
    """轮数未达但全文轮次区 ≥ 60k 字符 ⇒ 命中（任一命中即拆卷）；历史卷不计。

    变异证明：把字符阈值抬到不可达 / 去掉 archive 过滤 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _mk_journal(d, "2026010100000001-atlas-discussion-log.md", 5, pad=15_000)
        out = vl.journal_volume_overflow(d)
        assert out and "字符" in out[0], out
        _mk_journal(d, "2026010100000002-atlas-discussion-log-archive.md", 40)
        assert [o for o in vl.journal_volume_overflow(d) if "archive" in o] == [], out


# ---- 条目 schema（`3508 §97` 八字段：类型 / 优先级行内标签；§B112 残留清偿，2026-10-06）----

def test_ledger_schema_missing_tags_warn_and_listed() -> None:
    """未决条目缺 `类型：` / `优先级：` 行内标签 ⇒ WARN + 列名；归档卷不参与。

    变异证明 M31：摘掉 schema 判据 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        res = vl.validate(root)
        assert _levels(res)["条目 schema（类型/优先级）"] == "WARN", _levels(res)
        detail = _detail(res, "条目 schema（类型/优先级）")
        assert "B1" in detail and "B2" in detail, detail


def test_ledger_backtick_wrapped_id_row_is_scanned() -> None:
    """反引号包裹条号的行 `` | `B191-1` | `` 也是条目行（实测形态：3509 的 B191 行）。

    变异证明：退回裸正则（不容反引号）⇒ 本用例红（该行进不了 schema 判据与汇总计数）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, open_text=OPEN + "| `B191-1` | 图谱批 2 待建条目（反引号形态） | — | — |\n")
        res = vl.validate(root)
        detail = _detail(res, "条目 schema（类型/优先级）")
        assert "B191-1" in detail, detail
        assert "未决 3 项" in _detail(res, "待裁决汇总"), _detail(res, "待裁决汇总")


def test_ledger_schema_tagged_entries_pass_and_counts_correct() -> None:
    """带全标签的条目 ⇒ PASS；待裁决汇总按优先级分行计数（`§97` ④ 报告先行口径）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, open_text=OPEN.replace(
            "| B1 | 夹具问题一 | — | — |",
            "| B1 | 夹具问题一。类型：产品裁定；优先级：P0 | — | — |").replace(
            "| B2 | 夹具问题二 | — | — |",
            "| B2 | 夹具问题二。类型：流水线决策；优先级：P2 | — | — |"))
        res = vl.validate(root)
        assert _levels(res)["条目 schema（类型/优先级）"] == "PASS", _levels(res)
        summary = _detail(res, "待裁决汇总")
        assert "P0×1" in summary and "P2×1" in summary and "未标级×0" in summary, summary


def test_ledger_label_row_form_is_scanned() -> None:
    """第二格标签形态 `|| C9 | … |`（A / C 节）也进条目扫描（`§B102` 全卷对账）。

    变异证明 M32：把 LABEL_ROW 从扫描里摘掉 ⇒ 本用例红（C9 不进疑似清单也不进 schema 判据）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".atlas" / "shared").mkdir(parents=True, exist_ok=True)
        (root / ".atlas" / "shared" / "gates.md").write_text("x", encoding="utf-8")
        c_row = "|| C9 | 夹具待设计项：契约 `shared/gates.md` 形态待定 | 延后 |\n"
        mk(root, open_text=OPEN + "\n## C. 待设计\n\n| # | 缺什么 | 状态 |\n|---|---|---|\n" + c_row)
        res = vl.validate(root)
        # ① 疑似已落地扫到 C 行
        detail = _detail(res, "疑似已落地")
        assert "C9" in detail and "shared/gates.md" in detail, detail
        # ② schema 判据覆盖 C 行（未打标签 ⇒ 进缺口清单）
        assert "C9" in _detail(res, "条目 schema（类型/优先级）"), _detail(res, "条目 schema（类型/优先级）")
        # ③ 汇总的未决计数含 C 行（B1/B2/C9 = 3 项）
        assert "未决 3 项" in _detail(res, "待裁决汇总"), _detail(res, "待裁决汇总")


# ---- 契约时效对账（gates.md §2.2，2026-10-08 机器门）----

def test_contract_freshness_clean_passes() -> None:
    """契约与 Note 保持时效同步时，对账门 PASS。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        (root / "atlas" / "rings" / "structure").mkdir(parents=True, exist_ok=True)
        (root / "atlas" / "shared").mkdir(parents=True, exist_ok=True)
        c_file = root / "atlas" / "rings" / "structure" / "reference.md"
        c_file.write_text("contract", encoding="utf-8")

        vault = root / "vault" / "atlas"
        (vault / "2026010100000005-structure-ring.md").write_text(
            "---\nupdated: 2026-10-08\n---\n# structure", encoding="utf-8"
        )
        res = vl.validate(root)
        assert _levels(res)["契约时效对账"] == "PASS", _levels(res)


def test_contract_freshness_stale_note_warns() -> None:
    """契约在 git 中有更新提交，但 Note updated 日期滞后 ⇒ WARN。

    变异证明 M43：摘掉 check_contract_freshness 或不比对日期 ⇒ 本用例红。
    """
    import os
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=str(root), check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(root), check=True)

        (root / "atlas" / "rings" / "structure").mkdir(parents=True, exist_ok=True)
        (root / "atlas" / "shared").mkdir(parents=True, exist_ok=True)
        c_file = root / "atlas" / "rings" / "structure" / "reference.md"
        c_file.write_text("contract", encoding="utf-8")

        vault = root / "vault" / "atlas"
        (vault / "2026010100000005-structure-ring.md").write_text(
            "---\nupdated: 2026-01-01\n---\n# structure", encoding="utf-8"
        )

        subprocess.run(["git", "add", "."], cwd=str(root), check=True)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-10-08 12:00:00",
                   GIT_COMMITTER_DATE="2026-10-08 12:00:00")
        subprocess.run(["git", "commit", "-q", "-m", "update contract"],
                       cwd=str(root), env=env, check=True)

        res = vl.validate(root)
        assert _levels(res)["契约时效对账"] == "WARN", _levels(res)
        detail = _detail(res, "契约时效对账")
        assert "rings/structure/reference.md" in detail, detail
        assert "2026-10-08" in detail and "2026-01-01" in detail, detail

