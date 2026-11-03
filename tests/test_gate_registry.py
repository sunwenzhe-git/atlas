"""门登记表形态门（`RFC-20261103-03`；三钉 + 唯一性）。

口径（与 RFC §1.1 写死口径一致）：`shared/gates.md` 的 `## 2. 登记表` 与下一个
`## ` 小节之间、以 `|` 开头、排除表头行（首格 = `门`）与 `|---|` 分隔行之后的数据行。
切分按**未转义** `|`（`\\|` 视为字面字符，GFM 表格语义）。

钉：
1. `E2E 真跑` 行 ≤ 1600 字符（首拆防回长）；
2. 每个登记行按未转义 `|` 切分恰好 6 格（防游离竖线回潮）；
3. 每个登记行的 6 格 strip 后均非空。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E_CAP = 1600


def _registry_rows() -> list[str]:
    lines = (ROOT / "shared" / "gates.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 2. 登记表"))
    end = next(i for i, line in enumerate(lines) if line.startswith("## 3."))
    rows: list[str] = []
    for line in lines[start:end]:
        if not line.startswith("|"):
            continue
        first = line.split("|")[1].strip()
        if first == "门":
            continue
        if set(line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        rows.append(line)
    return rows


def _cells(row: str) -> list[str]:
    return re.split(r"(?<!\\)\|", row)[1:-1]


def test_e2e_row_is_unique_and_within_cap() -> None:
    rows = [r for r in _registry_rows() if r.startswith("| `E2E 真跑`")]
    assert len(rows) == 1, f"E2E 真跑行应恰有一条，实得 {len(rows)}"
    assert len(rows[0]) <= E2E_CAP, f"E2E 真跑行 {len(rows[0])} > {E2E_CAP}（回长即拆）"


def test_every_row_has_exactly_six_cells() -> None:
    for row in _registry_rows():
        cells = _cells(row)
        assert len(cells) == 6, f"格数 {len(cells)} ≠ 6（游离竖线）：{row[:40]}"


def test_every_cell_nonempty() -> None:
    for row in _registry_rows():
        for i, cell in enumerate(_cells(row), 1):
            assert cell.strip(), f"第 {i} 格为空：{row[:40]}"
