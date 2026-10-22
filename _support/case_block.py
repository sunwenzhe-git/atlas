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
- **行内注释口径（2026-10-16，issue #R1）**：**标量键**的值经 `strip_inline_comment` 剥掉行内
  `#` 注释（取用 `_support/stack_profile.py` 的**同一函数对象**，经包内 bootstrap；不得复制
  第二份等价实现）；**列表项逐字节不变**（`d[key].append(s[2:].strip())`）。
  **为什么两支持不同口径**（下一轮别把这里当「口径分裂」再改回去）：
  ① **标量键**的值被下游当作**代码字面量**发射（`scripts/gen_e2e_scripts.py` 的 `guard_url`
  → `page.goto('<值>')`）——注释会成为可执行代码的一部分；② **列表项**有下游剥注释通道
  （`scripts/gen_e2e_scripts.py` 的 `parse_line` → `line.partition("#")`，docstring 明写
  「机器只看 `#` 之前」），且列表项的 `#` 是**给人读的 note**，必须先原样交给该通道（例如
  `expected:` 里 `#` 后的 `initial:` 理由说明）。**标量剥、列表项不剥**是刻意设计。
- 纯标准库（契约 `rings/e2e/reference.md` §8.3）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 随包内核引导（`_support/`，2026-10-16，issue #R1）：本模块**在包内**取用
# `_support/stack_profile.strip_inline_comment`。只**引用函数对象**，不新增定义——
# `tests/test_shared_kernel.py::test_definitions_are_single_sourced` 按 `def <name>(` 计数，
# 任何第二处定义（含等价实现）都会红。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402

strip_inline_comment = load_module("stack_profile").strip_inline_comment

# 键空间 = `rings/e2e/reference.md` §5.5 用例块字段（消费方按需读取）。
# `参数`（2026-10-18，`DESIGN.md` D109）：宿主注入型 URL 参数的**键清单**（值内联在 step 的
# `goto` 查询串里）——不在键空间内的键会被按**标量**入表（`key = None`），其后 `- 项` 行跟丢。
# `hash参数`（2026-10-22，HashRouter 场景）：`#` 之后 hash 查询串的**键清单**（值同样内联在
# `goto` 的 hash 查询里）——与 `参数:` 分载体，值来自 `window.location.hash` 的查询段。
# `覆盖维度`（2026-10-21，`DESIGN.md` D130）：前端适配版 C01-C14 场景维度列表。
_BLOCK_KEYS = ("pages", "precondition", "seed", "mock", "step", "expected", "testid", "落点", "会话", "参数", "hash参数", "覆盖维度")


def parse_block(body: str) -> dict:
    """解析 `atlas-case` 块体 → dict（键见 `_BLOCK_KEYS`）。

    语义（与原两处实现逐字一致；**唯一例外** = 键空间外的标量键剥行内注释，见模块 docstring）：
    `- ` 开头的行归当前键；`<key>:` 开新键（键在键空间内）；`key: value` 带值形态追加一条；
    键空间外的 `key: value` 以标量入表（**标量值剥行内 `#` 注释**）。
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
                # 标量键：行内 `#` 注释剥掉（同一函数对象，见模块 docstring 的「为什么两支持不同口径」）。
                d[k] = strip_inline_comment(v)
                key = None
    return d
