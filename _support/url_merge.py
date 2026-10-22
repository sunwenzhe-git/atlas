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
- **只处理以 `/` 开头的目标**（外部绝对 URL、`#/…` 等一律不动）；目标自带 `?` 时与 base 的 query
  **求并集**（base 在前、目标在后，**同键 ⇒ 目标胜**）—— 2026-10-18（`DESIGN.md` D109）随
  `参数:` 通道转正为生效口径。
- 纯标准库。
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# 查询值的**形态白名单**（生成物里 URL 嵌在 `page.goto('<url>')` 的单引号内、且本身是查询串片段）：
# 禁空白 / 引号（含 `'`）/ 反斜杠 / `&` / `#` / `?`。越形态 ⇒ 两道（文本期门 + 生成期中止，不静默转义）。
# 单源：校验器与生成器共用本常量。
VALUE_RE = re.compile(r"^[A-Za-z0-9._~!$()*+,;:@%/-]+$")


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
    - `target` 非 `/` 开头（外部 URL / 相对 hash）⇒ 原样返回（不擅自改写）
    - `target` 无 `?` ⇒ 在 **path 与 hash 之间**插入 base query：`/a/b#/c` → `/a/b?<base query>#/c`
    - `target` 自带 `?`（= 用例内联的宿主注入参数，契约 §5.5 `参数:`）⇒ **求并集**：
      base 在前、target 在后，**同键 ⇒ target 胜**（逐用例比全局 base 更具体）。
      本分支 2026-10-17 落笔时记为「§5.7 下不可达，为未来扩展留位」；2026-10-18（`DESIGN.md` D109）
      随 `参数:` 通道**转正为生效口径**。
    """
    q = base_query(base)
    if not q or not target.startswith("/"):
        return target
    path, sep, frag = target.partition("#")
    head, qsep, own = path.partition("?")
    merged = q if not qsep else union_query(q, own)
    return f"{head}?{merged}" + (f"#{frag}" if sep else "")


def union_query(base_q: str, own_q: str) -> str:
    """两个查询串求并集：base 在前、own 在后；**同键 ⇒ own 胜**（片段文本原样保留，不重编码）。"""
    own = [p for p in own_q.split("&") if p]
    own_keys = {p.partition("=")[0] for p in own}
    base = [p for p in base_q.split("&") if p and p.partition("=")[0] not in own_keys]
    return "&".join(base + own)


def query_of(target: str) -> str:
    """`target` 的查询串（`/a?k=v#/h` ⇒ `k=v`；无 ⇒ 空串）。**不含** hash 段内的内容。"""
    if not target.startswith("/"):
        return ""
    return target.partition("#")[0].partition("?")[2]


def hash_query_of(target: str) -> str:
    """`target` 的 **hash 查询串**（`/a#/h?k=v` ⇒ `k=v`；无 hash / 无查询 ⇒ 空串）。

    与 `query_of` 分载体：HashRouter 页面的 `useSearchParams` 读的是 hash 内的查询段，
    常规查询串（`#` 之前）由 `query_of` 负责。两者不得混用。
    """
    if "#" not in target:
        return ""
    return target.partition("#")[2].partition("?")[2]


def query_keys(target: str) -> list[str]:
    """`target` 查询串里的键（按出现顺序去重）——「键须已声明」门与生成器守卫取值**共用本单源**。"""
    out: list[str] = []
    for part in query_of(target).split("&"):
        if not part:
            continue
        k = part.partition("=")[0].strip()
        if k and k not in out:
            out.append(k)
    return out


def append_query(target: str, q: str) -> str:
    """把查询串 `q` 追加到 `target` 的 query 上（**插在 hash 之前**；已有 `?` ⇒ 用 `&` 接）。

    供「守卫导航承载用例声明的注入参数」用：调用侧的 `url` 已并入 base query（幂等），而 `守卫:`
    是未合并的具体路径 ⇒ 两种形态都按「追加到自身 query」处理，随后的一次 `merge_base_query`
    会把 base 去重并上来（同键 ⇒ 目标胜，不会重复）。
    """
    if not q:
        return target
    head, sep, frag = target.partition("#")
    joined = f"{head}{'&' if '?' in head else '?'}{q}"
    return f"{joined}#{frag}" if sep else joined


def hash_query_keys(target: str) -> list[str]:
    """`target` 的 hash 查询键（按出现顺序去重）——`hash参数:` 声明门与生成器守卫取值共用。"""
    out: list[str] = []
    for part in hash_query_of(target).split("&"):
        if not part:
            continue
        k = part.partition("=")[0].strip()
        if k and k not in out:
            out.append(k)
    return out


def append_hash_query(target: str, q: str) -> str:
    """把查询串 `q` 追加到 `target` 的 **hash 查询段**（`/a#/h` ⇒ `/a#/h?q`）。

    只处理已带 hash 的目标；没有 hash 时原样返回（不私造一条 hash 路由，调用方应响亮失败）。
    已有 hash 查询 ⇒ 与 `q` 求并集（既有在前、`q` 在后，**同键 ⇒ `q` 胜**）。
    """
    if not q or "#" not in target:
        return target
    head, _, frag = target.partition("#")
    fpath, fsep, fq = frag.partition("?")
    merged = q if not fsep else union_query(fq, q)
    return f"{head}#{fpath}?{merged}"


def strip_query(target: str) -> str:
    """去掉**常规查询串**、保留 hash 段（含 hash 查询）（`/a?k=v#/h?x=1` ⇒ `/a#/h?x=1`）。

    只处理 `#` 之前的查询；hash 内的查询由 `strip_hash_query` 单独处理。
    """
    head, sep, frag = target.partition("#")
    if "?" in head:
        head = head.partition("?")[0]
    return f"{head}#{frag}" if sep else head


def strip_hash_query(target: str) -> str:
    """去掉 **hash 查询串**、保留 hash 路径（`/a#/h?k=v` ⇒ `/a#/h`）。"""
    head, sep, frag = target.partition("#")
    if not sep or "?" not in frag:
        return target
    return f"{head}#{frag.partition('?')[0]}"


def strip_queries(target: str) -> str:
    """同时去掉常规查询串与 hash 查询串，保留 hash 路径（`/a?t=1#/h?k=v` ⇒ `/a#/h`）。

    供 `goto` / `守卫` 路径门按**路径形态**匹配（页面表 `路由` 列是路径形态）。顺序无关。
    """
    return strip_hash_query(strip_query(target))


def origin_of(base: str) -> str:
    """`base` 的 origin（`scheme://netloc`）—— 供「拼出可直接访问的绝对地址」的消费者用
    （例：控制台手工项「打开」；字符串拼接 `base + path` 在 base 带 query 时必产畸形 URL）。"""
    if not base:
        return ""
    parts = urlsplit(base.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
