#!/usr/bin/env python3
"""M251: RFC-20261125-01 §11 classification confidence CLI.

Removing either score/margin comparison from the auto-accept conjunction (or
changing ``and`` to ``or``) must turn tests/test_governance_calibration.py's
M251 threshold-boundary tests red. The real four-stage mutation_proof is stored
at .atlas/runs/mutation-proof/M251.txt.

The CLI consumes externally scored candidates; it does not infer intent from
natural language. Explicit --type takes precedence and is traced, uncertain auto
results abstain once, and held-out inspection emits only frozen metadata.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.classification_contract import (  # noqa: E402
    ClassificationError,
    classify_record,
    load_frozen_heldout,
)
from _support.governance_io import atomic_write_json, load_json, safe_path  # noqa: E402
from validators.validate_calibration import validate_calibration  # noqa: E402


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default="shadow")
    commands = parser.add_subparsers(dest="command", required=True)
    classify = commands.add_parser("classify", help="apply explicit/auto/abstain output contract")
    classify.add_argument("--input", required=True, help="record with external candidates/scorer_version")
    classify.add_argument("--root", default=argparse.SUPPRESS)
    classify.add_argument("--json", action="store_true", dest="as_json", default=argparse.SUPPRESS)
    classify.add_argument("--type", dest="explicit_type", choices=("initial", "change", "bug"))
    classify.add_argument("--related", action="append", default=[])
    classify.add_argument("--calibration", help="validated ledger supplying frozen thresholds")
    classify.add_argument("--output", default=".atlas/runs/workflow-classification.json",
                          help="PASS 结果落盘路径，供 workflow receipt 绑定")
    heldout = commands.add_parser("heldout", help="show frozen held-out metadata without business text")
    heldout.add_argument("--root", default=argparse.SUPPRESS)
    heldout.add_argument("--json", action="store_true", dest="as_json", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.mode == "off":
            result = {"schema_version": 1, "module": "classification", "mode": "off",
                      "verdict": "UNVERIFIED", "cause": None, "rc": 2, "decision": "abstain",
                      "required_input": ["--type", "--related"]}
        elif args.command == "heldout":
            frozen = load_frozen_heldout()
            result = {key: value for key, value in frozen.items() if key != "samples"}
            result.update(module="classification", verdict="PASS", rc=0)
        else:
            input_path = Path(args.input) if Path(args.input).is_absolute() else safe_path(args.root, args.input)
            record = load_json(input_path)
            thresholds = None
            if args.calibration:
                checked = validate_calibration(args.root, args.calibration)
                if checked["rc"] != 0:
                    raise ClassificationError("calibration ledger 未通过，不能加载阈值")
                thresholds = load_json(safe_path(args.root, args.calibration))["thresholds"]
            scorer = record if args.explicit_type is None else None
            result = classify_record(record, scorer, explicit_type=args.explicit_type,
                                     related=args.related, thresholds=thresholds, mode=args.mode)
        if args.command == "classify" and result["rc"] == 0:
            atomic_write_json(safe_path(args.root, args.output), result)
    except (ClassificationError, OSError, ValueError, UnicodeError) as exc:
        result = {"schema_version": 1, "module": "classification", "verdict": "UNVERIFIED",
                  "rc": 2, "cause": "classification_unverified", "mode": args.mode, "decision": "abstain",
                  "required_input": ["--type", "--related"], "reasons": [str(exc)]}
    if args.as_json:
        _print(result)
    elif args.command == "heldout":
        print(f"[PASS] held-out sha={result['spec_sha256']} tuning_allowed=false")
    else:
        print(f"[{result['verdict']}] classification rc={result['rc']} decision={result['decision']}")
        if result["decision"] == "abstain":
            print("[UNVERIFIED] 请一次补充 --type/--related")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
