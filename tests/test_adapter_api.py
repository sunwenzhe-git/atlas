#!/usr/bin/env python3
"""`adapters/api.py` 的「喂坏输入必红」判据（2026-10-15 补）。

**为什么要它**：`api` 在 §6.2 判定为「接」（有聚合价值），但本适配器此前只认
Python 装饰器路由与 `.pyxl` action——对前端 adopt 的主力形态（TS 的 RPC / action
调用）产出恒为 **0 条**，且**机器可读描述那一支根本不可达**。两条都属「把缺口伪装成
配门」：接上线后事实表空着，对账却给绿灯。这里把两处判据钉住。

五侧：
  1. **TS RPC / action**：`request('a.b.c', …)` 与泛型 `mcpFetch<In, Out>('a.b.c', …)`
     都要收（含跨行调用）；`path` 记方法名本身、不合成 URL，`method` 记 `RPC`（不编传输动词）；
  2. **调用名闸**：点分字符串交给**非** request/fetch 系调用时不得收（实测误收族：
     OTel 属性键 `attributes.gen_ai.input.messages`）；
  3. **注释不算调用**：被注掉的调用不得进 `items`；
  4. **D 类「有描述」指针形态**：项目自带 `openapi.json` ⇒ 只给 `spec_entry`、**不产 items**，
     且**出声**（丢弃了多少条端点，不静默清空）；
  5. **适配器不做行键去重**：同一（方法, 路径）从两个域的两个文件被调 ⇒ **两条都在**
     （跨域重复是合法事实，各进各的域文件；同文件内的重复行键由渲染期折叠）。

变异 M54：让 `find_descriptors` 退回「搭源码后缀遍历」（描述文件恒找不到）⇒ 第 4 侧红。
变异 M56：在适配器里加回「按（方法, 路径）全局去重」⇒ 第 5 侧红。
变异 M57：把 RPC 的 `method` 写回 `POST` ⇒ 第 1 侧红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = PKG_ROOT / "adapters" / "api.py"

PROFILE = """product: 夹具
apps:
  - name: frontend
    path: frontend
    kind: frontend
    role: landing
    stack: 夹具
"""

RPC_TS = """\
import { request } from '@/common/request'

function mcpFetch<T, R>(api: string, params: T): Promise<R> {
  return request(api, params) as Promise<R>
}

export function listServers(params: ListParams): Promise<IPagingList<Server>> {
  return mcpFetch<ListParams, IPagingList<Server>>(
    'zeldaEasy.platform-infrastructure.mcp.pageList',
    params
  )
}

export function createServer(params: CreateParams): Promise<string> {
  return request('zeldaEasy.platform-console.provider.addProvider', { request: params })
}

// request('zeldaEasy.platform-console.provider.removed', {})
"""

NOISE_TS = """\
const span = tracer.startSpan('attributes.gen_ai.input.messages')
logger.set('otel.scope.name')
format('a.b.c')
"""


def mk(root: Path, files: dict) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE, encoding="utf-8")
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def run(root: Path) -> dict:
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                        "--app", "frontend", "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_ts_rpc_calls_are_extracted() -> None:
    """TS 的 RPC / action 调用：泛型调用与跨行调用都要收；`path` 记方法名本身。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/modules/mcp/api/index.ts": RPC_TS})
        items = run(root)["items"]
        assert sorted(i["path"] for i in items) == [
            "zeldaEasy.platform-console.provider.addProvider",
            "zeldaEasy.platform-infrastructure.mcp.pageList",
        ], items
        page = next(i for i in items if i["path"].endswith("pageList"))
        assert page["method"] == "RPC", page
        assert page["source_file"] == "frontend/src/modules/mcp/api/index.ts:8", page


def test_dotted_string_to_other_callee_is_not_an_endpoint() -> None:
    """点分字符串交给非 request/fetch 系调用 ⇒ 不是端点（防 OTel 属性键那类误收）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/tracing.ts": NOISE_TS})
        assert run(root)["items"] == []


def test_commented_out_call_is_not_an_endpoint() -> None:
    """被注掉的调用不得进 `items`（`'https://…'` 里的 `//` 也不是注释）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"frontend/src/modules/mcp/api/index.ts": RPC_TS})
        paths = [i["path"] for i in run(root)["items"]]
        assert not any("removed" in p for p in paths), paths


def test_cross_domain_call_sites_are_both_kept() -> None:
    """适配器**不得**按行键全局去重：items 粒度 = 代码里的事实。

    为何（2026-10-15 复核）：同一端点被两个域各调一次是**两条合法事实**——渲染期按
    `source_file` 分域后各自进自己的 `apis.md`（真项目实测 25 个重复（方法,路径）键
    **全部跨域**、零个落进同一张表）。在适配器里全局去重会把另一个域唯一的那条抹掉。
    同一文件内重复行键的折叠归渲染层（`refresh_structure.dedup_by_row_key`）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        call = "export const f = () => request('zeldaEasy.svc.thing.doIt', {})\n"
        mk(root, {"frontend/src/a/api/index.ts": call,
                  "frontend/src/b/api/index.ts": call})
        items = run(root)["items"]
        assert len(items) == 2, items
        assert {i["source_module"] for i in items} == {
            "frontend/src/a/api/index.ts", "frontend/src/b/api/index.ts"}, items


def run_full(root: Path) -> tuple[dict, subprocess.CompletedProcess]:
    """同 `run`，另把 CompletedProcess 交回（要读 stderr 的用例用）。"""
    out = root / "out.json"
    p = subprocess.run([sys.executable, str(ADAPTER), "--root", str(root),
                        "--app", "frontend", "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(out.read_text(encoding="utf-8")), p


def test_descriptor_file_yields_pointer_form() -> None:
    """D 类「有描述」：自带 `openapi.json` ⇒ 只给 `spec_entry`，**不产 items**、但**要出声**。

    描述文件必须**按文件名单独探测**——搭源码后缀遍历永远找不到 `.json`，
    那样这一支就是死代码（事实表空着，对账还报绿）。转指针形态 = 整体丢弃已抽到的
    items ⇒ 静默会让人只看到「清单是空的」而无从查因。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, {"openapi.json": '{"openapi": "3.0.0"}',
                  "frontend/src/modules/mcp/api/index.ts": RPC_TS})
        data, p = run_full(root)
        assert data.get("spec_entry") == "openapi.json", data
        assert "items" not in data or data["items"] == [], data
        assert "丢弃" in p.stderr and "WARN" in p.stderr, p.stderr
