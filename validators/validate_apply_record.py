#!/usr/bin/env python3
"""封条（apply record）只读校验：schema / upstream 绑定 / 路径宇宙 / 状态机 / 续签链。

RFC-20261111-03 §1.4 / §2.5 / §3.2 / §3.4 的 C 批读侧唯一入口（CLI 薄封装）。
判据本体在 `_support/solution_seal.py`，本文件不复制任何规则。

退出码：0 = 全 PASS（WARN 不影响）；1 = 任一 FAIL；2 = 输入错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support.siblings import load_module  # noqa: E402


def _canonical(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(value)


def collect_errors(root: Path, *,
                   allow_card_absent: bool = False
                   ) -> tuple[list[dict], list[dict], list[str], int, list[dict]]:
    solution = load_module("solution")
    seal = load_module("solution_seal")
    if not solution.manifest_path(root).is_file():
        return [], [], [], 0, []
    data = solution.load_manifest(root)
    lock = solution.read_lock(root)
    roots = [str((lock or {}).get("layout_assets_root") or solution._assets_root(root))]
    try:
        history_roots, _ = solution.historical_roots(root)
    except (solution.ChainUnverifiable, solution.LockHistoryUnparsable) as exc:
        return ([{"code": "chain_unverifiable", "message": str(exc), "path": None}],
                [], [], 1, [])
    if history_roots:
        roots = history_roots
    paths = seal.head_seals(root, roots)
    if not paths:
        return [], [], [], 0, []
    anchors = (lock or {}).get("seal_anchors")
    by_path = {k: v for k, v in anchors.items()
               if isinstance(v, dict)} if isinstance(anchors, dict) else {}
    errors: list[dict] = []
    warnings: list[dict] = []
    downgrades: list[dict] = []
    seen: set[tuple] = set()

    def absorb(item: dict, default_path: str | None = None) -> None:
        row = {"code": item["code"], "message": item["message"],
               "path": item.get("path") or default_path}
        if item.get("detail") is not None:
            row["detail"] = item["detail"]
        # 去重键 = (code, path, detail, message)：同码同路径允许并列（两个用例同时
        # 缺失 / 多个 role 同路径），detail 与 message 都是成因区分键，不得互相压掉。
        key = (row["code"], row["path"], _canonical(item.get("detail")),
               row["message"])
        if key in seen:
            return
        seen.add(key)
        if (allow_card_absent and row["code"] == "card_absent"
                and item["severity"] == "error"):
            # §3.3 表：`--allow-card-absent` 只降 `card_absent`，且必须写进
            # `downgrades[]`（schema v2：`(code, scope, path)` 排序）。
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            downgrades.append({
                "code": "card_absent",
                "flag": "--allow-card-absent",
                "scope": "card_absent",
                "path": detail.get("card") or row["path"],
                "detail": row["message"],
            })
            warnings.append(row)
            return
        (errors if item["severity"] == "error" else warnings).append(row)

    # B1：先走仓级 analyze（含锁缺失 / 键缺失 / 状态机 / 链），再补**未被其覆盖**的单封条
    # schema。有锁内键的路径已由 analyze 的 analyze_state 全判过（schema + 链），
    # 这里再跑一遍只会产出同码同路径的重复项；无键路径仍走 schema（链判据必由
    # `analyze` 的 unmapped/orphaned/unsupported 三支覆盖，不会因此绕过 chain_unverifiable）。
    for item in seal.analyze(root, data, lock, roots,
                             bind_from=solution.SEAL_UPSTREAM_BIND_FROM):
        absorb(item)
    for path in paths:
        if path in by_path:
            continue
        path_root = seal.SEAL_RE.match(path).group("root") if seal.SEAL_RE.match(path) else roots[0]
        findings = seal.validate_seal_record(
            root, data, path, None, path_root,
            bind_from=solution.SEAL_UPSTREAM_BIND_FROM)
        for item in findings:
            absorb(item, path)
    downgrades.sort(key=lambda d: (d["code"], d["scope"], str(d["path"])))
    return errors, warnings, paths, len(paths), downgrades


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--allow-card-absent", action="store_true",
                    help="本地开发：有封条但任务卡缺失降为 WARN 并记 downgrades[]"
                         "（CI 禁用该开关）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    try:
        errors, warnings, paths, count, downgrades = collect_errors(
            root, allow_card_absent=args.allow_card_absent)
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
        print(json.dumps({"ok": not errors, "seals": count,
                          "errors": errors, "warnings": warnings,
                          "downgrades": downgrades},
                         ensure_ascii=False, indent=2))
    print(f"{len(paths)} seal(s): {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
