#!/usr/bin/env python3
"""M247: RFC-20261125-01 P2 Docs Governance validator.

First paragraph declaration: deleting the unchanged-body/evidence guard in
_support/docs_governance.py must turn tests/test_docs_governance.py red. The
four-stage mutation_proof is .atlas/runs/mutation-proof/M247.txt.

Only explicitly registered documents are evaluated. Shadow preserves findings
with rc0; off is UNVERIFIED rc2. --doc-id exposes the pure task-scoped check
used by verify/finish without wiring those entry points in this module.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.docs_governance import DocsGovernanceError, check_docs, check_docs_for_ids


def _fallback(mode: str, exc: Exception) -> dict:
    if mode == "off":
        return {"schema_version": 1, "module": "docs", "mode": mode,
                "verdict": "UNVERIFIED", "cause": None, "rc": 2,
                "findings": [{"cause": "observation", "message": f"Docs 关闭：{exc}"}], "metrics": {}}
    return {"schema_version": 1, "module": "docs", "mode": mode,
            "verdict": "FAIL", "cause": "docs_stale", "rc": 0 if mode == "shadow" else 1,
            "findings": [{"cause": "docs_stale", "message": f"校验器异常：{type(exc).__name__}: {exc}"}], "metrics": {}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"),
                        default=os.environ.get("ATLAS_DOCS_MODE", "shadow"))
    parser.add_argument("--doc-id", action="append", default=[], dest="doc_ids",
                        help="只复核 task doc_ids；可重复")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        if args.doc_ids:
            result = check_docs_for_ids(args.root, args.doc_ids, mode=args.mode)
        else:
            result = check_docs(args.root, mode=args.mode)
    except Exception as exc:  # fail closed; never crash into an apparent PASS
        result = _fallback(args.mode, exc)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] docs rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for item in result["findings"]:
            print(f"[{result['verdict']}] {item.get('path', 'docs')}: {item['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
