#!/usr/bin/env python3
"""atlas 共享内核 —— `product/stack-profile.yaml` 单源解析器。

**为什么存在**（2026-10-12，`3507 BT` 后自审批 / ATLAS-UPSTREAM #198）：
同一段手写 YAML 解析此前在三个消费者里各存一份——`gen_e2e_scripts.parse_profile`（最全）、
`validate_stack_profile.parse_profile`（B197-1 才补齐对齐，登记行原文「对齐 gen 同款」）、
`validate_ac_alignment.load_stack_profile`（最简版）——**解析器漂移已实际发生一次**。
本模块把口径收敛为唯一实现；消费者一律经 `_support.siblings.load_module("stack_profile")` 取用。

- 语义基线 = 原 `gen_e2e_scripts.parse_profile`（最完整的实现）。
- 解析面 = atlas 契约消费的字段（`shared/stack-profile.md` §2）；**不是通用 YAML 解析器**——
  只为 atlas 自产 profile 的文件形态服务（顶层标量 / 顶层段 / `apps:` 列表 / 二三级子块）。
- 纯标准库（契约 `rings/e2e/reference.md` §8.3）；判定面（白名单 / 枚举）不在此，各消费者自持。
"""
from __future__ import annotations

import re

# 顶层段的键空间默认值（`shared/stack-profile.md` §2）。消费者按需读取，多余键被忽略。
_DEFAULTS: dict = {
    "product": None, "origin": None, "apps": [], "adapters": {},
    "prototype": {}, "e2e": {}, "graph": None, "backend_test": None,
}
# 值 = 空映射的顶层段（解析时直接初始化 dict，供后续缩进行填充）
_DICT_SECTIONS = ("graph", "backend_test")
# `e2e` 下「缩进 2 且值为空」开子块的键（§2 e2e 表；`app_login` / `seed` / `mock`）
_E2E_SUBBLOCK_KEYS = ("app_login", "seed", "mock")


def strip_inline_comment(line: str) -> str:
    """去掉 YAML 行内注释：`#` 前有空白（或行首）且在引号外时截断。

    手写解析器必须自己处理 —— 否则 `vault: /path   # 说明` 会把注释当成值的一部分。
    与 `validate_stack_profile` 既有口径逐字一致（收敛前它们各自维护同一实现）。
    """
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def yaml_scalar(raw: str):
    """把 YAML 标量转成 Python 值：空 / null 家族 → None，带引号则去引号。"""
    v = raw.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return v[1:-1]
    if v in ("", "null", "Null", "NULL", "~", "none", "None"):
        return None
    return v


def parse_profile(text: str) -> dict:
    """解析 stack-profile 全文 → dict（键空间见 `_DEFAULTS`）。"""
    data: dict = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                  for k, v in _DEFAULTS.items()}
    data["adapters"] = {}
    section = None
    cur = None
    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            # 非缩进行 = 顶层：`key:` 开段；`key: value` 是标量并**结束**当前段
            # （不结束的话，段头之后的顶层标量会被当上一段的子键吞掉——旧 bug 实证）。
            if s.endswith(":"):
                section = s[:-1].strip()
                if section in _DICT_SECTIONS:
                    data[section] = {}
                cur = None
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = yaml_scalar(v)
                section = None
                cur = None
            continue
        if section == "apps":
            m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
            if m:
                cur = {"name": yaml_scalar(m.group(1))}
                data["apps"].append(cur)
                continue
            m = re.match(r"^\s+(path|kind|role|stack):\s*(.*?)\s*$", line)
            if m and cur is not None:
                cur[m.group(1)] = yaml_scalar(m.group(2))
        elif section in ("adapters", "prototype", "e2e", "backend_test") \
                or (section == "graph" and isinstance(data["graph"], dict)):
            m = re.match(r"^\s+([\w.-]+):\s*(.*?)\s*$", line)
            if m:
                if section == "graph":
                    data["graph"][m.group(1)] = yaml_scalar(m.group(2))
                    continue
                indent = len(line) - len(line.lstrip())
                key, v = m.group(1), yaml_scalar(m.group(2))
                # e2e 子段（§B101 / B197-1 / §5.8）：「缩进 2 且值为空」开子块，
                # 更深缩进键归子 dict（旧实现全扁平化 ⇒ `seed.mode` 被误读成 e2e 顶层键）。
                if section == "e2e" and key in _E2E_SUBBLOCK_KEYS and indent == 2 and v is None:
                    data[section].setdefault(key, {})
                    cur = key
                    continue
                if cur is not None and indent > 2:
                    data[section][cur][key] = v
                    continue
                cur = None
                data[section][key] = v
    return data
