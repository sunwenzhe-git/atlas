#!/usr/bin/env python3
"""atlas 共享内核 —— 宿主注入型 **base query** 的转发（`e2e.app_base_url` 的 query 带到每一跳）。

**为什么存在**（2026-10-17，issue #27 / `DESIGN.md` D104）：某些靶场的应用把「宿主注入的前提」
（如 tenant：`?switchAgent=7202`）**只从 `window.location.search` 读**（无 sessionStorage 回落）⇒
`会话:` 通道（`D89`，写 sessionStorage）送不到它；而 `goto` 又被门禁「不得带查询参数」（§5.7）。

它只能住在唯一真相源 `e2e.app_base_url` 里。但**绝对路径会丢 base 的 query**：

```
new URL('/console/#/app/x', 'http://h/console/?switchAgent=7202')  // → http://h/console/#/app/x     ← query 丢
new URL('#/app/x',         'http://h/console/?switchAgent=7202')  // → …?switchAgent=7202#/app/x    ← 但 `#/…` 在
                                                                  //    .atlas-case 里写不出来（`#` 前有空格 = 行内注释）
```

⇒ 解法 = **生成期把 base 的 query 显式并进导航目标**（不是运行期助手：`playwright.config.ts` 用
`process.env.ATLAS_BASE_URL ?? '<base>'`，运行期助手要跟随覆盖就得反取 `test.info().project.use.baseURL`，
脆且隐式）。生成期变换把语义烘成常量：**`ATLAS_BASE_URL` 只覆盖 host，不覆盖 base 的 query**
（换 tenant 请改 `stack-profile.yaml`）——这条口径写进 `rings/e2e/reference.md` §5.5。

口径：
- **base 无 query ⇒ 逐字节零变化**（`merge_base_query` 原样返回目标）—— `生成物最新` 门看守派生件。
- **只处理以 `/` 开头的目标**（外部绝对 URL、`#/…` 等一律不动）；目标自带 `?` 时原样保留
  （§5.7 下不可达，为未来扩展留位，不写进生效口径）。
- 纯标准库。
"""
from __future__ import annotations

from urllib.parse import urlsplit


def base_query(base: str) -> str:
    """`base` 的 query 串（无 query / 非法 URL ⇒ 空串）。"""
    if not base:
        return ""
    try:
        return urlsplit(base.strip()).query
    except ValueError:
        return ""


def merge_base_query(target: str, base: str) -> str:
    """把 `base` 的 query 并进 `target`（**生成期**用它，运行期语义见模块头注）。

    - `base` 无 query ⇒ 原样返回 `target`（**零变化承诺**）
    - `target` 非 `/` 开头（外部 URL / 相对 hash）或已带 `?` ⇒ 原样返回（不擅自改写）
    - 否则在 **path 与 hash 之间**插入 query：`/a/b#/c` → `/a/b?<base query>#/c`
    """
    q = base_query(base)
    if not q or not target.startswith("/") or "?" in target:
        return target
    path, sep, frag = target.partition("#")
    return f"{path}?{q}" + (f"#{frag}" if sep else "")


def origin_of(base: str) -> str:
    """`base` 的 origin（`scheme://netloc`）—— 供「拼出可直接访问的绝对地址」的消费者用
    （例：控制台手工项「打开」；字符串拼接 `base + path` 在 base 带 query 时必产畸形 URL）。"""
    if not base:
        return ""
    parts = urlsplit(base.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
