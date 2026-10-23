"""源包内容摘要（P3 装配版本戳；2026-10-05；F30 装配集收窄 / F37 过滤口径 2026-10-15）。

**装配基线 manifest（2026-10-23，`RFC-20261023-02` ②）**：聚合摘要只能回答「变没变」，
回答不了「变在哪」——逐文件明细此前要另跑 `backflow.py`。`stamp_file()` 现在同点落
`.atlas/MANIFEST.json`（`{digest, files: {rel_posix: sha256}}`，与 VERSION 同一次遍历产出，
无二次读盘）。**写序定死：先 MANIFEST 后 VERSION**——VERSION 在场即 manifest 已齐；
VERSION 在场而 manifest 缺/空 = 干净的「旧装配」语义（半态协议，评审 B1）。判定
「装配态一致」的充分条件 = 摘要相等 ∧ manifest 覆盖装配集完整；未逐项解释的差异
（`backflow.py` 三态对账）只能记「不一致（已解释）」，不得记一致（运行时仍 WARN——
漂移是常态信号，非门禁失败）。manifest 落 target 侧 `.atlas/`，不在装配集白名单内，
不参与摘要（无自指）。

双端共用算法：install.sh 装配完成时对源包算摘要落 `<target>/.atlas/VERSION`；
副本侧 `atlas_check.py` 导入本模块重算当前源包摘要比对——不一致 ⇒ WARN（源包已
前进/落后于装配态；生效路径与差异明细见 `scripts/atlas_check.py` 装配版本门 WARN
文案：`atlas upgrade`/`atlas update` + 本地源仓 `install.sh` 两支路 + `backflow.py`
三态，`DESIGN.md` D79 ⑤）。**不依赖 git**（源包无仓库）；
摘要直接探测内容漂移，比版本号更贴「对账」本意。

**算法（F30，2026-10-15）**：摘要只遍历**装配集**——install.sh 实际拷入 `.atlas/`
的目录白名单（以 `ASSEMBLY_COVER_DIRS` 常量为准：包内 `shared`、`rings`、`apply`、
`scripts`、`templates`、`adapters`、`validators`、`patches`、`tests`、`_support`、
`extensions` 十一目录 + `LICENSE` 顶层文件 + `skills/*`；`agents/` 属退役清理项，不在拷集）。
旧口径遍历整个工作目录 ⇒ 源包只改 CHANGELOG/README/docs 等非装配文件也会让
「装配版本」门 WARN（R6 现场实证：每次 CHANGELOG 变更装配戳全变）。
**白名单 ⇔ install.sh 拷贝列表双向同步钉**见 `tests/test_tools.py` 的
`test_f30_assembly_cover_in_sync_with_install_sh`——防将来新增拷贝目录自成摘要盲区。
按相对 POSIX 路径排序，逐文件喂 `f"{rel}\0{sha256_hex(content)}\n"` 进 sha256，
取前 16 位十六进制。**改动算法须 install.sh 与 atlas_check 两侧同步**
（本模块是唯一实现点，两侧都 import 它）。

**过滤口径（F37，2026-10-15）**：`SKIP_DIRS` 判据用**根相对** parts——旧口径拿绝对
parts 判，而绝对路径含路径上每一级目录名；npm 全局安装的源包位于
`<prefix>/lib/node_modules/<pkg>`，于是**每个文件**都命中 `node_modules` 被滤掉 ⇒
`files == []` ⇒ 摘要恒为 `sha256('')[:16] = e3b0c44298fc1c14`，而 install.sh 落戳与
atlas_check 重算**两侧同错** ⇒ 恒等 ⇒ 「装配版本」门在任何漂移下都不报红
（现场实证：装配态打印 `源包与装配态一致（e3b0c44298fc1c14）`）。
同时把「装配集为空」由静默空摘要改为**响亮报错**（`EmptyAssembly`）——
「装配 0 文件」不得被记成一次合法装配。
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
                       "validators", "patches", "tests", "_support", "skills", "extensions")
ASSEMBLY_COVER_FILES = ("LICENSE",)


class EmptyAssembly(ValueError):
    """装配集过滤后为空（一个可摘要的文件都没有）——摘要必然等于 `sha256('')`。

    这是**响亮错误**而非合法结果：空摘要可用于对账的前提不成立（两侧都取空值就恒等，
    门变成只会通过的门）。`atlas_check` 对本类单列一条 WARN；install.sh 侧直接硬错。
    """


def _assembly_files(root: Path) -> list[Path]:
    """装配集内的可摘要文件（已过滤、已排序）。根越界/装配集为空 ⇒ 响亮报错。"""
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
    # 判据用**根相对** parts（F37）：绝对 parts 含路径上每一级目录名，npm 全局安装的
    # 源包必然位于 <prefix>/lib/node_modules/<pkg> ⇒ 命中 node_modules 后全被滤掉。
    # 根相对后，只有 `node_modules` 真落在装配集内部时才命中（那本来就该跳过）。
    files = sorted(
        p for p in files
        if not (set(p.relative_to(root).parts) & SKIP_DIRS)
        and not p.name.endswith(SKIP_SUFFIXES)
    )
    if not files:
        raise EmptyAssembly(
            f"装配集为空：{root} 下 {list(ASSEMBLY_COVER_DIRS)} + "
            f"{list(ASSEMBLY_COVER_FILES)} 内没有可摘要的文件（空摘要不可用于对账）")
    return files


def manifest(root: Path) -> dict:
    """装配基线：`{digest, files}`——聚合摘要 + 逐文件 sha256（同一次遍历产出）。

    `files` 的键 = 根相对 POSIX 路径；摘要算法与旧 `digest()` 逐字节一致（文件序 =
    装配集排序，逐文件喂 `rel\\0sha256\\n`）。
    """
    root = Path(root)
    files = _assembly_files(root)
    hashes: dict[str, str] = {}
    h = hashlib.sha256()
    for p in files:
        rel = p.relative_to(root).as_posix()
        fh = hashlib.sha256(p.read_bytes()).hexdigest()
        hashes[rel] = fh
        h.update(f"{rel}\0{fh}\n".encode("utf-8"))
    return {"digest": h.hexdigest()[:16], "files": hashes}


def digest(root: Path) -> str:
    """源包装配集摘要（前 16 位十六进制）。root 不存在 ⇒ ValueError；装配集为空 ⇒ EmptyAssembly。"""
    return manifest(root)["digest"]


def stamp_file(source_dir: Path, target_version_file: Path) -> str:
    """装配落戳：**先** MANIFEST.json（逐文件基线）**后** VERSION（摘要行 + 时间行 + 源包路径行）。

    写序是半态协议的一部分（评审 B1）：任何中断都不会留下「VERSION 新而 manifest 缺」
    的可信态。返回摘要。
    """
    import datetime
    import json

    m = manifest(source_dir)
    d = m["digest"]
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    target_version_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file = target_version_file.parent / "MANIFEST.json"
    manifest_file.write_text(
        json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
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
