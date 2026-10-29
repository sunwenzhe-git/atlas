#!/usr/bin/env python3
"""pytest AC 提取器（框架知识的合法落点）。

本文件是 `validators/validate_ac_alignment.py` 的 pytest 扫描实现：
只做「测试文件 → 归一化记录」，不判门、不读 PRD、不生成 baseline。
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

from . import ExtractResult

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from _support.siblings import load_module  # noqa: E402
from _support.layout import load_layout  # noqa: E402

_ac_coverage = load_module("ac_coverage")

# ---------------------------------------------------------------- 项目级配置兜底
# 注释剥离（2026-10-15 事故）：出厂模板的 `backend_test:` 段是**注释示例**，逐字匹配 raw
# 文本会把**每个**按模板开户的项目判成 Python 工程 ⇒ 纯前端仓库里凭空多出一个 pytest.ini。
# ⇒ 只认**声明项**。
RE_COMMENT = re.compile(r"(?:^|\s+)#.*$")

MARKERS_INI = (
    "[pytest]\n"
    "markers =\n"
    "    ac: mark test with AC ID for traceability\n"
)


def is_python_project(target: Path) -> bool:
    """探测是否为 Python 工程（stack-profile **声明**或根目录 Python 特征文件）。

    只看**声明**：注释里出现的关键字不算。声明面三种任一生效：
    `python` 字样 / `framework: pytest` / `extractor: pytest`。
    `backend_test:` 是框架中立的调度段，不能单独作为 Python 证据。
    显式声明了其它 extractor ⇒ 不是本 adapter 的项目。
    """
    prof_path = load_layout(target).stack_profile
    if prof_path.is_file():
        text = prof_path.read_text(encoding="utf-8", errors="ignore")
        declared = "\n".join(RE_COMMENT.sub("", ln) for ln in text.splitlines()).lower()
        m = re.search(r"^\s+(?:extractor|framework):\s*([a-z0-9][a-z0-9_-]*)\s*$",
                      declared, re.M)
        if m and m.group(1) != "pytest":
            return False
        if ("python" in declared
                or "framework: pytest" in declared
                or "extractor: pytest" in declared):
            return True
    for marker in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile", ".venv"):
        if (target / marker).exists():
            return True
    return False


def _has_pytest_section(pyproject: Path) -> bool:
    try:
        return "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def wire_project(target: Path, force: bool = False) -> dict:
    """AC 标记注册兜底——**载体优先级：已有配置 > 既有 ini > 新建 ini**。

    R6.2 对账定稿（2026-10-15）：本兜底只承担 **`ac` marker 注册**这一项正当元数据；
    `pythonpath = .` 环境补丁已随 F23 退役。

    **退役对称**：非本 adapter 工程里若躺着一份**逐字节等于兜底内容**的 ini，那是本
    脚本早先误建的 ⇒ 清掉；用户改过 ⇒ 一字不动。
    """
    ini_path = target / "pytest.ini"
    if not force and not is_python_project(target):
        if ini_path.is_file() and ini_path.read_text(encoding="utf-8") == MARKERS_INI:
            return {"file": "pytest.ini", "status": "removed",
                    "detail": "非本 extractor 工程：清掉早先误建的配置"
                              "（仅当内容逐字节等于兜底内容；用户改过则保留）",
                    "_remove": ini_path}
        return {"file": "pytest.ini", "status": "skipped", "detail": "非本 extractor 工程，跳过"}

    pyproject = target / "pyproject.toml"
    setup_cfg = target / "setup.cfg"

    if pyproject.is_file() and _has_pytest_section(pyproject):
        return {"file": "pytest.ini", "status": "skipped", "detail": "已由 pyproject.toml 承载配置"}
    if setup_cfg.is_file():
        text_cfg = setup_cfg.read_text(encoding="utf-8", errors="ignore")
        if "[tool:pytest]" in text_cfg:
            return {"file": "pytest.ini", "status": "skipped", "detail": "已由 setup.cfg 承载配置"}

    if not ini_path.is_file():
        return {"file": "pytest.ini", "status": "applied",
                "detail": "created pytest.ini with ac marker registration",
                "_write": (ini_path, MARKERS_INI)}

    content = ini_path.read_text(encoding="utf-8")
    if "markers" in content:
        return {"file": "pytest.ini", "status": "skipped", "detail": "pytest.ini 已包含 marker 注册"}

    new_content = content.rstrip("\n") + "\nmarkers =\n    ac: mark test with AC ID for traceability\n"
    return {"file": "pytest.ini", "status": "applied",
            "detail": "appended ac marker registration to existing pytest.ini",
            "_write": (ini_path, new_content)}

AC_ID_RE = re.compile(r"\b(AC-[A-Z0-9]+-\d+)\b")
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__",
    ".venv", "venv", "vendor", ".cache", "out", "target", ".atlas", ".atlas-run", ".scratch", ".trellis",
}
_UNSUPPORTED = object()


class PyTestACVisitor(ast.NodeVisitor):
    """AST 遍历提取 pytest 函数/方法中的 AC、dims、skip/weak 与 docstring 归属。"""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.tests: list[dict[str, Any]] = []
        self.module_weak = False
        self.module_pytestmark_ac = False
        self.seen: set[tuple[str, int]] = set()

    @staticmethod
    def _call_path(node: ast.AST) -> str:
        if not isinstance(node, ast.Call):
            return ""
        names: list[str] = []
        cur = node.func
        while isinstance(cur, ast.Attribute):
            names.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            names.append(cur.id)
        names.reverse()
        return ".".join(names)

    @staticmethod
    def _literal(node: ast.AST):
        try:
            return ast.literal_eval(node)
        except Exception:
            return _UNSUPPORTED

    @staticmethod
    def _has_mark(node: ast.AST, names: set[str]) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and sub.attr in names:
                return True
            if isinstance(sub, ast.Name) and sub.id in names:
                return True
        return False

    def _decorator_info(self, dec: ast.AST) -> dict[str, Any]:
        info: dict[str, Any] = {
            "acs": set(), "dims": set(), "dims_bad": [], "dims_shape_ok": True,
            "dims_present": False, "skipped": False, "waiver": "",
            "weak": False,
        }
        if isinstance(dec, ast.Call):
            path = self._call_path(dec)
            if path in ("pytest.mark.ac", "mark.ac", "ac"):
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        info["acs"].update(AC_ID_RE.findall(arg.value))
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                info["acs"].update(AC_ID_RE.findall(elt.value))
                for kw in dec.keywords:
                    if kw.arg != "dims":
                        continue
                    info["dims_present"] = True
                    val = self._literal(kw.value)
                    if val is _UNSUPPORTED:
                        info["dims_shape_ok"] = False
                        continue
                    dims, bad, ok = _ac_coverage.parse_dims_list(val)
                    info["dims"] = dims
                    info["dims_bad"] = bad
                    info["dims_shape_ok"] = ok
            elif path in ("pytest.mark.skip", "pytest.mark.xfail", "mark.skip", "mark.xfail", "skip", "xfail"):
                info["skipped"] = True
                info["weak"] = True
                for kw in dec.keywords:
                    if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        info["waiver"] = kw.value.value
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        info["waiver"] = arg.value
            elif path in ("pytest.mark.skipif", "mark.skipif", "skipif"):
                info["weak"] = True
            elif path in ("pytest.mark.parametrize", "mark.parametrize", "parametrize"):
                if self._has_mark(dec, {"skip", "xfail", "skipif"}):
                    info["weak"] = True
        elif isinstance(dec, ast.Attribute):
            if dec.attr in ("skip", "xfail"):
                info["skipped"] = True
                info["weak"] = True
        elif isinstance(dec, ast.Name) and dec.id in ("skip", "xfail"):
            info["skipped"] = True
            info["weak"] = True
        return info

    def _scan_pytestmark(self, node: ast.AST) -> tuple[bool, bool]:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            return False, False
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            return False, False
        value = node.value
        if value is None:
            return False, False
        return (
            self._has_mark(value, {"skip", "xfail", "skipif"}),
            self._has_mark(value, {"ac"}),
        )

    def visit_Module(self, node: ast.Module) -> None:
        for item in node.body:
            weak, ac = self._scan_pytestmark(item)
            self.module_weak = self.module_weak or weak
            self.module_pytestmark_ac = self.module_pytestmark_ac or ac
        self.generic_visit(node)

    def _visit_test_func(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str = "",
        class_weak: bool = False,
        class_pytestmark_ac: bool = False,
    ) -> None:
        if not node.name.startswith("test_"):
            return
        key = (self.rel_path, node.lineno)
        if key in self.seen:
            return
        self.seen.add(key)
        func_name = f"{prefix}{node.name}" if prefix else node.name
        marker_acs: set[str] = set()
        dims: set[str] = set()
        dims_bad: list[str] = []
        dims_present = False
        dims_shape_ok = True
        is_skipped = False
        waiver_reason = ""
        weak = class_weak or self.module_weak

        for dec in node.decorator_list:
            info = self._decorator_info(dec)
            marker_acs.update(info["acs"])
            if info["dims_present"]:
                dims_present = True
                dims.update(info["dims"])
                dims_bad.extend(info["dims_bad"])
                dims_shape_ok = dims_shape_ok and info["dims_shape_ok"]
            if info["skipped"]:
                is_skipped = True
                if info["waiver"]:
                    waiver_reason = info["waiver"]
            weak = weak or info["weak"]

        doc = ast.get_docstring(node) or ""
        doc_acs: set[str] = set()
        if doc:
            doc_acs.update(AC_ID_RE.findall(doc))
            if "waiver:" in doc.lower():
                waiver_reason = waiver_reason or doc

        self.tests.append({
            "name": func_name,
            "file": self.rel_path,
            "line": node.lineno,
            "acs": marker_acs | doc_acs,
            "marker_acs": marker_acs,
            "doc_acs": doc_acs,
            "dims": dims,
            "dims_bad": dims_bad,
            "dims_shape_ok": dims_shape_ok,
            "dims_present": dims_present,
            "skipped": is_skipped,
            "waiver": waiver_reason,
            "weak": weak,
            "marker_scope_unsupported": class_pytestmark_ac or self.module_pytestmark_ac,
        })

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_test_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_test_func(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_weak = self.module_weak
        class_ac = self.module_pytestmark_ac
        for item in node.body:
            weak, ac = self._scan_pytestmark(item)
            class_weak = class_weak or weak
            class_ac = class_ac or ac
        if node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._visit_test_func(
                        item, prefix=f"{node.name}.", class_weak=class_weak,
                        class_pytestmark_ac=class_ac,
                    )
        self.generic_visit(node)


def _files(test_dir: Path, pattern: str) -> list[Path]:
    return sorted(
        p for p in test_dir.rglob(pattern)
        if not any(part in SKIP_DIRS for part in p.parts)
    )


def scan_backend_tests_detailed(
    test_dir: Path, root: Path
) -> tuple[list[dict[str, Any]], list[str], list[str], str]:
    """扫描 Python 测试目录，返回 (tests, parse_errors, scan_face, input_state)。"""
    collected: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    scan_face: list[str] = []
    if not test_dir.is_dir():
        return collected, parse_errors, scan_face, "absent"

    test_files = _files(test_dir, "test_*.py")
    star_files = _files(test_dir, "*_test.py")
    input_state = "present" if test_files or star_files else "absent"
    if star_files:
        names = ", ".join(str(p.relative_to(root)) for p in star_files[:3])
        scan_face.append(f"存在未扫描的 *_test.py：{len(star_files)} 个（{names}）")
    if not test_files:
        scan_face.append(f"扫描面无 test_*.py：{test_dir}")
        return collected, parse_errors, scan_face, input_state

    for p in test_files:
        try:
            rel = str(p.relative_to(root))
            source = p.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(p))
            visitor = PyTestACVisitor(rel)
            visitor.visit(tree)
            collected.extend(visitor.tests)
        except Exception as exc:
            parse_errors.append(f"{p.relative_to(root)}: {exc}")
    return collected, parse_errors, scan_face, input_state


def scan_backend_tests(test_dir: Path, root: Path) -> list[dict[str, Any]]:
    """兼容旧调用：只返回 tests。"""
    return scan_backend_tests_detailed(test_dir, root)[0]


class Extractor:
    name = "pytest"

    def extract(self, root: Path, test_dir: Path, cfg: dict[str, Any] | None = None) -> ExtractResult:
        tests, parse_errors, scan_face, input_state = scan_backend_tests_detailed(test_dir, root)
        return ExtractResult(
            tests=tests,
            parse_errors=parse_errors,
            scan_face=scan_face,
            input_state=input_state,
        )

    def wire_project(self, target: Path, name: str | None = None) -> dict:
        return wire_project(target, force=bool(name))
