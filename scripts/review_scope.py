#!/usr/bin/env python3
"""审查范围内容封口 + apply 基线（RFC-20261103-01）。

三个子命令，全部纯标准库、只读项目内容（baseline 写 `.atlas/runs/`）：

    # 1) 生成实审集内容清单（给 cli_review_convert.py --scope-manifest）
    python3 .atlas/scripts/review_scope.py manifest --root . \
        --reviewed-files src/a.ts,src/b.ts --out product/reviews/r1/scope-manifest.json

    # 2) 复算：报告落盘后内容是否还是当时那份
    python3 .atlas/scripts/review_scope.py verify --root . --manifest <file>

    # 3) apply 起始脏工作区基线（A4；只告警不阻断）
    python3 .atlas/scripts/review_scope.py baseline --root . --unit <需求ID>
    python3 .atlas/scripts/review_scope.py baseline-check --root . --unit <需求ID> \
        --changed-files src/a.ts

退出码：0 通过/告警（baseline-check 的 WARN 不置红）；1 verify 内容不一致；2 输入错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support import review_scope_core as core  # noqa: E402


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def _paths(value: str | None, file_value: str | None) -> list[str]:
    out: list[str] = []
    if value:
        out.extend(p for p in value.split(",") if p.strip())
    if file_value:
        src = Path(file_value)
        try:
            raw = src.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(die(f"读 {src} 失败：{exc}"))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = [line.strip() for line in raw.splitlines() if line.strip()]
        if isinstance(data, dict):
            data = data.get("files") or data.get("reviewed_files")
        if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
            raise SystemExit(die(f"{src} 必须是字符串数组或 JSON {{files: [...]}} / 一行一路径"))
        out.extend(data)
    return out


def _resolve(root: Path, value: str) -> Path:
    """CLI 的相对路径按 `--root` 解析（与 cli_review_convert 的 --out 同口径）。"""
    p = Path(value)
    return p if p.is_absolute() else root.resolve() / p


def cmd_manifest(args: argparse.Namespace) -> int:
    paths = _paths(args.reviewed_files, args.reviewed_files_file)
    root = Path(args.root)
    try:
        manifest = core.build_manifest(root, paths, base=args.base, head=args.head)
    except core.ScopeError as exc:
        return die(str(exc))
    if args.out:
        out = _resolve(root, args.out)
        try:
            core.atomic_write_json(out, manifest)
        except OSError as exc:
            return die(f"写 {out} 失败：{exc}")
        print(f"review_scope manifest @ {out}   files {len(manifest['files'])}   "
              f"sha256 {manifest['scope_sha256'][:16]}…")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        manifest = core.load_manifest(_resolve(root, args.manifest))
    except core.ScopeError as exc:
        return die(str(exc))
    try:
        ok, current, diffs = core.verify_manifest(root, manifest)
    except core.ScopeError as exc:
        print(f"FAIL: {exc}")
        return 1
    if ok:
        print(f"PASS: {len(current['files'])} 个文件内容与清单一致 "
              f"（{current['scope_sha256'][:16]}…）")
        return 0
    print(f"FAIL: scope 内容已变化（清单 {manifest['scope_sha256'][:16]}… / "
          f"当前 {current['scope_sha256'][:16]}…）")
    for diff in diffs:
        print(f"  · {diff}")
    return 1


def cmd_baseline(args: argparse.Namespace) -> int:
    try:
        data = core.baseline_begin(Path(args.root), args.unit)
    except core.ScopeError as exc:
        return die(str(exc))
    except OSError as exc:
        return die(f"写基线失败：{exc}")
    path = core.baseline_path(Path(args.root).resolve(), args.unit)
    print(f"baseline @ {path}   files {len(data['files'])}   "
          f"dirty 摘要 {data['scope_sha256'][:16] if data['scope_sha256'] else '<clean>'}…")
    return 0


def cmd_baseline_check(args: argparse.Namespace) -> int:
    changed = _paths(args.changed_files, args.changed_files_file)
    root = Path(args.root)
    try:
        result = core.baseline_check(root, args.unit, changed)
    except core.ScopeError as exc:
        return die(str(exc))
    if args.out:
        out = _resolve(root, args.out)
        try:
            core.atomic_write_json(out, result)
        except OSError as exc:
            return die(f"写 {out} 失败：{exc}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("manifest", help="生成实审集内容清单")
    m.add_argument("--root", default=".")
    m.add_argument("--out", help="输出 JSON 路径；省略则打印到 stdout")
    m.add_argument("--reviewed-files", help="逗号分隔的实审文件列表")
    m.add_argument("--reviewed-files-file", help="字符串数组 / 一行一路径的文件")
    m.add_argument("--base", help="可选：git 起 ref（只作人读，不参与 scope_sha256）")
    m.add_argument("--head", help="可选：git 止 ref（只作人读，不参与 scope_sha256）")
    m.set_defaults(func=cmd_manifest)

    v = sub.add_parser("verify", help="复算清单内容是否仍一致")
    v.add_argument("--root", default=".")
    v.add_argument("--manifest", required=True)
    v.set_defaults(func=cmd_verify)

    b = sub.add_parser("baseline", help="记录 apply 起始既有脏工作区")
    b.add_argument("--root", default=".")
    b.add_argument("--unit", required=True)
    b.set_defaults(func=cmd_baseline)

    c = sub.add_parser("baseline-check", help="当前 dirty 与基线对账（只告警）")
    c.add_argument("--root", default=".")
    c.add_argument("--unit", required=True)
    c.add_argument("--changed-files", help="本次改动文件（逗号分隔）")
    c.add_argument("--changed-files-file", help="本次改动文件列表文件")
    c.add_argument("--out", help="可选：把结果写 JSON")
    c.set_defaults(func=cmd_baseline_check)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
