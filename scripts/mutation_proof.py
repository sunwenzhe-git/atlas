#!/usr/bin/env python3
"""atlas 共享工具 —— **变异证明**（mutation proof）的可复用实现。

契约纪律正文见 `.atlas/shared/global-rules.md` §6（「门会咬」的证明要逐字节对拍）；
本文件只把它落成可复算的代码，供各环 / 各项目复用。

四段协议（缺一不算证据）：
    ① **先证基线 GREEN** —— 否则后面的红说明不了任何事；
    ② 注入反事实 ⇒ **RED**；
    ③ **逐字节还原**（sha256 相符）；
    ④ 再跑 ⇒ **GREEN**。

两个已实测踩过的坑（`3509 §B80` / `§B87`）：
    * **假阳性**：源码变异后长度不变 + mtime 落在同一秒 ⇒ `.pyc` 被当成新鲜而复用，
      得出「还原后仍红」的假象 ⇒ 跑前清 `__pycache__` + 置 `PYTHONDONTWRITEBYTECODE=1`（本工具默认这么做）。
    * **假阴性**：`str.replace` 锚点静默不匹配 ⇒ 注入根本没发生，却报「门不咬」
      ⇒ **注入前断言字节确实改变**（本工具直接抛 `MutationNotApplied`）。

- **框架无关**：本文件不得出现任何具体框架名。
- 纯标准库。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Callable

__all__ = ["MutationNotApplied", "proof", "run_with_clean_pycache"]


class MutationNotApplied(RuntimeError):
    """注入没有改变目标字节 —— 锚点失效。这类「不咬」是假象，不得当成「门没咬」。"""


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_with_clean_pycache(cmd: list[str], cwd: pathlib.Path, root: pathlib.Path) -> tuple[int, str]:
    """跑一条命令，**先清 `__pycache__`**，并置 `PYTHONDONTWRITEBYTECODE=1`。

    `root` = 清 `__pycache__` 的范围（通常是**包根**，不是项目根 —— 项目的缓存不属本工具管）。
    """
    for d in root.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def proof(name: str, target: str | pathlib.Path, mutate: Callable[[bytes], bytes],
          run: Callable[[], tuple[int, str]], out_dir: str | pathlib.Path,
          expect_baseline_green: bool = True) -> bool:
    """跑一条变异切片，把三段原始输出落盘。返回本切片是否构成证据。

    * `target` —— 被变异的目标文件（**其所在仓库应受版本控制**，本工具不代替版本控制做还原）；
    * `mutate(bytes) -> bytes` —— 注入函数；返回值必须**不等于**入参，否则抛 `MutationNotApplied`；
    * `run() -> (退出码, 输出)` —— 跑目标门的回调（调用方自己决定怎么跑）；
    * `out_dir` —— 每条切片的原始输出落点。
    """
    target = pathlib.Path(target)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    before = target.read_bytes()
    h_before = sha256(before)

    lines = [f"# 变异：{name}", f"对象：{target}", "", "## 还原校验", f"原 sha256 = {h_before}", ""]

    # ① 基线
    rc_base, out_base = run()
    lines += ["## 基线（期望 GREEN）", f"退出码 {rc_base}", "```", out_base, "```", ""]
    if expect_baseline_green and rc_base != 0:
        lines += ["**基线不绿 ⇒ 本切片作废**（后面的红说明不了任何事）。", ""]
        (out_dir / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")
        return False

    # ② 注入
    mutated = mutate(before)
    if mutated == before:
        raise MutationNotApplied(
            f"[{name}] 变异**没有改变任何字节** —— 锚点失效。这类「不咬」是假象，"
            f"不得当成「门没咬」（实测踩到：str.replace 锚点 0 命中时静默不匹配）")
    target.write_bytes(mutated)
    rc_red, out_red = run()

    # ③ 逐字节还原
    target.write_bytes(before)
    h_after = sha256(target.read_bytes())
    same = h_before == h_after

    # ④ 复绿
    rc_green, out_green = run()

    lines += [
        f"## 注入后（期望 RED）", f"退出码 {rc_red}", "```", out_red, "```", "",
        f"## 还原校验（续）", f"后 sha256 = {h_after}", f"一致 = {same}", "",
        f"## 还原后（期望 GREEN）", f"退出码 {rc_green}", "```", out_green, "```", "",
    ]
    (out_dir / f"{name}.txt").write_text("\n".join(lines), encoding="utf-8")

    ok = rc_red != 0 and rc_green == 0 and same
    print(f"  {'✅' if ok else '❌'} {name}: 注入 rc={rc_red}（期望非 0） · "
          f"还原 rc={rc_green}（期望 0） · 字节一致={same}")
    return ok


def main() -> int:
    """自检：本工具的**唯一**职责是四段协议，故这里只验自己。

    关键：这个「假门」必须**直接读文件内容**（纯函数、无隐藏状态）。
    初版用状态标志模拟门，还原后标志没复位 ⇒ 自检假红 —— 即「证明工具自己要先对拍」（`3509 §B87`）。
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td) / "gate.txt"
        t.write_text("ok\n", encoding="utf-8")

        def run() -> tuple[int, str]:
            bad = t.read_bytes() != b"ok\n"
            return (1 if bad else 0), ("red\n" if bad else "green\n")

        def mutate(b: bytes) -> bytes:
            return b.replace(b"ok", b"bad")

        ok = proof("selfcheck", t, mutate, run, pathlib.Path(td) / "out")
        print(f"selfcheck: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
