#!/usr/bin/env python3
"""M248: executable Runtime Topology adapter entry point.

First paragraph declaration: bypassing collect_topology schema/dynamic guards must
turn tests/test_runtime_topology.py red. Mutation evidence is
.atlas/runs/mutation-proof/M248.txt. This adapter only reads files and writes --out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.governance_io import atomic_write_bytes  # noqa: E402
from _support.governance_schema import canonical_bytes, validate_topology  # noqa: E402
from _support.runtime_topology import DEFAULT_GLOBS, TopologyError, collect_topology  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default=".adapter-out/topology.json")
    parser.add_argument("--project", default=os.environ.get("ATLAS_TOPOLOGY_PROJECT"))
    parser.add_argument("--environment", default=os.environ.get("ATLAS_TOPOLOGY_ENVIRONMENT", "dev"))
    parser.add_argument("--cluster", default=os.environ.get("ATLAS_TOPOLOGY_CLUSTER", "local"))
    parser.add_argument("--release", default=os.environ.get("ATLAS_TOPOLOGY_RELEASE", "default"))
    parser.add_argument("--scan-glob", action="append", dest="scan_globs")
    parser.add_argument("--adapter", choices=("all", "compose", "helm", "kong"), default="all")
    parser.add_argument("--owner", default=os.environ.get("ATLAS_TOPOLOGY_OWNER"))
    parser.add_argument("--due", default=os.environ.get("ATLAS_TOPOLOGY_DUE"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).absolute()
        topology, _ = collect_topology(root, project=args.project or root.name,
                                       environment=args.environment, cluster=args.cluster,
                                       release=args.release, scan_globs=args.scan_globs or list(DEFAULT_GLOBS),
                                       owner=args.owner, due=args.due, adapter=args.adapter)
        errors = validate_topology(topology)
        if errors:
            raise TopologyError("topology schema: " + "; ".join(errors))
        if topology["coverage"]["parse_errors"]:
            result = {"module": "topology", "verdict": "UNVERIFIED", "rc": 2,
                      "cause": "topology_unverified", "coverage": topology["coverage"]}
        else:
            from _support.governance_io import safe_path
            output = Path(args.out)
            if output.is_absolute():
                try:
                    output = output.relative_to(root)
                except ValueError as exc:
                    raise TopologyError("--out 必须位于项目根内") from exc
            atomic_write_bytes(safe_path(root, output), canonical_bytes(topology) + b"\n")
            dynamic_fields = topology["coverage"]["unverified_fields"]
            result = {"module": "topology", "verdict": "UNVERIFIED" if dynamic_fields else "PASS",
                      "rc": 2 if dynamic_fields else 0,
                      "cause": "topology_unverified" if dynamic_fields else None,
                      "coverage": topology["coverage"]}
    except (TopologyError, OSError, ValueError) as exc:
        result = {"module": "topology", "verdict": "FAIL", "rc": 1,
                  "cause": "topology_stale", "message": str(exc)}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] topology rc={result['rc']} cause={result['cause']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
