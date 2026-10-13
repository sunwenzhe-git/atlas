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

- **语言中立架构**：以 AST 提取器与模式匹配器双轨运行，v1 原生支持 Python 测试提取，预留适配器接口。
- **纯标准库**：无第三方依赖。
- 判定：`PASS`/`WARN` → 退出码 0；`FAIL` → 1。

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

_sp = load_module("stack_profile")

AC_ID_RE = re.compile(r"\b(AC-[A-Z0-9]+-\d+)\b")
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__",
    ".venv", "venv", "vendor", ".cache", "out", "target", ".atlas", ".atlas-run"
}
BASELINE_PATH = Path(".atlas/runs/backend-ac-alignment.json")


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
        return "PASS"


def load_stack_profile(root: Path) -> dict[str, Any]:
    """经随包内核读取 stack-profile（单源口径，2026-10-12 单源批）。

    原为本文件自持的轻量扁平解析（第三份副本，B209-1 批引入时未收敛）——已改走
    `_support/stack_profile.py` 唯一实现（`_support.siblings.load_module` 引导）。
    """
    path = root / "product" / "stack-profile.yaml"
    if not path.is_file():
        return {}
    return _sp.parse_profile(path.read_text(encoding="utf-8"))


def collect_prd_acs(root: Path) -> dict[str, set[str]]:
    """收集 product/prd/ 目录下所有已声明的 AC ID。返回 {文件名: {AC_ID, ...}}。

    契约（rings/prd/reference.md §2）：仅扫平铺规范文件（prd.md 与 *-prd.md），
    显式排除 reviews/ 等子目录及 README.md，避免历史评审或说明文档中残留的旧 AC 污染。
    """
    prd_dir = root / "product" / "prd"
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
    """AST 遍历提取 pytest 函数及方法中的 AC 挂载与 skip 状态。"""

    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        # list of {name, file, line, acs, skipped, waiver}
        self.tests: list[dict[str, Any]] = []

    def _extract_acs_from_decorator(self, dec: ast.AST) -> tuple[set[str], bool, str]:
        """返回 (acs, is_skipped, waiver_reason)"""
        acs: set[str] = set()
        is_skipped = False
        waiver = ""

        # 形如 @pytest.mark.ac("AC-xxx") or @pytest.mark.skip(reason="waiver: ...")
        if isinstance(dec, ast.Call):
            func = dec.func
            # 装饰器名称提取
            names = []
            cur = func
            while isinstance(cur, ast.Attribute):
                names.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                names.append(cur.id)
            names.reverse()
            call_path = ".".join(names)

            if call_path in ("pytest.mark.ac", "mark.ac", "ac"):
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        for m in AC_ID_RE.findall(arg.value):
                            acs.add(m)
                    elif isinstance(arg, (ast.List, ast.Tuple)):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for m in AC_ID_RE.findall(elt.value):
                                    acs.add(m)
            elif call_path in ("pytest.mark.skip", "pytest.mark.xfail", "mark.skip", "mark.xfail", "skip", "xfail"):
                is_skipped = True
                for kw in dec.keywords:
                    if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        waiver = kw.value.value
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        waiver = arg.value
        elif isinstance(dec, ast.Attribute):
            # 无参 @pytest.mark.skip
            if dec.attr in ("skip", "xfail"):
                is_skipped = True

        return acs, is_skipped, waiver

    def _visit_test_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str = "") -> None:
        if not node.name.startswith("test_"):
            return
        func_name = f"{prefix}{node.name}" if prefix else node.name
        acs: set[str] = set()
        is_skipped = False
        waiver_reason = ""

        for dec in node.decorator_list:
            d_acs, d_skip, d_waiver = self._extract_acs_from_decorator(dec)
            acs.update(d_acs)
            if d_skip:
                is_skipped = True
                if d_waiver:
                    waiver_reason = d_waiver

        # 检查 docstring 兜底
        doc = ast.get_docstring(node) or ""
        if doc:
            for m in AC_ID_RE.findall(doc):
                acs.add(m)
            if "waiver:" in doc.lower():
                waiver_reason = waiver_reason or doc

        self.tests.append({
            "name": func_name,
            "file": self.rel_path,
            "line": node.lineno,
            "acs": acs,
            "skipped": is_skipped,
            "waiver": waiver_reason,
        })

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_test_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_test_func(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._visit_test_func(item, prefix=f"{node.name}.")
        self.generic_visit(node)


def scan_backend_tests(test_dir: Path, root: Path) -> list[dict[str, Any]]:
    """扫描 Python 测试目录提取所有挂载了 AC 的测试用例。"""
    collected: list[dict[str, Any]] = []
    if not test_dir.is_dir():
        return collected

    for p in test_dir.rglob("test_*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            rel = str(p.relative_to(root))
            source = p.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(p))
            visitor = PyTestACVisitor(rel)
            visitor.visit(tree)
            collected.extend(visitor.tests)
        except Exception:
            # 语法解析失败等，暂跳过或记录
            continue
    return collected


def validate_ac_alignment(root: Path) -> Result:
    res = Result()
    profile = load_stack_profile(root)
    backend_test_cfg = profile.get("backend_test") or {}
    if not isinstance(backend_test_cfg, dict):
        backend_test_cfg = {}

    test_dir_str = backend_test_cfg.get("test_dir") or "backend/tests"
    test_dir = root / test_dir_str

    # 1. 收集已声明的合法 AC 集合
    prd_acs_map = collect_prd_acs(root)
    all_declared_acs: set[str] = set()
    for acs in prd_acs_map.values():
        all_declared_acs.update(acs)

    # 2. 扫描测试用例
    tests = scan_backend_tests(test_dir, root) if test_dir.is_dir() else []

    # 门控态：若没有任何 PRD 文件，且没有测试目录，给 N/A
    if not all_declared_acs and not tests:
        res.add("AC对账门禁运行态", "PASS", "无 PRD 验收标准资产且无测试目录，门禁降级通过")
        return res

    # 3. 统计挂载情况
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

    # ---- 判据 1：无主 AC 拦截 (Dangling ACs)
    if dangling_acs:
        res.add(
            "无主AC拦截",
            "FAIL",
            f"测试中引用的 AC ID 未在任何 product/prd/*.md 中声明：{sorted(dangling_acs)}"
        )
    else:
        res.add("无主AC拦截", "PASS", f"测试中引用的 {len(all_cited_acs)} 个 AC 均有合法 PRD 声明")

    # ---- 判据 2：无效跳过测试拦截 (Unwaived Skip)
    if unwaived_skips:
        res.add(
            "无效跳过拦截",
            "FAIL",
            f"挂载 AC 的测试被 skip/xfail 但未附带合法的 waiver 豁免理由：{unwaived_skips}"
        )
    else:
        res.add("无效跳过拦截", "PASS", "所有挂载 AC 的跳过测试均具备有效豁免声明或无跳过")

    # ---- 判据 3：AC 双向覆盖状态统计
    mode = backend_test_cfg.get("mode", "advisory")
    total_declared = len(all_declared_acs)
    total_cited = len(all_cited_acs)
    coverage_ratio = (total_cited / total_declared) if total_declared > 0 else 1.0

    detail_msg = f"已声明 AC: {total_declared}，后端测试挂载覆盖: {total_cited} ({coverage_ratio:.1%})"
    if mode == "enforce" and total_declared > 0 and total_cited == 0:
        res.add("AC覆盖对账", "FAIL", f"{detail_msg}（enforce 模式下不允许零测试挂载）")
    else:
        # advisory 模式或有覆盖
        res.add("AC覆盖对账", "PASS", detail_msg)

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

    # 自动保存/刷新快照（若运行在工作区内，且本次检查未 FAIL 时才固化新基线，防坏输入污染棘轮）
    if res.status != "FAIL":
        try:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(json.dumps(current_snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
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
