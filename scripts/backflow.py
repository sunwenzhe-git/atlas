#!/usr/bin/env python3
"""atlas 回灌助手 —— `.atlas/`（副本先行态）→ `atlas/`（源包）的差异报告与同步。

用法（项目根 = 同时含 `.atlas/` 与 `atlas/` 的目录）：

    python3 atlas/scripts/backflow.py --root .            # dry-run（缺省）：差异报告
    python3 atlas/scripts/backflow.py --root . --apply    # 同步（源包独有差异 ⇒ 拒绝，除非 --force）

语义（2026-10-12 单源批，ATLAS-UPSTREAM #198；回灌纪律 = `ATLAS-UPSTREAM.md`）：

  * **清单** = `install.sh` 装配的包面目录（`BACKFLOW_DIRS` 与 install.sh 循环逐项一致，
    出厂测试守恒）——不碰发布行专属件（README / DESIGN / docs / skills …）。
  * **三态差异**：`NEW`（仅副本有 ⇒ 待回灌）/ `DIFF`（内容不同 ⇒ 待回灌）/
    `SOURCE_ONLY`（仅源包有 —— 发布行在飞改动或手工直改，**响亮警示**）。
  * `--apply`：仅在无 `SOURCE_ONLY` 时执行（`--force` 越过——越过前先人工核对方向：
    `ATLAS-UPSTREAM #191/#207` 覆盖事故的根因就是方向误判，dry-run 缺省即为此设）。
    逐文件复制（保留可执行位）。
  * **并发写入哨兵**（2026-10-12 首用实证，`3508 §211`）：复制前复核清单文件在
    「差异计算 → 复制前」窗口内未被改写；触发 ⇒ **中止（exit 3）**——防另一会话的
    在途半成品被卷入源包（本器首用即撞：并发会话 B201-1 在途内容被卷入 ⇒ 源包侧手术剥离）。
  * **`--apply` 后自动跑源包回归**（`<源包>/tests`，缺省开、`--no-verify` 跳过）：
    红 ⇒ exit 4 + 指路——「回灌后立即验证」纪律步的机器化。
  * **语义在飞无法机器判（写明盲区）**：本器只保「字节一致 + 窗口内未改写 + 回归绿」；
    「这份差异是完成态还是在途半成品」是语义 ⇒ 人工核对 ATLAS-UPSTREAM 在途批。
  * 判定：dry-run 恒 0（报告是产物）；`--apply` 被拒 → 2；并发窗口中止 → 3；
    源包回归红 → 4；成功 → 0。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# 与 install.sh 第 1 步的 `for pkg_dir in …` 逐项一致（出厂测试守恒；新增包面目录两处同改）。
BACKFLOW_DIRS = ("shared", "rings", "apply", "scripts", "templates",
                 "adapters", "validators", "patches", "tests", "_support", "extensions")
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".DS_Store"}
SKIP_SUFFIXES = (".pyc",)


def _iter_files(base: Path):
    """产出清单目录下的相对路径（跳过缓存与临时件）。"""
    for d in BACKFLOW_DIRS:
        root = base / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in SKIP_NAMES for part in p.parts):
                continue
            if p.name.endswith(SKIP_SUFFIXES):
                continue
            yield p.relative_to(base).as_posix()


def diff_trees(copy_root: Path, src_root: Path) -> dict:
    """三态差异报告。copy_root = `.atlas/`，src_root = `atlas/`。"""
    copy_files = set(_iter_files(copy_root))
    src_files = set(_iter_files(src_root))
    new = sorted(copy_files - src_files)
    source_only = sorted(src_files - copy_files)
    diff = sorted(rel for rel in (copy_files & src_files)
                  if (copy_root / rel).read_bytes() != (src_root / rel).read_bytes())
    return {"new": new, "diff": diff, "source_only": source_only}


def report(d: dict) -> str:
    lines = [
        f"NEW（仅副本有，待回灌）：{len(d['new'])}",
        *[f"  + {x}" for x in d["new"]],
        f"DIFF（内容不同，待回灌）：{len(d['diff'])}",
        *[f"  ~ {x}" for x in d["diff"]],
        f"SOURCE_ONLY（仅源包有 —— 发布行在飞改动警示）：{len(d['source_only'])}",
        *[f"  ! {x}" for x in d["source_only"]],
    ]
    return "\n".join(lines)


_PYTEST_TIMEOUT = 900


def _stat_of(p: Path) -> tuple[int, int]:
    st = p.stat()
    return (st.st_mtime_ns, st.st_size)


def drift_check(copy_root: Path, rels: list[str],
                snap: dict[str, tuple[int, int]]) -> list[str]:
    """并发写入哨兵：复核清单文件在「差异计算 → 复制前」窗口内未被改写。"""
    return [rel for rel in rels if _stat_of(copy_root / rel) != snap[rel]]


def apply(copy_root: Path, src_root: Path, force: bool,
          verify: bool = False) -> tuple[int, str]:
    d = diff_trees(copy_root, src_root)
    if d["source_only"] and not force:
        return 2, (report(d) + "\n拒绝执行：源包存在副本没有的文件（上表 SOURCE_ONLY）——"
                   "先与发布行/发起批核对方向；确认要覆盖时用 --force（`#191/#207` 事故教训）。")
    rels = d["new"] + d["diff"]
    snap = {rel: _stat_of(copy_root / rel) for rel in rels}
    drifted = drift_check(copy_root, rels, snap)
    if drifted:
        return 3, (report(d) + f"\n中止：副本侧在本次运行期间被改写（并发写入窗口）：{drifted} —— "
                   "疑似另一会话在途工作被卷入（首用实证 `3508 §211`）；核对后重跑。")
    copied = 0
    for rel in rels:
        dst = src_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copy_root / rel, dst)
        copied += 1
    lines = [report(d), f"已回灌 {copied} 个文件（保留可执行位）。"]
    if verify and (src_root / "tests").is_dir():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(src_root / "tests"), "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=str(src_root.parent), capture_output=True, text=True, timeout=_PYTEST_TIMEOUT)
        last = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
        summary = last[-1] if last else "(无输出)"
        if r.returncode != 0:
            lines.append(f"源包回归：{summary}")
            return 4, "\n".join(lines + [
                "回归红 —— 核对是否卷入了并发在途内容（`3508 §211` 首用实证）；确认无误后处理，或修正后重跑。"])
        lines.append(f"源包回归：{summary}（ok）")
    lines.append("下一步：①（已跑 verify 则跳过）双侧 pytest 复核；② ATLAS_ALLOW_OVERWRITE=1 bash "
                 "atlas/install.sh --target .（重落装配戳；并发在途窗口内让位）；"
                 "③ ATLAS-UPSTREAM.md 登记批号并改状态为「已回灌源包」。")
    return 0, "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--apply", action="store_true", help="执行同步（缺省 = dry-run 报告）")
    ap.add_argument("--force", action="store_true", help="越过 SOURCE_ONLY 拒绝（先核对方向）")
    ap.add_argument("--no-verify", action="store_true", help="跳过 --apply 后的源包回归（缺省=跑）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    copy_root, src_root = root / ".atlas", root / "atlas"
    for p in (copy_root, src_root):
        if not p.is_dir():
            print(f"回灌助手：{p} 不存在（项目根须同时含 .atlas/ 与 atlas/）", file=sys.stderr)
            return 2
    if args.apply:
        code, text = apply(copy_root, src_root, args.force, verify=not args.no_verify)
    else:
        code, text = 0, report(diff_trees(copy_root, src_root))
    if args.json:
        d = diff_trees(copy_root, src_root)
        print(json.dumps({"ok": code == 0, **d}, ensure_ascii=False, indent=2))
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
