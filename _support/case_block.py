#!/usr/bin/env python3
"""atlas 共享内核 —— 用例分块（`atlas-case` 块体）单源解析器。

**为什么存在**（2026-10-12 单源批，ATLAS-UPSTREAM #198）：本函数原在
`scripts/gen_e2e_scripts.py` 与 `validators/validate_e2e_index.py` 两处**逐字节相同**地
各存一份（生成器 + 索引校验器），是「无共享通道 ⇒ 就地复制」结构的第一现场。
本模块把口径收敛为唯一实现；两消费者经 `_support.siblings.load_module("case_block")` 取用。

- 语义 = 原两处实现逐字节等价（键空间 / 「- 」行归集 / 标量键）。
- `落点`（2026-10-16，issue #20）：应然 id 承载元素的**声明式落点**（`<tid> <相对项目根的路径>`），
  由 `validators/validate_testids.py` 的「应然落点」门校验（文件存在 + 文件内可解析到该 id）。
- `会话`（2026-10-16，issue #13）：**宿主注入型会话前提**（`<键>=<值>`），由生成器在首屏导航前
  经 `addInitScript` 写进 `sessionStorage`（契约 `rings/e2e/reference.md` §5.5）。
- `守卫`（2026-10-16，issue #23）**是标量键，**不**入本元组**（同 `id` / `intent` / `auth` 的形态）：
  值 = 元素齐全守卫导航用的具体路径（可选）；缺省 = 页面表 `路由` 列。带参页面用
  （`路由` 列按 §3.1 只有业务段，不可直接导航），见 `rings/e2e/reference.md` §5.5。
  **入本元组 = 被当成数组**（本元组内每个键都初始化为 list）——实隔时踩过：
  `case.get("守卫").strip()` 报 `'list' object has no attribute 'strip'`。
- 纯标准库（契约 `rings/e2e/reference.md` §8.3）。
"""
from __future__ import annotations

# 键空间 = `rings/e2e/reference.md` §5.1 用例块字段（消费方按需读取）。
_BLOCK_KEYS = ("pages", "precondition", "seed", "mock", "step", "expected", "testid", "落点", "会话")


def parse_block(body: str) -> dict:
    """解析 `atlas-case` 块体 → dict（键见 `_BLOCK_KEYS`）。

    语义（与原两处实现逐字一致）：`- ` 开头的行归当前键；`<key>:` 开新键（键在键空间内）；
    `key: value` 带值形态追加一条；键空间外的 `key: value` 以标量入表。
    """
    d: dict = {k: [] for k in _BLOCK_KEYS}
    key = None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("- ") and key:
            d[key].append(s[2:].strip())
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            k, v = k.strip(), v.strip()
            if k in d:
                key = k
                if v:
                    d[k].append(v)
            else:
                d[k] = v
                key = None
    return d
