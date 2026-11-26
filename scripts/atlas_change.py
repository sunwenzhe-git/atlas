#!/usr/bin/env python3
"""atlas change — unified requirement-change and defect backflow entrypoint."""
# ATLAS_CHANGE_AUTO_V1
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from atlas_bug import main as bug_main


def main() -> int:
    return bug_main(default_kind="需求变更")


if __name__ == "__main__":
    sys.exit(main())
