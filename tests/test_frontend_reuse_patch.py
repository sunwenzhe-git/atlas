#!/usr/bin/env python3
"""前端复用契约的回归测试（D177 契约面；挂载补丁已随执行层移除）。

守护：
  ① `shared/frontend-reuse.md` 的适用四档 / 四层 / 五列 / surface / 打桩边界存在；
  ② 片段与契约不含具体框架名；
  ③ `shared/single-source.md` 已登记复用决策记录 owner。

运行：
    python3 tests/test_frontend_reuse_patch.py
    pytest tests/test_frontend_reuse_patch.py
"""

from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = PKG_ROOT / "shared" / "frontend-reuse.md"
SINGLE_SOURCE = PKG_ROOT / "shared" / "single-source.md"

FRAMEWORK_WORDS = re.compile(r"\b(react|vue|svelte|angular|next\.js|nuxt|solidstart)\b", re.I)


def _assert_no_framework_words(text: str, where: str) -> None:
    hits = sorted(set(m.group(0).lower() for m in FRAMEWORK_WORDS.finditer(text)))
    assert not hits, f"{where} 出现具体框架名：{hits}"


def test_contract_shape() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for heading in (
        "## 1. 适用性与执行顺序",
        "## 2. 交互清点（先于组件查找）",
        "## 3. 四层查找",
        "## 4. 复用决策表",
        "## 5. 新模块的目录确认（执行侧）",
        "## 6. 验证与证据",
        "## 7. 可选的项目侧索引",
        "## 8. 反模式（硬）",
    ):
        assert heading in text, f"契约缺章节：{heading}"
    for token in ("new-module", "refactor", "new-files", "not-applicable"):
        assert token in text, f"契约缺适用档：{token}"
    for column in ("Capability", "Reference", "Reuse Decision", "Gap / Deviation", "Verification"):
        assert column in text, f"契约缺决策列：{column}"
    for keyword in ("surface", "打桩", "E2E", "非门", "非真相源"):
        assert keyword in text, f"契约缺关键语义：{keyword}"
    _assert_no_framework_words(text, "shared/frontend-reuse.md")


def test_single_source_registration() -> None:
    text = SINGLE_SOURCE.read_text(encoding="utf-8")
    assert "前端复用决策记录" in text


def main() -> int:
    test_contract_shape()
    test_single_source_registration()
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
