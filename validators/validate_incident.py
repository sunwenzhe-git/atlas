#!/usr/bin/env python3
"""M246: RFC-20261125-01 §7 Incident gate and shared close/finish validator.

First paragraph declaration: dropping verification-reference existence
validation must turn tests/test_incident.py's no-verification-evidence
counterexample red. The real four-stage mutation_proof evidence is stored at
.atlas/runs/mutation-proof/M246.txt.

The validator is read-only. It replays timeline.jsonl as sole authority,
checks both generated projections, safe evidence paths and SHA-256 hashes,
reference existence, signed/measured verification, action waivers and legal
state transitions. Default shadow reports observations with rc0; off is
UNVERIFIED/rc2; enforce maps deterministic evidence/state failures to rc1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.incident import check_incident, incident_error_result, validate_incident_closed, with_repair_commands  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--closed", action="store_true", help="使用 close/finish 共用关闭判据")
    parser.add_argument("incident_id", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.closed:
            if not args.incident_id:
                parser.error("--closed 必须指定 incident_id")
            result = validate_incident_closed(args.root, args.incident_id, mode=args.mode)
        else:
            result = check_incident(args.root, args.incident_id, mode=args.mode)
    except Exception as exc:  # fail closed: a validator crash is never PASS
        result = incident_error_result(exc, args.mode)
    with_repair_commands(result, args.root, args.incident_id)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] incident rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'incident')}: {finding['message']}")
        if result["verdict"] == "PASS" and not result["findings"]:
            print("[PASS] Incident timeline/schema/evidence/references/actions/projections 全部一致")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
