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

DEFAULT_PATHS = ("docs/map/index.md", "docs/map/gates.md", "shared/gates.md")

# 裸数字 lint（2026-11-21 复盘 R1/L1）：受管正文里「N 器 / N 个校验器 / N 个 validate_*」
# 族计数若未登记 `〔数:〕` 占位，就是同一事实的散文第二副本，无门可查——L1 实证
# `docs/map` 四处写 12 实为 13 存活多日。`N 行` 声明归 `test_map_anchors`（M155），
# changelog / guide 属历史快照语境不扫；负向环视排除 `2.2 校验器` 这类节号引用误报。
LINT_GLOBS = ("docs/map/*.md", "shared/*.md")
LINT_FILES = ("README.md",)
BARE_NUM_RE = re.compile(
    r"(?<![\d.])(\d+)\s*(个\s*)?(器|校验器|validate_[a-z*]+|个测试文件|个出厂测试)")


def lint_bare_numbers(root: Path) -> list[str]:
    """扫受管正文的未登记裸计数，返回违规清单（`path:line: 片段`）；空 = 绿。"""
    root = root.resolve()
    targets = [p for g in LINT_GLOBS for p in sorted(root.glob(g))]
    targets += [root / f for f in LINT_FILES]
    bad: list[str] = []
    for p in targets:
        if not p.is_file():
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = BARE_NUM_RE.search(ln)
            if m:
                frag = ln[max(0, m.start() - 24):m.end() + 24].strip()
                bad.append(f"{p.relative_to(root).as_posix()}:{i}: …{frag}…")
    return bad


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


def _precondition_validators(root: Path) -> list[str] | None:
    """`scripts/atlas_check.py` `_gate_preconditions` 声明 SKIP 三态前置的校验器（AST 实收）。

    单源动机（复盘 R1/L1）：`docs/map/gates.md` 散文写「7 个校验器」却只枚举了 6 个
    （漏 `validate_task_card`）——计数与清单各自手抄、各自漂。此处按声明顺序实收，
    计数与清单两个键同源。函数整体缺席 ⇒ 返回 None 不出键（同 `编排门行` 先例：
    最小 fixture / 副本态不拦；真实仓若正文写了占位而键缺失，按未知键当场炸）。
    """
    src_path = root / "scripts" / "atlas_check.py"
    if not src_path.is_file():
        return None
    for node in ast.walk(ast.parse(src_path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == "_gate_preconditions":
            keys = [k.value for n in ast.walk(node) for k in getattr(n, "keys", [])
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and k.value.startswith("validate_")]
            if not keys:
                raise SnapshotError(
                    "_gate_preconditions 无 validate_* 键：前置 SKIP 清单无法计算（不静默 0）")
            return keys
    return None


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
    pres = _precondition_validators(root)
    if pres is not None:
        facts["前置SKIP器"] = str(len(pres))
        facts["前置SKIP清单"] = "/".join(k.removeprefix("validate_") for k in pres)
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
    # 变异编号上限：钉子定义在 tests/；门册自身的提及不参与派生（否则读到占位里的旧值，自我循环）。
    # 2026-11-21 改扫 **docstring**（钉的声明面）：裸文本扫描会把变异测试夹具载荷字符串里的
    # 钉号（如 M195 反例里注入的幽灵钉 M999）当成事实——M10「字符串幽灵」教训的又一形态。
    best: tuple[int, str] = (0, "")
    for p in test_files:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                continue
            for m in re.finditer(r"(?<![A-Za-z0-9_])M(\d+)([a-z]?)(?![A-Za-z0-9_])", doc):
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
    ap.add_argument("--lint-bare-numbers", action="store_true",
                    help="扫受管正文未登记的裸计数（器/校验器族）；命中 exit 1，不依赖派生源")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if args.lint_bare_numbers:
        bad = lint_bare_numbers(root)
        if bad:
            print("FAIL：裸计数未登记占位（〔数:〕）:\n  " + "\n  ".join(bad))
            return 1
        print("OK：受管正文无未登记裸计数（器/校验器族）")
        return 0
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
