#!/usr/bin/env python3
"""独立复核的**输入清单**（指针化，不复制）—— 3509 §B66 / §B65。

**问题**：三轮复核的产物里，`inputs/` 与 `snapshot-copies/` 是原型 / AC / 索引 / 用例的**副本**，
共 ~500KB；而且副本会与现状脱节 —— 实测踩到：某轮快照只有 24 条用例、当前 35 条，
拿它当「审查期基线」做 diff 会得出错误结论。

**解决方式**：审查输入改为**内容指纹清单**（`{path, sha256, 取样时刻}`），不复制文件。
审查者按清单读**当前**文件；要冻结某次审查的基线时，用 sha256 而非拷贝。

用法：
    python3 .atlas/scripts/make_review_inputs.py --out <资产根>/e2e/reviews/<日期>-<主题>/inputs

- 默认收录：`<资产根>/e2e/e2e-index.md`、`<资产根>/e2e/cases/*.md`、`<资产根>/prd/*.md`
  （资产根默认 `product/`，由项目根 `atlas.config.yaml` 解析）；可用 `--include` 追加 glob、`--exclude` 排除。
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

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402


def defaults_for(root: Path) -> tuple[str, ...]:
    """默认收录：索引 + 用例分片 + 域级 PRD。

    `e2e.index` / `e2e.cases_dir` 若在 stack-profile 中覆盖，必须与生成器用同一来源；
    否则清单收的是默认路径，生成门按覆盖路径核对 ⇒ 真 PASS 也会被误判 stale（issue #48）。
    """
    lay = load_layout(root)
    index = lay.print_value("e2e_index")
    cases = lay.print_value("e2e_cases")
    profile_path = lay.stack_profile
    if profile_path.is_file():
        try:
            from _support.stack_profile import parse_profile  # noqa: E402 — 延迟导入，保持脚本轻量
            e2e = parse_profile(profile_path.read_text(encoding="utf-8")).get("e2e")
            if isinstance(e2e, dict):
                index = str(e2e.get("index") or index)
                cases = str(e2e.get("cases_dir") or cases)
        except Exception:
            # 清单工具不替代生成器的 profile 校验；解析失败时保持 layout 默认值。
            pass
    root_resolved = root.resolve()
    for label, value in (("e2e.index", index), ("e2e.cases_dir", cases)):
        p = Path(value)
        if ".." in p.parts:
            raise LayoutError(f"{label} 不得包含 `..`：{value}")
        if p.is_absolute() and not p.resolve().is_relative_to(root_resolved):
            raise LayoutError(f"{label} 必须在项目根内：{value}")
    return (
        index,
        f"{cases}/*.md",
        f"{lay.print_value('prd')}/*.md",
    )


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(root: Path, patterns: list[str]) -> list[dict]:
    root = root.resolve()
    seen: list[Path] = []
    for pat in patterns:
        p = Path(pat)
        if p.is_absolute():
            p = p.resolve()
            if any(c in p.name for c in "*?["):
                seen.extend(sorted(p.parent.glob(p.name)))
            elif p.is_file():
                seen.append(p)
            continue
        seen.extend(sorted(root.glob(pat)) if any(c in pat for c in "*?[") else
                    ([root / pat] if (root / pat).is_file() else []))
    out = []
    for p in sorted(set(seen)):
        if not p.is_file():
            continue
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            rel = p
        out.append({"path": str(rel).replace("\\", "/"),
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
    try:
        pats = list(defaults_for(root)) + args.include
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
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
