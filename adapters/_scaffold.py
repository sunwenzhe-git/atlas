#!/usr/bin/env python3
"""atlas 适配器**脚手架** —— 复制本文件为 `adapters/<category>.py` 后填 `extract()`。

契约：`.atlas/shared/stack-profile.md` §3。要点：
  * 调用：`<adapter> --root <项目根> [--app <name>] --out <json 路径>`
    - `--root` 传**项目根**（`source_file` 用项目根相对路径）；`--app` 传 `apps[].name` 过滤。
  * 输出：`{"category": <名>, "items": [...], "source_files": [...], "adapter_version": "..."}`
    - 只出**机械可抽**字段；用途 / 交互 / 语义等由 agent 补。
    - **按条目带上 `source_file`**（项目根相对）——事实区自动渲染靠它做「表/模块 → 域」归属（D69）。
  * **约束**：只读代码；**幂等**（同输入同输出）；失败非零退出且**不产半成品**；不写文档。
  * **框架知识只能在本文件内**：核心 / shared / rings / templates / validators 一律不得出现框架名；
    适配器是唯一允许「认识某个技术栈」的地方（全局规则 §1）。
  * 未声明适配器（`null`）= 该类别降级为 agent 撰写；写不了就返回空 `items`，不要猜。

用法（填好后）：
    python3 <adapter>.py --root <项目根> --out <json> [--app <name>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CATEGORY = "CHANGE_ME"          # routes | api | models | tests
VERSION = "0.1.0"
DEFAULT_GLOBS = ("**/*",)       # 按栈收窄，例如 ("**/*.py",)；空 = 全扫


def iter_files(root: Path, app_path: str | None):
    """产出候选源文件；按栈收窄扩展名 / 目录。"""
    base = (root / app_path) if app_path else root
    for glob in DEFAULT_GLOBS:
        for f in sorted(base.glob(glob)):
            if f.is_file():
                yield f


def extract(text: str, rel: str) -> list[dict]:
    """把单个文件解析为 items[]（机械可抽字段 + `source_file`）。填这里。"""
    # 示例（占位逻辑，勿照抄）：每行非空文本产出一条
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--app", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root 不是目录: {root}", file=sys.stderr)
        return 2

    items: list[dict] = []
    source_files: list[str] = []
    for f in iter_files(root, args.app):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = f.relative_to(root).as_posix()
        got = extract(text, rel)
        if got:
            source_files.append(rel)
            items.extend(got)

    out = {"category": CATEGORY, "items": items,
           "source_files": sorted(source_files), "adapter_version": VERSION}
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{CATEGORY}] {len(items)} 条 / {len(source_files)} 源文件 -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
