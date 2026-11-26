#!/usr/bin/env python3
"""M247: explicit Docs Governance CLI (list/check/touch).

First paragraph declaration: an unchanged body or a no-impact attestation
without objective evidence must never clear source stale. The mutation proof
is .atlas/runs/mutation-proof/M247.txt. Default mode is shadow; off is rc2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.docs_governance import DocsGovernanceError, check_docs, list_documents, touch_document


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _failure(exc: Exception, as_json: bool, mode: str = "enforce") -> int:
    if mode == "off":
        result = {"schema_version": 1, "module": "docs", "mode": mode,
                  "verdict": "UNVERIFIED", "cause": None, "rc": 2,
                  "findings": [{"cause": "observation", "message": str(exc)}]}
    elif isinstance(exc, OSError):
        result = {"schema_version": 1, "module": "docs", "mode": mode,
                  "verdict": "UNVERIFIED", "cause": "docs_unverified", "rc": 0 if mode == "shadow" else 2,
                  "findings": [{"cause": "docs_unverified", "message": str(exc)}]}
    else:
        result = {"schema_version": 1, "module": "docs", "mode": mode,
                  "verdict": "FAIL", "cause": "docs_stale", "rc": 0 if mode == "shadow" else 1,
                  "findings": [{"cause": "docs_stale", "message": str(exc)}]}
    if as_json:
        _print_json(result)
    else:
        print(f"[{result['verdict']}] docs rc={result['rc']} cause={result['cause']}: {exc}", file=sys.stderr)
    return result["rc"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"),
                        default=os.environ.get("ATLAS_DOCS_MODE", "shadow"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出显式登记文档（不扫描未登记文档）")
    commands.add_parser("check", help="复核显式登记文档的来源摘要与链接")
    touch = commands.add_parser("touch", help="追加机器复核事件，不改正文")
    touch.add_argument("doc_id")
    touch.add_argument("--by", required=True, dest="actor")
    touch.add_argument("--evidence", required=True)
    touch.add_argument("--no-impact", action="store_true", help="来源变化无需改正文；必须给客观证据")
    for command in (commands.choices["list"], commands.choices["check"], touch):
        command.add_argument("--json", action="store_true", dest="as_json", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            documents = list_documents(args.root)
            if args.as_json:
                _print_json({"version": 1, "documents": documents})
            else:
                for item in documents:
                    print(f"{item['id']}\t{item['path']}\t{item['owner']}\t{item['status']}")
                if not documents:
                    print("N/A 无 governance.yaml 或未登记文档")
            return 0
        if args.command == "check":
            result = check_docs(args.root, mode=args.mode)
            if args.as_json:
                _print_json(result)
            else:
                print(f"[{result['verdict']}] docs rc={result['rc']} cause={result['cause']} mode={result['mode']}")
                for finding in result["findings"]:
                    print(f"[{result['verdict']}] {finding.get('path', 'docs')}: {finding['message']}")
            return result["rc"]
        if args.mode == "off":
            raise DocsGovernanceError("Docs Governance 已关闭；in-scope touch 不可判定")
        event = touch_document(args.root, args.doc_id, args.actor, args.evidence, no_impact=args.no_impact)
        if args.as_json:
            _print_json(event)
        else:
            label = "attestation（无影响声明，不是语义同步证明）" if event["kind"] == "attestation" else "touch"
            print(f"[PASS] {event['doc_id']} {label} actor={event['actor']} evidence={event['evidence']}")
        return 0
    except (DocsGovernanceError, OSError, ValueError, RuntimeError) as exc:
        return _failure(exc, args.as_json, args.mode)


if __name__ == "__main__":
    sys.exit(main())
