#!/usr/bin/env python3
"""atlas 校验器 —— 架构决策记录（ADR）长效资产守卫（2026-10-13）。

守一件事：
  项目级长效架构决策唯一落地于 `资产根/adr/NNNN-<slug>.md`（资产根默认 `product/`，
  由项目根 `atlas.config.yaml` 的 `layout.assets_root` 解析）。
  规范文档形态，保障状态合法性、决策确定性与版本演进追溯。

判定（三态 + WARN）：
  - 无 `资产根/adr/` 目录或目录为空 ⇒ SKIP（尚未创建任何 ADR，非失败）。
  - 有 ADR 文件：
      * 编号唯一：无同号异名冲突（0001-foo ⇔ 0001-bar）。
      * Frontmatter 合法：status 必须属于 {proposed, accepted, superseded, deprecated}。
      * 演进链闭环：status 为 superseded 时必须声明 superseded_by 且指向有效 ADR。
      * 章节完整：具备 Context、Decision、Consequences 三大核心章节。
      * 内容非空：accepted 状态的 ADR 其 Decision 章节不得为空。
  - 缺陷以 WARN 呈现（初期软性巡检，不阻断正常构建）；严重损坏时 FAIL。

显式盲区（不查）：
  - 编号连续性（跳号合法，支持按需立项）。
  - 日期时序与提交历史是否一致。
  - 决策的工程合理性（语义层面由人类与评审智能体承担）。

CLI：`python3 validate_adr.py --root <项目根> [--json]`
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402

ADR_FILENAME_PATTERN = re.compile(r"^(\d{4})-[a-z0-9_-]+\.md$", re.IGNORECASE)
VALID_STATUSES = {"proposed", "accepted", "superseded", "deprecated"}


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        statuses = [c["status"] for c in self.checks]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        if statuses and all(s == "SKIP" for s in statuses):
            return "SKIP"
        return "PASS"

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def parse_frontmatter(text: str) -> dict[str, str]:
    """提取极简 YAML frontmatter 键值对。"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    res = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            res[k.strip()] = v.strip().strip("'\"")
    return res


def extract_section(text: str, section_kw: str) -> str | None:
    """提取指定标题关键字的小节内容。"""
    pattern = re.compile(rf"^##\s+.*(?:{section_kw}).*$", re.MULTILINE | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], re.MULTILINE)
    if next_match:
        return text[start : start + next_match.start()].strip()
    return text[start:].strip()


def validate_adr(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    adr_dir = lay.adr_dir

    if not adr_dir.exists() or not adr_dir.is_dir():
        res.add("adr_dir_exists", "SKIP",
                f"前置未声明（未就绪，非失败）：无 {lay.print_value('adr')}/")
        return res

    files = [f for f in adr_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    adr_files = [f for f in files if ADR_FILENAME_PATTERN.match(f.name)]

    if not adr_files:
        res.add("adr_files_present", "SKIP", f"尚无 ADR 文件（目录为空或无 NNNN-slug.md 形态文件）")
        return res

    # 1. 编号唯一性检查
    ids_map: dict[str, list[str]] = {}
    for f in adr_files:
        m = ADR_FILENAME_PATTERN.match(f.name)
        if m:
            seq = m.group(1)
            ids_map.setdefault(seq, []).append(f.name)

    conflicts = [f"{seq}: {', '.join(names)}" for seq, names in ids_map.items() if len(names) > 1]
    if conflicts:
        res.add("adr_id_uniqueness", "WARN", f"ADR 编号冲突（同号撞号）：{'; '.join(conflicts)}")
    else:
        res.add("adr_id_uniqueness", "PASS", f"全量 {len(adr_files)} 篇 ADR 编号严格唯一")

    all_ids = set(ids_map.keys())

    # 2. 逐文件内容与状态校验
    superseded_graph: dict[str, list[str]] = {}
    for f in sorted(adr_files):
        m = ADR_FILENAME_PATTERN.match(f.name)
        seq = m.group(1) if m else f.stem.split("-")[0]
        try:
            content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            res.add(f"file_encoding:{f.name}", "FAIL", "编码错误：非 UTF-8 编码")
            continue

        fm = parse_frontmatter(content)
        if not fm:
            res.add(f"frontmatter:{f.name}", "WARN", "缺失有效 YAML Frontmatter 头部")
            continue

        # 状态检查
        status = fm.get("status", "").lower()
        if status not in VALID_STATUSES:
            res.add(f"status_validity:{f.name}", "WARN", f"状态 '{status}' 非法，必须属于 {VALID_STATUSES}")
        else:
            if status == "superseded":
                sub_by = fm.get("superseded_by", "")
                sub_match = re.search(r"\d{4}", sub_by)
                if not sub_match or sub_match.group(0) not in all_ids:
                    res.add(f"superseded_chain:{f.name}", "WARN", f"superseded 状态未指向有效的新 ADR 编号 (指向: '{sub_by}')")
                else:
                    superseded_graph.setdefault(seq, []).append(sub_match.group(0))

        # 关键章节存在性检查
        has_context = bool(re.search(r"^##\s+.*(Context|背景)", content, re.M | re.I))
        has_decision = bool(re.search(r"^##\s+.*(Decision|裁决|决策)", content, re.M | re.I))
        has_consequences = bool(re.search(r"^##\s+.*(Consequences|影响|后果)", content, re.M | re.I))

        missing_sections = []
        if not has_context:
            missing_sections.append("Context/背景")
        if not has_decision:
            missing_sections.append("Decision/裁决")
        if not has_consequences:
            missing_sections.append("Consequences/影响")

        if missing_sections:
            res.add(f"sections:{f.name}", "WARN", f"缺失必要章节：{', '.join(missing_sections)}")
        else:
            # 若已 Accepted，检查 Decision 正文是否非空占位
            if status == "accepted":
                sec_text = extract_section(content, "Decision|裁决|决策") or ""
                # 过滤注释与占位符
                cleaned = re.sub(r"\[必填.*?\]", "", sec_text).strip()
                if not cleaned:
                    res.add(f"decision_content:{f.name}", "WARN", "已 Accepted 的 ADR 决策章节内容为空或残留占位符")
                else:
                    res.add(f"content:{f.name}", "PASS", "章节完整且裁决内容充实")
            else:
                res.add(f"content:{f.name}", "PASS", "章节完整")

    # 3. 演进链有向图成环检测 (Cycle Detection)
    adj: dict[str, list[str]] = superseded_graph
    color: dict[str, int] = {}
    cycles: list[str] = []

    def _dfs(u: str, stack: list[str]) -> None:
        color[u] = 1
        for v in adj.get(u, []):
            if color.get(v) == 1:
                cycles.append("->".join(stack[stack.index(v):] + [v]))
            elif color.get(v) is None:
                _dfs(v, stack + [v])
        color[u] = 2

    for n in sorted(adj):
        if color.get(n) is None:
            _dfs(n, [n])

    seen_cycles = set()
    for c in cycles:
        if c not in seen_cycles:
            seen_cycles.add(c)
            res.add("adr_cycle_detected", "WARN",
                    f"演进链存在循环引用环路: {c}"
                    "（F36 修复指令：把最新一代的 `superseded_by` 指向**移出环外**的有效编号，"
                    "或撤销现行非终态取代行并登记变更；改后复跑本器复绿，收口清单有对应行）")

    return res


def main() -> int:
    parser = argparse.ArgumentParser(description="atlas 架构决策记录（ADR）校验器")
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    res = validate_adr(args.root.resolve())

    if args.json:
        print(json.dumps({
            "ok": res.ok,
            "status": res.status,
            "checks": res.checks
        }, ensure_ascii=False, indent=2))
    else:
        for c in res.checks:
            detail = f" —— {c['detail']}" if c.get("detail") else ""
            print(f"[{c['status']}] {c['check']}{detail}")
        print(f"\nFinal status: {res.status}")

    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
