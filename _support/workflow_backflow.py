#!/usr/bin/env python3
"""需求变更/缺陷的 diff 回推、校验与 finish 新鲜度指纹。"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from _support.layout import LayoutError, load_layout
from _support.semver import parse as parse_semver
from _support.workflow_context import select_specs
from _support.workflow_plan import PlanError, load_tasks, read_requirement_fields
from _support.workflow_request import (
    clause_text, item_ids, living_document_findings, parse_request, request_diff_path,
    request_items, sha256_text, update_change_conclusion, update_request_status,
)

RECORD_BEGIN = "<!-- atlas:backflow:begin -->"
RECORD_END = "<!-- atlas:backflow:end -->"
IDENTIFIER_RES = (
    ("testid", re.compile(r"data-testid['\"]?\s*[:=]\s*[\"'`]([^\"'`]+)[\"'`]")),
    ("api", re.compile(r"[\"'`](/[A-Za-z0-9_{}?&=./:-]+)[\"'`]")),
    ("error", re.compile(r"\b(?:E[A-Z0-9_]{2,}|[A-Z]{2,}_[A-Z0-9_]+)\b")),
    ("field", re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[\"'`]")),
    ("field_value", re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*[\"'`]([^\"'`]+)[\"'`]")),
)


def _run(root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=root, capture_output=True, text=True,
                            errors="replace", timeout=60)
    if check and result.returncode != 0:
        raise PlanError(f"命令失败：{' '.join(args)}：{(result.stderr or result.stdout).strip()}")
    return result


def _git(root: Path, *args: str, check: bool = True) -> str:
    return _run(root, ["git", *args], check=check).stdout


def default_base(root: Path) -> str:
    for ref in ("master", "main"):
        if _run(root, ["git", "rev-parse", "--verify", ref], check=False).returncode == 0:
            return ref
    raise PlanError("无法确定默认基线：请显式传 --from <commit|range>")


def _managed(path: str, assets_rel: str) -> bool:
    return (path == ".atlas" or path.startswith(".atlas/") or path == "docs"
            or path.startswith("docs/") or path == assets_rel or path.startswith(assets_rel + "/"))


def changed_code_files(root: Path, base: str) -> list[str]:
    assets_rel = load_layout(root).assets_root.resolve().relative_to(root.resolve()).as_posix()
    tracked = _git(root, "diff", "--name-only", "-z", "--no-renames", base).split("\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({p for p in tracked + untracked if p and not _managed(p, assets_rel)})


def _blob(root: Path, spec: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", spec], cwd=root, capture_output=True, timeout=60)
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def code_snapshot(root: Path, base: str) -> dict:
    files = []
    for rel in changed_code_files(root, base):
        path = root / rel
        work = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        files.append({
            "path": rel,
            "worktree": work,
            "index": _blob(root, f":{rel}", rel),
            "head": _blob(root, f"HEAD:{rel}", rel),
        })
    payload = {"base": base, "files": files}
    payload["sha256"] = hashlib.sha256(
        json.dumps({"base": base, "files": files}, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def diff_text(root: Path, base: str) -> str:
    text = _git(root, "diff", "-U0", "--no-renames", base)
    for rel in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"):
        if not rel or _managed(rel, load_layout(root).assets_root.resolve().relative_to(root.resolve()).as_posix()):
            continue
        path = root / rel
        if path.is_file():
            text += f"diff --git a/{rel} b/{rel}\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,999 @@\n"
            text += "".join("+" + line + "\n" for line in path.read_text(encoding="utf-8", errors="replace").splitlines())
    allowed = set(changed_code_files(root, base))
    kept: list[str] = []
    for section in re.split(r"(?=^diff --git )", text, flags=re.M):
        match = re.search(r"^diff --git a/.* b/(.+)$", section, re.M)
        if not section.startswith("diff --git ") or (match and match.group(1) in allowed):
            kept.append(section)
    return "".join(kept)


def _identifiers(text: str, *, added: bool) -> dict[str, dict[str, list[tuple[str, str]]]]:
    found: dict[str, dict[str, list[tuple[str, str]]]] = {kind: {} for kind, _ in IDENTIFIER_RES}
    current_file = ""
    for line in text.splitlines():
        header = re.match(r"^diff --git a/.* b/(.+)$", line)
        if header:
            current_file = header.group(1)
            continue
        if added:
            if not line.startswith("+") or line.startswith("+++"):
                continue
            line = line[1:]
        else:
            if not line.startswith("-") or line.startswith("---"):
                continue
            line = line[1:]
        for kind, regex in IDENTIFIER_RES:
            for value in regex.findall(line):
                found[kind].setdefault(value, []).append((current_file, line.strip()))
    return found


def _field_decl(line: str) -> tuple[str, str] | None:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*['\"`]([^'\"`]+)['\"`]", line)
    return (match.group(1), match.group(2)) if match else None


def _doc_files(root: Path, feature_root: Path, specs: list[dict]) -> list[Path]:
    layout = load_layout(root)
    paths = [feature_root / "requirement.md"]
    paths.extend(sorted(layout.prd_dir.rglob("*.md")))
    paths.extend(sorted(layout.e2e_dir.rglob("*.md")))
    paths.extend(root / spec["rel"] for spec in specs)
    return [p for p in dict.fromkeys(paths) if p.is_file()]


def _occurrences(path: Path, token: str) -> list[int]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])")
    return [i for i, line in enumerate(lines, 1) if pattern.search(line)]


def analyze_impact(root: Path, feature_root: Path, base: str, kind: str) -> tuple[list[dict], list[dict]]:
    files = changed_code_files(root, base)
    specs = select_specs(root, paths=files)
    impacts: list[dict] = []
    conflicts: list[dict] = []
    for spec in specs:
        impacts.append({
            "target": spec["rel"], "type": "spec", "basis": f"paths: {', '.join(spec['paths'])}",
            "action": "review", "line": 1,
        })
    removed = _identifiers(diff_text(root, base), added=False)
    added = _identifiers(diff_text(root, base), added=True)
    docs = _doc_files(root, feature_root, specs)
    for token_kind, values in removed.items():
        for old, lines in values.items():
            if old in added[token_kind]:
                continue
            old_files = {name for name, _line in lines}
            candidates: list[str] = []
            for value, occurrences in added[token_kind].items():
                if token_kind == "field":
                    continue
                if value == old or value in removed[token_kind]:
                    continue
                if not old_files & {name for name, _line in occurrences}:
                    continue
                if token_kind == "field_value":
                    old_decls = [d for _f, line in lines if (d := _field_decl(line))]
                    new_decls = [d for _f, line in occurrences if (d := _field_decl(line))]
                    if not any(ok == nk for ok, _ov in old_decls for nk, _nv in new_decls):
                        continue
                candidates.append(value)
            new = candidates[0] if len(candidates) == 1 else None
            for path in docs:
                occurrences = _occurrences(path, old)
                if not occurrences:
                    continue
                action = "update" if new else "conflict"
                if kind == "缺陷" and token_kind != "testid":
                    action = "conflict"
                impact = {
                    "target": path.relative_to(root).as_posix(), "type": token_kind,
                    "basis": f"代码删除标识符 {old}" + (f" → {new}" if new else ""),
                    "action": action, "line": occurrences[0], "old": old, "new": new,
                }
                impacts.append(impact)
                if action == "conflict":
                    conflicts.append({
                        "target": impact["target"], "line": occurrences[0], "old": old, "new": new,
                        "reason": "缺陷修复不得静默改写业务契约" if kind == "缺陷" and token_kind != "testid"
                        else "无法唯一确定替换值",
                    })
    for token_kind, values in added.items():
        for token in values:
            for path in docs:
                occurrences = _occurrences(path, token)
                if occurrences:
                    impacts.append({
                        "target": path.relative_to(root).as_posix(), "type": token_kind,
                        "basis": f"代码新增标识符 {token} 已存在于文档",
                        "action": "confirm", "line": occurrences[0], "old": None, "new": token,
                    })
    if not impacts:
        conflicts.append({"target": "diff", "line": 1, "old": "", "new": "",
                          "reason": "代码改动未命中 spec paths 或文档标识符"})
    elif not any(i["action"] in ("update", "confirm") for i in impacts) and not conflicts:
        conflicts.append({"target": "diff", "line": 1, "old": "", "new": "",
                          "reason": "仅命中 spec 路径，需确认文档是否受影响"})
    return impacts, conflicts


def _replace_value(text: str, old: str, new: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(old)}(?![A-Za-z0-9_-])")
    return pattern.sub(new, text)


def _replace_token(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = _replace_value(text, old, new)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _request_after(feature_root: Path, request_path: Path, clause_override: str | None) -> tuple[str | None, str | None]:
    if clause_override:
        return clause_override, None
    meta = parse_request(request_path)
    if meta.get("kind") != "需求变更":
        return None, None
    diff_path = request_diff_path(request_path, meta.get("kind", ""))
    if not diff_path.is_file():
        return None, "变更请求缺 diff.md"
    text = diff_path.read_text(encoding="utf-8")
    text = re.sub(r"\n*## 回推记录\s*\n.*\Z", "", text, flags=re.S)
    before_match = re.search(r"^## 变更前\s*\n(.*?)(?=^## 变更后\s*$)", text, re.M | re.S)
    after_match = re.search(r"^## 变更后\s*\n(.*)$", text, re.M | re.S)
    before = before_match.group(1).strip() if before_match else ""
    after = after_match.group(1).strip() if after_match else ""
    if not after:
        return None, "diff.md 缺「变更后」正文"
    return after, before


def _bump_prd(path: Path, kind: str, request_id: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    header = text[3:end]
    match = re.search(r"^version:\s*(\S+)\s*$", header, re.M)
    if not match:
        return False
    parsed = parse_semver(match.group(1))
    if parsed is None:
        return False
    (major, minor, patch), pre = parsed
    if kind == "需求变更":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    suffix = "-" + ".".join(pre) if pre else ""
    version = f"{major}.{minor}.{patch}{suffix}"
    header = re.sub(r"^version:.*$", f"version: {version}", header, count=1, flags=re.M)
    header = re.sub(r"^date:.*$", f"date: {date.today().isoformat()}",
                    header, count=1, flags=re.M)
    text = text[:3] + header + text[end:]
    heading = re.search(r"^##\s+[^\n]*(?:变更记录|修订记录)[^\n]*$", text, re.M)
    row = f"| {version} | {date.today().isoformat()} | {request_id} 回推 | 代码 diff 影响 | 已校验 |"
    if heading:
        start = heading.end()
        next_heading = re.search(r"^##\s", text[start:], re.M)
        stop = start + next_heading.start() if next_heading else len(text)
        text = text[:stop].rstrip() + "\n" + row + "\n\n" + text[stop:].lstrip("\n")
    else:
        text = text.rstrip() + "\n\n## 变更记录\n\n| 版本 | 日期 | 变更内容及原因 | 影响 | 结论与后续 |\n|---|---|---|---|---|\n" + row + "\n"
    path.write_text(text, encoding="utf-8")
    return True


def apply_backflow(root: Path, feature_root: Path, request_path: Path, *, base: str,
                   impacts: list[dict], conflicts: list[dict], clause_override: str | None,
                   decision: str | None, decision_by: str | None) -> tuple[list[Path], list[dict]]:
    changed: list[Path] = []
    remaining = list(conflicts)
    meta = parse_request(request_path)
    kind = meta.get("kind", "")
    if decision and not decision_by:
        return [], [{"target": "request", "line": 1,
                     "reason": "--decision 必须同时提供 --decision-by"}]
    authorized = bool(decision and decision_by)
    remaining = [c for c in conflicts if not (authorized and c.get("new"))]
    after, before = _request_after(feature_root, request_path, clause_override)
    if after:
        seen_mappings: set[tuple[str, str]] = set()
        for impact in impacts:
            if impact.get("old") and impact.get("new"):
                mapping = (impact["old"], impact["new"])
                if mapping in seen_mappings:
                    continue
                seen_mappings.add(mapping)
                after = _replace_value(after, impact["old"], impact["new"])
                if before is not None:
                    before = _replace_value(before, impact["old"], impact["new"])
    for impact in impacts:
        if (impact["action"] != "update" and not (authorized and impact["action"] == "conflict")) or not impact.get("old") or not impact.get("new"):
            continue
        path = root / impact["target"]
        try:
            replaced = _replace_token(path, impact["old"], impact["new"])
        except UnicodeError:
            remaining.append({"target": impact["target"], "line": impact.get("line", 1),
                              "reason": "目标文档不是合法 UTF-8，未写入"})
            continue
        if replaced:
            changed.append(path)
    if after:
        items = request_items(meta)
        if len(items) != 1:
            remaining.append({"target": "request", "line": 1, "reason": "条款更新要求唯一 R 条款"})
        else:
            item = items[0]
            current = clause_text(feature_root, item)
            if current == after:
                pass
            elif current is None:
                remaining.append({"target": (feature_root / "requirement.md").relative_to(root).as_posix(), "line": 1,
                                  "reason": f"条款不存在：{item}"})
            elif before is not None and hashlib.sha256(current.encode("utf-8")).hexdigest() != sha256_text(before) and not authorized:
                remaining.append({"target": (feature_root / "requirement.md").relative_to(root).as_posix(), "line": 1,
                                  "reason": "条款基线已变化，需 --decision 确认后改写"})
            elif current != after:
                doc_path = feature_root / "requirement.md"
                text = doc_path.read_text(encoding="utf-8")
                pattern = rf"(^###\s+{re.escape(item)}\b[^\n]*\n)(.*?)(?=^###\s+R-\d{{2,3}}\b|^##\s|\Z)"
                text, count = re.subn(pattern, lambda m: m.group(1) + "\n" + after + "\n\n", text,
                                      count=1, flags=re.M | re.S)
                if count != 1:
                    remaining.append({"target": doc_path.relative_to(root).as_posix(), "line": 1, "reason": f"无法定位条款：{item}"})
                else:
                    doc_path.write_text(text, encoding="utf-8")
                    changed.append(doc_path)
    prd_dir = load_layout(root).prd_dir.resolve()
    for path in list(dict.fromkeys(changed)):
        try:
            path.resolve().relative_to(prd_dir)
        except ValueError:
            continue
        try:
            bumped = _bump_prd(path, kind, meta.get("id", ""))
        except UnicodeError:
            remaining.append({"target": path.relative_to(root).as_posix(), "line": 1,
                              "reason": "PRD 不是合法 UTF-8，未更新版本"})
            continue
        if bumped:
            changed.append(path)
    return list(dict.fromkeys(changed)), remaining


def run_validators(root: Path, feature_root: Path, request_path: Path, *,
                   include_structure: bool) -> list[dict]:
    findings = living_document_findings(feature_root, request_path)
    results = [{"validator": "validate_living_requirement",
                "status": "FAIL" if findings else "PASS",
                "returncode": 1 if findings else 0,
                "output": "\n".join(findings)}]
    validators = ["validate_prd", "validate_e2e_index", "validate_testids"]
    if include_structure:
        validators.append("validate_structure")
    for name in validators:
        script = root / ".atlas" / "validators" / f"{name}.py"
        if not script.is_file():
            script = Path(__file__).resolve().parents[1] / "validators" / f"{name}.py"
        result = _run(root, [sys.executable, str(script), "--root", str(root), "--json"], check=False)
        try:
            payload = json.loads(result.stdout or "{}")
            status = payload.get("status", "FAIL" if result.returncode else "PASS")
        except json.JSONDecodeError:
            status = "FAIL" if result.returncode else "PASS"
        results.append({"validator": name, "status": status, "returncode": result.returncode,
                        "output": (result.stdout + result.stderr).strip()[:4000]})
    return results


def parse_record(request_path: Path) -> dict | None:
    try:
        text = request_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    start = text.find(RECORD_BEGIN)
    end = text.find(RECORD_END, start)
    if start < 0 or end < 0:
        return None
    block = text[start + len(RECORD_BEGIN):end]
    match = re.search(r"```json\s*\n(.*?)\n```", block, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_record(request_path: Path, record: dict) -> None:
    block = RECORD_BEGIN + "\n```json\n" + json.dumps(
        record, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n" + RECORD_END
    text = request_path.read_text(encoding="utf-8")
    start = text.find(RECORD_BEGIN)
    end = text.find(RECORD_END, start)
    if start >= 0 and end >= 0:
        text = text[:start] + block + text[end + len(RECORD_END):]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    request_path.write_text(text, encoding="utf-8")


def write_diff_report(request_path: Path, impacts: list[dict], conflicts: list[dict],
                      validators: list[dict]) -> None:
    kind = parse_request(request_path).get("kind", "")
    path = request_diff_path(request_path, kind)
    text = path.read_text(encoding="utf-8") if path.is_file() else "# 回推差异\n"
    text = re.sub(r"\n*## 回推记录\s*\n.*\Z", "", text, flags=re.S).rstrip()
    lines = ["", "## 回推记录", "", "| 对象 | 类型 | 依据 | 动作 |", "|---|---|---|---|"]
    for impact in impacts:
        lines.append(f"| {impact['target']}:{impact.get('line', 1)} | {impact['type']} | "
                     f"{impact['basis']} | {impact['action']} |")
    if conflicts:
        lines += ["", "### 待拍板", ""]
        lines += [f"- {c['target']}:{c.get('line', 1)} — {c['reason']}" for c in conflicts]
    if validators:
        lines += ["", "### 校验", ""]
        lines += [f"- {v['validator']}: {v['status']}（rc={v['returncode']}）" for v in validators]
    path.write_text(text + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def resolve_request(root: Path, unit: str) -> tuple[Path, Path, dict]:
    task = next((t for t in load_tasks(root / ".atlas" / "tasks", include_archived=True)
                 if t["id"] == unit), None)
    if task and task.get("request_path"):
        feature_root = root / task["requirement_root"]
        request_path = root / task["request_path"]
        return feature_root, request_path, task
    base = load_layout(root).assets_root / "requirements"
    if not base.is_dir():
        raise PlanError(f"未找到请求或任务：{unit}")
    for feature_root in sorted(base.iterdir()):
        if not feature_root.is_dir():
            continue
        for request_path in sorted(feature_root.glob("bugs/BUG-*.md")) + sorted(feature_root.glob("changes/CHG-*/request.md")):
            if parse_request(request_path).get("id") == unit:
                return feature_root, request_path, {}
    raise PlanError(f"未找到请求或任务：{unit}")


def backflow_findings(root: Path, task: dict) -> list[str]:
    if task.get("intake_version") != 2 or task.get("intake_type") == "初始需求":
        return []
    request_ref = task.get("request_path")
    if not isinstance(request_ref, str) or not request_ref:
        return ["缺陷/变更请求未执行回推：缺 request_path"]
    request_path = root / request_ref
    record = parse_record(request_path)
    if record is None:
        return [f"请求未执行 atlas bug/change 回推：{request_ref}"]
    if record.get("status") != "ok":
        return [f"回推记录未通过：{record.get('status')}（冲突或校验失败）"]
    request_meta = parse_request(request_path)
    if (request_meta.get("id") != record.get("request_id")
            or request_meta.get("kind") != record.get("kind")
            or request_meta.get("status") != "implemented"):
        return ["请求元数据与回推回执不一致"]
    base = record.get("base") or task.get("base_commit")
    if not base:
        return ["回推记录缺 base"]
    try:
        snapshot = code_snapshot(root, base)
    except (PlanError, OSError, LayoutError) as exc:
        return [f"回推指纹无法重算：{exc}"]
    if snapshot["sha256"] != record.get("code_sha256"):
        return ["代码 diff 已变化，回推记录过期"]
    feature_root = root / task["requirement_root"]
    document_findings = living_document_findings(feature_root, request_path)
    if document_findings:
        return [f"活需求文档结构非法：{document_findings[0]}"]
    for rel, expected in (record.get("doc_sha256") or {}).items():
        if "#clause:" in rel:
            path_rel, item = rel.split("#clause:", 1)
            value = clause_text(root / path_rel.removesuffix("/requirement.md"), item)
            actual = sha256_text(value) if value is not None else None
        elif "#change-row:" in rel:
            path_rel, request_id = rel.split("#change-row:", 1)
            path = root / path_rel
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
            row = next((line for line in lines if line.startswith(f"| {request_id} |")), None)
            actual = sha256_text(row) if row is not None else None
        elif "#item:" in rel:
            path_rel, item_id = rel.split("#item:", 1)
            path = root / path_rel
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
            row = next((line for line in lines if line.startswith(f"| {item_id} |")), None)
            fragment = "|".join(row.split("|")[1:4]) if row else None
            actual = sha256_text(fragment) if fragment else None
        else:
            path = root / rel
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != expected:
            return [f"回推文档已变化：{rel}"]
    return []
