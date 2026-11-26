#!/usr/bin/env python3
"""Project adapter facts and check Atlas semantic contracts without changing expected."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.semantic_contracts import (
    SemanticError, check_contracts, refresh_contracts, rollback_contracts, semantic_error_result,
)
from _support.siblings import load_module


def _testid_inputs():
    path = Path(__file__).resolve().parents[1] / "validators/validate_testids.py"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return load_module("validate_testids"), f"validate_testids@{digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("check", "rollback"), default="check")
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", help="base commit；缺省 HEAD")
    parser.add_argument("--head", help="head commit；缺省与 base 相同")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default=None)
    parser.add_argument("--write", action="store_true", help="只重写 observed.json/graph.json")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.action == "rollback":
            if args.write:
                parser.error("rollback 不能与 --write 同用")
            result = rollback_contracts(args.root, mode=args.mode)
        elif args.write:
            extractor, version = _testid_inputs()
            result = refresh_contracts(args.root, base=args.base, head=args.head, mode=args.mode,
                                       testid_extractor=extractor, testid_version=version)
        else:
            if args.base or args.head:
                raise SemanticError("--base/--head 只能与 --write 同用")
            extractor, version = _testid_inputs()
            result = check_contracts(args.root, mode=args.mode,
                                     testid_extractor=extractor, testid_version=version)
    except (OSError, ValueError, RuntimeError) as exc:
        result = semantic_error_result(exc, args.mode, args.root)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] semantic rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'contracts')}: {finding['message']}")
        if result.get("metrics", {}).get("digests"):
            print("[digests] " + " ".join(f"{key}={value}" for key, value in sorted(result["metrics"]["digests"].items())))
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
