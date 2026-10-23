#!/usr/bin/env python3
"""atlas 工具 —— 写面 claim 仲裁（M3，`RFC-20261022-01` 批 3，2026-10-23）。

把 `apply/reference.md` §5.1 的「one writer per file / 冲突停下报告、不得抢占」
从纯纪律变成**命令拒绝**：

    write_claim.py take    --file <路径> --task <需求ID> [--root .]
    write_claim.py release --file <路径> [--task <需求ID>] [--root .]

原子性（评审 P1-4）：**每 claim 一个文件** `.atlas/runs/write-claims/<hash>.json`，
`os.open(..., O_CREAT|O_EXCL)` 天然原子——并发 take 同一文件时后者直接失败退出非零。
**不搞单 JSON 读改写**：那会把锁本身变成被并发打穿的伪锁。

- `take` 幂等：同一任务重复 take 同一文件 ⇒ 退出 0（已经持有）；
  他人持有 ⇒ 退出 2 + 指名在办任务与取得时间（`§5.1 停下报告，不得抢占`）。
- `release` 即删文件；不存在 ⇒ 退出 0（幂等）；`--task` 不符 ⇒ 退出 2 拒绝释放他人的 claim。
- 残留（收口未释放）= glob 目录；消费面在 `atlas_check` 的 `写面残留` 行（WARN）。
- **边界自认**：`.atlas/` 不入库为合法形态 ⇒ claims 是纯运行态、不进 git 历史，
  也不做事实；目录清扫走**逐文件 unlink**（`.atlas/runs/` 是白名单保留目录，不整目录清）。

框架无关；纯标准库。退出码：0 = 持有 / 释放成功；2 = 冲突 / 参数 / 损坏。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

CLAIMS_RELPATH = Path(".atlas") / "runs" / "write-claims"
CLAIM_SUFFIX = ".json"


class ClaimError(RuntimeError):
    """冲突 / 无法判定的硬失败（exit 2）。"""


def claims_dir(root: Path) -> Path:
    return root / CLAIMS_RELPATH


def normalize_file(root: Path, raw: str) -> str:
    """→ 根相对 posix 路径；根外路径按绝对路径存（同一文件两种写法归一到同一 claim）。"""
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    root_abs = root.resolve()
    p_abs = p.resolve()
    try:
        return p_abs.relative_to(root_abs).as_posix()
    except ValueError:
        return p_abs.as_posix()


def _canon(rel: str) -> str:
    """claim 键的归一：NFC + casefold。

    大小写不敏感文件系统（darwin/APFS 默认）上 `README.md` 与 `readme.md` 是
    同一物理文件；不归一 ⇒ 两个持有人各拿一把锁，one-writer 承诺被穿
    （评审 P1-4）。保守起见在**所有**文件系统上都按大小写不敏感处理。
    """
    return unicodedata.normalize("NFC", rel).casefold()


def _same_file(a: object, b: str) -> bool:
    return a is not None and _canon(str(a)) == _canon(b)


def claim_key(rel: str) -> str:
    return hashlib.sha256(_canon(rel).encode("utf-8")).hexdigest()[:16]


def claim_path(root: Path, rel: str) -> Path:
    return claims_dir(root) / f"{claim_key(rel)}{CLAIM_SUFFIX}"


def _read_claim(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ClaimError(f"claim 文件不可解析（{path.name}：{type(e).__name__}）——人工核对后删除")
    if not isinstance(data, dict):
        raise ClaimError(f"claim 文件顶层不是 object（{path.name}）——人工核对后删除")
    return data


def take(root: Path, raw_file: str, task: str) -> tuple[int, str]:
    if not task.strip():
        raise ClaimError("--task 不得为空（写面必须能指名在办任务）")
    rel = normalize_file(root, raw_file)
    path = claim_path(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "file": rel,
        "task": task,
        "pid": os.getpid(),
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2)
    fd = None
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileExistsError:
            try:
                data = _read_claim(path)
            except ClaimError:
                # 持有方在 EEXIST 与读取之间 release ⇒ 文件消失，重试一次拿锁
                # （评审 P1-3：否则合法 take 被误拒，且指引指向一个不存在的文件）
                if not path.exists() and attempt == 0:
                    continue
                raise
            if not _same_file(data.get("file"), rel):
                # 哈希 16 位的同前缀碰撞（极不可能）；响亮失败而不是把两把锁混成一把
                raise ClaimError(
                    f"claim 文件碰撞：{path.name} 记录的是 {data.get('file')!r}，本次是 {rel!r}")
            holder = str(data.get("task", "?"))
            if holder == task:
                return 0, f"已持有：{rel}（task={task}）"
            raise ClaimError(
                f"冲突：{rel} 的写权由 {holder} 持有"
                f"（taken_at={data.get('taken_at', '?')}）—— §5.1 停下报告，不得抢占")
    if fd is None:
        raise ClaimError("claim 状态竞争过频（连续两次 EEXIST 后消失）——请重试")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    return 0, f"取得写权：{rel}（task={task}；claim={path.name}）"


def release(root: Path, raw_file: str, task: str | None = None) -> tuple[int, str]:
    rel = normalize_file(root, raw_file)
    path = claim_path(root, rel)
    if not path.is_file():
        return 0, f"无 claim（幂等释放）：{rel}"
    if task is not None:
        if not task.strip():
            # 空串 ≠ 未传：不得用 `--task ""` 静默绕过持有者校验（评审 P2-5）
            raise ClaimError("--task 不得为空串（空串不等于未传；省略该参数才是无归属释放）")
        data = _read_claim(path)
        holder = str(data.get("task", "?"))
        if holder != task:
            raise ClaimError(f"拒绝释放：{rel} 由 {holder} 持有，调用方是 {task}（不得释放他人的 claim）")
    # 并发双 release 的第二个不得裸 traceback（评审 P1-3）
    path.unlink(missing_ok=True)
    return 0, f"释放写权：{rel}"


def scan_residuals(root: Path) -> list[dict]:
    """残留 claim 清单（消费面 = `atlas_check` 的 `写面残留` WARN）。

    只 glob `*.json`；同目录其它文件不是 claim（逐文件清理，不整目录清）。
    解析失败也计入残留（`task` 标「不可解析」）——损坏的锁必须可见，不得静默跳过。
    """
    d = claims_dir(root)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(d.glob(f"*{CLAIM_SUFFIX}")):
        entry = {"claim": p.name, "file": p.name, "task": "不可解析", "taken_at": None}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entry.update({
                    "file": str(data.get("file", p.name)),
                    "task": str(data.get("task", "?")),
                    "taken_at": data.get("taken_at"),
                })
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        out.append(entry)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="写面 claim 仲裁（原子 O_EXCL）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="取得某文件的写权")
    t.add_argument("--file", required=True)
    t.add_argument("--task", required=True)
    t.add_argument("--root", default=".")
    r = sub.add_parser("release", help="释放某文件的写权")
    r.add_argument("--file", required=True)
    r.add_argument("--task", default=None)
    r.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.cmd == "take":
            code, msg = take(root, args.file, args.task)
        else:
            code, msg = release(root, args.file, args.task)
    except ClaimError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
