"""源包内容摘要（P3 装配版本戳；2026-10-05）。

双端共用算法：install.sh 装配完成时对源包算摘要落 `<target>/.atlas/VERSION`；
副本侧 `atlas_check.py` 导入本模块重算当前源包摘要比对——不一致 ⇒ WARN（源包已
前进/落后于装配态，重跑 install.sh 前先回灌对账）。**不依赖 git**（源包无仓库）；
摘要直接探测内容漂移，比版本号更贴「对账」本意。

算法：遍历包目录（跳过 `.git` / `__pycache__` / `.pytest_cache` / `*.pyc` /
`.DS_Store`），按相对 POSIX 路径排序，逐文件喂 `f"{rel}\0{sha256_hex(content)}\n"`
进 sha256，取前 16 位十六进制。**改动算法须 install.sh 与 atlas_check 两侧同步**
（本模块是唯一实现点，两侧都 import 它）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".DS_Store")


def digest(root: Path) -> str:
    """源包内容摘要（前 16 位十六进制）。root 不存在 ⇒ ValueError。"""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    h = hashlib.sha256()
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and not (set(p.parts) & SKIP_DIRS)
        and not p.name.endswith(SKIP_SUFFIXES)
    )
    for p in files:
        rel = p.relative_to(root).as_posix()
        fh = hashlib.sha256(p.read_bytes()).hexdigest()
        h.update(f"{rel}\0{fh}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def stamp_file(source_dir: Path, target_version_file: Path) -> str:
    """装配落戳：VERSION = 摘要行 + 时间行 + 源包绝对路径行。返回摘要。"""
    import datetime

    d = digest(source_dir)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    target_version_file.parent.mkdir(parents=True, exist_ok=True)
    target_version_file.write_text(f"{d}\n{now}\n{source_dir.resolve()}\n", encoding="utf-8")
    return d


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: pkg_digest.py <source-dir>", file=sys.stderr)
        sys.exit(2)
    try:
        print(digest(Path(sys.argv[1])))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
