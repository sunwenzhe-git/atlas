#!/usr/bin/env python3
"""atlas 影响面基准报告器 —— 每单需求的机器侧影响面预测（atlas-apply §4 的结构证据之一）。

设计共识（2026-10-05 图谱批 1）：

* **advisory 附件，不是门**：本报告落 `.trellis/tasks/<需求ID>/impact.json|md`，
  agent 推导影响面时**先读本报告再做语义判断**；对账门（预测集 vs 实际 diff）属批 2，
  本批只产基准、不判罚。
* **确定性**：分层 BFS（一跳 = 直接会坏 L1，二跳 = 间接 L2，三跳 = 传递 L3，深度封顶），
  全查询 ORDER BY、输出无时间戳——同代码态重跑字节一致（对账门的存在前提）。
* **用前现刷**：生成前 `ensure_index()`（图谱批纪律，`adapters/_graph.py`）。
* **三态**：profile 未声明 graph 段 / cgc 不可用 ⇒ 退出码 3 + `not_ready` JSON
  （前置未声明，显式可见跳过；同 `gen_e2e_scripts` 先例）；输入缺失 ⇒ 退出码 1（用法错）。

用法：
    python3 impact_report.py --root <项目根> --task <需求ID> \
        [--symbols a,b] [--paths x.py,y.ts] [--diff-base <git ref>] [--depth 3]

输入至少给一种（--symbols / --paths / --diff-base）；`--task` 落
`.trellis/tasks/<ID>/`，或用 `--out <目录>` 指定任意落点（冒烟 / 评测用）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = "impact_report"
DEFAULT_DEPTH = 3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters"))
import _graph  # noqa: E402  # 全线唯一后端接触面


def die(msg: str) -> None:
    print(f"ERROR[{SCRIPT}]: {msg}", file=sys.stderr)
    sys.exit(1)


def not_ready(reason: str) -> int:
    print(json.dumps({"status": "not_ready", "reason": reason}, ensure_ascii=False))
    return 3


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        die(f"git {' '.join(args)} 失败: {(p.stderr or '').strip()[:200]}")
    return p.stdout


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--task", default=None, help="需求 ID（= Trellis task id）→ .trellis/tasks/<ID>/")
    ap.add_argument("--out", default=None, help="自定义输出目录（优先于 --task；冒烟/评测用）")
    ap.add_argument("--symbols", default=None, help="逗号分隔的符号名（函数/方法）")
    ap.add_argument("--paths", default=None, help="逗号分隔的文件路径（项目根相对）")
    ap.add_argument("--diff-base", default=None, help="git ref：改动文件 = diff --name-only <ref>（工作树 vs ref，可传区间）")
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH, help="影响面分层深度（默认 3，封顶）")
    args = ap.parse_args()
    if not args.out and not args.task:
        die("--task 与 --out 至少给一个")
    if args.depth < 1 or args.depth > 5:
        die(f"--depth 超界: {args.depth}（1..5；深度再大噪音 > 信号）")
    return args


def collect_seed_symbols(root: Path, args: argparse.Namespace,
                         cfg: dict) -> tuple[list[str], dict, list[str]]:
    """种子符号 = 显式 --symbols ∪ --paths 内定义的符号 ∪ --diff-base 改动文件的符号。"""
    seeds: set[str] = set()
    inputs: dict = {"symbols": [], "paths": [], "diff_base": None}
    touched: list[str] = []

    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
        seeds.update(syms)
        inputs["symbols"] = sorted(syms)
    if args.paths:
        paths = [p.strip().strip("/") for p in args.paths.split(",") if p.strip()]
        for p in paths:
            if not (root / p).exists():
                die(f"--paths 文件不存在: {p}")
        inputs["paths"] = sorted(set(paths))
        touched.extend(inputs["paths"])
    if args.diff_base:
        out = git(root, "diff", "--name-only", args.diff_base)
        changed = sorted({ln.strip() for ln in out.splitlines() if ln.strip()})
        inputs["diff_base"] = args.diff_base
        inputs["diff_files"] = changed
        touched.extend(changed)

    if touched:
        for sym in _graph.symbols_in_files(root, touched, cfg):
            seeds.add(sym["name"])
    return sorted(seeds), inputs, touched


def bfs_layers(root: Path, seeds: list[str], depth: int, cfg: dict) -> list[list[dict]]:
    """分层反查调用方：L1 = 直接调用方；Lk = L(k-1) 的调用方 − 已见。每层按 (path, name) 序。

    排除按**符号名**（与 callers 的 name 级匹配口径一致）：种子同名定义与各层
    已见符号不再入下层，防自引用 / 同名环导致层间重复。
    """
    excluded: set[str] = set(seeds)
    seen: set[tuple[str, str]] = set()
    layers: list[list[dict]] = []
    frontier = list(seeds)
    for _ in range(depth):
        if not frontier:
            break
        found: dict[tuple[str, str], dict] = {}
        for sym in frontier:
            for c in _graph.callers(root, sym, cfg):
                if c["name"] in excluded:
                    continue
                k = (c["name"], c["path"])
                if k in seen:
                    continue
                seen.add(k)
                found[k] = c
        layer = [found[k] for k in sorted(found)]
        if not layer:
            break
        layers.append(layer)
        excluded.update(c["name"] for c in layer)
        frontier = [c["name"] for c in layer]
    return layers


def render(out_dir: Path, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "impact.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# 影响面基准（impact baseline）",
        "",
        f"- 代码态：head `{payload['head'] or '(空仓库)'}`（脏文件 {payload['dirty_files']} 个）",
        f"- 后端：`{payload['backend']}`（用前现刷）",
        f"- 种子输入：symbols={payload['inputs'].get('symbols') or '—'} · "
        f"paths={payload['inputs'].get('paths') or '—'} · "
        f"diff-base={payload['inputs'].get('diff_base') or '—'}",
        "",
        "> advisory 基准，不是门：agent 推导影响面时先读本报告再做语义判断"
        "（apply §4 的结构证据之一）。收口时与实际 diff 对账（批 2 门，本批不判罚）。",
        "",
    ]
    name_by_key: dict[tuple[str, str], str] = {}
    for i, layer in enumerate(payload["layers"], start=1):
        syms = layer["symbols"]
        lines.append(f"## L{i} —— {'直接会坏' if i == 1 else '间接' if i == 2 else '传递（需复查）'}"
                     f"（{len(syms)} 符号 / {len(layer['files'])} 文件）")
        lines.append("")
        for s in syms:
            lines.append(f"- `{s['name']}` — {s['path']}")
            name_by_key[(s["name"], s["path"])] = s["name"]
        if layer["files"]:
            lines.append("")
            lines.append("文件集：")
            for f in layer["files"]:
                lines.append(f"  - {f}")
        lines.append("")
    if not payload["layers"]:
        lines.append("（无调用方命中——注意：无边 ≠ 无人用；框架入口 / 反射 / 跨语言引用"
                     "不在静态调用图内，语义侧仍须人工确认。）")
    (out_dir / "impact.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        die(f"--root 不是目录: {root}")

    cfg = _graph.load_graph_config(root)
    if cfg is None:
        return not_ready("profile 未声明 graph 段（可选能力；声明见 shared/stack-profile.md §2）")
    det = _graph.detect(root, cfg)
    if det is None:
        return not_ready("cgc 不可用（未安装或探测失败）——图谱消费者显式跳过，不静默")

    _graph.ensure_index(root, cfg, version=det["version"])
    seeds, inputs, _touched = collect_seed_symbols(root, args, cfg)
    if not seeds:
        die("输入为空：--symbols / --paths / --diff-base 至少给一种且命中符号"
            "（paths/diff 文件里没有可索引符号时，用 --symbols 显式给）")

    layers = bfs_layers(root, seeds, args.depth, cfg)
    payload = {
        "category": "impact",
        # B191-1（2026-10-07）：种子改动文件入 payload —— 对账器（impact_reconcile）的
        # predicted 集需要它；此前 touched 只活在 collect_seed_symbols 返回值里。
        "touched_files": sorted(_touched),
        "backend": f"cgc@{det['version']}",
        "head": git(root, "rev-parse", "HEAD").strip() if subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=str(root),
            capture_output=True).returncode == 0 else "",
        "dirty_files": sum(1 for ln in git(root, "status", "--porcelain").splitlines() if ln.strip()),
        "depth": args.depth,
        "seeds": seeds,
        "inputs": inputs,
        "layers": [
            {
                "symbols": [{"name": c["name"], "path": c["path"]} for c in layer],
                "files": sorted({c["path"] for c in layer if c["path"]}),
            }
            for layer in layers
        ],
    }
    out_dir = Path(args.out).resolve() if args.out else root / ".trellis" / "tasks" / args.task
    render(out_dir, payload)
    total = sum(len(l["symbols"]) for l in payload["layers"])
    print(f"[{SCRIPT}] 种子 {len(seeds)} → L1..L{len(payload['layers'])} 共 {total} 符号 "
          f"/ {sum(len(l['files']) for l in payload['layers'])} 文件 -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
