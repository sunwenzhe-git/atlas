#!/usr/bin/env python3
"""adapters/ac 注册表与 pytest adapter 的出厂测试。"""
from __future__ import annotations

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from adapters.ac import DEFAULT, ExtractResult, available, resolve  # noqa: E402
from adapters.ac import command as ac_command  # noqa: E402


def _extract(tmp_path: Path, files: dict[str, str]):
    for name, code in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(code, encoding="utf-8")
    adapter = resolve("pytest")
    assert adapter is not None
    return adapter.extract(tmp_path, tmp_path, {})


def test_registry_resolves_default_and_rejects_unknown() -> None:
    assert DEFAULT == "pytest"
    assert available() == ["pytest", "vitest", "jest", "junit5"]
    assert resolve(None) is not None
    assert resolve("pytest") is not None
    assert resolve("vitest") is not None
    assert resolve("jest") is not None
    assert resolve("junit5") is not None
    assert resolve("no-such-extractor") is None


def test_pytest_extract_normalizes_record(tmp_path: Path) -> None:
    result = _extract(tmp_path, {
        "test_a.py": (
            "import pytest\n\n"
            "@pytest.mark.ac('AC-X-001', dims=['C01'])\n"
            "def test_ok():\n"
            "    assert True\n"
        ),
    })
    assert isinstance(result, ExtractResult)
    assert result.input_state == "present"
    assert len(result.tests) == 1
    t = result.tests[0]
    assert t["name"] == "test_ok"
    assert t["acs"] == {"AC-X-001"}
    assert t["marker_acs"] == {"AC-X-001"}
    assert t["doc_acs"] == set()
    assert t["dims"] == {"C01"}
    assert t["marker_scope_unsupported"] is False
    assert "uncertain" not in t
    assert "pytestmark_ac_unsupported" not in t


def test_pytest_input_state_absent_and_scan_face(tmp_path: Path) -> None:
    result = _extract(tmp_path, {"other.txt": "nothing\n"})
    assert result.input_state == "absent"
    assert any("扫描面无" in s for s in result.scan_face)

    star = _extract(tmp_path, {
        "foo_test.py": "def test_x():\n    assert True\n",
    })
    assert star.input_state == "present"
    assert any("*_test.py" in s for s in star.scan_face)


def test_pytest_parse_errors_are_reported(tmp_path: Path) -> None:
    result = _extract(tmp_path, {"test_bad.py": "def broken(:\n"})
    assert result.input_state == "present"
    assert result.tests == []
    assert result.parse_errors and "test_bad.py" in result.parse_errors[0]


def test_class_methods_are_not_duplicated(tmp_path: Path) -> None:
    result = _extract(tmp_path, {
        "test_class.py": (
            "import pytest\n\n"
            "class TestX:\n"
            "    @pytest.mark.ac('AC-X-001')\n"
            "    def test_ok(self):\n"
            "        assert True\n"
        ),
    })
    assert len(result.tests) == 1
    assert result.tests[0]["name"] == "TestX.test_ok"


def test_module_pytestmark_ac_marks_scope_unsupported(tmp_path: Path) -> None:
    result = _extract(tmp_path, {
        "test_scope.py": (
            "import pytest\n"
            "pytestmark = pytest.mark.ac('AC-X-001')\n\n"
            "@pytest.mark.ac('AC-X-001')\n"
            "def test_ok():\n"
            "    assert True\n"
        ),
    })
    assert result.tests[0]["marker_scope_unsupported"] is True


def _extract_js(tmp_path: Path, name: str, files: dict[str, str]):
    for rel, code in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
    adapter = resolve(name)
    assert adapter is not None
    return adapter.extract(tmp_path, tmp_path, {})


def test_vitest_title_ac_and_jsdoc_dims(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "vitest", {
        "backend/src/refund.test.ts": (
            "/** @atlas-dims C01,C11 */\n"
            "it('[AC-PAYMENT-001] rejects insufficient balance', () => {});\n"
        ),
    })
    assert result.input_state == "present"
    assert len(result.tests) == 1
    t = result.tests[0]
    assert t["acs"] == {"AC-PAYMENT-001"}
    assert t["dims"] == {"C01", "C11"}
    assert t["name"] == "[AC-PAYMENT-001] rejects insufficient balance"
    assert t["marker_scope_unsupported"] is False


def test_jest_skip_waiver_and_todo(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "jest", {
        "__tests__/refund.spec.js": (
            "test.skip('[AC-P-002] retry waiver: sandbox', () => {});\n"
            "test.todo('[AC-P-003] pending');\n"
        ),
    })
    assert result.tests[0]["skipped"] is True
    assert "waiver:" in result.tests[0]["waiver"]
    assert result.tests[1]["skipped"] is True
    assert result.tests[1]["waiver"] == ""


def test_describe_skip_marks_children_and_scope_unsupported(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "vitest", {
        "group.test.ts": (
            "describe.skip('[AC-GROUP-001] group', () => {\n"
            "  it('child without own AC', () => {});\n"
            "});\n"
        ),
    })
    t = result.tests[0]
    assert t["skipped"] is True
    assert t["marker_scope_unsupported"] is True
    assert any("describe 级" in s for s in result.scan_face)


def test_js_dynamic_title_is_weak_and_reported(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "vitest", {
        "dyn.test.ts": "it(`[AC-DYN-001] ${'${label}'}`, () => {});\n",
    })
    t = result.tests[0]
    assert t["acs"] == {"AC-DYN-001"}
    assert t["weak"] is True
    assert any("动态标题" in s for s in result.scan_face)


def test_js_e2e_scripts_are_excluded(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "vitest", {
        "product/e2e/scripts/home.spec.ts": "it('[AC-E2E-001] ui', () => {});\n",
        "backend/src/home.test.ts": "it('[AC-BE-001] api', () => {});\n",
    })
    assert [t["acs"] for t in result.tests] == [{"AC-BE-001"}]


def test_js_absent_input(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "jest", {"README.md": "nothing\n"})
    assert result.input_state == "absent"
    assert any("扫描面无" in s for s in result.scan_face)


def test_junit5_display_name_ac_tags_and_disabled(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "junit5", {
        "src/test/java/com/x/RefundTest.java": (
            "class RefundTest {\n"
            "  @Test\n"
            "  @DisplayName(\"[AC-PAY-001] 余额不足拒绝\")\n"
            "  @Tag(\"atlas-dims-C01\")\n"
            "  @Tag(\"atlas-dims-C11\")\n"
            "  void refundRejected() {}\n\n"
            "  @Test\n"
            "  @DisplayName(\"[AC-PAY-002] 网关重试\")\n"
            "  @Disabled(\"waiver: 沙箱依赖\")\n"
            "  void retry() {}\n"
            "}\n"
        ),
    })
    assert result.input_state == "present"
    assert result.tests[0]["acs"] == {"AC-PAY-001"}
    assert result.tests[0]["dims"] == {"C01", "C11"}
    assert result.tests[1]["skipped"] is True
    assert "waiver:" in result.tests[1]["waiver"]


def test_junit5_class_scope_is_unsupported(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "junit5", {
        "src/test/java/com/x/GroupTest.java": (
            "@DisplayName(\"[AC-GROUP-001] group\")\n"
            "class GroupTest {\n"
            "  @Test\n"
            "  void child() {}\n"
            "}\n"
        ),
    })
    assert result.tests[0]["marker_scope_unsupported"] is True
    assert any("class 级" in s for s in result.scan_face)


def test_junit5_parameterized_is_weak(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "junit5", {
        "src/test/java/com/x/PTest.java": (
            "class PTest {\n"
            "  @ParameterizedTest\n"
            "  @DisplayName(\"[AC-P-001] 参数化 {0}\")\n"
            "  void p(String x) {}\n"
            "}\n"
        ),
    })
    t = result.tests[0]
    assert t["acs"] == {"AC-P-001"}
    assert t["weak"] is True
    assert any("参数化" in s for s in result.scan_face)


def test_junit5_comments_are_ignored(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "junit5", {
        "src/test/java/com/x/C.java": (
            "class C {\n"
            "  // @Test\n"
            "  // @DisplayName(\"[AC-FAKE-001] commented\")\n"
            "  void notATest() {}\n"
            "}\n"
        ),
    })
    assert result.tests == []


def test_junit5_absent_input(tmp_path: Path) -> None:
    result = _extract_js(tmp_path, "junit5", {"README.md": "nothing\n"})
    assert result.input_state == "absent"
    assert any("扫描面无" in s for s in result.scan_face)


def _fake_extractor(tmp_path: Path, body: str) -> str:
    script = tmp_path / "extract.py"
    script.write_text(body, encoding="utf-8")
    return f"{sys.executable} {script}"


def test_external_command_valid_json(tmp_path: Path) -> None:
    cmd = _fake_extractor(tmp_path, (
        "import json\n"
        "print(json.dumps({'schema_version': 1, 'input_state': 'present',\n"
        "  'tests': [{'name': 'J.t', 'file': 'T.java', 'line': 1, 'acs': ['AC-X-001'],\n"
        "    'marker_acs': ['AC-X-001'], 'doc_acs': [], 'dims': [], 'dims_bad': [],\n"
        "    'dims_shape_ok': True, 'dims_present': False, 'skipped': False,\n"
        "    'waiver': '', 'weak': False, 'marker_scope_unsupported': False}],\n"
        "  'parse_errors': [], 'scan_face': []}))\n"
    ))
    result = ac_command.run(cmd, tmp_path, tmp_path)
    assert result.input_state == "present"
    assert result.tests[0]["acs"] == ["AC-X-001"]
    assert result.parse_errors == []


def test_external_command_invalid_json_fails(tmp_path: Path) -> None:
    cmd = _fake_extractor(tmp_path, "print('not json')\n")
    try:
        ac_command.run(cmd, tmp_path, tmp_path)
    except ac_command.ExtractError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON must fail")


def test_external_command_nonzero_exit_fails(tmp_path: Path) -> None:
    cmd = _fake_extractor(tmp_path, "import sys\nsys.stderr.write('boom\\n')\nsys.exit(2)\n")
    try:
        ac_command.run(cmd, tmp_path, tmp_path)
    except ac_command.ExtractError as exc:
        assert "退出码 2" in str(exc) and "boom" in str(exc)
    else:
        raise AssertionError("non-zero exit must fail")


def test_external_command_missing_executable_fails(tmp_path: Path) -> None:
    try:
        ac_command.run("definitely-no-such-command-xyz", tmp_path, tmp_path)
    except ac_command.ExtractError as exc:
        assert "命令不存在" in str(exc)
    else:
        raise AssertionError("missing executable must fail")


def test_external_command_schema_version_required(tmp_path: Path) -> None:
    cmd = _fake_extractor(tmp_path, "import json\nprint(json.dumps({'tests': []}))\n")
    try:
        ac_command.run(cmd, tmp_path, tmp_path)
    except ac_command.ExtractError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("schema_version must be required")
