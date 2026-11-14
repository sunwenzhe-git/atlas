#!/usr/bin/env python3
"""docs/map 计数锚刷新器（`RFC-20261114-04` 阶段 1）。

检测真源**不另造**：直接复用 `tests/test_map_anchors.py` 的
`collect_docs` / `check_snapshot` / `check_freshness` / `_derive_snapshot`，
本器只是「薄 CLI + 写层」。

只写三类（其余一律跳过并打印）：
  1. md 里的 `path`(N 行) 括注与 `| `path` | N |` 表格行数；
  2. `docs/map/index.md`「## 数字快照」的实收键数字（键表复用 `_derive_snapshot`）；
  3. `docs/map/atlas-map.html` 文件条目的 `N 行` 与 `×N` / `N 文件` 计数。

明确不写：
  * `path:line` 行号锚——那个锚类的唯一写者是 `tests/test_map_anchors.py --fix`；
  * `shared/gates.md` 与 canonical 计数——打印「范围外 N 处」，归机器判 + 人工改；
  * 版本串——只报告，版本是发版动作。

纪律：缺省 dry-run（`--write` 才落盘）；脏树响亮告警但按工作树现值写；
非源仓（无 `docs/map`）或非 git 仓 ⇒ 响亮 SKIP（exit 0，不假装通过）；
写后同进程复跑三个检测函数，余漂非零 exit 1。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_map_anchors import (  # noqa: E402
    HTML_FILE_RE,
    _derive_snapshot,
    _resolve,
    _strip_section,
    check_freshness,
    check_snapshot,
    collect_docs,
)

DEFAULT_ROOT = HERE.parent

# 括注形态：`scripts/a.py`(818 行)——行数在括号内紧跟「行」
PAREN_RE = re.compile(r"`(?P<path>[^`\s]+)`\((?P<num>\d+)(?=\s*行)")
# 表格形态：| `scripts/a.py` | 818 | desc |
TABLE_RE = re.compile(r"^\|\s*`(?P<path>[^`\s]+)`\s*\|\s*(?P<num>\d+)\s*\|", re.M)
SNAP_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", re.M)
HTML_LINE_RE = re.compile(r"(\d+)\s*行")
HTML_COUNT_RES = (
    (re.compile(r"出厂测试 ×(\d+)"), "出厂测试文件"),
    (re.compile(r"tests/ (\d+) 文件"), "出厂测试文件"),
    (re.compile(r"契约 ×(\d+)"), "共享契约"),
    (re.compile(r"内核 ×(\d+)"), "共享内核"),
)
# `shared/gates.md` 里由 canonical 机器判的计数形态：本器只数不写
GATES_COUNT_RES = (
    re.compile(r"(\d+)\s*个\**\s*测试文件"),
    re.compile(r"移除后\s*\**(\d+)/(\d+)\**"),
    re.compile(r"自检（\**(\d+)\s*条"),
    re.compile(r"当前\s*(\d+)\s*\)"),
    re.compile(r"`tests/[\w.]+\.py`[^|]{0,80}?\d+\s*条"),
)


def _read(path: Path) -> str:
    """newline='' 读：写回时除数字外逐字节不动（不静默转 CRLF）。"""
    with path.open(encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def _is_count_target(tok: str) -> bool:
    """计数锚的路径值域：不得是 `path:line`（行号锚归 fix_drifts）。"""
    return ":" not in tok


def _count_line(tok: str, root: Path) -> int | None:
    """与 `check_freshness._claim` 同口径：路径 → 工作树实况行数。"""
    if not _is_count_target(tok):
        return None
    target = _resolve(_strip_section(tok), root)
    if target is None or not target.is_file():
        return None
    return len(_read(target).splitlines())


def self_check_regexes() -> None:
    """正则写死后的自检：同一行同时有 `path:line` 与计数时，只准命中计数。

    自检不通过 = 本器会误改行号锚 ⇒ 当场 AssertionError（宁可炸，不可错写）。
    """
    line = "`keep`(`scripts/a.py:12`) + `scripts/a.py`(34 行)"
    hits = [m.group("path") for m in PAREN_RE.finditer(line)]
    assert hits == ["scripts/a.py"], f"括注正则误命中行号锚：{hits}"
    bad_row = "| `scripts/a.py:12` | 12 |"
    m = TABLE_RE.search(bad_row)
    assert m is not None and not _is_count_target(m.group("path")), \
        "表格正则把 `path:line` 当成计数锚（一个锚类只准一个写者）"
    good_row = "| `scripts/a.py` | 12 |"
    m2 = TABLE_RE.search(good_row)
    assert m2 is not None and _is_count_target(m2.group("path")), \
        "表格正则漏接合法计数锚"


class Plan:
    def __init__(self) -> None:
        self.edits: dict[Path, list[tuple[int, int, str, str]]] = {}
        self.targets: set[Path] = set()
        self.out_of_scope: list[str] = []

    def add(self, path: Path, start: int, end: int, old: str, new: str) -> None:
        if old == new:
            return
        self.edits.setdefault(path, []).append((start, end, old, new))

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.edits.values())


def _collect_md(plan: Plan, root: Path) -> None:
    for f in sorted((root / "docs" / "map").glob("*.md")):
        text = _read(f)
        for rx in (PAREN_RE, TABLE_RE):
            for m in rx.finditer(text):
                tok = m.group("path")
                real = _count_line(tok, root)
                if real is None:
                    continue
                target = _resolve(_strip_section(tok), root)
                if target is not None:
                    plan.targets.add(target)
                plan.add(f, m.start("num"), m.end("num"), m.group("num"), str(real))


def _collect_snapshot(plan: Plan, root: Path, derived: dict[str, int]) -> None:
    """index.md 数字快照：键表 = `_derive_snapshot` 实收键，不另抄一份。"""
    idx = root / "docs" / "map" / "index.md"
    if not idx.is_file():
        return
    text = _read(idx)
    if "## 数字快照" not in text:
        plan.out_of_scope.append("docs/map/index.md 无「## 数字快照」段")
        return
    start = text.index("## 数字快照")
    section = text[start:]
    if "\n## " in section:
        section = section[:section.index("\n## ")]
    for m in SNAP_ROW_RE.finditer(section):
        name, val = m.group(1).strip(), m.group(2)
        if name in ("量", "---"):
            continue
        if name not in derived:
            plan.out_of_scope.append(f"docs/map/index.md「{name}」行（无机器判据，本器不写）")
            continue
        num = re.search(r"(\d+)\s*行", val) or re.search(r"(\d+)", val)
        if not num:
            continue
        real = derived[name]
        if name == "最大单件":
            scripts = sorted((root / "scripts").glob("*.py")) if (root / "scripts").is_dir() else []
            if scripts:
                best = max(scripts, key=lambda p: len(_read(p).splitlines()))
                claimed = re.search(r"`([^`]+)`", val)
                if claimed and claimed.group(1) != f"scripts/{best.name}":
                    plan.out_of_scope.append(
                        f"最大单件易主：{claimed.group(1)} → scripts/{best.name}"
                        "（只改数字，不改文件名）")
        abs_start = start + m.start(2) + num.start(1)
        plan.targets.add(idx)
        plan.add(idx, abs_start, abs_start + len(num.group(1)), num.group(1), str(real))


def _collect_html(plan: Plan, root: Path, derived: dict[str, int]) -> None:
    html = root / "docs" / "map" / "atlas-map.html"
    if not html.is_file():
        return
    text = _read(html)
    for m in HTML_FILE_RE.finditer(text):
        entry, desc = m.group(1), m.group(2)
        if not desc:
            continue
        real = _count_line(re.sub(r":\d+$", "", entry), root)
        if real is None:
            continue
        target = _resolve(_strip_section(re.sub(r":\d+$", "", entry)), root)
        base = m.start(2)
        for dm in HTML_LINE_RE.finditer(desc):
            if target is not None:
                plan.targets.add(target)  # 只有「声明了 N 行」的目标才算行数敏感件
            plan.add(html, base + dm.start(1), base + dm.end(1), dm.group(1), str(real))
    for rx, key in HTML_COUNT_RES:
        for cm in rx.finditer(text):
            plan.add(html, cm.start(1), cm.end(1), cm.group(1), str(derived[key]))


def collect_plan(root: Path) -> Plan:
    plan = Plan()
    derived = _derive_snapshot(root)
    _collect_md(plan, root)
    _collect_snapshot(plan, root, derived)
    _collect_html(plan, root, derived)
    gates = root / "shared" / "gates.md"
    if gates.is_file():
        g = _read(gates)
        n = sum(len(rx.findall(g)) for rx in GATES_COUNT_RES)
        if n:
            plan.out_of_scope.append(
                f"shared/gates.md 计数 {n} 处（canonical 机器判，本器不碰）")
    return plan


def _warn_dirty(plan: Plan, root: Path) -> None:
    rels = sorted({p.relative_to(root).as_posix() for p in plan.targets
                   if p.is_file() and root in p.parents})
    if not rels:
        return
    p = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *rels],
                       capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        return
    print("[WARN] 脏树：以下行数敏感文件工作树 != HEAD——数字按工作树现值写，"
          "须与锚同批提交，否则干净树咬红（a0bdd53）")
    for line in p.stdout.splitlines():
        print("       " + line)


def _report(plan: Plan, root: Path) -> None:
    if not plan.total:
        print("计数锚：0 处待写（已对齐）")
    else:
        print(f"计数锚：待写 {plan.total} 处（{len(plan.edits)} 个文件）")
        for path in sorted(plan.edits):
            rel = path.relative_to(root).as_posix()
            for _start, _end, old, new in plan.edits[path]:
                print(f"  [写] {rel}: {old} -> {new}")
    for item in plan.out_of_scope:
        print(f"  范围外：{item}")


def _apply(plan: Plan) -> int:
    n = 0
    for path, edits in plan.edits.items():
        text = _read(path)
        for start, end, _old, new in sorted(edits, key=lambda e: e[0], reverse=True):
            text = text[:start] + new + text[end:]
            n += 1
        _write(path, text)
    return n


def _in_git(root: Path) -> bool:
    p = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return p.returncode == 0 and p.stdout.strip() == "true"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="刷新 docs/map 计数锚（RFC-20261114-04；缺省 dry-run）")
    ap.add_argument("--write", action="store_true", help="落盘（缺省只打印计划）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="源包根（含 docs/map）")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if not (root / "docs" / "map").is_dir():
        print("SKIP：docs/map 不在场——本器源包态专用（采纳仓装配态无实现地图，不假装通过）")
        return 0
    if not _in_git(root):
        print("SKIP：本仓不是 git 仓库——本器源包态专用")
        return 0

    self_check_regexes()
    plan = collect_plan(root)
    _warn_dirty(plan, root)
    _report(plan, root)
    for v in check_freshness(root):
        if v["code"] == "version_stale":
            print(f"  [报告·不写] {v['where']} {v['msg']}")

    if not args.write:
        print("dry-run：未落盘（--write 才写）")
        return 0

    n = _apply(plan)
    print(f"已写 {n} 处数字（{len(plan.edits)} 个文件）")
    bad = collect_docs(root) + check_snapshot(root) + check_freshness(root)
    if bad:
        for v in bad:
            print(f"  [余漂] {v['code']} {v['where']} {v['msg']}")
        print(f"写后自检：余漂 {len(bad)} 处 -> exit 1")
        return 1
    print("写后自检：collect_docs / check_snapshot / check_freshness 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
