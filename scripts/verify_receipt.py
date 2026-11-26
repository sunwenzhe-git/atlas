#!/usr/bin/env python3
"""Verify a workflow receipt from base plus its staged binary patch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.workflow_receipt import RECEIPT_REL, receipt_error_result, verify_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default=None)
    parser.add_argument("--receipt", default=RECEIPT_REL)
    parser.add_argument("--current-tree", action="store_true", help="finish 本地同时复核当前暂存 tree")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = verify_receipt(args.root, mode=args.mode, receipt_path=args.receipt,
                                check_current_tree=args.current_tree)
    except Exception as exc:  # fail closed: a validator crash is never PASS
        result = receipt_error_result(exc, args.mode)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] receipt rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', RECEIPT_REL)}: {finding['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
