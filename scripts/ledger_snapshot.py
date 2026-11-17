#!/usr/bin/env python3
"""账本单一源：派生数字生成器（2026-11-17 账本设计案 方案乙 · 步 1）。

问题定义（`2026-11-17/design-defect-audit` F1）：同一条计数事实在 `shared/gates.md` /
`docs/map/index.md` / `atlas-map.html` / 章节散文里有多份手抄副本，而门只锁其中一部分句式。
实测「门全绿但账本自相矛盾」三例：版本串 7 处停在旧版、`docs/map/gates.md` 的「77 个测试文件」
与实况 80 不符、同文件 M162/M164 与实际最大 M176b 不符。

本器把「可算的数字」收敛到唯一源，正文用 `〔数:key=value〕` 标注：
  * 机器只认 key（与句式无关），value 是给人看的现值；
  * 缺源即炸、未知键即炸（不静默 0、不静默原样放过）；
  * `--write` 按源改写 value；`--check` 只报漂移（exit 1），不落盘。

明确不派生（判断性内容，生成即降质）：门册的「不查什么」/取证等级/缺口、DESIGN 决策理由、
changelog 措辞、QUEUE 判断。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"〔数:([^=〕\n]+)=([^〕\n]*)〕")
TESTS_GLOB = "test_*.py"
C_DECL_RE = re.compile(r'^\s*c\("', re.M)  # 与 canonical 同口径：只认双引号 c("
PIN_DECL_RE = re.compile(r"^\s*(M\d+[a-z]?)")

DEFAULT_PATHS = ("docs/map/index.md", "shared/gates.md")


class SnapshotError(RuntimeError):
    """源缺失或键未登记——必须响亮失败，不得以 0 或原样占位蒙混。"""


def _require_dir(root: Path, rel: str) -> Path:
    p = root / rel
    if not p.is_dir():
        raise SnapshotError(f"缺源目录 {rel}：派生层无法计算（不静默 0）")
    return p


def _require_file(root: Path, rel: str) -> Path:
    p = root / rel
    if not p.is_file():
        raise SnapshotError(f"缺源文件 {rel}：派生层无法计算（不静默 0）")
    return p


def count_tests(path: Path) -> int:
    """逐文件用例数（AST 实收口径，与 `test_canonical_consistency._collected_test_count` 同口径）。

    不得用 `^def test_` 正则——坏输入 fixture 会把被测写法整文件内嵌进三引号字符串，
    正则会数进永不收集的幽灵用例（2026-09-28 审计教训）。
    """
    n = 0
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            n += sum(1 for m in node.body
                     if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and m.name.startswith("test_"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            n += 1
    return n


def _validators(root: Path) -> int:
    src = _require_file(root, "scripts/atlas_check.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "VALIDATORS" for t in node.targets):
            return len(node.value.elts)
    raise SnapshotError("scripts/atlas_check.py 无 VALIDATORS 赋值：校验器数无法计算")


def _orchestrator_rows(text: str) -> int | None:
    """`shared/gates.md` §2.2 表的编排层数据行数（表头与分隔线不计）。"""
    parts = re.split(r"^### 2\.2", text, maxsplit=1, flags=re.M)
    if len(parts) < 2:
        return None
    body = re.split(r"^### ", parts[1], maxsplit=1, flags=re.M)[0]
    rows = [l for l in body.splitlines() if l.startswith("|")]
    return len(rows) - 2 if len(rows) > 2 else None


def derive(root: Path) -> dict[str, str]:
    """从唯一源算出全部派生键（值一律为字符串，便于正文内联）。"""
    root = root.resolve()
    facts: dict[str, str] = {}
    facts["校验器"] = str(_validators(root))
    facts["校验器文件"] = str(len(list(_require_dir(root, "validators").glob("validate_*.py"))))
    test_files = sorted(_require_dir(root, "tests").glob(TESTS_GLOB))
    if not test_files:
        raise SnapshotError("tests/ 下无测试文件：派生层无法计算（不静默 0）")
    facts["出厂测试文件"] = str(len(test_files))
    facts["自检声明"] = str(len(C_DECL_RE.findall(
        _require_file(root, "install.py").read_text(encoding="utf-8"))))
    facts["skills"] = str(len([d for d in _require_dir(root, "skills").iterdir() if d.is_dir()]))
    facts["环"] = str(len(list(_require_dir(root, "rings").glob("*/reference.md"))))
    facts["共享契约"] = str(len(list(_require_dir(root, "shared").glob("*.md"))))
    facts["共享内核"] = str(len(list(_require_dir(root, "_support").glob("*.py"))))
    scripts = sorted(_require_dir(root, "scripts").glob("*.py"))
    if not scripts:
        raise SnapshotError("scripts/ 下无 .py：最大单件无法计算（不静默 0）")
    biggest = max(scripts, key=lambda p: len(p.read_text(encoding="utf-8").splitlines()))
    facts["最大单件文件"] = f"scripts/{biggest.name}"
    facts["最大单件行数"] = str(len(biggest.read_text(encoding="utf-8").splitlines()))
    # 门册 §2.2 编排层数据行数（不含表头/分隔线）；副本态无该节则不出键，
    # 真实仓若本键缺失而正文有占位，会按「未知键」当场炸，不静默放过。
    gates_file = root / "shared" / "gates.md"
    if gates_file.is_file():
        rows = _orchestrator_rows(gates_file.read_text(encoding="utf-8"))
        if rows is not None:
            facts["编排门行"] = str(rows)
    for p in test_files:
        facts[f"用例数.{p.name}"] = str(count_tests(p))
    # 变异编号上限：钉子定义在 tests/；门册自身的提及不参与派生（否则读到占位里的旧值，自我循环）
    best: tuple[int, str] = (0, "")
    for p in test_files:
        for m in re.finditer(r"(?<![A-Za-z0-9_])M(\d+)([a-z]?)(?![A-Za-z0-9_])",
                             p.read_text(encoding="utf-8")):
            best = max(best, (int(m.group(1)), m.group(2)))
    if best[0]:
        facts["变异编号上限"] = f"M{best[0]}{best[1]}"
    # 无钉的空仓不出键：真实仓若本键缺失，正文占位会按「未知键」当场炸，不会静默放过。
    return facts


def declared_pin_ids(root: Path) -> set[str]:
    """测试侧声明的变异钉：测试函数 docstring 首段以 `M<id>` 开头的那些。

    约定即登记面（新增钉写 docstring 是既有做法），只取首段是为了避开正文里的
    「承 M10 教训」这类引用，不把它们误算成新钉。
    """
    ids: set[str] = set()
    for p in sorted(_require_dir(root, "tests").glob(TESTS_GLOB)):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")):
                doc = ast.get_docstring(node)
                m = PIN_DECL_RE.match(doc) if doc else None
                if m:
                    ids.add(m.group(1))
    return ids


def rewrite(text: str, facts: dict[str, str]) -> tuple[str, list[tuple[str, str, str]]]:
    """按源改写全部占位；返回 (新文本, 漂移清单[(key, 旧值, 新值)])。

    未知键当场抛错：正文写了没登记的 key = 门永远看不到的假派生面。
    """
    drifts: list[tuple[str, str, str]] = []

    def _sub(m: re.Match[str]) -> str:
        key, old = m.group(1), m.group(2)
        if key not in facts:
            raise SnapshotError(
                f"未知数字键「{key}」：正文占位必须先在 derive() 里登记"
                f"（已知键：{', '.join(sorted(facts))}）")
        new = facts[key]
        if new != old:
            drifts.append((key, old, new))
        return f"〔数:{key}={new}〕"

    return TOKEN_RE.sub(_sub, text), drifts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="派生数字生成器（账本单一源；缺省只打印源值）")
    ap.add_argument("paths", nargs="*", help=f"待对账正文（缺省：{' '.join(DEFAULT_PATHS)}）")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--write", action="store_true", help="按源改写占位值（缺省只报告）")
    ap.add_argument("--json", action="store_true", help="打印全部派生键值")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        facts = derive(root)
    except SnapshotError as e:
        print(f"FAIL：{e}")
        return 2

    if args.json:
        print(json.dumps(facts, ensure_ascii=False, indent=1, sort_keys=True))
        return 0

    targets = [Path(p) if Path(p).is_absolute() else root / p
               for p in (args.paths or DEFAULT_PATHS)]
    total = 0
    try:
        for p in targets:
            if not p.is_file():
                print(f"SKIP：{p} 不在场")
                continue
            text = p.read_text(encoding="utf-8")
            new_text, drifts = rewrite(text, facts)
            rel = p.relative_to(root).as_posix() if root in p.parents else str(p)
            for key, old, new in drifts:
                total += 1
                print(f"[漂移] {rel} 〔数:{key}〕 写 {old} ≠ 源 {new}")
            if args.write and drifts:
                p.write_text(new_text, encoding="utf-8")
    except SnapshotError as e:
        print(f"FAIL：{e}")
        return 2

    if args.write:
        print(f"已按源改写 {total} 处占位")
        return 0
    print(f"派生数字：{'全对齐' if not total else str(total) + ' 处漂移'}")
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main())
