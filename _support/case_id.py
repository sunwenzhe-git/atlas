#!/usr/bin/env python3
"""atlas 共享内核 —— 用例 ID 文法单源。

**为什么存在**：`E2E-<PAGE>-NNN` 的文法体此前在 `validators/validate_e2e_index.py`
与 `scripts/e2e_console.py` 两处各存一份（各自只支持单段 `PAGE`），是
「无共享通道 ⇒ 就地复制」结构的又一现场（同类第一现场见 `_support/case_block.py`）。
本模块把**文法体**收敛为唯一实现；两消费者经 `_support.siblings.load_module("case_id")` 取用。

- **正文归 `rings/e2e/reference.md` §5.3**（含 `PAGE` 段的推导规则）；本模块只承载它的**机器可读形态**。
- **只导出文法体，不导出锚点**：整格判定（`^…$`）与「从生成产物取 ID 前缀」是两个不同的判定，
  锚点属消费者语义，各留。
- **纯标准库**（契约 `rings/e2e/reference.md` §8.3）。
"""
from __future__ import annotations

# 文法体：`E2E` + 一个或多个大写段（连字符分隔）+ 三位定长尾号。
# `PAGE` 段的推导 = slug 大写原文、连字符原样保留（`rings/e2e/reference.md` §5.3）。
GRAMMAR = r"E2E-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}"

# 取用者登记表（包根相对 POSIX 路径）。
# 新增取用者必须登记在此 —— `tests/test_tools.py` 的普查钉按本表对账：
# 「含 case-ID 文法 token 的处所 ⊆ 本表」，未登记即红。
CONSUMERS = (
    "validators/validate_e2e_index.py",
    "scripts/e2e_console.py",
)
