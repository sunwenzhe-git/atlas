#!/usr/bin/env python3
"""RFC-20261125-01 §12 read-only governance metrics CLI.

Reads check-events, governance-calibration.json and the aggregate governance
module-result snapshot. It never writes a report and never copies business text;
missing inputs and zero denominators remain explicit N/A, not numeric zero.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.governance_metrics import compute_metrics  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default="shadow")
    args = parser.parse_args(argv)
    try:
        result = compute_metrics(args.root)
        if args.mode == "off":
            result = {"schema_version": 1, "module": "metrics", "mode": "off",
                      "verdict": "UNVERIFIED", "cause": None, "rc": 2, "metrics": {}}
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"schema_version": 1, "module": "metrics", "verdict": "UNVERIFIED",
                  "rc": 2, "cause": "metrics_unverified", "mode": args.mode, "metrics": {}, "findings": [], "reasons": [str(exc)]}
    unverified = any(source["status"] == "UNVERIFIED" for source in result.get("sources", {}).values()) \
        or any(metric.get("status") == "UNVERIFIED" for metric in result.get("metrics", {}).values()) \
        or result.get("classification_calibration", {}).get("status") == "UNVERIFIED" \
        or all(source["status"] == "N/A" for source in result.get("sources", {}).values()) \
        or all(metric.get("status") == "N/A" for metric in result.get("metrics", {}).values())
    result.update(verdict="UNVERIFIED" if unverified else "PASS", rc=2 if unverified else 0,
                  cause="metrics_unverified" if unverified else None, findings=[], mode=args.mode)
    if args.mode == "off":
        result.update(verdict="UNVERIFIED", rc=2, cause=None)
    calibration_path = Path(args.root) / ".atlas/runs/governance-calibration.json"
    if args.mode != "off" and calibration_path.is_file():
        validator = Path(__file__).resolve().parents[1] / "validators" / "validate_calibration.py"
        checked = subprocess.run([sys.executable, str(validator), "--root", args.root, "--json"],
                                 capture_output=True, text=True, timeout=60)
        if checked.returncode != 0:
            result.update(verdict="UNVERIFIED", rc=2, cause="metrics_unverified")
            result["classification_calibration"] = {"status": "UNVERIFIED", "decision": "shadow"}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] governance metrics rc={result['rc']}")
        for name, metric in sorted(result.get("metrics", {}).items()):
            value = metric.get("value", metric.get("p50"))
            print(f"[{metric['status']}] {name}={value if value is not None else 'N/A'}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
