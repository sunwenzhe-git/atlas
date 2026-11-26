#!/usr/bin/env python3
"""Migrate OpenSpec/Trellis/legacy docs into immutable code-first generations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.legacy_migration import migrate, rollback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--test-command", help="真实执行的测试命令（argv，经 shlex 拆分；不经过 shell）")
    parser.add_argument("--test-node", action="append", default=[], help="补充测试节点；可重复")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default="shadow")
    parser.add_argument("--rollback", action="store_true", help="只把 manifest 指针切回上一代")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            if args.test_command or args.test_node:
                parser.error("--rollback 不能与测试执行参数同用")
            result = rollback(args.root, mode=args.mode)
        else:
            result = migrate(args.root, test_command=args.test_command,
                             test_nodes=args.test_node, mode=args.mode)
    except (OSError, ValueError, RuntimeError) as exc:
        error_mode = args.mode
        result = {"schema_version": 1, "module": "migration", "mode": error_mode,
                  "verdict": "UNVERIFIED", "cause": None if error_mode == "off" else "migration_unverified",
                  "rc": 0 if error_mode == "shadow" else 2,
                  "findings": [{"cause": "migration_unverified", "message": str(exc)}]}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] migration rc={result['rc']} cause={result['cause']}")
        if result.get("generation"):
            print(f"[{result['verdict']}] generation={result['generation']} -> {result['path']}")
        for item in result["findings"]:
            print(f"[{result['verdict']}] {item.get('path', 'migration')}: {item['message']}")
        if args.rollback:
            print(f"[{result['verdict']}] manifest 指针已回切；需重跑 check 复核代际")
        elif result["verdict"] == "PASS" and not result["findings"]:
            print("[PASS] 迁移代际已发布；旧文档与代码未修改")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
