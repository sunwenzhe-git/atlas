#!/usr/bin/env python3
"""DR4 **口径 B** —— `bugs.md` 同根段聚类（族规模 × 活跃窗）的**单源实现**。

口径正文见 `duty-review/README.md` §2「DR4 复发」的口径 B；本文件只承载它的机器可读形态。
两个消费者：`scripts/duty_signals.sh`（巡检信号，只读打印）与 `tests/test_duty_bug_families.py`
（形状钉 + 喂坏输入钉）——**不造第二份**（本仓 `shared/single-source.md` §2）。

**为什么单独立件**：口径 B 的输入是**人工写的** `bugs.md`（分段 = 按环归档）。解析形状一旦与
文件形状漂开，最坏结果是**静默归零**（每段都数成 0 ⇒ 永不升室），而那恰好会让本机制要治的
「复发靠撞见」原封不动地回来。故：解析逻辑可被测试直接调，形状漂 ⇒ 钉红。

铁则：**全程只读**（不落任何文件 —— 巡检铁则，`README.md` §1）；纯标准库。
"""
from __future__ import annotations

import datetime
import pathlib
import re
import subprocess
import sys

WINDOW_DAYS = 30
UPSTREAM = "duty-review/bugs.md"


def parse_sections(text: str) -> list[dict]:
    """按 `## ` 分段；每段收 `#NN` 去重集与段内日期取证。

    * `ids` —— 段内出现的 `#NN` 去重集（**上界近似**：条目、同根归纳行、交叉引用都算）
    * `has_root` —— 段首是否有「同根归纳」行（族锚）
    * `last_date` —— 段内出现的最大 `YYYY-MM-DD`（无 ⇒ 空串）
    """
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            cur = {"name": m.group(1).strip(), "ids": set(), "has_root": False, "last_date": ""}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("- 同根归纳"):
            cur["has_root"] = True
        cur["ids"].update(re.findall(r"#(\d+)", line))
        for d in re.findall(r"20\d\d-\d\d-\d\d", line):
            cur["last_date"] = max(cur["last_date"], d)
    return sections


def families(text: str, today: datetime.date | None = None) -> list[dict]:
    """给每段判「升室候选 / 族已静默 / 无同根归纳 / 案数不足」。

    **升室 = 同根归纳在案 ∧ 案数（上界）≥3 ∧ 段内最近日期在近 `WINDOW_DAYS` 天**（三项齐 =
    这族**近来还在长**）。只满足前两项 ⇒ 「族已静默」：同一族清算完还天天喊，就是把红灯
    训练成噪声（本仓旧教训，故设活跃窗）。
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
        out.append({**s, "count": n, "active": active, "verdict": verdict, "cutoff": cutoff})
    return out


def render(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(无 duty-review/bugs.md，跳过)"]
    lines = [f"(活跃窗 = 近 {WINDOW_DAYS} 天，cutoff {rows[0]['cutoff']}；"
             "日期取证 = 段内文本里的日期，无日期 ⇒ 视为已静默)"]
    for r in rows:
        lines.append(
            f"{'同根归纳在案' if r['has_root'] else '无同根归纳  '} | 案数(上界)={r['count']:<3}"
            f" | 最近日期={r['last_date'] or '-':<10} | {r['verdict']:<8} | {r['name']}"
            + ("   <== DR4 口径 B 候选（>=3 案 且 近 30 天有新案）" if r["verdict"] == "升室候选" else ""))
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
