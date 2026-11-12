#!/usr/bin/env python3
"""封条（apply record）只读校验：schema / upstream 绑定 / 路径宇宙 / 状态机 / 续签链。

RFC-20261111-03 §1.4 / §2.5 / §3.2 / §3.4 的 C 批读侧唯一入口（CLI 薄封装）。
判据本体在 `_support/solution_seal.py`，本文件不复制任何规则。

退出码：0 = 全 PASS（WARN 不影响）；1 = 任一 FAIL；2 = 输入错误。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support.siblings import load_module  # noqa: E402


def collect_errors(root: Path) -> tuple[list[dict], list[dict], list[str], int]:
    solution = load_module("solution")
    seal = load_module("solution_seal")
    if not solution.manifest_path(root).is_file():
        return [], [], [], 0
    data = solution.load_manifest(root)
    lock = solution.read_lock(root)
    roots = [str((lock or {}).get("layout_assets_root") or solution._assets_root(root))]
    try:
        history_roots, _ = solution.historical_roots(root)
    except (solution.ChainUnverifiable, solution.LockHistoryUnparsable) as exc:
        return ([{"code": "chain_unverifiable", "message": str(exc), "path": None}],
                [], [], 1)
    if history_roots:
        roots = history_roots
    paths = seal.head_seals(root, roots)
    if not paths:
        return [], [], [], 0
    anchors = (lock or {}).get("seal_anchors")
    by_path = {k: v for k, v in anchors.items()
               if isinstance(v, dict)} if isinstance(anchors, dict) else {}
    errors: list[dict] = []
    warnings: list[dict] = []
    seen: set[tuple] = set()

    def absorb(item: dict, default_path: str | None = None) -> None:
        row = {"code": item["code"], "message": item["message"],
               "path": item.get("path") or default_path}
        key = (row["code"], row["path"], row["message"])
        if key in seen:
            return
        seen.add(key)
        (errors if item["severity"] == "error" else warnings).append(row)

    # B1：先走仓级 analyze（含锁缺失 / 键缺失 / 状态机 / 链），再补单封条 schema。
    for item in seal.analyze(root, data, lock, roots,
                             bind_from=solution.SEAL_UPSTREAM_BIND_FROM):
        absorb(item)
    for path in paths:
        path_root = seal.SEAL_RE.match(path).group("root") if seal.SEAL_RE.match(path) else roots[0]
        findings = seal.validate_seal_record(
            root, data, path, by_path.get(path), path_root,
            bind_from=solution.SEAL_UPSTREAM_BIND_FROM)
        for item in findings:
            absorb(item, path)
    return errors, warnings, paths, len(paths)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        errors, warnings, paths, count = collect_errors(root)
    except Exception as exc:  # noqa: BLE001 - 校验器不得因坏输入崩溃
        print(f"[FAIL] apply_record_unreadable: {type(exc).__name__}: {exc}")
        return 1
    if count == 0:
        print("[N/A] 仓内没有封条（reviews/apply/**/*.seal.json）")
        return 0
    for item in errors:
        print(f"[FAIL] {item['code']}: {item['message']}（{item.get('path')}）")
    for item in warnings:
        print(f"[WARN] {item['code']}: {item['message']}（{item.get('path')}）")
    if args.json:
        import json
        print(json.dumps({"ok": not errors, "seals": count,
                          "errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    print(f"{len(paths)} seal(s): {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
