#!/usr/bin/env python3
"""M249: RFC-20261125-01 §6 semantic contract validator.

First paragraph declaration: removing the observed field type comparison in
_support/semantic_contracts.py must turn tests/test_semantic_contracts.py's
field-type drift counterexample red. The real four-stage mutation_proof
evidence is stored at .atlas/runs/mutation-proof/M249.txt.

The validator is read-only. It checks the three versioned stores and digests,
base/head revisions, source file:line/hash anchors, adapter versions, graph
edges and deterministic expected-versus-observed drift. Shadow keeps rc0;
off is UNVERIFIED/rc2; enforce maps drift to FAIL/rc1 and unknown to
UNVERIFIED/rc2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.semantic_contracts import check_contracts, semantic_error_result
from _support.siblings import load_module


def _testid_inputs():
    path = Path(__file__).with_name("validate_testids.py")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return load_module("validate_testids"), f"validate_testids@{digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        extractor, version = _testid_inputs()
        result = check_contracts(args.root, mode=args.mode,
                                 testid_extractor=extractor, testid_version=version)
    except Exception as exc:  # fail closed: a validator crash is never PASS
        result = semantic_error_result(exc, args.mode, args.root)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] semantic rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'contracts')}: {finding['message']}")
        if result["verdict"] == "PASS":
            print("[PASS] expected/observed/graph 三库、摘要、来源锚与语义对账一致")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
