#!/usr/bin/env python3
"""atlas AC 提取器注册表（框架知识的合法落点）。

`validators/validate_ac_alignment.py` 只依赖本注册表返回的归一化记录；
具体框架的扫描/解析逻辑只允许出现在本目录的 adapter 内。
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from _support.layout import load_layout  # noqa: E402
from _support.siblings import load_module  # noqa: E402

_sp = load_module("stack_profile")


@dataclass
class ExtractResult:
    tests: list[dict[str, Any]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    scan_face: list[str] = field(default_factory=list)
    input_state: str = "absent"  # "present" | "absent"


DEFAULT = "pytest"
# name -> (模块名, Extractor 构造参数)；具体框架知识只在本目录。
_BUILTINS = {
    "pytest": ("pytest", None),
    "vitest": ("js", "vitest"),
    "jest": ("js", "jest"),
    "junit5": ("junit", "junit5"),
}


def resolve(name: str | None = None):
    """按名字解析内置 adapter；未知返回 None。"""
    key = (name or DEFAULT).strip()
    spec = _BUILTINS.get(key)
    if spec is None:
        return None
    module_name, label = spec
    module = importlib.import_module(f".{module_name}", __name__)
    return module.Extractor(label) if label else module.Extractor()


def available() -> list[str]:
    return list(_BUILTINS)


def wire_project(target: Path) -> dict:
    """按项目声明的 extractor 调其项目级配置 hook；不支持则诚实跳过。"""
    target = Path(target)
    name = None
    try:
        lay = load_layout(target)
        if lay.stack_profile.is_file():
            profile = _sp.parse_profile(lay.stack_profile.read_text(encoding="utf-8"))
            cfg = profile.get("backend_test") or {}
            if isinstance(cfg, dict):
                name = (cfg.get("extractor_command")
                        or cfg.get("extractor")
                        or cfg.get("framework"))
    except Exception:
        name = None
    adapter = resolve(name)
    if adapter is None:
        return {"file": None, "status": "skipped",
                "detail": f"extractor={name!r} 无项目级配置钩子（不写任何配置）"}
    fn = getattr(adapter, "wire_project", None)
    if fn is None:
        return {"file": None, "status": "skipped",
                "detail": "该 extractor 无项目级配置钩子（不写任何配置）"}
    return fn(target, name)
