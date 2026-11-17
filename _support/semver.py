#!/usr/bin/env python3
"""semver 比较单源（2026-11-17 P1 / 2A）。

背景：此前有两份 `semver_lt`——内核 `_support/solution.py` 一份、CLI
`scripts/atlas_solution.py` 一份；两份在**不可解析输入**上结论相反（内核判
"不小于"，CLI 退回字符串比较），同一组输入可以给出相反答案。本模块是唯一实现。

`lt(a, b)` 的不可判定语义 = **False**（fail-closed）：

- 对「宽限/放行」类门（CLI 的 `--allow-dangling-acs` 版本门控）：False ⇒ 不放行；
- 对「拒绝」类门（内核 schema 门）：调用方都在**空版本**处先短路（`if reader and ...`），
  非空但不可解析的值不应被当成"新版本"继续放宽——宁可判不出就不放行。

不返回"看起来合理"的结果，也不抛异常：调用方需要的是布尔门，不是排序。

注意：`scripts/release.py` 另有 `parse_semver`（5 元组、带预发布序号、用于版本推导），
与比较门不是同一职责，未并入本模块。
"""
from __future__ import annotations

import re

_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse(raw: str) -> tuple[tuple[int, int, int], tuple[str, ...]] | None:
    """`((major, minor, patch), (pre, ...))`；不可解析 ⇒ None（含装配摘要形态）。"""
    m = _SEMVER_RE.match((raw or "").strip())
    if m is None:
        return None
    pre = tuple(m.group(4).split(".")) if m.group(4) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), pre


def _cmp_pre(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """semver §11 预发布比较：数字段按数值、数字 < 字母、前缀相同则更短更小。"""
    if a == b:
        return 0
    if not a:
        return 1          # 正式版 > 预发布
    if not b:
        return -1
    for x, y in zip(a, b):
        if x == y:
            continue
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            return -1 if int(x) < int(y) else 1
        if xn != yn:
            return -1 if xn else 1
        return -1 if x < y else 1
    return -1 if len(a) < len(b) else 1


def lt(a: str, b: str) -> bool:
    """`a < b`；任一不可解析（空串、非版本串、装配摘要）⇒ **False**（fail-closed）。"""
    pa, pb = parse(a), parse(b)
    if pa is None or pb is None:
        return False
    if pa[0] != pb[0]:
        return pa[0] < pb[0]
    return _cmp_pre(pa[1], pb[1]) < 0
