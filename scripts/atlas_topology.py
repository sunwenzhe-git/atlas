#!/usr/bin/env python3
"""M248: RFC-20261125-01 P3 Runtime Topology CLI.

First paragraph declaration: making refresh overwrite the active generation or
making rollback delete it must turn tests/test_runtime_topology.py red. The real
four-stage mutation_proof is .atlas/runs/mutation-proof/M248.txt.

Default mode is shadow; deterministic failures remain rc1 and dynamic/parse
uncertainty is rc2. No command contacts a cluster or evaluates templates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.runtime_topology import (  # noqa: E402
    MODES,
    TopologyError,
    check_topology,
    refresh_topology,
    rollback_topology,
)


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _failure(exc: Exception, mode: str, as_json: bool) -> int:
    off = mode == "off"
    io_error = isinstance(exc, OSError) and not off
    result = {"schema_version": 1, "module": "topology", "mode": mode,
              "verdict": "UNVERIFIED" if off or io_error else "FAIL",
              "cause": None if off else "topology_unverified" if io_error else "topology_stale",
              "rc": 2 if off or io_error and mode == "enforce" else 0 if io_error else 1,
              "findings": [{"cause": "observation" if off else "topology_unverified" if io_error else "topology_stale",
              "message": str(exc)}], "metrics": {}}
    if as_json:
        _print(result)
    else:
        print(f"[{result['verdict']}] topology rc={result['rc']} cause={result['cause']}: {exc}", file=sys.stderr)
    return result["rc"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=MODES, default=os.environ.get("ATLAS_TOPOLOGY_MODE", "shadow"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh", help="扫描静态部署事实并原子发布新代")
    refresh.add_argument("--project", default=os.environ.get("ATLAS_TOPOLOGY_PROJECT"))
    refresh.add_argument("--environment", default=os.environ.get("ATLAS_TOPOLOGY_ENVIRONMENT", "dev"))
    refresh.add_argument("--cluster", default=os.environ.get("ATLAS_TOPOLOGY_CLUSTER", "local"))
    refresh.add_argument("--release", default=os.environ.get("ATLAS_TOPOLOGY_RELEASE", "default"))
    refresh.add_argument("--scan-glob", action="append", dest="scan_globs")
    refresh.add_argument("--adapter", choices=("all", "compose", "helm", "kong"), default="all")
    refresh.add_argument("--owner", default=os.environ.get("ATLAS_TOPOLOGY_OWNER"))
    refresh.add_argument("--due", default=os.environ.get("ATLAS_TOPOLOGY_DUE"))
    refresh.add_argument("--json", action="store_true", dest="as_json", default=argparse.SUPPRESS)
    commands.add_parser("check", help="复核 schema、悬空边、文件集与源 hash")
    rollback = commands.add_parser("rollback", help="只切回上一代 manifest 指针")
    rollback.add_argument("--json", action="store_true", dest="as_json", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "refresh":
            result = refresh_topology(args.root, project=args.project, environment=args.environment,
                                      cluster=args.cluster, release=args.release, scan_globs=args.scan_globs,
                                      owner=args.owner, due=args.due, mode=args.mode, adapter=args.adapter)
        elif args.command == "check":
            result = check_topology(args.root, mode=args.mode)
        else:
            result = rollback_topology(args.root, mode=args.mode)
    except (TopologyError, OSError, ValueError) as exc:
        return _failure(exc, args.mode, args.as_json)
    if args.as_json:
        _print(result)
    else:
        print(f"[{result['verdict']}] topology rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'topology')}: {finding['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
