#!/usr/bin/env python3
"""atlas 出厂护栏 —— 测试套件卫生（2026-09-28，事故 #114 后加）。

钉住两类真实事故（`3508 §103`）：
  1. **同名测试双定义**：`test_validators.py` 里 stack_profile 三测各存两份，后者静默
     覆盖前者——改「前者」不生效，差点误判修复完成。⇒ 本护栏：每个测试文件内，顶层
     `test_*` 函数名必须唯一（AST 判定，与运行器 globals 收集同口径）。
  2. **测试文件必须可解析**：任何 SyntaxError 都会让整个文件的门静默消失
     （pytest collection error 只在 check-all 里显眼）。

- 框架无关；纯标准库。判定：全部通过 → 0；任一违规 → 1。

用法：
    python3 test_suite_hygiene.py [--json]
"""
from __future__ import annotations

import ast
import argparse
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def scan() -> list[dict]:
    out: list[dict] = []
    for path in sorted((PKG_ROOT / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            out.append({"file": path.name, "check": "文件可解析", "ok": False,
                        "detail": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            continue
        names = [n.name for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        dups = sorted({n for n in names if names.count(n) > 1})
        out.append({"file": path.name, "check": "test_ 函数名唯一", "ok": not dups,
                    "detail": f"重复定义={dups}" if dups else ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = scan()
    ok = all(c["ok"] for c in checks)
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("test_suite_hygiene @ 测试套件卫生")
        for c in checks:
            mark = "ok " if c["ok"] else "FAIL"
            extra = f" —— {c['detail']}" if c["detail"] else ""
            print(f"  [{mark}] {c['file']}: {c['check']}{extra}")
        print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
