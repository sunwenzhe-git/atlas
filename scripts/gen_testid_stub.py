#!/usr/bin/env python3
"""atlas 生成器 —— 实现期 testid 薄桩（`rings/e2e/reference.md` §4.1）。

产出 `<项目根>/.trellis/spec/conventions/testid.md`：**派生视图**（祈使句 + 指针 + 当前 testid 清单）。

**抽取源与 `validate_testids.py` 同一个函数**（`collect_testids`）⇒ 薄桩里的清单与门眼里的集合
永不漂移 —— 这就是 `3509 §B73`（「契约要求它、却没有生产者」）要的生产者。

- **框架无关**：本文件不得出现任何具体框架名。
- 纯标准库；**确定性**（同输入同输出）。
- 幂等：重复运行覆盖同一文件；除本文件外不写任何东西。

用法：
    python3 gen_testid_stub.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vt = _load("validate_testids", "validators/validate_testids.py")

STUB_REL = ".trellis/spec/conventions/testid.md"

# 祈使句按形态取（`rings/e2e/reference.md` §4.1）：`adopt` 下真实 UI 是真相源 ⇒ 方向相反。
IMPERATIVE = ("实现按**第一块（分片应然）**命名 `data-testid`，**不得自造**；"
              "既有实现保持现有 `data-testid`（见第二块实然）。")


def render(root: Path, globs: list[str]) -> tuple[str, int]:
    per_page, _counts, sources = vt.collect_testids(root, globs)
    cases = root / "product" / "e2e" / "cases"
    _attr_pages = sorted((set(per_page) - {""}) | {m.stem for m in cases.glob("*.md")})
    want = vt.shard_testids(cases, _attr_pages) if cases.is_dir() else {}
    paths = [f"{g}/**" for g in globs] or ["**"]
    lines = [
        "---",
        "paths:",
        *[f"  - '{p}'" for p in paths],
        "---",
        "",
        "<!-- atlas:testid:begin -->",
        "# testid 约定（实现期）",
        "",
        IMPERATIVE,
        "",
        "命名规则正文：`.atlas/rings/e2e/reference.md` §4（本文件是**派生视图**，"
        "由 `python3 .atlas/scripts/gen_testid_stub.py --root .` 生成，**勿手改**）。",
        "",
        f"前端扫描源：{', '.join(f'`{s}`' for s in sources[:6]) or '（无）'}"
        f"{f' 等 {len(sources)} 个文件' if len(sources) > 6 else ''}。",
        "",
        "## 第一块：分片应然（按页）",
        "",
        "> 用例分片 `testid:` / step / expected 引用的集合 —— **实现者的命名依据**（应然源）。",
        "",
        "| 页 slug | 应然 testid |",
        "|---|---|",
    ]
    n = 0
    for page in sorted(want):
        for tid in sorted(want[page]):
            lines.append(f"| {page or '（未归属）'} | `{tid}` |")
            n += 1
    if n == 0:
        lines.append("| （空） | 分片暂无 testid 引用 |")

    lines += [
        "",
        "## 第二块：前端实然（按页）",
        "",
        "> 前端源码已有的 `data-testid` —— 现状；与第一块的差集 = 待实现面 / 漂移面。",
        "",
        "| 页 slug | 实然 testid |",
        "|---|---|",
    ]
    m = 0
    for page in sorted(per_page):
        for tid in sorted(per_page[page]):
            lines.append(f"| {page or '（未归属）'} | `{tid}` |")
            m += 1
    if m == 0:
        lines.append("| （空） | 前端暂无 `data-testid`（全部页未实现） |")

    lines += ["", "<!-- atlas:testid:end -->", ""]
    return "\n".join(lines), n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    globs = vt.app_globs(root)
    text, n = render(root, globs)
    out = root / STUB_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, "root": str(root),
                          "paths": [f"{g}/**" for g in globs] or ["**"],
                          "testids": n, "out": STUB_REL}, ensure_ascii=False, indent=2))
    else:
        print(f"gen_testid_stub @ {root}")
        print(f"  抽取源={'/'.join(globs) or '（无 frontend app）'} 注入 paths={[f'{g}/**' for g in globs] or ['**']} 应然={n}")
        print(f"  写入 {STUB_REL}")
        print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
