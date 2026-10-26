#!/usr/bin/env python3
"""atlas 校验器 —— 后端与全栈验收标准（AC）对账门禁（Phase 1）。

依据 B209-1 / 3507 BT 决策（2026-10-12）：
  * **无主 AC 拦截（Dangling ACs）**：测试中挂载的 AC ID 必须在现有 PRD 资产中存在（无主即 FAIL）。
  * **无效跳过拦截（Unwaived Skip/Xfail）**：挂载了 AC 的测试若被标记为跳过（如 skip / xfail），
    必须附带显式豁免说明（`reason` 包含 `waiver:` 或 docstring 声明 `waiver:`），否则 FAIL。
  * **双向对账与覆盖清单（Alignment Coverage）**：
    提取各需求 PRD 的 AC 集合与测试代码映射。若配置为 enforce 模式，检查对应后端 AC 挂载覆盖度。
  * **差量防退化（Delta Ratchet）**：
    与上一次执行留存的基线快照比对，挂载 AC 的测试用例数与覆盖的 AC 数净增不得为负。
  * **AC × 覆盖维度（后端通道，D153）**：
    域级 PRD 验收表可选列 `后端适用覆盖维度` ⇔ 测试 `@pytest.mark.ac(..., dims=[...])`；
    缺维度 / 仅弱证据 / 零测试 / 未知 / 孤儿 ⇒ WARN（不 FAIL）。第 4 列仍归 E2E 门（D130）。

- **语言中立架构**：以 AST 提取器与模式匹配器双轨运行，v1 原生支持 Python 测试提取，预留适配器接口。
- **纯标准库**：无第三方依赖。
- 判定：`PASS`/`WARN`/`N/A` → 退出码 0；`FAIL` → 1。

用法：
    python3 validate_ac_alignment.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

# 随包内核引导（`_support/`，2026-10-12 单源批）：profile 解析走单源实现
# （本文件原持第三份手写解析，B209-1 引入时未收敛，见 `_support/stack_profile.py` 头注）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402
from _support.layout import LayoutError, load_layout  # noqa: E402

_sp = load_module("stack_profile")
ac_coverage = load_module("ac_coverage")
parse_dims_cell = ac_coverage.parse_dims_cell

AC_ID_RE = re.compile(r"\b(AC-[A-Z0-9]+-\d+)\b")
AC_ID_STRICT_RE = re.compile(r"^AC-[A-Z0-9]+-\d{3}$")
BACKEND_DIM_HEADER = "后端适用覆盖维度"
E2E_DIM_HEADER = "适用覆盖维度"
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__",
    ".venv", "venv", "vendor", ".cache", "out", "target", ".atlas", ".atlas-run"
}
BASELINE_PATH = Path(".atlas/runs/backend-ac-alignment.json")
_UNSUPPORTED = object()


class Result:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        statuses = {c["status"] for c in self.checks}
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        if self.checks and statuses <= {"N/A"}:
            return "N/A"
        return "PASS"


def load_stack_profile(root: Path, lay=None) -> dict[str, Any]:
    """经随包内核读取 stack-profile（单源口径，2026-10-12 单源批）。"""
    lay = lay or load_layout(root)
    path = lay.stack_profile
    if not path.is_file():
        return {}
    return _sp.parse_profile(path.read_text(encoding="utf-8"))


def collect_prd_acs(root: Path, lay=None) -> dict[str, set[str]]:
    """收集资产根/prd/ 目录下所有已声明的 AC ID。返回 {文件名: {AC_ID, ...}}。"""
    lay = lay or load_layout(root)
    prd_dir = lay.prd_dir
    if not prd_dir.is_dir():
        return {}
    acs_by_file: dict[str, set[str]] = {}
    valid_files = sorted(prd_dir.glob("*-prd.md"))
    prd_global = prd_dir / "prd.md"
    if prd_global.is_file():
        valid_files.insert(0, prd_global)

    for p in valid_files:
        content = p.read_text(encoding="utf-8")
        matches = set(AC_ID_RE.findall(content))
        if matches:
            acs_by_file[p.name] = matches
    return acs_by_file


class PyTestACVisitor(ast.NodeVisitor):
    """AST 遍历提取 pytest 函数/方法中的 AC、dims、skip/weak 与 docstring 归属。"""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.tests: list[dict[str, Any]] = []
        self.module_weak = False
        self.module_pytestmark_ac = False

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
            "weak": False, "uncertain": False,
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
                    dims, bad, ok = ac_coverage.parse_dims_list(val)
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
                info["uncertain"] = True
            elif path in ("pytest.mark.parametrize", "mark.parametrize", "parametrize"):
                if self._has_mark(dec, {"skip", "xfail", "skipif"}):
                    info["weak"] = True
                    info["uncertain"] = True
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
        func_name = f"{prefix}{node.name}" if prefix else node.name
        marker_acs: set[str] = set()
        dims: set[str] = set()
        dims_bad: list[str] = []
        dims_present = False
        dims_shape_ok = True
        is_skipped = False
        waiver_reason = ""
        weak = class_weak or self.module_weak
        uncertain = False

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
            uncertain = uncertain or info["uncertain"]

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
            "uncertain": uncertain,
            "pytestmark_ac_unsupported": class_pytestmark_ac or self.module_pytestmark_ac,
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


def scan_backend_tests_detailed(
    test_dir: Path, root: Path
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """扫描 Python 测试目录，返回 (tests, parse_errors, scan_face_warnings)。"""
    collected: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    scan_face: list[str] = []
    if not test_dir.is_dir():
        return collected, parse_errors, scan_face

    def _files(pattern: str) -> list[Path]:
        return sorted(
            p for p in test_dir.rglob(pattern)
            if not any(part in SKIP_DIRS for part in p.parts)
        )

    test_files = _files("test_*.py")
    star_files = _files("*_test.py")
    if star_files:
        names = ", ".join(str(p.relative_to(root)) for p in star_files[:3])
        scan_face.append(f"存在未扫描的 *_test.py：{len(star_files)} 个（{names}）")
    if not test_files:
        scan_face.append(f"扫描面无 test_*.py：{test_dir}")
        return collected, parse_errors, scan_face

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
    return collected, parse_errors, scan_face


def scan_backend_tests(test_dir: Path, root: Path) -> list[dict[str, Any]]:
    """兼容旧调用：只返回 tests（既有四条判据使用）。"""
    return scan_backend_tests_detailed(test_dir, root)[0]


def _strip_cell(raw) -> str:
    return ac_coverage.strip_md_cell(raw)


def _empty_dim_cell(raw) -> bool:
    return _strip_cell(raw) in ("", "N/A", "—", "-")


def collect_backend_dims(prd_dir: Path) -> tuple[dict[str, set[str]], list[str], bool]:
    """解析 `*-prd.md` 的 `后端适用覆盖维度` 列。

    返回 (declared, issues, had_legal)。had_legal = 至少一张 AC 表出现该表头。
    逐表处理：一个 4 列旧表 / 错表头文件只跳过自身，不擦掉其他域。
    """
    declared: dict[str, set[str]] = {}
    issues: list[str] = []
    had_legal = False
    if not prd_dir.is_dir():
        return declared, issues, had_legal

    for p in sorted(prd_dir.glob("*-prd.md")):
        text = p.read_text(encoding="utf-8")
        for header, rows in ac_coverage.iter_md_tables(text):
            hdr = [_strip_cell(c) for c in header]
            if "AC ID" not in hdr or "回指规则" not in hdr:
                continue
            ac_idx = hdr.index("AC ID")
            if BACKEND_DIM_HEADER in hdr:
                had_legal = True
                dim_idx = hdr.index(BACKEND_DIM_HEADER)
                if dim_idx == 3:
                    issues.append(
                        f"{p.name}: 后端维度列表头位于第 4 列（疑似与 E2E 列位混淆；建议保留第 4 列 E2E、把后端列放第 5 列）"
                    )
                for row in rows:
                    if ac_idx >= len(row):
                        continue
                    ac = _strip_cell(row[ac_idx])
                    if not AC_ID_RE.fullmatch(ac):
                        continue
                    if not AC_ID_STRICT_RE.fullmatch(ac):
                        issues.append(f"{ac} 不符合 NNN 契约")
                    cell = row[dim_idx] if dim_idx < len(row) else ""
                    if _empty_dim_cell(cell):
                        continue
                    dims, _looks = parse_dims_cell(cell)
                    unknown = ac_coverage.unknown_dim_tokens(cell)
                    if unknown:
                        issues.append(f"{p.name}:{ac} 后端维度含未知 token：{','.join(unknown)}")
                    if not dims:
                        issues.append(f"{p.name}:{ac} 后端维度无法解析：{cell!r}")
                        continue
                    if ac in declared:
                        suffix = "（后者覆盖前者）" if declared[ac] != dims else ""
                        issues.append(f"{p.name}:{ac} 后端维度重复声明{suffix}")
                    declared[ac] = dims
                continue

            # 没有合法后端表头：只对「表头含 维度/备注/后端 或列位 ≥5」的列做疑似扫描；
            # 永远排除第 4 列 `适用覆盖维度`（标准 E2E 表不得误判）。
            suspect = [
                i for i, h in enumerate(hdr)
                if h != E2E_DIM_HEADER
                and (("维度" in h) or ("备注" in h) or ("后端" in h) or i >= 4)
            ]
            hit = False
            for row in rows:
                if ac_idx >= len(row):
                    continue
                ac = _strip_cell(row[ac_idx])
                if not AC_ID_RE.fullmatch(ac):
                    continue
                for i in suspect:
                    if i < len(row) and ac_coverage.has_dim_claim(row[i]):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                issues.append(f"{p.name}: 疑似后端维度列但表头/列位不符")

    seen: set[str] = set()
    uniq: list[str] = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            uniq.append(issue)
    return declared, uniq, had_legal


def backend_channel_reason(root: Path, profile: dict[str, Any], backend_test_cfg: dict[str, Any]) -> str:
    """后端通道适用/可用判据；返回空串 = 可用。"""
    apps = profile.get("apps")
    if not isinstance(apps, list) or not apps:
        return "未声明 apps（无法判定后端通道）"
    kinds = [a.get("kind") for a in apps if isinstance(a, dict)]
    backend_kinds = [k for k in kinds if k in ("backend", "fullstack")]
    if not backend_kinds:
        return "无 backend/fullstack 应用（当前栈不适用）"
    if len(backend_kinds) > 1:
        return "多后端应用未建模（apps 中 backend/fullstack > 1）"
    if not backend_test_cfg:
        return "未声明 backend_test（合法降级）"
    framework = backend_test_cfg.get("framework")
    if framework and framework != "pytest":
        return f"framework={framework!r} 非 pytest（v1 仅支持 pytest）"
    test_dir = backend_test_cfg.get("test_dir") or "backend/tests"
    if not (root / test_dir).is_dir():
        return f"test_dir 不存在：{test_dir}"
    return ""


def _cap(items: list[str], n: int = 8) -> str:
    if len(items) <= n:
        return "、".join(items)
    return "、".join(items[:n]) + f"…（共 {len(items)}）"


def validate_ac_alignment(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    profile = load_stack_profile(root, lay)
    backend_test_cfg = profile.get("backend_test") or {}
    if not isinstance(backend_test_cfg, dict):
        backend_test_cfg = {}

    test_dir_str = backend_test_cfg.get("test_dir") or "backend/tests"
    test_dir = root / test_dir_str

    prd_acs_map = collect_prd_acs(root, lay)
    all_declared_acs: set[str] = set()
    for acs in prd_acs_map.values():
        all_declared_acs.update(acs)

    tests, parse_errors, scan_face = scan_backend_tests_detailed(test_dir, root)

    # 门控态：无 PRD 资产且无测试 ⇒ 整门 N/A（D153：不再伪装 PASS）
    if not all_declared_acs and not tests:
        res.add("AC对账门禁运行态", "N/A", "无 PRD 验收标准资产且无测试目录（不适用）")
        return res

    test_with_ac = [t for t in tests if t["acs"]]
    all_cited_acs: set[str] = set()
    dangling_acs: set[str] = set()
    unwaived_skips: list[str] = []

    for t in test_with_ac:
        for ac in t["acs"]:
            all_cited_acs.add(ac)
            if ac not in all_declared_acs:
                dangling_acs.add(f"{ac} ({t['file']}:{t['name']})")
        if t["skipped"]:
            waiver = t["waiver"].strip()
            if not waiver or "waiver:" not in waiver.lower():
                unwaived_skips.append(f"{t['file']}:{t['name']} (挂载 {','.join(t['acs'])})")

    if dangling_acs:
        res.add(
            "无主AC拦截", "FAIL",
            f"测试中引用的 AC ID 未在任何 {lay.print_value('prd')}/*.md 中声明：{sorted(dangling_acs)}",
        )
    else:
        res.add("无主AC拦截", "PASS", f"测试中引用的 {len(all_cited_acs)} 个 AC 均有合法 PRD 声明")

    if unwaived_skips:
        res.add(
            "无效跳过拦截", "FAIL",
            f"挂载 AC 的测试被 skip/xfail 但未附带合法的 waiver 豁免理由：{unwaived_skips}",
        )
    else:
        res.add("无效跳过拦截", "PASS", "所有挂载 AC 的跳过测试均具备有效豁免声明或无跳过")

    mode = backend_test_cfg.get("mode", "advisory")
    total_declared = len(all_declared_acs)
    total_cited = len(all_cited_acs)
    coverage_ratio = (total_cited / total_declared) if total_declared > 0 else 1.0
    detail_msg = f"已声明 AC: {total_declared}，后端测试挂载覆盖: {total_cited} ({coverage_ratio:.1%})"
    if mode == "enforce" and total_declared > 0 and total_cited == 0:
        res.add("AC覆盖对账", "FAIL", f"{detail_msg}（enforce 模式下不允许零测试挂载）")
    else:
        res.add("AC覆盖对账", "PASS", detail_msg)

    # ---- 判据 5：AC × 覆盖维度（后端通道）
    declared_dims, dim_issues, had_legal = collect_backend_dims(lay.prd_dir)
    reason = backend_channel_reason(root, profile, backend_test_cfg)
    check = "AC × 覆盖维度（后端通道）"

    if reason:
        detail = reason
        if dim_issues:
            detail += "；" + "；".join(dim_issues[:4])
        res.add(check, "WARN" if dim_issues else "N/A", detail)
    elif not had_legal:
        if dim_issues:
            res.add(check, "WARN", "；".join(dim_issues[:4]))
        else:
            res.add(check, "N/A", "未声明「后端适用覆盖维度」列（按需启用）")
    elif not declared_dims:
        detail = "后端列已存在但未声明任何维度"
        if dim_issues:
            detail += "；" + "；".join(dim_issues[:4])
        res.add(check, "WARN" if dim_issues else "N/A", detail)
    else:
        unique: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for t in tests:
            key = (t["file"], t["line"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)

        zero: list[str] = []
        missing: list[str] = []
        weak_only: list[str] = []
        bad: list[str] = []
        empty: list[str] = []
        multi: list[str] = []
        orphan: list[str] = []
        shape: list[str] = []
        pm_ac: set[str] = set()

        for t in unique:
            label = f"{t['file']}:{t['name']}"
            if t.get("pytestmark_ac_unsupported"):
                pm_ac.add(t["file"])
            if t.get("dims_bad"):
                bad.append(f"{label}={'/'.join(t['dims_bad'])}")
            if t.get("dims_present") and not t.get("dims_shape_ok"):
                shape.append(label)
            if t.get("dims_present") and not t.get("dims_bad") and t.get("dims_shape_ok") and not t.get("dims"):
                empty.append(label)
            if t.get("dims_present") and not t.get("marker_acs"):
                orphan.append(label)
            if t.get("dims_present") and len(t.get("marker_acs") or ()) > 1:
                multi.append(label)

        for ac, dims in sorted(declared_dims.items()):
            ac_tests = [t for t in unique if ac in t["marker_acs"]]
            if not ac_tests:
                zero.append(ac)
                continue
            active: set[str] = set()
            weak: set[str] = set()
            for t in ac_tests:
                if t.get("dims_present") and len(t.get("marker_acs") or ()) != 1:
                    continue
                if not t.get("dims_shape_ok", True):
                    continue
                (weak if t.get("weak") else active).update(t.get("dims") or ())
            covered = active | weak
            miss = dims - covered
            if miss:
                missing.append(f"{ac}缺{','.join(sorted(miss))}")
            weak_only_dims = (dims & weak) - active
            if weak_only_dims:
                weak_only.append(f"{ac}仅弱证据={'/'.join(sorted(weak_only_dims))}")

        parts: list[str] = []
        if zero:
            parts.append(f"零测试={_cap(zero)}")
        if missing:
            parts.append(f"缺维度={_cap(missing)}")
        if weak_only:
            parts.append(f"弱证据={_cap(weak_only)}")
        if bad:
            parts.append(f"未知维度={_cap(bad, 4)}")
        if empty:
            parts.append(f"空dims={_cap(empty, 4)}")
        if multi:
            parts.append(f"一测多AC带dims={_cap(multi, 4)}")
        if orphan:
            parts.append(f"孤儿dims={_cap(orphan, 4)}")
        if shape:
            parts.append(f"dims形态不支持={_cap(shape, 4)}")
        if pm_ac:
            parts.append(f"pytestmark挂AC不支持={_cap(sorted(pm_ac), 4)}")
        if dim_issues:
            parts.append("；".join(dim_issues[:4]))
        if scan_face:
            parts.extend(scan_face[:2])
        if parse_errors:
            parts.append(f"解析失败={len(parse_errors)}个：{'; '.join(parse_errors[:3])}")

        status = "WARN" if parts else "PASS"
        detail = "；".join(parts) if parts else f"{len(declared_dims)} 条 AC 后端维度全量覆盖"
        res.add(check, status, detail)

    # ---- 判据 4：差量防回退 (Delta Ratchet)
    baseline_file = root / BASELINE_PATH
    delta_issues = []
    current_snapshot = {
        "tests_with_ac_count": len(test_with_ac),
        "covered_acs_count": len(all_cited_acs),
        "total_test_count": len(tests),
    }

    if baseline_file.is_file():
        try:
            prev = json.loads(baseline_file.read_text(encoding="utf-8"))
            if current_snapshot["tests_with_ac_count"] < prev.get("tests_with_ac_count", 0):
                delta_issues.append(
                    f"挂载测试数退化: {current_snapshot['tests_with_ac_count']} < 基线 {prev.get('tests_with_ac_count')}"
                )
            if current_snapshot["covered_acs_count"] < prev.get("covered_acs_count", 0):
                delta_issues.append(
                    f"覆盖 AC 范围退化: {current_snapshot['covered_acs_count']} < 基线 {prev.get('covered_acs_count')}"
                )
        except Exception:
            pass

    if delta_issues:
        res.add("差量防回退", "WARN", "；".join(delta_issues))
    else:
        res.add("差量防回退", "PASS", f"当前挂载测试数: {len(test_with_ac)}，覆盖 AC 数: {len(all_cited_acs)}")

    if res.status != "FAIL":
        try:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(
                json.dumps(current_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    return res


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="项目根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    root = args.root.resolve()
    result = validate_ac_alignment(root)

    if args.json:
        payload = {
            "status": result.status,
            "root": str(root),
            "checks": result.checks,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"validate_ac_alignment @ {root}")
        for c in result.checks:
            detail = f" —— {c['detail']}" if c["detail"] else ""
            print(f"  [{c['status']:<4}] {c['check']}{detail}")
        print(result.status)

    return 1 if result.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
