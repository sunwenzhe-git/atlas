#!/usr/bin/env python3
"""atlas 校验器 —— 后端与全栈验收标准（AC）对账门禁（Phase 1）。

依据 B209-1 / 3507 BT 决策（2026-10-12）：
  * **无主 AC 拦截（Dangling ACs）**：测试中挂载的 AC ID 必须在现有 PRD 资产中存在（无主即 FAIL）。
  * **无效跳过拦截（Unwaived Skip/Xfail）**：挂载了 AC 的测试若被标记为跳过，必须附带显式豁免说明
    （`reason` 包含 `waiver:` 或 docstring 声明 `waiver:`），否则 FAIL。
  * **双向对账与覆盖清单（Alignment Coverage）**：
    提取各需求 PRD 的 AC 集合与测试代码映射。若配置为 enforce 模式，检查对应后端 AC 挂载覆盖度。
  * **差量防退化（Delta Ratchet）**：
    与上一次执行留存的基线快照比对，挂载 AC 的测试用例数与覆盖的 AC 数净增不得为负。
  * **AC × 覆盖维度（后端通道，D153）**：
    域级 PRD 验收表可选列 `后端适用覆盖维度` ⇔ 测试记录的 `dims`；
    缺维度 / 仅弱证据 / 零测试 / 未知 / 孤儿 ⇒ WARN（不 FAIL）。第 4 列仍归 E2E 门（D130）。

**语言中立架构**：本文件不识别任何具体测试框架，也不识别测试文件命名约定；
框架知识只在 `adapters/ac/` 的提取器内。本文件只消费归一化记录，并按项目形态决定门是否适用。

判定：`PASS`/`WARN`/`N/A` → 退出码 0；`FAIL` → 1。

用法：
    python3 validate_ac_alignment.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# 随包内核引导（`_support/`，2026-10-12 单源批）：profile 解析走单源实现
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402
from _support.layout import LayoutError, load_layout  # noqa: E402

_sp = load_module("stack_profile")
ac_coverage = load_module("ac_coverage")
parse_dims_cell = ac_coverage.parse_dims_cell

try:
    import adapters.ac as ac_adapters
    from adapters.ac import command as ac_command
except Exception as exc:  # 装配缺失 / 加载失败必须响亮，不静默降级
    ac_adapters = None
    ac_command = None
    _ADAPTER_IMPORT_ERROR = exc

AC_ID_RE = re.compile(r"\b(AC-[A-Z0-9]+-\d+)\b")
AC_ID_STRICT_RE = re.compile(r"^AC-[A-Z0-9]+-\d{3}$")
BACKEND_DIM_HEADER = "后端适用覆盖维度"
E2E_DIM_HEADER = "适用覆盖维度"
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
    """维度子项的通道适用/可用判据；返回空串 = 可用。

    具体框架支持性不在这里判：extractor 解析已在主流程完成；本函数只判
    「形态 / 多后端 / 是否声明 backend_test / test_dir 是否存在」。
    """
    apps = profile.get("apps")
    if not isinstance(apps, list) or not apps:
        return "未声明 apps（无法判定后端通道）"
    kinds = [a.get("kind") for a in apps if isinstance(a, dict)]
    backend_kinds = [k for k in kinds if k in ("backend", "fullstack")]
    if not backend_kinds:
        return "无 backend/fullstack 应用（当前栈不适用）"
    if not backend_test_cfg:
        return "未声明 backend_test（合法降级）"
    test_dir = backend_test_cfg.get("test_dir") or "backend/tests"
    if not (root / test_dir).is_dir():
        return f"test_dir 不存在：{test_dir}"
    return ""


def _cap(items: list[str], n: int = 8) -> str:
    if len(items) <= n:
        return "、".join(items)
    return "、".join(items[:n]) + f"…（共 {len(items)}）"


def _as_str_set(value: Any) -> set[str] | None:
    if not isinstance(value, (list, tuple, set)):
        return None
    if not all(isinstance(x, str) for x in value):
        return None
    return set(value)


def _record_schema_errors(tests: list[dict[str, Any]], root: Path) -> list[str]:
    """校验 adapter 归一化记录的不变量；返回空列表 = 合法。"""
    errors: list[str] = []
    seen: set[tuple[str, int]] = set()
    required = (
        "name", "file", "line", "acs", "marker_acs", "doc_acs",
        "dims", "dims_bad", "dims_shape_ok", "dims_present",
        "skipped", "waiver", "weak", "marker_scope_unsupported",
    )
    for idx, t in enumerate(tests):
        if not isinstance(t, dict):
            errors.append(f"#{idx} 记录不是对象")
            continue
        missing = [k for k in required if k not in t]
        if missing:
            errors.append(f"#{idx} 缺字段 {missing}")
            continue
        name, file, line = t["name"], t["file"], t["line"]
        if not isinstance(name, str) or not name.strip():
            errors.append(f"#{idx} name 非空字符串")
        if not isinstance(file, str) or not file.strip():
            errors.append(f"#{idx} file 非空字符串")
        else:
            p = Path(file)
            if p.is_absolute() or ".." in p.parts:
                errors.append(f"#{idx} file 必须是项目根相对路径：{file!r}")
        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:
            errors.append(f"#{idx} line 必须为正整数：{line!r}")
        acs = _as_str_set(t["acs"])
        marker_acs = _as_str_set(t["marker_acs"])
        doc_acs = _as_str_set(t["doc_acs"])
        dims = _as_str_set(t["dims"])
        dims_bad = _as_str_set(t["dims_bad"])
        if acs is None or marker_acs is None or doc_acs is None or dims is None or dims_bad is None:
            errors.append(f"#{idx} acs/marker_acs/doc_acs/dims/dims_bad 必须是字符串集合")
            continue
        if marker_acs - acs or doc_acs - acs:
            errors.append(f"#{idx} marker_acs/doc_acs 必须是 acs 的子集")
        if acs != (marker_acs | doc_acs):
            errors.append(f"#{idx} acs 必须等于 marker_acs ∪ doc_acs")
        if not isinstance(t["dims_shape_ok"], bool) or not isinstance(t["dims_present"], bool):
            errors.append(f"#{idx} dims_shape_ok/dims_present 必须是布尔")
        if not isinstance(t["skipped"], bool) or not isinstance(t["weak"], bool):
            errors.append(f"#{idx} skipped/weak 必须是布尔")
        if not isinstance(t["waiver"], str):
            errors.append(f"#{idx} waiver 必须是字符串")
        if not isinstance(t["marker_scope_unsupported"], bool):
            errors.append(f"#{idx} marker_scope_unsupported 必须是布尔")
        if isinstance(file, str) and isinstance(line, int) and not isinstance(line, bool) and line > 0:
            key = (file, line)
            if key in seen:
                errors.append(f"#{idx} (file,line) 重复：{file}:{line}")
            seen.add(key)
    return errors


def _run_checks(
    res: Result,
    result,
    root: Path,
    lay,
    profile: dict[str, Any],
    backend_test_cfg: dict[str, Any],
    all_declared_acs: set[str],
    mode: str,
) -> Result:
    tests = result.tests
    parse_errors = result.parse_errors
    scan_face = result.scan_face

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

    if parse_errors:
        status = "FAIL" if mode == "enforce" else "WARN"
        res.add("测试提取完整性", status,
                f"[PARSE] 解析失败={len(parse_errors)}个：{'; '.join(parse_errors[:3])}")
    else:
        res.add("测试提取完整性", "PASS", "所有测试文件解析成功")

    if scan_face:
        res.add("测试扫描面", "WARN", f"[SCAN] {'；'.join(scan_face[:4])}")

    total_declared = len(all_declared_acs)
    total_cited = len(all_cited_acs)
    coverage_ratio = (total_cited / total_declared) if total_declared > 0 else 1.0
    detail_msg = f"已声明 AC: {total_declared}，后端测试挂载覆盖: {total_cited} ({coverage_ratio:.1%})"
    if mode == "enforce" and total_declared > 0 and total_cited == 0:
        res.add("AC覆盖对账", "FAIL", f"{detail_msg}（enforce 模式下不允许零测试挂载）")
    elif total_declared > 0 and total_cited == 0:
        res.add("AC覆盖对账", "WARN", f"[ZERO-COVERAGE] {detail_msg}")
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
            if t.get("marker_scope_unsupported"):
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
            parts.append(f"模块/类级AC标记不支持={_cap(sorted(pm_ac), 4)}")
        if dim_issues:
            parts.append("；".join(dim_issues[:4]))

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

    # 解析失败时快照不完整：不写 baseline，避免把坏快照冻成新基线
    if res.status != "FAIL" and not parse_errors:
        try:
            baseline_file.parent.mkdir(parents=True, exist_ok=True)
            baseline_file.write_text(
                json.dumps(current_snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    return res


def validate_ac_alignment(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    if ac_adapters is None:
        res.add("AC提取器注册表", "FAIL",
                f"adapters/ac 加载失败：{_ADAPTER_IMPORT_ERROR}")
        return res

    profile = load_stack_profile(root, lay)
    backend_test_cfg = profile.get("backend_test") or {}
    if not isinstance(backend_test_cfg, dict):
        backend_test_cfg = {}
    mode = backend_test_cfg.get("mode", "advisory")
    if mode not in ("advisory", "enforce"):
        mode = "advisory"

    apps = profile.get("apps")
    apps_declared = isinstance(apps, list) and bool(apps)
    backend_apps = [
        a for a in (apps or [])
        if isinstance(a, dict) and a.get("kind") in ("backend", "fullstack")
    ] if apps_declared else []

    if apps_declared and not backend_apps:
        res.add("门控态", "N/A", "无 backend/fullstack 应用（当前形态不适用）")
        return res

    prd_acs_map = collect_prd_acs(root, lay)
    all_declared_acs: set[str] = set()
    for acs in prd_acs_map.values():
        all_declared_acs.update(acs)

    explicit = backend_test_cfg.get("extractor") or backend_test_cfg.get("framework")
    command = backend_test_cfg.get("extractor_command")
    test_dir_str = backend_test_cfg.get("test_dir") or "backend/tests"
    if command:
        try:
            result = ac_command.run(command, root, root / test_dir_str)
        except ac_command.ExtractError as exc:
            res.add("测试提取通道", "FAIL", f"[EXTRACTOR] {exc}")
            return res
    else:
        adapter = ac_adapters.resolve(explicit) if explicit else ac_adapters.resolve(None)
        if explicit and adapter is None:
            if not all_declared_acs:
                res.add("AC对账门禁运行态", "N/A", "无 PRD AC 且 extractor 未注册（无输入面）")
                return res
            res.add(
                "后端测试提取通道",
                "WARN" if mode == "advisory" else "FAIL",
                f"[UNVERIFIED] extractor={explicit!r} 未注册；后端 AC 覆盖未验证",
            )
            return res
        result = adapter.extract(root, root / test_dir_str, backend_test_cfg)
    input_present = result.input_state == "present"

    if not all_declared_acs and not input_present:
        res.add("AC对账门禁运行态", "N/A", "无 PRD 验收标准资产且无测试输入（不适用）")
        return res

    if not apps_declared:
        res.add(
            "后端通道适用性",
            "WARN" if mode == "advisory" else "FAIL",
            "[UNVERIFIED] stack-profile 未声明 apps，后端通道适用性无法判定",
        )
        if not input_present:
            return res

    # backend_test 已声明但既没有 extractor、默认提取器也没发现输入：
    # 不假设项目是 Python，报未验证而不是 ZERO-COVERAGE。
    if backend_test_cfg and not explicit and not command and not input_present:
        res.add(
            "后端测试提取通道",
            "WARN" if mode == "advisory" else "FAIL",
            "[UNVERIFIED] 未声明 extractor 且默认提取器未发现测试输入；"
            "非 Python 后端请声明 extractor",
        )
        return res

    schema_errors = _record_schema_errors(result.tests, root)
    if schema_errors:
        res.add("测试提取契约", "FAIL", f"[EXTRACTOR] {_cap(schema_errors, 6)}")
        return res

    return _run_checks(
        res, result, root, lay, profile, backend_test_cfg, all_declared_acs, mode
    )


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
