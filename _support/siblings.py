#!/usr/bin/env python3
"""atlas 共享内核 —— 随包模块加载器（单源引导器）。

用途：`scripts/` 与 `validators/` 内多个消费者需要复用随包脚本 / 校验器
（例：`validate_e2e_mocks` 复用生成器的 mock 文法、控制台复用索引解析器）。
本模块把「spec_from_file_location + sys.modules 缓存」这一模式**收敛为单一实现**——
此前该模式在 5 处各写各的（含一次模块名不统一的实况），属 B197-1 型漂移温床。

- **随包分发**：本目录（`_support/`）随 `install.sh` 整包装配；包根 = 本文件上一级。
- **纯标准库**：无第三方依赖（契约 `rings/e2e/reference.md` §8.3）。
- 加载失败**响亮抛错**，绝不静默返回 None / 空模块（§B92 族纪律）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent  # `.atlas/` 或 `atlas/` 包根
_SEARCH_DIRS = ("scripts", "validators", "_support")


def load_module(name: str, prefer_root: Path | None = None):
    """按名字加载随包模块（`scripts/` → `validators/` → `_support/` 依次查找）。

    - `sys.modules` 键带 `_atlas_` 前缀防与目标项目模块撞名；同进程同 name 只加载一次
      （atlas 分发模型下逐树独立进程运行，双树并存不构成实际场景）。
    - `prefer_root`（可选，控制台专用）：给定时**优先**从 `<prefer_root>/.atlas/<dir>/`
      加载同名模块（项目部署副本 = 随包时两者同物；临时 / 独立运行目录容错），
      找不到才回落随包——保控制台既有「项目 .atlas 优先」语义。
    - 找不到 ⇒ `FileNotFoundError` 带查找面（响亮，不静默）。
    """
    key = f"_atlas_{name}"
    if key in sys.modules:
        return sys.modules[key]
    candidates: list[Path] = []
    if prefer_root is not None:
        for d in _SEARCH_DIRS:
            p = prefer_root / ".atlas" / d / f"{name}.py"
            if p.is_file():
                candidates.append(p)
    for d in _SEARCH_DIRS:
        p = PKG_ROOT / d / f"{name}.py"
        if p.is_file():
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError(
            f"随包模块不存在：{name}（已在 {PKG_ROOT} 的 {_SEARCH_DIRS} 下查找）")
    spec = importlib.util.spec_from_file_location(key, candidates[0])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod
