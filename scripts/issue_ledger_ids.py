#!/usr/bin/env python3
"""atlas 发号器 —— 取号前直查各号空间的当前实况（`3509 §B94` 半条 + `§B112` 残留清偿，2026-10-06）。

**病根**（三次实测）：取号靠「记忆里的 max + 模式匹配 grep」——① 模式有盲区：`14[89]`/`15[0-9]`
漏看 146/147 段 ⇒ 撞了并发会话的 #146（2026-09-30）；② 并发各取一次：2026-10-04 两会话同写
`## 179.`，`validate_ledger` 撞号门当场抓红 ⇒ 门有效、发号侧缺（2026-10-05 纪要 §188 登记）；
③ 正文里的举例（如 `B139-1 ≠ B139` 的说明文字）会让 grep 求 max 得出假号。本器把「按号直查
实况」机制化：读**当前**文件求真 max；`--check` 按整串精确核对候选号（`B139` ≠ `B139-1`，
两种形态通吃）。

号空间（四类）：

  - **纪要轮次** `§<N>`：vault 纪要卷（含历史卷）的 `## <N>.` 节号，全局连续；
  - **台账号** `B<NN>[-<k>]`：vault 台账卷（未决 + 归档）、纪要卷、项目台账 `product/issues.md`、
    `ATLAS-UPSTREAM.md` 里的**整串出现**（正文引用也算占用 —— 保守侧）；
  - **回灌批号** `#<N>`：`ATLAS-UPSTREAM.md`；
  - **项目侧条目号** `P<NN>`：`product/issues.md` + vault（`P0/P1/P2` 优先级词形与号同形 ⇒
    检查是保守的：同串出现即算占用）。

用法：

    python3 .atlas/scripts/issue_ledger_ids.py --root .              # 各号空间 max + 建议下一号
    python3 .atlas/scripts/issue_ledger_ids.py --check B191-3        # 台账号
    python3 .atlas/scripts/issue_ledger_ids.py --check "§192"        # 纪要轮次
    python3 .atlas/scripts/issue_ledger_ids.py --check "#174"        # 回灌批号
    python3 .atlas/scripts/issue_ledger_ids.py --check P13           # 项目侧条目号

退出码：0 = 空闲 / 正常；1 = 已被占用（`--check`，列名出处）或**回灌清单重号**（默认模式，
2026-10-07 补：max 直查抓不到重号、`--check` 只答候选号占用也放行）；2 = 环境不可用 / 候选号
形态不认识（显式失败，不静默）。纯标准库；vault 定位复用 `validators/validate_ledger.py` 的解析。

**盲区（写明，不冒充互斥锁）**：本器只读直查 ⇒ 检查与写入之间存在并发窗口，同窗双取仍可能
同号。兜底 = ① **落笔当轮取号**（写入前重跑本器重读文件尾）；② `validate_ledger` 撞号门事后
必咬（纪要卷编号唯一 / 台账跨卷整串唯一）⇒ 后写者让号（2026-10-04 实操先例）。
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

_VL = Path(__file__).resolve().parents[1] / "validators" / "validate_ledger.py"


def _load_vl():
    spec = importlib.util.spec_from_file_location("_atlas_validate_ledger_for_ids", _VL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vl = _load_vl()


def scan_texts(root: Path) -> list[tuple[str, str]]:
    """(来源名, 文本)：vault 全部 note + 项目台账 + ATLAS-UPSTREAM（存在才进）。"""
    out: list[tuple[str, str]] = []
    vault, dirname = vl.read_knowledge(root)
    if vault:
        vdir = Path(vault) / dirname
        if vdir.is_dir():
            for f in sorted(vdir.glob("*.md")):
                out.append((f"vault:{f.name}", f.read_text(encoding="utf-8", errors="replace")))
    for rel in ("product/issues.md", "ATLAS-UPSTREAM.md"):
        p = root / rel
        if p.is_file():
            out.append((rel, p.read_text(encoding="utf-8", errors="replace")))
    return out


def journal_max(vault_dir: Path) -> int:
    """纪要轮次真 max：全部纪要卷（含历史卷）的 `## <N>.` 节号取最大（`§0` 常驻节不计）。"""
    mx = 0
    for f in vault_dir.glob("*discussion-log*.md"):
        for n in vl.JOURNAL_SEC.findall(f.read_text(encoding="utf-8", errors="replace")):
            i = int(n.split(".")[0])
            if i > mx:
                mx = i
    return mx


def upstream_max(root: Path) -> int:
    """回灌批号真 max：**两种形态都扫** —— 散文引用 `#173` 与清单行首格 `| 173 |`
    （实测：清单行不带 `#` 前缀，只扫 `#N` 会漏看整段行号，2026-10-06 首跑即咬）。"""
    p = root / "ATLAS-UPSTREAM.md"
    if not p.is_file():
        return 0
    text = p.read_text(encoding="utf-8", errors="replace")
    nums = ([int(x) for x in re.findall(r"#(\d+)", text)]
            + [int(x) for x in re.findall(r"\|\s*(\d+)\s*\|", text)])
    return max(nums) if nums else 0


def upstream_duplicates(root: Path) -> dict[int, int]:
    """回灌清单**行首格批号重号**检测（2026-10-07 实撞：两行同号 `| 174 |` 并存——
    max 直查抓不到重号、`--check` 只答候选号占用也放行 ⇒ 重号让「按号可查」失义）。
    返回 {批号: 出现行数}（仅 >1 的）。"""
    p = root / "ATLAS-UPSTREAM.md"
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8", errors="replace")
    counts: dict[int, int] = {}
    for m in re.finditer(r"^\|\s*(\d+)\s*\|", text, re.M):
        n = int(m.group(1))
        counts[n] = counts.get(n, 0) + 1
    return {n: c for n, c in counts.items() if c > 1}


def project_p_max(root: Path) -> int:
    p = root / "product" / "issues.md"
    if not p.is_file():
        return 0
    nums = [int(x) for x in re.findall(r"\bP(\d+)\b", p.read_text(encoding="utf-8", errors="replace"))]
    return max(nums) if nums else 0


def _candidate_pattern(candidate: str) -> tuple[list[re.Pattern], str] | None:
    """候选号 → （该算占用的精确形态正则组, 归属号空间）。不认识的形态返回 None。"""
    m = re.fullmatch(r"B(\d+)(?:-(\d+))?", candidate)
    if m:
        if m.group(2):  # 轮次前缀形态：整串唯一，但不得吃掉 B139-10 里的 B139-1
            return [re.compile(rf"\bB{m.group(1)}-{m.group(2)}(?!\d)")], "台账号"
        return [re.compile(rf"\bB{m.group(1)}(?![\d-])")], "台账号"  # 裸形态 ≠ B139-1（§B94）
    m = re.fullmatch(r"§(\d+)", candidate)
    if m:  # 正文引用 `§179` 与节标题 `## 179.` 两种占用形态
        return [re.compile(rf"§{m.group(1)}(?![\d.])"),
                re.compile(rf"^##\s*{m.group(1)}\.\s", re.M)], "纪要轮次"
    m = re.fullmatch(r"#(\d+)", candidate)
    if m:  # 两种占用形态：散文引用 `#173` 与清单行首格 `| 173 |`（实测行号不带 # 前缀）
        return [re.compile(rf"#{m.group(1)}(?!\d)"),
                re.compile(rf"\|\s*{m.group(1)}\s*\|")], "回灌批号"
    m = re.fullmatch(r"P(\d+)", candidate)
    if m:
        return [re.compile(rf"\bP{m.group(1)}(?!\d)")], "项目侧条目号"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", default=None,
                    help="候选号：B191-3 / §192 / #174 / P13 —— 直查是否已被占用")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    vault, dirname = vl.read_knowledge(root)
    if not vault or not (Path(vault) / dirname).is_dir():
        print(f"ERROR: vault 不可定位（knowledge.vault = {vault!r}）—— 显式失败，不给结论",
              file=sys.stderr)
        return 2

    if args.check:
        parsed = _candidate_pattern(args.check)
        if parsed is None:
            print(f"ERROR: 候选号「{args.check}」形态不认识"
                  "（支持 B<NN>[-<k>] / §<N> / #<N> / P<NN>）", file=sys.stderr)
            return 2
        pats, space = parsed
        texts = scan_texts(root)
        if space == "回灌批号":  # #N 只在 ATLAS-UPSTREAM 空间有语义，别处 #123 是锚/标题
            texts = [(n, t) for n, t in texts if n == "ATLAS-UPSTREAM.md"]
        if space == "项目侧条目号":  # P 号注册处 = 项目台账；vault 引用一并保守计入
            texts = [(n, t) for n, t in texts if n != "ATLAS-UPSTREAM.md"]
        hits: list[str] = []
        for name, text in texts:
            if any(p.search(text) for p in pats):
                hits.append(name)
        if hits:
            print(f"{args.check}（{space}）已被占用：{'、'.join(hits)}")
            return 1
        print(f"{args.check}（{space}）空闲")
        return 0

    vdir = Path(vault) / dirname
    dups = upstream_duplicates(root)
    if dups:
        for n, c in sorted(dups.items()):
            print(f"回灌清单重号：#{n} 出现 {c} 行（撞号——后写者让号，先改号再取号；"
                  f"重号让「按号可查」失义，2026-10-07 实撞形态）")
        return 1
    jm = journal_max(vdir)
    um = upstream_max(root)
    pm = project_p_max(root)
    print(f"纪要轮次：max §{jm} ⇒ 下一轮 §{jm + 1}（建议台账号 B{jm + 1}-<序号>，轮次前缀形态）")
    print(f"回灌批号：max #{um} ⇒ 建议 #{um + 1}（ATLAS-UPSTREAM.md）")
    print(f"项目侧条目号：max P{pm} ⇒ 建议 P{pm + 1}（product/issues.md）")
    print("落笔前用 --check <候选> 直查占用；本器只读，并发窗口由撞号门 + 后写者让号兜底。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
