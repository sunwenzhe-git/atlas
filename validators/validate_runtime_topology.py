#!/usr/bin/env python3
"""M248: RFC-20261125-01 P3 Runtime Topology validator.

First paragraph declaration: bypassing validate_topology or source file-set/hash
comparison must turn tests/test_runtime_topology.py red. The real four-stage
mutation_proof is .atlas/runs/mutation-proof/M248.txt.

The validator is read-only. Schema/dangling-edge/stale failures are rc1; dynamic
fields, parse uncertainty, missing artifacts and off are UNVERIFIED rc2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.runtime_topology import MODES, TopologyError, check_topology  # noqa: E402


def _fallback(mode: str, exc: Exception) -> dict:
    off = mode == "off"
    return {"schema_version": 1, "module": "topology", "mode": mode,
            "verdict": "UNVERIFIED" if off else "FAIL", "cause": None if off else "topology_stale",
            "rc": 2 if off else 1,
            "findings": [{"cause": "observation" if off else "topology_stale",
                          "message": f"校验器异常：{type(exc).__name__}: {exc}"}], "metrics": {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=MODES, default=os.environ.get("ATLAS_TOPOLOGY_MODE", "shadow"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = check_topology(args.root, mode=args.mode)
    except Exception as exc:  # fail closed; a crash must never look like PASS
        result = _fallback(args.mode, exc)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] topology rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'topology')}: {finding['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
