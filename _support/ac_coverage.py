#!/usr/bin/env python3
"""共享内核 —— AC 覆盖维度解析（E2E 第 4 列 / 后端列单源）。

D130 的维度 token 口径从 `validate_e2e_index.py` 原样抽出（2026-10-26，D153）：
  * C01-C14 闭集；
  * 区间 `C01-C03` 展开；
  * 中文邻接 `C01正常流` 命中（`\\b` 对 CJK 失效）；
  * 疑似写法 `C99` 由 `looks` 出声。

消费方：
  * `validate_e2e_index.py`：`parse_dims_cell`（纯抽取，行为逐字节一致）；
  * `validate_ac_alignment.py`：`parse_dims_cell`（后端列）+ `parse_dim_token` / `parse_dims_list`（结构化 dims）。

**不负责** PRD 表定位 / E2E 索引解析；`iter_md_tables` 只是通用 Markdown 表切分，
供后端列解析复用，避免第四份表解析器口径漂移（parity 钉见 `tests/test_shared_kernel.py`）。
"""
from __future__ import annotations

import re

DIM_IDS = tuple(f"C{i:02d}" for i in range(1, 15))

_DIM_TOKEN = r"C(?:0[1-9]|1[0-4])"
_DIM_RANGE_RE = re.compile(
    rf"(?<![0-9A-Za-z])({_DIM_TOKEN})\s*[-~至]\s*({_DIM_TOKEN})(?![0-9])"
)
_DIM_CODE_RE = re.compile(rf"(?<![0-9A-Za-z]){_DIM_TOKEN}(?![0-9])")
_DIM_LOOKS_RE = re.compile(r"[Cc]\d{1,2}")
_DIM_EXACT_RE = re.compile(rf"^{_DIM_TOKEN}$")
# 备注/错位列表头扫描用：排除 AC ID 里的 `AC-C01-...`（防把 AC 编号当维度声明）。
_DIM_CLAIM_RE = re.compile(r"(?<!AC-)(?<![0-9A-Za-z])[Cc](\d{1,2})(?![0-9])")


def parse_dims_cell(raw) -> tuple[set[str], bool]:
    """维度单元格文本 → (命中维度集合, 是否含疑似维度写法)。区间展开、中文邻接可命中。"""
    text = str(raw or "")
    dims: set[str] = set()
    for m in _DIM_RANGE_RE.finditer(text):
        lo, hi = int(m.group(1)[1:]), int(m.group(2)[1:])
        if lo > hi:
            lo, hi = hi, lo
        dims |= {f"C{i:02d}" for i in range(lo, hi + 1)}
    dims |= set(_DIM_CODE_RE.findall(text))
    return dims, bool(_DIM_LOOKS_RE.search(text))


def parse_dim_token(raw) -> str | None:
    """精确 token：仅接受 C01-C14；`C01正常流` / `C01C02` / `C99` 一律 None。"""
    text = str(raw or "").strip().strip("`").strip()
    return text if _DIM_EXACT_RE.fullmatch(text) else None


def parse_dims_list(value) -> tuple[set[str], list[str], bool]:
    """结构化 `dims=` → (命中集合, 坏 token 列表, 形态是否受支持)。

    支持 list / tuple / 逗号（中英文）分隔字符串；元素必须是 C01-C14 精确 token。
    set / 变量 / 非字符串元素 ⇒ shape_ok=False（调用方 WARN「形态不支持」）。
    """
    if isinstance(value, str):
        items = [x for x in re.split(r"[,，\s]+", value.strip()) if x]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return set(), [], False

    dims: set[str] = set()
    bad: list[str] = []
    for item in items:
        if not isinstance(item, str):
            return set(), [], False
        token = parse_dim_token(item)
        if token:
            dims.add(token)
        elif item.strip():
            bad.append(item)
    return dims, bad, True


def split_md_row(line: str) -> list[str]:
    """单行 Markdown 表 → 单元格（去首尾 `|`，逐格 strip）。"""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def iter_md_tables(text: str):
    """逐张产出 (header, rows)；分隔行剔除。口径与 `validate_e2e_index.tables()` 一致。"""
    block: list[list[str]] = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            block.append(split_md_row(line))
        elif block:
            yield block[0], [r for r in block[1:] if not all(set(c) <= set("-: ") for c in r)]
            block = []
    if block:
        yield block[0], [r for r in block[1:] if not all(set(c) <= set("-: ") for c in r)]


def strip_md_cell(raw) -> str:
    """表头 / AC 单元格去空白与反引号。"""
    return str(raw or "").strip().strip("`").strip()


def has_dim_claim(raw) -> bool:
    """单元格是否含维度形态（备注/错位表头的疑似扫描；排除 AC ID 的 `AC-` 前缀）。"""
    return bool(_DIM_CLAIM_RE.search(str(raw or "")))


def unknown_dim_tokens(raw) -> list[str]:
    """从散文单元格里找出**非 C01-C14** 的维度形态 token（如 `C99` / `C15`）。"""
    out: list[str] = []
    for m in _DIM_CLAIM_RE.finditer(str(raw or "")):
        token = f"C{int(m.group(1)):02d}"
        if token not in DIM_IDS and token not in out:
            out.append(token)
    return out

