#!/usr/bin/env python3
"""validate_ac_alignment 的出厂假绿测试（喂坏输入必红）。

依据 gates.md 假绿测试义务：
  - 无主 AC 必红 (FAIL)
  - 无 waiver skip/xfail 必红 (FAIL)
  - 有 waiver 豁免的 skip 放行 (PASS)
  - enforce 模式下零测试挂载必红 (FAIL)
  - 差量退化必报 WARN
  - 正常场景全绿 (PASS)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    """随树加载（`atlas_check` 的出厂测试行不带 PYTHONPATH —— 直接 import 校验器包会
    ModuleNotFoundError；本仓测试惯例 = 按 PKG_ROOT 路径加载，见 test_validators.py）。"""
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


vaa = _load("validate_ac_alignment", "validators/validate_ac_alignment.py")
validate_ac_alignment, Result = vaa.validate_ac_alignment, vaa.Result


def create_minimal_project(
    tmp_path: Path,
    prd_acs: list[str] | None = None,
    test_code: str | None = None,
    profile_extra: str = "",
    baseline_data: dict | None = None,
) -> Path:
    # 1. PRD 资产
    prd_dir = tmp_path / "product" / "prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    if prd_acs is not None:
        lines = ["# 模块 PRD", "## 五、验收标准", "| AC ID | 场景 | 回指规则 |", "|---|---|---|"]
        for ac in prd_acs:
            lines.append(f"| `{ac}` | Given x When y Then 返回成功 | `R-001` |")
        (prd_dir / "test-prd.md").write_text("\n".join(lines), encoding="utf-8")

    # 2. stack-profile
    sp_lines = [
        "product: 测试项目",
        "origin: greenfield",
        "apps:",
        "  - name: backend",
        "    path: backend",
        "    kind: backend",
        "    role: landing",
        "    stack: python",
    ]
    if profile_extra:
        sp_lines.append(profile_extra)
    (tmp_path / "product" / "stack-profile.yaml").write_text("\n".join(sp_lines), encoding="utf-8")

    # 3. 后端测试代码
    test_dir = tmp_path / "backend" / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    if test_code is not None:
        (test_dir / "test_sample.py").write_text(test_code, encoding="utf-8")

    # 4. 基线
    if baseline_data is not None:
        runs_dir = tmp_path / ".atlas" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "backend-ac-alignment.json").write_text(
            json.dumps(baseline_data, indent=2), encoding="utf-8"
        )

    return tmp_path


def test_baseline_all_pass(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
def test_valid_case():
    assert True
"""
    proj = create_minimal_project(tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code)
    res = validate_ac_alignment(proj)
    assert res.status == "PASS"
    checks = {c["check"]: c["status"] for c in res.checks}
    assert checks["无主AC拦截"] == "PASS"
    assert checks["无效跳过拦截"] == "PASS"
    assert checks["AC覆盖对账"] == "PASS"


def test_dangling_ac_fails(tmp_path: Path):
    # 测试引用的 AC 在 PRD 中不存在 -> 必须 FAIL
    test_code = """
import pytest

@pytest.mark.ac("AC-GHOST-999")
def test_fake_case():
    assert True
"""
    proj = create_minimal_project(tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code)
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL"
    dangling_check = [c for c in res.checks if c["check"] == "无主AC拦截"][0]
    assert dangling_check["status"] == "FAIL"
    assert "AC-GHOST-999" in dangling_check["detail"]


def test_unwaived_skip_fails(tmp_path: Path):
    # 挂载了 AC 的测试被 skip 但无 waiver 理由 -> 必须 FAIL
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
@pytest.mark.skip(reason="暂未实现")
def test_skipped_without_waiver():
    assert False
"""
    proj = create_minimal_project(tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code)
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL"
    skip_check = [c for c in res.checks if c["check"] == "无效跳过拦截"][0]
    assert skip_check["status"] == "FAIL"
    assert "test_skipped_without_waiver" in skip_check["detail"]


def test_waived_skip_passes(tmp_path: Path):
    # 显式附带 waiver: 豁免理由的 skip -> 放行 PASS
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
@pytest.mark.skip(reason="waiver: 第三方支付接口临时维护中")
def test_skipped_with_waiver():
    assert False
"""
    proj = create_minimal_project(tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code)
    res = validate_ac_alignment(proj)
    assert res.status == "PASS"
    skip_check = [c for c in res.checks if c["check"] == "无效跳过拦截"][0]
    assert skip_check["status"] == "PASS"


def test_enforce_mode_zero_coverage_fails(tmp_path: Path):
    # enforce 模式下，PRD 有 AC 但完全无测试挂载 -> 必须 FAIL
    extra = """
backend_test:
  mode: enforce
"""
    test_code = """
def test_unrelated():
    assert True
"""
    proj = create_minimal_project(
        tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code, profile_extra=extra
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL"
    cov_check = [c for c in res.checks if c["check"] == "AC覆盖对账"][0]
    assert cov_check["status"] == "FAIL"


def test_delta_regression_warns(tmp_path: Path):
    # 挂载测试数量较基线发生倒退 -> 必须 WARN
    baseline = {
        "tests_with_ac_count": 5,
        "covered_acs_count": 3,
        "total_test_count": 10,
    }
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
def test_only_one():
    assert True
"""
    proj = create_minimal_project(
        tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code, baseline_data=baseline
    )
    res = validate_ac_alignment(proj)
    assert res.status == "WARN"
    delta_check = [c for c in res.checks if c["check"] == "差量防回退"][0]
    assert delta_check["status"] == "WARN"
    assert "挂载测试数退化" in delta_check["detail"]


def test_ac_alignment_ignores_reviews_and_subdirectories(tmp_path: Path):
    """验证 collect_prd_acs 严格收敛于平铺规范（prd.md 与 *-prd.md），
    不会将 reviews/ 评审历史目录中的废弃 AC 误当成合法声明。
    """
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
def test_valid():
    assert True
"""
    proj = create_minimal_project(
        tmp_path, prd_acs=["AC-TEST-001"], test_code=test_code
    )
    # 在 product/prd/ 下注入 reviews/ 子目录，内含未覆盖的幽灵/旧 AC
    reviews_dir = proj / "product" / "prd" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / "review-old.md").write_text(
        "# Review\n- 曾经提议的 `AC-OBSOLETE-999` 已废弃\n", encoding="utf-8"
    )

    # 如果 collect_prd_acs 错误递归扫了 reviews，已声明 AC 会变成 2 个，未覆盖率会导致对账失败
    res = validate_ac_alignment(proj)
    assert res.status == "PASS"
    cov_check = [c for c in res.checks if c["check"] == "AC覆盖对账"][0]
    assert cov_check["status"] == "PASS"
    assert "已声明 AC: 1" in cov_check["detail"]


# ---------------------------------------------------------------------------
# D153：后端通道 AC × 覆盖维度
# ---------------------------------------------------------------------------

BACKEND_CHECK = "AC × 覆盖维度（后端通道）"


def _check(res, name=BACKEND_CHECK):
    return next((c for c in res.checks if c["check"] == name), None)


def create_backend_project(
    tmp_path: Path,
    prd_rows: list[tuple],
    test_code: str | None,
    *,
    header: list[str] | None = None,
    with_backend_test: bool = True,
    framework: str | None = None,
    mode: str = "advisory",
    apps: list[dict] | None = None,
    test_dir_files: dict[str, str] | None = None,
) -> Path:
    prd_dir = tmp_path / "product" / "prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    header = header or ["AC ID", "场景", "回指规则", "适用覆盖维度", "后端适用覆盖维度"]
    lines = [
        "# 模块 PRD",
        "## 五、验收标准",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for row in prd_rows:
        lines.append("| " + " | ".join(row) + " |")
    (prd_dir / "test-prd.md").write_text("\n".join(lines), encoding="utf-8")

    apps = apps or [
        {"name": "backend", "path": "backend", "kind": "backend", "role": "landing", "stack": "python"}
    ]
    sp = ["product: 测试项目", "origin: greenfield", "apps:"]
    for a in apps:
        sp.extend([
            f"  - name: {a['name']}",
            f"    path: {a['path']}",
            f"    kind: {a['kind']}",
            f"    role: {a['role']}",
            f"    stack: {a['stack']}",
        ])
    if with_backend_test:
        sp.extend([
            "backend_test:",
            "  test_dir: backend/tests",
            f"  mode: {mode}",
            "  ac_marker: pytest_mark",
        ])
        if framework:
            sp.append(f"  framework: {framework}")
    (tmp_path / "product" / "stack-profile.yaml").write_text("\n".join(sp) + "\n", encoding="utf-8")

    test_dir = tmp_path / "backend" / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    if test_code is not None:
        (test_dir / "test_sample.py").write_text(test_code, encoding="utf-8")
    for name, code in (test_dir_files or {}).items():
        (test_dir / name).write_text(code, encoding="utf-8")
    return tmp_path


def test_backend_dimensions_pass(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01", "C02"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01,C02")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "PASS", check
    assert res.status == "PASS"


def test_backend_dimensions_missing_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01,C02,C11")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "C02" in check["detail"] and "C11" in check["detail"], check


def test_backend_zero_test_warn(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        "def test_unrelated():\n    assert True\n",
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "零测试" in check["detail"] and "AC-TEST-001" in check["detail"], check


def test_backend_weak_only_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
@pytest.mark.skip(reason="waiver: 临时跳过")
def test_ok():
    assert False
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "弱证据" in check["detail"], check


def test_backend_skipif_weak(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.skipif(False, reason="off")
@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "弱证据" in check["detail"], check


def test_backend_multi_ac_dims_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", "AC-TEST-002", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [
            ("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01"),
            ("`AC-TEST-002`", "Given x When y Then z", "`R-001`", "", "C01"),
        ],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "一测多AC" in check["detail"], check


def test_backend_docstring_ac_not_dims(tmp_path: Path):
    test_code = '''
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    """也提到 AC-OTHER-001。"""
    assert True
'''
    proj = create_backend_project(
        tmp_path,
        [
            ("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01"),
            ("`AC-OTHER-001`", "Given x When y Then z", "`R-001`", "", ""),
        ],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "PASS", check


def test_backend_dims_shape_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims={"C01"})
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "dims形态不支持" in check["detail"], check


def test_backend_unknown_dim_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C99"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "未知维度" in check["detail"], check


def test_backend_three_column_na(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`")],
        test_code,
        header=["AC ID", "场景", "回指规则"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check


def test_backend_standard_e2e_four_column_not_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "C01,C02")],
        test_code,
        header=["AC ID", "场景", "回指规则", "适用覆盖维度"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check


def test_backend_header_in_fourth_column_warns(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "C01")],
        test_code,
        header=["AC ID", "场景", "回指规则", "后端适用覆盖维度"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "第 4 列" in check["detail"], check


def test_backend_notes_column_with_dims_warns(tmp_path: Path):
    test_code = 'def test_unrelated():\n    assert True\n'
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        header=["AC ID", "场景", "回指规则", "适用覆盖维度", "备注"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "疑似后端维度列" in check["detail"], check


def test_backend_template_placeholder_na(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "N/A")],
        "def test_unrelated():\n    assert True\n",
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check


def test_backend_no_backend_test_na(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        with_backend_test=False,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check
    assert "backend_test" in check["detail"], check


def test_backend_non_pytest_na(tmp_path: Path):
    test_code = 'def test_unrelated():\n    assert True\n'
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        framework="unittest",
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check
    assert "非 pytest" in check["detail"], check


def test_backend_multi_app_na(tmp_path: Path):
    apps = [
        {"name": "api1", "path": "api1", "kind": "backend", "role": "landing", "stack": "python"},
        {"name": "api2", "path": "api2", "kind": "backend", "role": "landing", "stack": "python"},
    ]
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        apps=apps,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check
    assert "多后端应用" in check["detail"], check


def test_backend_star_test_scan_face(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        test_dir_files={
            "foo_test.py": 'import pytest\n\n@pytest.mark.ac("AC-TEST-001", dims=["C01"])\ndef test_x():\n    assert True\n'
        },
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "扫描面" in check["detail"] and "零测试" in check["detail"], check
    assert "foo_test.py" in check["detail"], check


def test_backend_syntax_error_warn(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        test_dir_files={"test_bad.py": "def broken(:\n"},
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "解析失败" in check["detail"], check
    assert "test_bad.py" in check["detail"], check


def test_backend_empty_root_na(tmp_path: Path):
    proj = create_backend_project(tmp_path, [], None)
    res = validate_ac_alignment(proj)
    assert res.status == "N/A"
    check = _check(res, "AC对账门禁运行态")
    assert check is not None and check["status"] == "N/A", check


def test_backend_dims_string_and_tuple(tmp_path: Path):
    for idx, dims in enumerate(['"C01,C02"', '("C01", "C02")']):
        root = tmp_path / str(idx)
        test_code = f"""
import pytest

@pytest.mark.ac("AC-TEST-001", dims={dims})
def test_ok():
    assert True
"""
        proj = create_backend_project(
            root,
            [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01,C02")],
            test_code,
        )
        res = validate_ac_alignment(proj)
        check = _check(res)
        assert check is not None and check["status"] == "PASS", (dims, check)


def test_backend_module_pytestmark_weak(tmp_path: Path):
    test_code = """
import pytest
pytestmark = pytest.mark.skipif(False, reason="off")

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "弱证据" in check["detail"], check


def test_backend_class_pytestmark_weak(tmp_path: Path):
    test_code = """
import pytest

class TestX:
    pytestmark = pytest.mark.skipif(False, reason="off")

    @pytest.mark.ac("AC-TEST-001", dims=["C01"])
    def test_ok(self):
        assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "弱证据" in check["detail"], check


def test_backend_pytestmark_ac_unsupported(tmp_path: Path):
    test_code = """
import pytest
pytestmark = pytest.mark.ac("AC-TEST-001")

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "pytestmark挂AC不支持" in check["detail"], check


def test_backend_prd_unknown_token_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01,C99")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "未知 token" in check["detail"] and "C99" in check["detail"], check


def test_backend_cross_prd_duplicate_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    (proj / "product" / "prd" / "other-prd.md").write_text(
        "# 另一域 PRD\n## 五、验收标准\n"
        "| AC ID | 场景 | 回指规则 | 适用覆盖维度 | 后端适用覆盖维度 |\n"
        "|---|---|---|---|---|\n"
        "| `AC-TEST-001` | Given x When y Then z | `R-002` |  | C01 |\n",
        encoding="utf-8",
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "重复声明" in check["detail"], check


def test_backend_notes_ac_id_no_false_warn(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "AC-C01-001")],
        "def test_unrelated():\n    assert True\n",
        header=["AC ID", "场景", "回指规则", "适用覆盖维度", "备注"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check


def test_backend_real_template_placeholder_na(tmp_path: Path):
    template = (PKG_ROOT / "templates" / "prd" / "domain.md").read_text(encoding="utf-8")
    proj = create_backend_project(
        tmp_path,
        [],
        'import pytest\n\n@pytest.mark.ac("AC-TEST-001")\ndef test_ok():\n    assert True\n',
    )
    (proj / "product" / "prd" / "test-prd.md").write_text(
        template.replace("<CODE>", "TEST"), encoding="utf-8"
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "N/A", check
    assert "零测试" not in check["detail"], check


def test_backend_six_column_pass(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "", "C01")],
        test_code,
        header=["AC ID", "场景", "回指规则", "适用覆盖维度", "备注", "后端适用覆盖维度"],
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "PASS", check


def test_backend_empty_dims_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=[])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "空dims" in check["detail"], check


def test_backend_parametrize_marks_weak(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.skip)])
@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok(x):
    assert x
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert "弱证据" in check["detail"], check


def test_backend_enforce_dim_gap_warn(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001", dims=["C01"])
def test_ok():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01,C02")],
        test_code,
        mode="enforce",
    )
    res = validate_ac_alignment(proj)
    check = _check(res)
    assert check is not None and check["status"] == "WARN", check
    assert res.status == "WARN", res.status

