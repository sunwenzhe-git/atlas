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
import sys
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
    extractor: str | None = None,
    extractor_command: str | None = None,
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
        if extractor_command:
            sp.append(f'  extractor_command: "{extractor_command}"')
        elif extractor:
            sp.append(f"  extractor: {extractor}")
        elif framework:
            sp.append(f"  framework: {framework}")
    (tmp_path / "product" / "stack-profile.yaml").write_text("\n".join(sp) + "\n", encoding="utf-8")

    test_dir = tmp_path / "backend" / "tests"
    test_dir.mkdir(parents=True, exist_ok=True)
    if test_code is not None:
        (test_dir / "test_sample.py").write_text(test_code, encoding="utf-8")
    for name, code in (test_dir_files or {}).items():
        p = test_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
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


def test_backend_unknown_extractor_unverified(tmp_path: Path):
    test_code = 'def test_unrelated():\n    assert True\n'
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        extractor="unittest",
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "后端测试提取通道")
    assert check is not None and check["status"] == "WARN", check
    assert "[UNVERIFIED]" in check["detail"], check
    assert res.status == "WARN", res.status


def test_backend_multi_app_uses_global_test_dir(tmp_path: Path):
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
    assert check is not None and check["status"] == "PASS", check
    assert res.status == "PASS", res.status


def test_backend_multi_app_root_test_dir_scans_all_apps(tmp_path: Path):
    apps = [
        {"name": "api1", "path": "api1", "kind": "backend", "role": "landing", "stack": "python"},
        {"name": "api2", "path": "api2", "kind": "backend", "role": "landing", "stack": "python"},
    ]
    proj = create_backend_project(
        tmp_path,
        [
            ("`AC-A-001`", "Given x When y Then z", "`R-001`", "", "C01"),
            ("`AC-B-001`", "Given x When y Then z", "`R-002`", "", "C01"),
        ],
        None,
        apps=apps,
    )
    profile = proj / "product" / "stack-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("test_dir: backend/tests", "test_dir: ."),
        encoding="utf-8",
    )
    for app, ac in (("api1", "AC-A-001"), ("api2", "AC-B-001")):
        d = proj / app / "tests"
        d.mkdir(parents=True)
        (d / "test_x.py").write_text(
            f"import pytest\n\n@pytest.mark.ac('{ac}', dims=['C01'])\ndef test_ok():\n    assert True\n",
            encoding="utf-8",
        )
    res = validate_ac_alignment(proj)
    assert res.status == "PASS", [(c["check"], c["status"], c["detail"]) for c in res.checks]
    cov = _check(res, "AC覆盖对账")
    assert cov is not None and "覆盖: 2" in cov["detail"], cov


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
    check = _check(res, "测试扫描面")
    assert check is not None and check["status"] == "WARN", check
    assert "[SCAN]" in check["detail"], check
    assert "foo_test.py" in check["detail"], check


def test_backend_syntax_error_warn(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        test_dir_files={"test_bad.py": "def broken(:\n"},
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "测试提取完整性")
    assert check is not None and check["status"] == "WARN", check
    assert "[PARSE]" in check["detail"], check
    assert "test_bad.py" in check["detail"], check
    assert res.status == "WARN", res.status


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
    assert "模块/类级AC标记不支持" in check["detail"], check


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


# ---------------------------------------------------------------------------
# D163：三形态适用性 / extractor 边界 / 诚实状态
# ---------------------------------------------------------------------------

def test_frontend_only_ac_gate_na(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-TEST-001")
def test_ok():
    assert True
"""
    apps = [{"name": "web", "path": "frontend", "kind": "frontend", "role": "landing", "stack": "react"}]
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
        apps=apps,
    )
    res = validate_ac_alignment(proj)
    assert res.status == "N/A", res.status
    check = _check(res, "门控态")
    assert check is not None and check["status"] == "N/A", check
    assert "backend/fullstack" in check["detail"], check
    assert not (proj / ".atlas" / "runs" / "backend-ac-alignment.json").exists()


def test_missing_apps_dangling_ac_still_fails(tmp_path: Path):
    test_code = """
import pytest

@pytest.mark.ac("AC-GHOST-999")
def test_fake():
    assert True
"""
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        test_code,
    )
    (proj / "product" / "stack-profile.yaml").write_text("product: x\n", encoding="utf-8")
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无主AC拦截")
    assert check is not None and check["status"] == "FAIL", check
    assert "AC-GHOST-999" in check["detail"], check
    applicability = _check(res, "后端通道适用性")
    assert applicability is not None and applicability["status"] == "WARN", applicability


def test_missing_apps_without_input_unverified(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
    )
    (proj / "product" / "stack-profile.yaml").write_text("product: x\n", encoding="utf-8")
    res = validate_ac_alignment(proj)
    applicability = _check(res, "后端通道适用性")
    assert applicability is not None and applicability["status"] == "WARN", applicability
    assert "[UNVERIFIED]" in applicability["detail"], applicability
    assert res.status == "WARN", res.status


def test_backend_no_extractor_without_input_unverified(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "后端测试提取通道")
    assert check is not None and check["status"] == "WARN", check
    assert "[UNVERIFIED]" in check["detail"], check
    assert res.status == "WARN", res.status


def test_backend_non_python_without_extractor_unverified_not_zero_coverage(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        test_dir_files={"a.test.ts": "// no Python test input\n"},
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "后端测试提取通道")
    assert check is not None and check["status"] == "WARN", check
    assert "[UNVERIFIED]" in check["detail"], check
    cov = _check(res, "AC覆盖对账")
    assert cov is None, cov  # 未验证分支不应再产出 ZERO-COVERAGE


def test_backend_zero_coverage_advisory_warns(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        "def test_unrelated():\n    assert True\n",
        with_backend_test=False,
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "AC覆盖对账")
    assert check is not None and check["status"] == "WARN", check
    assert "[ZERO-COVERAGE]" in check["detail"], check
    assert res.status == "WARN", res.status


def test_backend_enforce_parse_errors_fail(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        test_dir_files={"test_bad.py": "def broken(:\n"},
        mode="enforce",
    )
    res = validate_ac_alignment(proj)
    check = _check(res, "测试提取完整性")
    assert check is not None and check["status"] == "FAIL", check
    assert "[PARSE]" in check["detail"], check
    assert res.status == "FAIL", res.status


def test_record_schema_rejects_bad_records(tmp_path: Path):
    base = {
        "name": "test_x",
        "file": "backend/tests/test_x.py",
        "line": 1,
        "acs": {"AC-X-001"},
        "marker_acs": {"AC-X-001"},
        "doc_acs": set(),
        "dims": set(),
        "dims_bad": [],
        "dims_shape_ok": True,
        "dims_present": False,
        "skipped": False,
        "waiver": "",
        "weak": False,
        "marker_scope_unsupported": False,
    }
    assert vaa._record_schema_errors([base], tmp_path) == []
    bad_union = dict(base, acs={"AC-X-001"}, marker_acs=set())
    assert any("acs 必须等于" in e for e in vaa._record_schema_errors([bad_union], tmp_path))
    bad_line = dict(base, line=0)
    assert any("line 必须为正整数" in e for e in vaa._record_schema_errors([bad_line], tmp_path))
    dup = dict(base, name="test_y")
    assert any("(file,line) 重复" in e for e in vaa._record_schema_errors([base, dup], tmp_path))
    absolute = dict(base, file=str(tmp_path / "x.py"))
    assert any("相对路径" in e for e in vaa._record_schema_errors([absolute], tmp_path))


# ---------------------------------------------------------------------------
# D164：TS / Vitest / Jest 内置 extractor（Batch C1）
# ---------------------------------------------------------------------------

def test_backend_vitest_title_ac_and_dims_pass(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="vitest",
        test_dir_files={
            "refund.test.ts": (
                "/** @atlas-dims C01 */\n"
                "it('[AC-TEST-001] 余额不足时拒绝退款', () => {});\n"
            ),
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "PASS", [(c["check"], c["status"], c["detail"]) for c in res.checks]
    cov = _check(res, "AC覆盖对账")
    assert cov is not None and "覆盖: 1" in cov["detail"], cov
    dim = _check(res)
    assert dim is not None and dim["status"] == "PASS", dim


def test_backend_vitest_dangling_ac_fails(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="vitest",
        test_dir_files={
            "refund.test.ts": "it('[AC-GHOST-999] 假挂载', () => {});\n",
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无主AC拦截")
    assert check is not None and "AC-GHOST-999" in check["detail"], check


def test_backend_jest_skip_without_waiver_fails(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="jest",
        test_dir_files={
            "__tests__/refund.spec.js": "test.skip('[AC-TEST-001] 暂不做', () => {});\n",
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无效跳过拦截")
    assert check is not None and check["status"] == "FAIL", check


def test_backend_vitest_unwaived_describe_skip_fails(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="vitest",
        test_dir_files={
            "refund.test.ts": (
                "describe.skip('group', () => {\n"
                "  it('[AC-TEST-001] 暂不做', () => {});\n"
                "});\n"
            ),
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无效跳过拦截")
    assert check is not None and "AC-TEST-001" in check["detail"], check



def test_backend_junit5_title_ac_and_dims_pass(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="junit5",
        test_dir_files={
            "RefundTest.java": (
                "class RefundTest {\n"
                "  @Test\n"
                "  @DisplayName(\"[AC-TEST-001] 余额不足拒绝\")\n"
                "  @Tag(\"atlas-dims-C01\")\n"
                "  void refundRejected() {}\n"
                "}\n"
            ),
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "PASS", [(c["check"], c["status"], c["detail"]) for c in res.checks]
    dim = _check(res)
    assert dim is not None and dim["status"] == "PASS", dim


def test_backend_junit5_dangling_ac_fails(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="junit5",
        test_dir_files={
            "RefundTest.java": (
                "class RefundTest {\n"
                "  @Test\n"
                "  @DisplayName(\"[AC-GHOST-999] 假挂载\")\n"
                "  void fake() {}\n"
                "}\n"
            ),
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无主AC拦截")
    assert check is not None and "AC-GHOST-999" in check["detail"], check


def test_backend_junit5_disabled_without_waiver_fails(tmp_path: Path):
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor="junit5",
        test_dir_files={
            "RefundTest.java": (
                "class RefundTest {\n"
                "  @Test\n"
                "  @DisplayName(\"[AC-TEST-001] 暂不做\")\n"
                "  @Disabled(\"later\")\n"
                "  void pending() {}\n"
                "}\n"
            ),
        },
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "无效跳过拦截")
    assert check is not None and check["status"] == "FAIL", check


def _external_extractor(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    return f"{sys.executable} {path}"


def test_backend_external_command_passes(tmp_path: Path):
    script = tmp_path / "extract.py"
    cmd = _external_extractor(script, (
        "import json\n"
        "print(json.dumps({'schema_version': 1, 'input_state': 'present', 'tests': [{\n"
        "  'name': 'T.ac', 'file': 'backend/tests/T.java', 'line': 3,\n"
        "  'acs': ['AC-TEST-001'], 'marker_acs': ['AC-TEST-001'], 'doc_acs': [],\n"
        "  'dims': ['C01'], 'dims_bad': [], 'dims_shape_ok': True, 'dims_present': True,\n"
        "  'skipped': False, 'waiver': '', 'weak': False, 'marker_scope_unsupported': False\n"
        "}], 'parse_errors': [], 'scan_face': []}))\n"
    ))
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor_command=cmd,
    )
    res = validate_ac_alignment(proj)
    assert res.status == "PASS", [(c["check"], c["status"], c["detail"]) for c in res.checks]
    dim = _check(res)
    assert dim is not None and dim["status"] == "PASS", dim


def test_backend_external_command_invalid_json_fails(tmp_path: Path):
    script = tmp_path / "extract.py"
    cmd = _external_extractor(script, "print('not json')\n")
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor_command=cmd,
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "测试提取通道")
    assert check is not None and "[EXTRACTOR]" in check["detail"], check


def test_backend_external_command_nonzero_fails(tmp_path: Path):
    script = tmp_path / "extract.py"
    cmd = _external_extractor(script, "import sys\nsys.stderr.write('bad\\n')\nsys.exit(3)\n")
    proj = create_backend_project(
        tmp_path,
        [("`AC-TEST-001`", "Given x When y Then z", "`R-001`", "", "C01")],
        None,
        extractor_command=cmd,
    )
    res = validate_ac_alignment(proj)
    assert res.status == "FAIL", res.status
    check = _check(res, "测试提取通道")
    assert check is not None and "退出码 3" in check["detail"], check


def test_backend_junit5_multi_module_test_dir_root(tmp_path: Path):
    """多模块 Maven/Gradle：单 app + test_dir: . 时递归盘点各模块测试。"""
    proj = create_backend_project(
        tmp_path,
        [
            ("`AC-MODA-001`", "Given x When y Then z", "`R-001`", "", "C01"),
            ("`AC-MODB-001`", "Given x When y Then z", "`R-002`", "", "C01"),
        ],
        None,
        extractor="junit5",
    )
    profile = proj / "product" / "stack-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("test_dir: backend/tests", "test_dir: ."),
        encoding="utf-8",
    )
    for module, ac in (("module-a", "AC-MODA-001"), ("module-b", "AC-MODB-001")):
        d = proj / module / "src" / "test" / "java" / "com" / "x"
        d.mkdir(parents=True)
        (d / f"{module.title()}Test.java").write_text(
            "class T {\n"
            "  @Test\n"
            f"  @DisplayName(\"[{ac}] case\")\n"
            "  @Tag(\"atlas-dims-C01\")\n"
            "  void t() {}\n"
            "}\n",
            encoding="utf-8",
        )
    res = validate_ac_alignment(proj)
    assert res.status == "PASS", [(c["check"], c["status"], c["detail"]) for c in res.checks]
    cov = _check(res, "AC覆盖对账")
    assert cov is not None and "覆盖: 2" in cov["detail"], cov
