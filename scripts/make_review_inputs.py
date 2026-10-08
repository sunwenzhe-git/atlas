#!/usr/bin/env python3
"""独立复核的**输入清单**（指针化，不复制）—— 3509 §B66 / §B65。

**问题**：三轮复核的产物里，`inputs/` 与 `snapshot-copies/` 是原型 / AC / 索引 / 用例的**副本**，
共 ~500KB；而且副本会与现状脱节 —— 实测踩到：某轮快照只有 24 条用例、当前 35 条，
拿它当「审查期基线」做 diff 会得出错误结论。

**解决方式**：审查输入改为**内容指纹清单**（`{path, sha256, 取样时刻}`），不复制文件。
审查者按清单读**当前**文件；要冻结某次审查的基线时，用 sha256 而非拷贝。

用法：
    python3 .atlas/scripts/make_review_inputs.py --out product/e2e/reviews/<日期>-<主题>/inputs

- 默认收录：`product/e2e/e2e-index.md`、`product/e2e/cases/*.md`、`product/prd/*.md`、
  `product/e2e/cases/*.md`；可用 `--include` 追加 glob、`--exclude` 排除。
- 输出 `MANIFEST.json`（机器读）+ 一行摘要（人读）。
- 纯标准库、框架无关。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULTS = ("product/e2e/e2e-index.md", "product/e2e/cases/*.md", "product/prd/*.md",
            "product/e2e/cases/*.md")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(root: Path, patterns: list[str]) -> list[dict]:
    seen: list[Path] = []
    for pat in patterns:
        seen.extend(sorted(root.glob(pat)) if any(c in pat for c in "*?[") else
                    ([root / pat] if (root / pat).is_file() else []))
    out = []
    for p in sorted(set(seen)):
        if not p.is_file():
            continue
        out.append({"path": str(p.relative_to(root)).replace("\\", "/"),
                    "sha256": sha256(p), "bytes": p.stat().st_size,
                    "lines": len(p.read_text(encoding="utf-8", errors="ignore").splitlines())})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", required=True, help="审查目录（会写 MANIFEST.json）")
    ap.add_argument("--include", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    pats = list(DEFAULTS) + args.include
    files = collect(root, pats)
    for ex in args.exclude:
        files = [f for f in files if ex not in f["path"]]
    if not files:
        print("ERROR: 没有任何文件入清单（检查 --root / --include）", file=sys.stderr)
        return 2
    outdir = (root / args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": "atlas-review-input-manifest",
        "note": "指针化清单：审查者按 path 读**当前**文件；要冻结基线用 sha256，不要拷副本。",
        "root": str(root),
        "taken_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": files,
    }
    (outdir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"review inputs @ {outdir}   共 {len(files)} 个文件（未复制任何文件）")
        for f in files:
            print(f"  {f['sha256'][:12]}  {f['lines']:>5} 行  {f['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
