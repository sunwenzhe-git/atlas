#!/usr/bin/env python3
"""`scripts/issue_ledger_ids.py` 回归测试（`3509 §B94` 半条 + `§B112` 残留清偿，2026-10-06）。

夹具 = 假 vault（未决 + 归档 + 纪要 + 纪要历史卷）+ `product/issues.md` + `ATLAS-UPSTREAM.md`。
三条线（正例必须绿）：

  1. **max 直查**：纪要轮次跨卷（含历史卷）取真 max；回灌批号 / 项目侧 P 号各自取真 max；
  2. **--check 精确核对**：整串唯一（`B139` ≠ `B139-1`，`§B94`）；正文引用也算占用（保守侧）；
  3. **响亮失败**：候选号形态不认识 / vault 不可定位 ⇒ exit 2（不静默给结论）。

变异证明（`gates.md` 2.1 行）：M33 摘掉「B139 ≠ B139-1」的形态区分 ⇒
`test_check_bare_id_not_confused_with_prefixed` 红；M34 摘掉历史卷参与 max ⇒ `test_next_round_spans_archive_volumes` 红。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
IL = PKG_ROOT / "scripts" / "issue_ledger_ids.py"

PROFILE = """product: 夹具
knowledge:
  vault: {vault}
  dir: atlas
"""

OPEN = """# 未决卷

> 卷角色：未决

| # | 问题 |
|---|---|
| B2 | 夹具条目 |
"""

ARCH = """# 已决归档

> 卷角色：已决归档

| # | 解决 |
|---|---|
| B139-1 | 轮次前缀形态条目（占号） |
"""

JOURNAL = """# 讨论纪要

## 1. 第一节

## 2. 第二节
"""

JOURNAL_ARCH = """# 讨论纪要（历史卷）

## 8. 历史第八节
"""

ISSUES = """# 项目侧台账

| # | 问题 |
|---|---|
| P3 | 夹具项目条目 |
"""

UPSTREAM = """# 回灌清单

| # | 变更 |
|---|---|
| 171 | 夹具批（清单行形态：首格裸号，实测不带 # 前缀） |
"""


def mk(root: Path, *, knowledge_enabled: bool = True) -> None:
    vault = root / "vault" / "atlas"
    vault.mkdir(parents=True, exist_ok=True)
    (root / "product").mkdir(parents=True, exist_ok=True)
    profile = PROFILE.format(vault=root / "vault") if knowledge_enabled else \
        "product: 夹具\nknowledge:\n  vault: null\n"
    (root / "product" / "stack-profile.yaml").write_text(profile, encoding="utf-8")
    (vault / "2026010100000001-open.md").write_text(OPEN, encoding="utf-8")
    (vault / "2026010100000002-arch.md").write_text(ARCH, encoding="utf-8")
    (vault / "2026010100000003-atlas-discussion-log.md").write_text(JOURNAL, encoding="utf-8")
    (vault / "2026010100000004-atlas-discussion-log-archive.md").write_text(JOURNAL_ARCH, encoding="utf-8")
    (root / "product" / "issues.md").write_text(ISSUES, encoding="utf-8")
    (root / "ATLAS-UPSTREAM.md").write_text(UPSTREAM, encoding="utf-8")


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(IL), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=120)


def test_next_round_spans_archive_volumes() -> None:
    """纪要轮次 max 跨历史卷：当前卷 max §2、历史卷有 §8 ⇒ 下一轮 §9。

    变异证明 M34：只扫当前卷 ⇒ 本用例红（会建议 §3，撞历史卷的 §8 之后空间）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p = run(root)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "§9" in p.stdout, p.stdout          # max §8（历史卷）⇒ 下一轮 §9
        assert "B9" in p.stdout, p.stdout          # 建议台账号 B<轮次>-<序号>
        assert "#172" in p.stdout, p.stdout        # 回灌 max #171 ⇒ 建议 #172
        assert "P4" in p.stdout, p.stdout          # 项目侧 max P3 ⇒ 建议 P4


def test_check_prefixed_id_taken() -> None:
    """`--check B139-1`：归档卷已有同串条目 ⇒ exit 1 + 列名出处。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p = run(root, "--check", "B139-1")
        assert p.returncode == 1, p.stdout + p.stderr
        assert "arch.md" in p.stdout, p.stdout


def test_check_bare_id_not_confused_with_prefixed() -> None:
    """`B139` 与 `B139-1` 是**不同条号**（`§B94` 整串唯一）⇒ 查 B139 必须空闲。

    变异证明 M33：裸形态正则退回 `\\bB139\\b`（会匹配 B139-1 的前缀）⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p = run(root, "--check", "B139")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "空闲" in p.stdout, p.stdout


def test_check_journal_reference_counts_as_taken() -> None:
    """正文引用也算占用（保守侧）：`§2` 既有节标题又在纪要卷 ⇒ exit 1；`§3` 空闲。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        assert run(root, "--check", "§2").returncode == 1
        assert run(root, "--check", "§3").returncode == 0


def test_check_upstream_and_project_ids() -> None:
    """`#171` 占用（清单行裸号形态）/ `#172` 空闲；`P3` 占用 / `P4` 空闲。

    变异证明：upstream 只扫 `#N` 散文形态 ⇒ 首跑实况漏看 166–173 整段（2026-10-06 首跑即咬）
    ⇒ 本用例红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        assert run(root, "--check", "#171").returncode == 1
        assert run(root, "--check", "#172").returncode == 0
        assert run(root, "--check", "P3").returncode == 1
        assert run(root, "--check", "P4").returncode == 0


def test_upstream_duplicate_rows_fail_loudly() -> None:
    """回灌清单两行同号 ⇒ 默认模式 exit 1 + 指名（2026-10-07 实撞形态：两行 `| 174 |` 并存）。

    max 直查抓不到重号、`--check` 只答候选号占用也放行 ⇒ 重号必须由本检测咬。
    变异证明 M37：摘掉 `upstream_duplicates` 调用 ⇒ 本用例红（exit 0 且不指名）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        (root / "ATLAS-UPSTREAM.md").write_text(
            UPSTREAM + "| 171 | 重复批（后写者本应让号） |\n", encoding="utf-8")
        p = run(root)
        assert p.returncode == 1, p.stdout + p.stderr
        assert "#171" in p.stdout, p.stdout
        assert "重号" in p.stdout, p.stdout
        assert "2 行" in p.stdout, p.stdout


def test_check_unknown_form_fails_loudly() -> None:
    """候选号形态不认识 ⇒ exit 2（显式失败，不猜）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root)
        p = run(root, "--check", "XYZ")
        assert p.returncode == 2, p.stdout + p.stderr


def test_disabled_vault_fails_loudly() -> None:
    """vault 不可定位 ⇒ exit 2（响亮原则：显式失败，不给结论）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, knowledge_enabled=False)
        p = run(root)
        assert p.returncode == 2, p.stdout + p.stderr
        assert "ERROR" in p.stderr, p.stderr
