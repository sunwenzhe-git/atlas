#!/usr/bin/env python3
"""M250: RFC-20261125-01 §10 workflow receipt validator.

First paragraph declaration: removing the reconstructed write-tree comparison
in _support/workflow_receipt.py must turn tests/test_workflow_receipt.py's
tree-mismatch counterexample red. The real four-stage mutation_proof evidence
is stored at .atlas/runs/mutation-proof/M250.txt.

Validation is read-only and uses a temporary GIT_INDEX_FILE for read-tree,
cached binary patch application and write-tree. Schema/scope/hash/tree/review
failures are FAIL/rc1; unreachable base or an inapplicable patch is
UNVERIFIED/rc2. Off never passes and shadow preserves findings with rc0.
"""
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
        if result["verdict"] == "PASS":
            print("[PASS] receipt schema/scope/patch/review/base 与临时索引 write-tree 对拍一致")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
