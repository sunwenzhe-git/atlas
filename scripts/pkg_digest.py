"""源包内容摘要（P3 装配版本戳；2026-10-05；F30 装配集收窄 2026-10-15）。

双端共用算法：install.sh 装配完成时对源包算摘要落 `<target>/.atlas/VERSION`；
副本侧 `atlas_check.py` 导入本模块重算当前源包摘要比对——不一致 ⇒ WARN（源包已
前进/落后于装配态，重跑 install.sh 前先回灌对账）。**不依赖 git**（源包无仓库）；
摘要直接探测内容漂移，比版本号更贴「对账」本意。

**算法（F30，2026-10-15）**：摘要只遍历**装配集**——install.sh 实际拷入 `.atlas/`
的目录白名单（以 `ASSEMBLY_COVER_DIRS` 常量为准：包内 `shared`、`rings`、`apply`、
`scripts`、`templates`、`adapters`、`validators`、`patches`、`tests`、`_support`
十目录 + `LICENSE` 顶层文件 + `skills/*`；`agents/` 属退役清理项，不在拷集）。
旧口径遍历整个工作目录 ⇒ 源包只改 CHANGELOG/README/docs 等非装配文件也会让
「装配版本」门 WARN（R6 现场实证：每次 CHANGELOG 变更装配戳全变）。
**白名单 ⇔ install.sh 拷贝列表双向同步钉**见 `tests/test_tools.py` 的
`test_f30_assembly_cover_in_sync_with_install_sh`——防将来新增拷贝目录自成摘要盲区。
按相对 POSIX 路径排序，逐文件喂 `f"{rel}\0{sha256_hex(content)}\n"` 进 sha256，
取前 16 位十六进制。**改动算法须 install.sh 与 atlas_check 两侧同步**
（本模块是唯一实现点，两侧都 import 它）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
SKIP_SUFFIXES = (".pyc", ".DS_Store")
# 装配集白名单（F30）：与 install.sh 的 pkg_dir 循环 + [2]/[3] 步拷集 对齐；
# 目前口径 = 这些目录外的 CHANGELOG/README/docs/package.json 等不进摘要。
ASSEMBLY_COVER_DIRS = ("shared", "rings", "apply", "scripts", "templates", "adapters",
                       "validators", "patches", "tests", "_support", "skills")
ASSEMBLY_COVER_FILES = ("LICENSE",)


def digest(root: Path) -> str:
    """源包装配集摘要（前 16 位十六进制）。root 不存在 ⇒ ValueError。"""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    files: list[Path] = []
    for rel_dir in ASSEMBLY_COVER_DIRS:
        base = root / rel_dir
        if not base.is_dir():
            continue
        files.extend(p for p in base.rglob("*") if p.is_file())
    for rel_file in ASSEMBLY_COVER_FILES:
        p = root / rel_file
        if p.is_file():
            files.append(p)
    files = sorted(
        p for p in files
        if not (set(p.parts) & SKIP_DIRS)
        and not p.name.endswith(SKIP_SUFFIXES)
    )
    h = hashlib.sha256()
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
