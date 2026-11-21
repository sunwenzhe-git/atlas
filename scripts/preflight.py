#!/usr/bin/env python3
"""批次预检：按「本批改了哪些文件」挑测试，只跑命中的那些。

问题定义（2026-11-17 设计缺陷审计 F1 / 账本设计案步 5）：D100 把提交时的门交给
「CI + 全量纪律」，但 CI 只跑 2 个测试文件，本地也没有任何按批入口 —— 改动到发版
之间没有机器反馈。本器补这个入口；判据不新写，命中即跑既有 `tests/`，保持单源。

输入：本批改动文件（缺省 = `origin/main...HEAD` + 工作树 + 未跟踪；可 `--base` / `--files`）
输出：每个改动文件命中了哪些测试；跑不到测试的显式列「无覆盖」；实际运行结果。

映射规则（过近似：宁可多跑，不可漏跑）：
  1. `tests/test_*.py` 改动 ⇒ 跑它自己；
  2. 账本/契约正文（`DESIGN.md`、`shared/**`、`docs/map/**`）⇒ 账本窄集；
  3. 装配面（`install.py` / `install.sh` / `package.json` / `bin/` / `.github/`）⇒ 装配窄集；
  4. 其余按「测试文本里是否出现该文件的路径 / 文件名 / 模块名」反查。

已知盲区（不静默：命中为空时一定打印「无覆盖」）：
  * 测试用动态拼出的模块名、或只经夹具间接覆盖的行为，反查不到；
  * `.github/` 下的 YAML 没有测试，只能映射到装配窄集（CI 行为本身无覆盖）；
  * 过近似会让「改内核 ⇒ 跑很多测试」，这是刻意的取舍，不是缺陷。

退出码：0 全部通过（允许存在无覆盖，但会显式列出）；1 有用例失败；2 输入/环境错误。
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
TESTS_GLOB = "test_*.py"

# 窄集：正文改动的固定落点（只列真实存在的文件；缺失的跳过并在输出里说明）
LEDGER_TESTS = (
    "tests/test_canonical_consistency.py",
    "tests/test_map_anchors.py",
    "tests/test_ledger_snapshot.py",
    "tests/test_gate_registry.py",
)
ASSEMBLY_TESTS = (
    "tests/test_assembly_surface.py",
    "tests/test_cli_commands.py",
    "tests/test_project_wiring.py",
)

LEDGER_FILES = {"DESIGN.md", "scripts/atlas_check.py"}
LEDGER_PREFIXES = ("shared/", "docs/map/", "validators/")
# 2026-11-21 复盘 R4/C4/B2：`scripts/atlas_check.py`（校验器数源）与 `validators/`
# （校验器文件数源）是派生键的**源**——改源必改派生值，却不触发账本测试，导致
# 「12 器 vs 13」存活多日（B2）与行数锚发版前 1 分钟才复位（C4）。显式入映射，
# 不再依赖回退的文件名字面量反查。
ASSEMBLY_FILES = {"install.py", "install.sh", "package.json"}
ASSEMBLY_PREFIXES = ("bin/", ".github/")


class PreflightError(RuntimeError):
    """输入/环境错误 —— 不许静默退回「跑全量」或「什么都不跑」。"""


def _git(root: Path, *args: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise PreflightError(
            f"git {' '.join(args)} 失败：{(r.stderr or r.stdout).strip()}\n"
            "提示：确认 --base 是有效 ref（缺省 origin/main），或显式传 --files")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def changed_files(root: Path, base: str) -> list[str]:
    """本批改动 = base...HEAD（提交）+ HEAD 工作树（暂存/未暂存）+ 未跟踪。"""
    out: set[str] = set()
    if base:
        out.update(_git(root, "diff", "--name-only", f"{base}...HEAD"))
    out.update(_git(root, "diff", "--name-only", "HEAD"))
    out.update(_git(root, "ls-files", "--others", "--exclude-standard"))
    return sorted(out)


def _tokens(rel: str) -> set[str]:
    """反查用的字面量：整条相对路径、文件名、以及够长的模块名。"""
    p = Path(rel)
    toks = {rel, p.name}
    if p.suffix == ".py" and len(p.stem) >= 3:
        toks.add(p.stem)
    return toks


def _existing(root: Path, rels: tuple[str, ...]) -> list[str]:
    return [r for r in rels if (root / r).is_file()]


def select(root: Path, changed: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """返回 (每个改动文件的命中测试, 无覆盖文件)。

    纯映射，不跑测试：便于测试与 `--list` 复用。
    """
    test_texts = {
        str(p.relative_to(root)).replace("\\", "/"): p.read_text(encoding="utf-8")
        for p in sorted((root / "tests").glob(TESTS_GLOB))
    }
    mapping: dict[str, list[str]] = {}
    uncovered: list[str] = []

    for rel in changed:
        hits: list[str] = []
        if (rel.startswith("tests/") and rel.endswith(".py")
                and Path(rel).name.startswith("test_")):
            hits = [rel]
        elif rel in LEDGER_FILES or rel.startswith(LEDGER_PREFIXES):
            hits = _existing(root, LEDGER_TESTS)
        elif rel in ASSEMBLY_FILES or rel.startswith(ASSEMBLY_PREFIXES):
            hits = _existing(root, ASSEMBLY_TESTS)

        if not hits:
            toks = _tokens(rel)
            hits = [name for name, text in test_texts.items()
                    if any(tok in text for tok in toks)]

        if hits:
            mapping[rel] = sorted(set(hits))
        else:
            uncovered.append(rel)

    return mapping, uncovered


def _print_plan(root: Path, changed: list[str], mapping: dict[str, list[str]],
                uncovered: list[str], selected: list[str]) -> None:
    print(f"批次改动：{len(changed)} 个文件")
    for rel in changed:
        if rel in mapping:
            print(f"  {rel} → {', '.join(mapping[rel])}")
        else:
            print(f"  {rel} → 无覆盖")
    missing = [t for t in (*LEDGER_TESTS, *ASSEMBLY_TESTS)
               if not (root / t).is_file() and t not in selected]
    if missing:
        print(f"  窄集缺件（跳过）：{', '.join(missing)}")
    print(f"将运行 {len(selected)} 个测试文件：{', '.join(selected) or '（无）'}")
    if uncovered:
        print(f"[无覆盖] {len(uncovered)} 个改动文件没有可映射的测试："
              f"{', '.join(uncovered)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="批次预检：按本批改动文件挑测试（判据单源 = tests/）")
    ap.add_argument("--base", default="origin/main",
                    help="批次基线（缺省 origin/main；传空串表示只看工作树）")
    ap.add_argument("--files", nargs="*", default=None,
                    help="显式指定改动文件（相对仓根），跳过 git 解析")
    ap.add_argument("--root", default=str(PKG_ROOT), help="仓库根")
    ap.add_argument("--list", action="store_true", help="只打印映射，不跑测试")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / "tests").is_dir():
        print(f"ERROR：{root} 下没有 tests/ —— 不是包根，拒绝猜测")
        return 2

    try:
        changed = (sorted(set(args.files)) if args.files is not None
                   else changed_files(root, args.base))
    except PreflightError as exc:
        print(f"ERROR：{exc}")
        return 2

    if not changed:
        print(f"ERROR：批次为空（--base {args.base or '∅'} 与工作树都没有改动）——"
              "请显式传 --base 或 --files；本器不静默退回 HEAD~1")
        return 2

    mapping, uncovered = select(root, changed)
    selected = sorted({t for hits in mapping.values() for t in hits})
    _print_plan(root, changed, mapping, uncovered, selected)

    if args.list:
        return 0
    if not selected:
        print("结果：没有可运行的测试（全部无覆盖）——未验证，不要当成通过")
        return 0

    cmd = [sys.executable, "-m", "pytest", *selected, "-q"]
    print("运行：" + " ".join(shlex.quote(c) for c in cmd))
    rc = subprocess.run(cmd, cwd=root).returncode
    if rc != 0:
        print(f"结果：FAIL（pytest exit {rc}）")
        return 1
    print(f"结果：PASS（{len(selected)} 个测试文件）")
    if uncovered:
        print(f"[无覆盖] {len(uncovered)} 个改动文件未经验证：{', '.join(uncovered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
