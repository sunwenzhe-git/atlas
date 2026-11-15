"""`hidden` / `absent` 语义分离与零步基线逐例豁免（2026-11-15 诊断 S5）。

- `hidden` 必须先在 DOM 中存在（否则「功能块被裁掉」会被 toBeHidden 误判为「按预期隐藏」）；
- `absent` = 数量为 0（不存在），与 `hidden`（存在但不可见）分工；
- 零步基线对 mock 用例逐例豁免，同页非 mock 用例的探针照跑（不是整页空转）。
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gen_e2e", ROOT / "scripts" / "gen_e2e_scripts.py")
gn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gn)


def _case(**over) -> dict:
    base = {
        "id": "E2E-S5-001",
        "intent": "语义分离",
        "pages": ["home"],
        "precondition": [],
        "step": ["click home-cta-btn"],
        "expected": ["absent home-empty", "hidden home-badge", "visible home-title"],
        "testid": ["home-cta-btn", "home-empty", "home-badge", "home-title"],
    }
    base.update(over)
    return base


def test_hidden_requires_presence_and_absent_counts_zero() -> None:
    spec = gn.ts_case(_case(), "/s5")
    assert "await expect(page.getByTestId('home-empty')).toHaveCount(0);" in spec
    assert "await expect(page.getByTestId('home-badge')).not.toHaveCount(0);" in spec
    assert "await expect(page.getByTestId('home-badge').first()).toBeHidden();" in spec


def test_zero_step_baseline_exempts_mock_cases_only() -> None:
    mock_case = _case(id="E2E-S5-002", mock=["GET /api/x -> fixtures/home/x.json"],
                      expected=["visible mock-only"], testid=["mock-only"], step=["refresh"])
    out = gn.ts_zero_step_baseline("home", "/s5", [_case(), mock_case])
    assert "home-empty" in out and "home-badge" in out
    assert "mock-only" not in out
