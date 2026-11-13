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
    "impl_review": None,
}
# 值 = 空映射的顶层段（解析时直接初始化 dict，供后续缩进行填充）
_DICT_SECTIONS = ("graph", "backend_test", "impl_review")
# `e2e` 下「缩进 2 且值为空」开子块的键（§2 e2e 表；`app_login` / `seed` / `mock` / `review`）
# `query_preset`：宿主注入型 **URL 参数**白名单（2026-10-18，契约 §5.5 / `DESIGN.md` D109），
# 与 `session_preset`（会话载体）对称：同为「前提面」而非「数据态面」。
# `targets`（2026-10-27，多靶场）：具名靶场登记表（`名: 路由` 映射，闭集）；值非空的映射子块，
# 走同一「缩进 2 开子块」通道（`cur = "targets"`），更深缩进的 `名: 路由` 逐条入子 dict。
_E2E_SUBBLOCK_KEYS = ("app_login", "seed", "mock", "review", "session_preset", "query_preset", "targets")


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
    """把 YAML 标量转成 Python 值：null 家族 → None，带引号则去引号。

    null 家族与 YAML 一致：**只认 `null` / `~` / 空**（`2026-10-16 收窄，RFC-20261015-02`
    —— 旧口径把裸 `none` / `None` 也归入 null，超出 YAML；本 RFC 的 `e2e.app_login.mode: none`
    是**字符串取值**（靶场无访问门），必须原样读出，不得被吞成 null ⇒ 缺省判据会把它读成 `real`）。
    """
    v = raw.strip()
    if len(v) >= 2 and v[0] in "'\"" and v[-1] == v[0]:
        return v[1:-1]
    if v in ("", "null", "Null", "NULL", "~"):
        return None
    return v


def parse_profile(text: str) -> dict:
    """解析 stack-profile 全文 → dict（键空间见 `_DEFAULTS`）。

    支持 `e2e` 子段内的**嵌套子块**（2026-11-12，RFC-20261112-01 §4.2：`app_login.probe` 是对象，
    其 `expect_json` 又是 `JSON Pointer → 期望值` 映射，缩进最深到 8 格）；更浅的既有形态
    （`session_preset.keys` 列表、`seed` / `mock` / `review` 平铺）语义不变。
    """
    data: dict = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
                  for k, v in _DEFAULTS.items()}
    data["adapters"] = {}
    section = None
    sub_stack: list[tuple[int, dict]] = []   # e2e 子块嵌套栈：(缩进, 该层 dict)
    cur = None                               # 当前 e2e 子段名（列表项归属）
    pending: tuple[int, str, dict] | None = None   # 空值键候选：(缩进, 键, 父 dict)
    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            # 非缩进行 = 顶层：`key:` 开段；`key: value` 是标量并**结束**当前段
            # （不结束的话，段头之后的顶层标量会被当上一段的子键吞掉——旧 bug 实证）。
            sub_stack, cur, pending = [], None, None
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
        elif section in ("adapters", "prototype", "e2e", "backend_test", "impl_review") \
                or (section == "graph" and isinstance(data["graph"], dict)):
            indent = len(line) - len(line.lstrip())
            # 块列表项（`shared/stack-profile.md` §2 的 `e2e.session_preset.keys` 族，2026-10-16）：
            # 形态 = `<键>:` 后跟若干更深缩进的 `- 项`。惰性物化，对「空值 = None」零行为变化。
            m_item = re.match(r"^\s*-\s*(.+?)\s*$", line)
            if m_item and section == "e2e" and pending is not None and indent > pending[0]:
                bucket = pending[2].get(pending[1])
                if bucket is None:
                    bucket = []
                    pending[2][pending[1]] = bucket
                if isinstance(bucket, list):
                    bucket.append(yaml_scalar(m_item.group(1)))
                continue
            m = re.match(r"^(\s+)(\S[^:]*?):\s*(.*?)\s*$", line)
            if not m:
                continue
            key, raw_value = m.group(2), m.group(3)
            v = yaml_scalar(raw_value)
            is_empty = (raw_value.strip() == "")
            if section == "graph":
                data["graph"][key] = v
                continue
            if section != "e2e":
                data[section][key] = v
                continue
            if indent == 2:
                # e2e 顶层：空值且属于已知子段 ⇒ 开子块；否则是普通标量 / 列表头。
                sub_stack, pending = [], None
                if key in _E2E_SUBBLOCK_KEYS and is_empty:
                    data["e2e"].setdefault(key, {})
                    sub_stack = [(2, data["e2e"][key])]
                    cur = key
                else:
                    cur = None
                    data["e2e"][key] = v
                    pending = (2, key, data["e2e"]) if is_empty else None
                continue
            # indent > 2：e2e 子段内部（可嵌套：app_login → probe → expect_json）。
            while sub_stack and indent <= sub_stack[-1][0]:
                sub_stack.pop()
            parent = sub_stack[-1][1] if sub_stack else data["e2e"]
            if is_empty:
                parent.setdefault(key, None)
                pending = (indent, key, parent)
                continue
            if pending is not None and indent > pending[0]:
                child = pending[2].get(pending[1])
                if not isinstance(child, dict):
                    child = {}
                    pending[2][pending[1]] = child
                sub_stack.append((pending[0], child))
                pending = None
            elif pending is not None:
                pending = None
            while sub_stack and indent <= sub_stack[-1][0]:
                sub_stack.pop()
            target = sub_stack[-1][1] if sub_stack else data["e2e"]
            target[key] = v
    return data


def normalize_mock_prefixes(raw, mode: str = "off") -> tuple[list[str] | None, list[str]]:
    """`e2e.mock.api_prefix` 归一化（2026-11-12）：标量或列表 → 列表 + 逐项错误。

    契约 `rings/e2e/reference.md` §5.8：多前缀是既有能力（生成物 `ATLAS_MOCK_PREFIXES`），
    解析层不得只认标量。返回 `(prefixes, errors)`：

      * mode 未开（off）⇒ `(None, [])`（未启用时该键不参与判定，与旧行为一致）；
      * mode on/auto 且未声明 ⇒ `(["/"], [])`（兜底全前缀）；
      * 每项须为**非空字符串、以 `/` 开头、无空白**；空列表或任一项不合格 ⇒
        `(None, [点名第 N 项的错误…])`（不静默丢弃非法项）。
    """
    if mode not in ("on", "auto"):
        return None, []
    if raw is None:
        return ["/"], []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return None, [f"应为字符串或字符串列表，得 {raw!r}"]
    if not items:
        return None, ["列表为空（on/auto 至少声明一项，或以 / 兜底）"]
    errors: list[str] = []
    for i, item in enumerate(items, 1):
        if not isinstance(item, str) or not item:
            errors.append(f"第 {i} 项 {item!r} 须为非空字符串")
        elif not item.startswith("/"):
            errors.append(f"第 {i} 项 {item!r} 未以 / 开头")
        elif any(ch.isspace() for ch in item):
            errors.append(f"第 {i} 项 {item!r} 含空白")
    return (None, errors) if errors else (items, [])


def path_matches_prefix(path: str, prefixes) -> bool:
    """mock 路径锚定：标量或列表任一前缀命中即可（`None` 表示不锚定）。"""
    if prefixes is None:
        return True
    items = prefixes if isinstance(prefixes, (list, tuple)) else [prefixes]
    return any(path.startswith(str(p)) for p in items if p)

