#!/usr/bin/env python3
r"""DR4 **口径 B** —— `bugs.md` 同根段聚类（族规模 × 活跃窗）的**单源实现**。

口径正文见 `duty-review/README.md` §2「DR4 复发」的口径 B 与「条目字段制式」小节
（2026-10-26，D154 / `proposals/RFC-20261026-04` v2 + 评审 `proposals/REVIEW-20261026-07`）；
本文件只承载它的机器可读形态。两个消费者：`scripts/duty_signals.sh`（巡检信号，只读打印）与
`tests/test_duty_bug_families.py`（形状钉 + 喂坏输入钉）——**不造第二份**（本仓
`shared/single-source.md` §2）。

**条目字段制式**（D154 落地）：条目行尾允许一个全角尾缀块 `〔…〕`，键以 `｜` 分隔，闭集键 =
`日期`（必填，`20\d\d-\d\d-\d\d`）/ `状态`（`开放`｜`已修·待复验`｜`已出库`）/ `族`（跨段族标识，
**只解析记录、不参与判据**）/ `证`（D131 证明件锚；优先级 = DESIGN.md D 决策行 > M 变异号/
钉名 > 留档路径辅注）。坏形状（未知键 / 重复键 / 值空 / 值域外 / 日期形态非法 / 缺必填 / 尾缀
不闭合）⇒ **运行面 WARN + 按无字段回退**，不静默（对齐「静默吸收」教训族）。

**日期来源分层**（判据三项与「案数上界」计量基准不变——`duty-review/README.md` §2 DR4 /
`DESIGN.md` D102；活跃窗语义不变，只改日期取数面）：带字段条目 ⇒ 字段日期；无字段条目行 ⇒
行内日期；**其余行（段头 / 同根归纳行 / 收尾说明 / 无害正文）不再是日期来源**。

**为什么单独立件**：口径 B 的输入是**人工写的** `bugs.md`（分段 = 按环归档）。解析形状一旦与
文件形状漂开，最坏结果是**静默归零**（每段都数成 0 ⇒ 永不升室），而那恰好会让本机制要治的
「复发靠撞见」原封不动地回来。故：解析逻辑可被测试直接调，形状漂 ⇒ 钉红。

铁则：**全程只读**（不落任何文件 —— 巡检铁则，`README.md` §1）；纯标准库。

变异证明 **M91**（计数正则退行首 ⇒ 上界塌 ≤1 ⇒ 钉红）、**M157a**（摘分层日期来源 ⇒ 回全行
散文日期 ⇒「陈旧说明不抬窗」正向钉红）、**M157b**（摘坏形状 WARN ⇒ 钉红）。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import subprocess
import sys

WINDOW_DAYS = 30
UPSTREAM = "duty-review/bugs.md"

HEADER_RE = re.compile(r"^##\s+(.+)$")
ID_RE = re.compile(r"#(\d+)")
DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")
TAIL_DATE_RE = re.compile(r"^20\d\d-\d\d-\d\d$")
BRACKET_OPEN, BRACKET_CLOSE, SEP = "〔", "〕", "｜"
FIELD_KEYS = ("日期", "状态", "族", "证")
STATUS_VALUES = ("开放", "已修·待复验", "已出库")


def _tail_fields(line: str) -> tuple[str, dict[str, str], str, str]:
    """拆条目行尾缀字段块（D154 制式）。

    返回 `(state, fields, reason, body)`：
    * `none` —— 行无尾缀；`body` = 原行（散文日期来源）；
    * `ok` —— 尾缀合法；`fields` = 键→值；`body` = 摘尾后的条目文本（精确病案 id 的取数域；
      该行散文日期**不再**参与活跃窗——字段日期是唯一来源）；
    * `bad` —— 形状坏（WARN 源，按无字段回退）；`body` = 摘尾后的文本（散文日期回退源；
      坏尾缀内的内容不参与任何取数）。
    """
    if BRACKET_OPEN not in line:
        return "none", {}, "", line
    if line.count(BRACKET_OPEN) != 1 or not line.endswith(BRACKET_CLOSE):
        return "bad", {}, "尾缀块不闭合", line[: line.index(BRACKET_OPEN)]
    head = line[: line.index(BRACKET_OPEN)]
    content = line[line.index(BRACKET_OPEN) + 1: -1]
    fields: dict[str, str] = {}
    for part in content.split(SEP):
        part = part.strip()
        if not part:
            return "bad", {}, "字段尾缀含空键", head
        key, _, value = part.partition(" ")
        key, value = key.strip(), value.strip()
        if key not in FIELD_KEYS:
            return "bad", {}, f"未知字段键「{key}」", head
        if key in fields:
            return "bad", {}, f"重复字段键「{key}」", head
        if not value:
            return "bad", {}, f"字段「{key}」值为空", head
        fields[key] = value
    if "日期" not in fields:
        return "bad", {}, "缺必填字段「日期」", head
    if not TAIL_DATE_RE.fullmatch(fields["日期"]):
        return "bad", {}, f"「日期」形态非法：{fields['日期']}", head
    if "状态" in fields and fields["状态"] not in STATUS_VALUES:
        return "bad", {}, f"「状态」值域外：{fields['状态']}", head
    return "ok", fields, "", head


def parse_sections(text: str) -> list[dict]:
    """按 `## ` 分段；每段收 `#NN` 去重集与**分层**日期取证。

    * `ids` —— 段内出现的 `#NN` 去重集（**上界近似**，判据计量基准不变：条目、同根归纳行、
      交叉引用都算）
    * `has_root` —— 段内是否有「同根归纳」行（族锚；**实现是段内任意位置**，非段首）
    * `last_date` —— **分层来源**最大日期（D154）：带字段条目只用字段日期；无字段条目行用
      行内日期；其余行（段头 / 归纳行 / 收尾说明 / 正文）不再参与。无 ⇒ 空串。
    * `exact_ids` —— 带字段条目自身病案 id 去重集（`render` 显示列输入；**不参与判据**——
      计量升格须按 DR1 另案，`RFC-20261026-04` §2.2）
    * `warns` —— 坏形状条目摘录（运行面 WARN 源；`render` 打印，不静默）
    """
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            cur = {"name": m.group(1).strip(), "ids": set(), "has_root": False,
                   "last_date": "", "exact_ids": set(), "warns": []}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("- 同根归纳"):
            cur["has_root"] = True
            cur["ids"].update(ID_RE.findall(line))  # 上界含归纳行自带的 #NN（README 口径 B 原语义）
            continue
        cur["ids"].update(ID_RE.findall(line))
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        state, fields, reason, body = _tail_fields(stripped)
        if state == "bad":
            cur["warns"].append(f"{reason}（已按无字段回退）")
        elif state == "ok":
            cur["exact_ids"].update(ID_RE.findall(body))
        dates = [fields["日期"]] if state == "ok" else DATE_RE.findall(body)
        for d in dates:
            cur["last_date"] = max(cur["last_date"], d)
    return sections


def families(text: str, today: datetime.date | None = None) -> list[dict]:
    """给每段判「升室候选 / 族已静默 / 无同根归纳 / 案数不足」。

    **升室 = 同根归纳在案 ∧ 案数（上界）≥3 ∧ 段内最近日期在近 `WINDOW_DAYS` 天**（三项齐 =
    这族**近来还在长**）。只满足前两项 ⇒ 「族已静默」：同一族清算完还天天喊，就是把红灯
    训练成噪声（本仓旧教训，故设活跃窗）。判据三项与计量基准与 D154 前逐字一致。
    """
    day = today or datetime.date.today()
    cutoff = (day - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    out = []
    for s in parse_sections(text):
        n = len(s["ids"])
        active = bool(s["last_date"]) and s["last_date"] >= cutoff
        if not s["has_root"]:
            verdict = "无同根归纳"
        elif n < 3:
            verdict = "案数不足"
        elif active:
            verdict = "升室候选"
        else:
            verdict = "族已静默"
        out.append({**s, "count": n, "active": active, "verdict": verdict, "cutoff": cutoff,
                    "exact": len(s["exact_ids"]) or None})
    return out


def render(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(无 duty-review/bugs.md，跳过)"]
    lines = [f"(活跃窗 = 近 {WINDOW_DAYS} 天，cutoff {rows[0]['cutoff']}；"
             "日期取证 = 带字段条目的字段日期 ∪ 无字段条目行内日期，其余行不参与；"
             "无日期 ⇒ 视为已静默)"]
    for r in rows:
        exact = f" | 精确病案数={r['exact']}" if r.get("exact") else ""
        lines.append(
            f"{'同根归纳在案' if r['has_root'] else '无同根归纳  '} | 案数(上界)={r['count']:<3}{exact}"
            f" | 最近日期={r['last_date'] or '-':<10} | {r['verdict']:<8} | {r['name']}"
            + ("   <== DR4 口径 B 候选（>=3 案 且 近 30 天有新案）" if r["verdict"] == "升室候选" else ""))
        for w in r.get("warns", []):
            lines.append(f"    WARN 条目字段形状：[{r['name']}] {w}")
    return lines


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        path = pathlib.Path(argv[0])
    else:
        try:
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True).stdout.strip()
        except Exception:
            top = ""
        path = pathlib.Path(top or ".") / UPSTREAM
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    print("\n".join(render(families(text) if text else [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
