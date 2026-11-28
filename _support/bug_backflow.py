#!/usr/bin/env python3
"""Requirement-change/defect diff analysis, canonical backflow, and finish validation."""
# ATLAS_CHANGE_AUTO_V1
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from _support.bug_record import (
    ALL_REPORT_PATHS, BugRecordError, OBJECT_TYPES, RECORD_FILE, REPORT_PATHS, append_history,
    atomic_write_bytes, canonical_bytes, dedupe_identity, new_record, read_record,
    refresh_hashes, sha256_bytes, utc_now, validate_record, write_record,
)
from _support.layout import LayoutError, load_layout
from _support.semver import parse as parse_semver
from _support.siblings import load_module
from _support.workflow_context import select_specs
from _support.workflow_plan import (
    PlanError, REQUIREMENT_DOC_FILE, REQUIREMENT_RELATED_RE,
    REQUIREMENT_TYPES, load_tasks, read_requirement_fields, requirement_relation_findings,
    requirement_type, resolve_requirement_root_by_slug, strip_fences,
)

IDENTIFIER_RES = (
    ("testid", re.compile(r"data-testid['\"]?\s*[:=]\s*[\"'`]([^\"'`]+)[\"'`]")),
    ("ac", re.compile(r"\bAC-[A-Z0-9]+-\d+\b")),
    ("e2e", re.compile(r"\bE2E-[A-Z0-9-]+-\d+\b")),
    ("api", re.compile(r"[\"'`](/[A-Za-z0-9_{}?&=./:-]+)[\"'`]")),
    ("error", re.compile(r"\b(?:E[A-Z0-9_]{2,}|[A-Z]{2,}_[A-Z0-9_]+)\b")),
    ("field", re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[\"'`]")),
    ("field_value", re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*[\"'`]([^\"'`]+)[\"'`]")),
)
AUTHORITY_FIELDS = ("类型", "关联需求", "状态", "结论", "证据")
REQUIREMENT_ROOT_ITEMS_FILE = "items.md"
CHANGE_TYPES = ("需求变更", "缺陷")


class BackflowError(ValueError):
    def __init__(self, message: str, cause: str = "bug_backflow_invalid"):
        super().__init__(message)
        self.cause = cause


def _run(root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=str(root), capture_output=True, text=True,
                            errors="replace", timeout=60)
    if check and result.returncode != 0:
        raise BackflowError(f"命令失败：{' '.join(args)}：{(result.stderr or result.stdout).strip()}",
                            cause="bug_backflow_invalid")
    return result


def _git(root: Path, *args: str, check: bool = True) -> str:
    return _run(root, ["git", *args], check=check).stdout


def _git_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=60)
    if check and result.returncode != 0:
        raise BackflowError(f"git 命令失败：{' '.join(args)}", cause="bug_backflow_invalid")
    return result.stdout


def default_base(root: Path) -> str:
    for ref in ("origin/main", "main", "master"):
        if _run(root, ["git", "rev-parse", "--verify", ref], check=False).returncode == 0:
            return ref
    raise BackflowError("无法确定默认基线：请显式传 --from <range|staged>",
                        cause="bug_backflow_missing")


def resolve_defect_root(root: Path, slug: str) -> Path | None:
    candidate = resolve_requirement_root_by_slug(Path(root), slug)
    if candidate is None:
        return None
    return candidate


def strict_requirement_fields(req_root: Path) -> tuple[dict[str, str], list[str]]:
    path = Path(req_root) / REQUIREMENT_DOC_FILE
    if not path.is_file() or path.is_symlink():
        return {}, ["requirement.md 缺失或为 symlink"]
    try:
        text = strip_fences(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        return {}, [f"requirement.md 不可读：{exc}"]
    fields: dict[str, str] = {}
    findings: list[str] = []
    for key in AUTHORITY_FIELDS:
        matches = re.findall(rf"^\*\*{re.escape(key)}\*\*[：:]\s*(.*?)\s*$", text, re.M)
        if len(matches) > 1:
            findings.append(f"requirement.md 的 {key} 重复 {len(matches)} 次")
        elif matches:
            fields[key] = matches[0].strip()
    return fields, findings


def defect_intent(req_root: Path) -> bool:
    return ((Path(req_root) / RECORD_FILE).is_file()
            or any((Path(req_root) / rel).is_file() for rel in ALL_REPORT_PATHS))


def _related_target(root: Path, related: str) -> tuple[Path, str]:
    match = REQUIREMENT_RELATED_RE.fullmatch(related)
    if not match:
        raise BackflowError(f"关联需求形态非法：{related!r}", cause="bug_backflow_missing")
    target = resolve_requirement_root_by_slug(Path(root), match.group("slug"))
    if target is None:
        raise BackflowError(f"关联需求找不到唯一落点：{match.group('slug')}",
                            cause="bug_backflow_missing")
    fields = read_requirement_fields(target)
    if fields.get("状态") not in ("已确认", "已拆", "已收口"):
        raise BackflowError("关联需求基线状态非法", cause="bug_backflow_missing")
    item = match.group("item")
    items = target / REQUIREMENT_ROOT_ITEMS_FILE
    if not items.is_file() or not re.search(
            rf"^\|\s*{re.escape(item)}\s*\|", strip_fences(items.read_text(encoding="utf-8")), re.M):
        raise BackflowError(f"关联需求条目不存在：{related}", cause="bug_backflow_missing")
    return target, item


def bootstrap_defect(root: Path, slug: str, related: str, report_text: str,
                     stage: str, kind: str = "缺陷") -> Path:
    if kind not in CHANGE_TYPES:
        raise BackflowError(f"非法变更类型：{kind!r}", cause="bug_backflow_missing")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", slug):
        raise BackflowError(f"非法 slug：{slug!r}", cause="bug_backflow_missing")
    if resolve_defect_root(root, slug) is not None:
        raise BackflowError(f"落点已存在：{slug}", cause="bug_backflow_invalid")
    target, item = _related_target(root, related)
    layout = load_layout(root)
    base = layout.assets_root / "requirements"
    if base.is_symlink():
        raise BackflowError("requirements 不得经 symlink 改道", cause="bug_backflow_invalid")
    base.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{slug}.", dir=str(base)))
    report_rel = REPORT_PATHS[kind]
    try:
        (temp / "work").mkdir()
        requirement = (
            f"# {kind} {slug}\n\n"
            f"**类型**：{kind}\n"
            f"**关联需求**：{related}\n"
            "**状态**：候选\n\n"
            f"> 审计台账：`record.json`；证据正文唯一住址：`{report_rel}`。\n"
        )
        items = (
            "# 落点条目表\n\n"
            "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
            f"| {item} | {target.name}#{item} | 关联需求 | 引用 {target.name}#{item}（正文唯一住址） |\n"
        )
        report = report_text.rstrip() + "\n"
        (temp / REQUIREMENT_DOC_FILE).write_text(
            requirement, encoding="utf-8", newline="")
        (temp / REQUIREMENT_ROOT_ITEMS_FILE).write_text(
            items, encoding="utf-8", newline="")
        (temp / report_rel).write_text(report, encoding="utf-8", newline="")
        record = new_record(slug, related, stage, sha256_bytes(report.encode("utf-8")),
                            report_path=report_rel)
        findings = validate_record(record)
        if findings:
            raise BackflowError("；".join(findings), cause="bug_backflow_invalid")
        atomic_write_bytes(temp / RECORD_FILE,
                           json.dumps(record, ensure_ascii=False, indent=2,
                                      sort_keys=True).encode("utf-8") + b"\n")
        destination = base / slug
        if destination.exists() or destination.is_symlink():
            raise BackflowError(f"落点已存在：{slug}", cause="bug_backflow_invalid")
        os.rename(temp, destination)
        return destination
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _raw_entries(root: Path, mode: str, base: str | None) -> list[dict]:
    object_format = _git(root, "rev-parse", "--show-object-format").strip()
    abbrev = 64 if object_format == "sha256" else 40
    if mode == "staged":
        args = ["diff", "--cached", "--raw", "-z", "--no-renames", f"--abbrev={abbrev}"]
    else:
        if not base:
            raise BackflowError("range 模式缺 base..head", cause="bug_backflow_missing")
        args = ["diff", "--raw", "-z", "--no-renames", f"--abbrev={abbrev}", base]
    raw = _git_bytes(root, *args)
    parts = raw.split(b"\0")
    entries: list[dict] = []
    index = 0
    while index < len(parts):
        header = parts[index].decode("ascii", errors="replace")
        index += 1
        if not header:
            continue
        if index >= len(parts):
            raise BackflowError("git raw diff 缺路径", cause="bug_backflow_invalid")
        path = parts[index].decode("utf-8", errors="surrogateescape")
        index += 1
        match = re.match(r"^:(\d{6}) (\d{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z])$", header)
        if not match:
            raise BackflowError(f"无法解析 git raw diff：{header}", cause="bug_backflow_invalid")
        old_mode, new_mode, old_oid, new_oid, status = match.groups()
        if old_mode == "120000" or new_mode == "120000":
            obj_type = "symlink"
        elif old_mode == "160000" or new_mode == "160000":
            obj_type = "commit"
        elif status == "T":
            obj_type = "unknown"
        else:
            obj_type = "blob"
        entries.append({
            "path": path, "old_oid": old_oid, "new_oid": new_oid,
            "old_mode": old_mode, "new_mode": new_mode, "obj_type": obj_type,
            "status": status,
        })
    return entries


def source_snapshot(root: Path, mode: str, base: str | None,
                    artifact_paths: set[str]) -> dict:
    entries = _raw_entries(root, mode, base)
    unsupported = [e["path"] for e in entries
                   if e["path"] not in artifact_paths and e["obj_type"] != "blob"]
    if unsupported:
        raise BackflowError(
            "不支持的非 blob 实现变更：" + "、".join(unsupported),
            cause="bug_backflow_unsupported_object_type")
    files = []
    for entry in entries:
        if entry["path"] in artifact_paths:
            continue
        files.append({k: entry[k] for k in (
            "path", "old_oid", "new_oid", "old_mode", "new_mode", "obj_type")})
    files.sort(key=lambda item: item["path"])
    head = "WORKTREE" if mode == "staged" else (base or "")
    base_value = "HEAD" if mode == "staged" else (base or "")
    payload = {"mode": mode, "base": base_value, "head": head,
               "implementation_files": files}
    return {**payload, "sha256": sha256_bytes(canonical_bytes(payload))}


def _all_changed_paths(root: Path, mode: str, base: str | None) -> list[str]:
    return [entry["path"] for entry in _raw_entries(root, mode, base)]


def staged_paths(root: Path) -> set[str]:
    raw = _git_bytes(root, "diff", "--cached", "--name-only", "-z", "--no-renames")
    return {p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p}


def _index_matches_worktree(root: Path, rel: str) -> bool | None:
    """Compare Git-object IDs so autocrlf/eol clean filters do not cause false divergence."""
    try:
        index = subprocess.run(["git", "rev-parse", f":{rel}"], cwd=str(root),
                               capture_output=True, text=True, timeout=60)
        worktree = subprocess.run(["git", "hash-object", f"--path={rel}", "--", rel],
                                  cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if worktree.returncode != 0:
        return None
    if index.returncode != 0:
        return False if (root / rel).is_file() else None
    return index.stdout.strip() == worktree.stdout.strip()


def index_worktree_findings(root: Path, source: dict, artifact_paths: set[str]) -> list[str]:
    findings: list[str] = []
    for item in source.get("implementation_files", []):
        rel = item["path"]
        if item["new_oid"] == "0" * len(item["new_oid"]):
            if (Path(root) / rel).exists() or (Path(root) / rel).is_symlink():
                findings.append(f"删除路径仍在工作树：{rel}")
            continue
        path = Path(root) / rel
        if not path.is_file() or path.is_symlink():
            findings.append(f"实现路径不是普通工作树文件：{rel}")
            continue
        if _index_matches_worktree(root, rel) is False:
            findings.append(f"index/worktree 不一致：{rel}")
    for rel in sorted(artifact_paths):
        path = Path(root) / rel
        if not path.is_file() or path.is_symlink():
            findings.append(f"回推产物不是普通工作树文件：{rel}")
            continue
        matched = _index_matches_worktree(root, rel)
        if matched is False:
            findings.append(f"回推产物 index/worktree 不一致：{rel}")
        elif matched is None:
            findings.append(f"回推产物未暂存：{rel}")
    return findings


def _diff_text(root: Path, mode: str, base: str | None,
               implementation_paths: list[str]) -> str:
    parts: list[str] = []
    for rel in implementation_paths:
        if mode == "staged":
            args = ["diff", "--cached", "-U0", "--no-renames", "--", rel]
        else:
            args = ["diff", "-U0", "--no-renames", base or "", "--", rel]
        parts.append(_git(root, *args))
    return "".join(parts)


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


def _doc_files(root: Path, req_root: Path, specs: list[dict]) -> list[Path]:
    layout = load_layout(root)
    paths = [Path(req_root) / REQUIREMENT_DOC_FILE, Path(req_root) / REQUIREMENT_ROOT_ITEMS_FILE]
    paths.extend(sorted(layout.prd_dir.rglob("*.md")))
    paths.extend(sorted(layout.e2e_dir.rglob("*.md")))
    paths.extend(Path(root) / spec["rel"] for spec in specs)
    return [path for path in dict.fromkeys(paths) if path.is_file() and not path.is_symlink()]


def _occurrences(path: Path, token: str) -> list[int]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])")
    return [index for index, line in enumerate(lines, 1) if pattern.search(line)]


def _stable_id(prefix: str, *values: str) -> str:
    raw = "\0".join(values).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:12]}"


def analyze_impact(root: Path, req_root: Path, source: dict,
                   artifact_paths: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    artifact_paths = artifact_paths or set()
    diff = _diff_text(root, source["mode"], None if source["mode"] == "staged" else source["base"],
                      [item["path"] for item in source["implementation_files"]])
    specs = select_specs(root, paths=[item["path"] for item in source["implementation_files"]])
    docs = _doc_files(root, req_root, specs)
    removed = _identifiers(diff, added=False)
    added = _identifiers(diff, added=True)
    impacts: list[dict] = []
    conflicts: list[dict] = []
    confirmed_impacts: list[dict] = []

    def resolved_kind(path: Path, kind: str) -> str:
        rel = path.relative_to(root).as_posix()
        return "spec" if rel.startswith(".atlas/spec/") else kind

    def add_pending(path: Path, line: int, old: str, new: str, reason: str,
                    kind: str = "prd") -> None:
        rel = path.relative_to(root).as_posix()
        kind = resolved_kind(path, kind)
        conflict_id = _stable_id("conflict", rel, old, new, reason)
        impacts.append({
            "id": _stable_id("impact", conflict_id, kind),
            "conflict_id": conflict_id,
            "kind": kind,
            "target": f"{rel}#L{line}",
            "evidence": f"{rel}:{line}",
            "action": "pending",
        })
        conflicts.append({
            "id": conflict_id, "path": rel, "old": old, "new": new,
            "reason": reason, "status": "open",
        })

    def add_confirmed(path: Path, line: int, token: str, kind: str) -> None:
        rel = path.relative_to(root).as_posix()
        kind = resolved_kind(path, kind)
        confirmed_impacts.append({
            "id": _stable_id("impact", "confirmed", rel, token, kind),
            "conflict_id": None,
            "kind": kind,
            "target": f"{rel}#L{line}",
            "evidence": f"标识符 {token} 在 {rel}:{line} 保持对应",
            "action": "confirmed",
        })

    for token_kind, values in removed.items():
        for old, locations in values.items():
            if old in added[token_kind]:
                for path in docs:
                    lines = _occurrences(path, old)
                    if lines:
                        kind = "e2e" if token_kind in ("testid", "e2e") else (
                            "ac" if token_kind == "ac" else "prd")
                        add_confirmed(path, lines[0], old, kind)
                continue
            for path in docs:
                lines = _occurrences(path, old)
                if lines:
                    kind = "e2e" if token_kind in ("testid", "e2e") else (
                        "ac" if token_kind == "ac" else "prd")
                    add_pending(path, lines[0], old, "",
                                f"代码删除标识符 {old}，权威文档仍引用该值", kind)
    for token_kind, values in added.items():
        for token, locations in values.items():
            if token in removed[token_kind]:
                continue
            matched = False
            for path in docs:
                lines = _occurrences(path, token)
                if lines:
                    matched = True
                    kind = "e2e" if token_kind in ("testid", "e2e") else (
                        "ac" if token_kind == "ac" else "prd")
                    add_confirmed(path, lines[0], token, kind)
            if not matched:
                target_doc = docs[0] if docs else Path(req_root) / REQUIREMENT_DOC_FILE
                add_pending(target_doc, 1, "", token,
                            f"代码新增行为标识符 {token}，文档/AC/E2E 无对应",
                            "e2e" if token_kind in ("testid", "e2e") else "prd")

    executable_changed = False
    executable_file = ""
    for line in diff.splitlines():
        header = re.match(r"^diff --git a/.* b/(.+)$", line)
        if header:
            executable_file = header.group(1)
            continue
        if not (line.startswith("+") or line.startswith("-")) or line.startswith(("+++", "---")):
            continue
        content = line[1:].strip()
        if not content or content.startswith(("#", "//", "/*", "*", "*/")):
            continue
        executable_changed = True
        break
    if executable_changed:
        target_doc = docs[0] if docs else Path(req_root) / REQUIREMENT_DOC_FILE
        add_pending(target_doc, 1, "", "",
                    f"可执行 hunk 无语言 adapter 等价证明，需要签字确认行为语义（{executable_file}）")
    else:
        impacts.extend(confirmed_impacts)
    if not impacts:
        target_doc = docs[0] if docs else Path(req_root) / REQUIREMENT_DOC_FILE
        add_pending(target_doc, 1, "", "",
                    "改动未命中 spec paths 或文档标识符，无法证明无偏移")
    return impacts, conflicts


def _safe_document_path(root: Path, req_root: Path, rel: str) -> Path:
    if Path(rel).is_absolute():
        raise BackflowError(f"决策路径不得为绝对路径：{rel}", cause="bug_backflow_invalid")
    root = Path(root).resolve()
    raw_path = root / rel
    if raw_path.is_symlink():
        raise BackflowError(f"决策路径不得为 symlink：{rel}", cause="bug_backflow_invalid")
    candidate = raw_path.parent.resolve() / raw_path.name
    if root not in candidate.parents:
        raise BackflowError(f"决策路径越界：{rel}", cause="bug_backflow_invalid")
    layout = load_layout(root)
    allowed = [
        layout.assets_root.resolve(), layout.adr_dir.resolve(), layout.prd_dir.resolve(),
        layout.e2e_dir.resolve(), Path(req_root).resolve(),
        (root / ".atlas" / "spec").resolve(),
    ]
    if not any(candidate == base or base in candidate.parents for base in allowed):
        raise BackflowError(f"决策路径不在合法资产/spec 面：{rel}", cause="bug_backflow_invalid")
    if candidate.is_symlink():
        raise BackflowError(f"决策路径不得为 symlink：{rel}", cause="bug_backflow_invalid")
    return candidate


def _bump_version_and_change(path: Path, bug_id: str, change_ref: str) -> tuple[bool, str | None, str | None]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False, None, None
    end = text.find("\n---", 3)
    if end < 0:
        return False, None, None
    header = text[3:end]
    match = re.search(r"^version:\s*(\S+)\s*$", header, re.M)
    if not match:
        return False, None, None
    parsed = parse_semver(match.group(1))
    if parsed is None:
        return False, None, None
    (major, minor, patch), pre = parsed
    before = match.group(1)
    after = f"{major}.{minor}.{patch + 1}" + (("-" + ".".join(pre)) if pre else "")
    header = re.sub(r"^version:.*$", f"version: {after}", header, count=1, flags=re.M)
    header = re.sub(r"^date:.*$", f"date: {utc_now()[:10]}", header, count=1, flags=re.M)
    text = text[:3] + header + text[end:]
    heading = re.search(r"^##\s+[^\n]*(?:变更记录|修订记录)[^\n]*$", text, re.M)
    row = (f"| {after} | {utc_now()[:10]} | {bug_id} 缺陷回推（{change_ref}） | "
           "代码 diff 与权威资产对账 | 已校验 |")
    if heading:
        start = heading.end()
        next_heading = re.search(r"^##\s", text[start:], re.M)
        stop = start + next_heading.start() if next_heading else len(text)
        text = text[:stop].rstrip() + "\n" + row + "\n\n" + text[stop:].lstrip("\n")
    else:
        text = text.rstrip() + "\n\n## 变更记录\n\n| 版本 | 日期 | 变更内容及原因 | 影响 | 结论与后续 |\n|---|---|---|---|---|\n" + row + "\n"
    path.write_text(text, encoding="utf-8")
    return True, before, after


def _load_claim_module():
    return load_module("write_claim")


def _current_version(path: Path) -> tuple[bool, str | None, str | None]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False, None, None
    end = text.find("\n---", 3)
    if end < 0:
        return False, None, None
    match = re.search(r"^version:\s*(\S+)\s*$", text[3:end], re.M)
    if not match or parse_semver(match.group(1)) is None:
        return False, None, None
    return True, match.group(1), match.group(1)


def _apply_transaction(root: Path, req_root: Path, record: dict,
                       replacements: list[dict], confirmed_documents: list[str], *,
                       include_structure: bool) -> tuple[list[dict], dict[str, str]]:
    claim = _load_claim_module()
    owner = f"{record['id']}:{uuid.uuid4().hex}"
    record_rel = (Path(req_root) / RECORD_FILE).relative_to(root).as_posix()
    stub_rel = ".atlas/spec/conventions/testid.md"
    document_paths = {item["path"] for item in replacements} | set(confirmed_documents)
    conflict_by_id = {item.get("id"): item for item in record.get("conflicts", [])
                      if isinstance(item, dict)}
    decision_by_conflict = {item.get("conflict_id"): item for item in replacements}
    for conflict in record.get("conflicts", []):
        if conflict.get("status") != "open":
            continue
        decision = decision_by_conflict.get(conflict.get("id"))
        if decision is None:
            raise BackflowError(f"冲突未签字：{conflict.get('id')}", cause="bug_backflow_pending")
        if decision.get("path") != conflict.get("path"):
            raise BackflowError("决策 path 与 conflict.path 不一致", cause="bug_backflow_pending")
        if conflict.get("old") and decision.get("old") != conflict.get("old"):
            raise BackflowError("决策 old 与 conflict.old 不一致", cause="bug_backflow_pending")
    decision_by_path: dict[str, str] = {}
    for item in replacements:
        decision_by_path.setdefault(item["path"], item["id"])
    targets: dict[str, bytes | None] = {}
    for rel in sorted(document_paths):
        path = _safe_document_path(root, req_root, rel)
        if not path.is_file():
            raise BackflowError(f"决策目标不存在：{rel}", cause="bug_backflow_invalid")
        targets[rel] = path.read_bytes()
    stub_path = root / stub_rel
    targets[stub_rel] = stub_path.read_bytes() if stub_path.is_file() else None
    targets[record_rel] = (root / record_rel).read_bytes() if (root / record_rel).is_file() else None
    acquired: list[str] = []
    journal: list[tuple[Path, bytes | None]] = []
    try:
        for rel in sorted(targets):
            claim.take(root, rel, owner)
            acquired.append(rel)
        simulated: dict[str, str] = {}
        for rel in document_paths:
            data = targets[rel]
            assert data is not None
            simulated[rel] = data.decode("utf-8")
        for decision in replacements:
            rel = decision["path"]
            text = simulated.get(rel)
            if text is None:
                raise BackflowError(f"决策目标不可读：{rel}", cause="bug_backflow_invalid")
            if sha256_bytes(text.encode("utf-8")) != decision.get("old_sha256"):
                raise BackflowError(f"决策文档摘要不匹配：{rel}", cause="bug_backflow_pending")
            if text.count(decision["old"]) != 1:
                raise BackflowError(f"old 文本在 {rel} 中不是唯一出现", cause="bug_backflow_pending")
            simulated[rel] = text.replace(decision["old"], decision["new"], 1)
        after_hashes: dict[str, str] = {}
        documents: list[dict] = []
        replacement_paths = {item["path"] for item in replacements}
        for rel in sorted(document_paths):
            path = root / rel
            old_bytes = targets[rel]
            assert old_bytes is not None
            if rel in replacement_paths:
                path.write_text(simulated[rel], encoding="utf-8")
                journal.append((path, old_bytes))
                supported, before_version, after_version = _bump_version_and_change(
                    path, record["id"], decision_by_path[rel])
                action = "update"
            else:
                supported, before_version, after_version = _current_version(path)
                action = "confirmed"
            after_bytes = path.read_bytes()
            after_hash = sha256_bytes(after_bytes)
            after_hashes[rel] = after_hash
            documents.append({
                "path": rel, "action": action,
                "version": {"supported": supported, "before": before_version, "after": after_version},
                "change_ref": decision_by_path.get(rel) if action == "update" else None,
                "before_sha256": sha256_bytes(old_bytes), "after_sha256": after_hash,
            })
        for conflict in record.get("conflicts", []):
            if conflict.get("status") != "open":
                continue
            path = root / conflict["path"]
            text = path.read_text(encoding="utf-8")
            if conflict.get("old") and conflict["old"] in text:
                raise BackflowError(f"冲突旧值仍存在：{conflict['path']}", cause="bug_backflow_pending")
            if conflict.get("new") and conflict["new"] not in text:
                raise BackflowError(f"冲突新值未落入文档：{conflict['path']}", cause="bug_backflow_pending")
        record["documents"] = documents
        known_decisions = {item.get("id") for item in record.get("decisions", [])}
        record["decisions"] = list(record.get("decisions", [])) + [
            item for item in replacements if item.get("id") not in known_decisions]
        record["conflicts"] = [{**item, "status": "resolved"} for item in record["conflicts"]]
        record["impact"] = [{**item, "action": "update" if item.get("conflict_id") else "confirmed"}
                            for item in record["impact"]]
        record["backflow_status"] = "ready"
        append_history(record, "decision_applied" if replacements else "analysis",
                       source_sha256=record["source"]["sha256"],
                       document_sha256=after_hashes)
        write_record(req_root, record)
        journal.append((root / record_rel, targets[record_rel]))
        journal.append((stub_path, targets[stub_rel]))
        results = run_validators(root, include_structure=include_structure)
        failed = [item for item in results if item["returncode"] != 0]
        if failed:
            detail = "；".join(f"{item['validator']}: {item['output']}" for item in failed)
            raise BackflowError(f"回推校验失败：{detail}", cause="bug_backflow_invalid")
        if stub_path.is_file():
            stub_after = stub_path.read_bytes()
            stub_hash = sha256_bytes(stub_after)
            if targets[stub_rel] != stub_after:
                after_hashes[stub_rel] = stub_hash
                record["documents"].append({
                    "path": stub_rel, "action": "update",
                    "version": {"supported": False, "before": None, "after": None},
                    "change_ref": None,
                    "before_sha256": sha256_bytes(targets[stub_rel] or b""),
                    "after_sha256": stub_hash,
                })
        record["backflow_status"] = "applied"
        append_history(record, "validated", source_sha256=record["source"]["sha256"],
                       document_sha256=after_hashes)
        write_record(req_root, record)
        return results, after_hashes
    except Exception:
        for path, old_bytes in reversed(journal):
            try:
                if old_bytes is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, old_bytes)
            except OSError:
                pass
        raise
    finally:
        for rel in reversed(acquired):
            try:
                claim.release(root, rel, owner)
            except Exception:
                pass


def run_validators(root: Path, *, include_structure: bool) -> list[dict]:
    names = ["validate_prd", "validate_e2e_index", "validate_testids"]
    if include_structure:
        names.append("validate_structure")
    results: list[dict] = []
    for name in names:
        local = root / ".atlas" / "validators" / f"{name}.py"
        script = local if local.is_file() else Path(__file__).resolve().parents[1] / "validators" / f"{name}.py"
        result = _run(root, [sys.executable, str(script), "--root", str(root), "--json"], check=False)
        try:
            payload = json.loads(result.stdout or "{}")
            status = payload.get("status", "FAIL" if result.returncode else "PASS")
        except json.JSONDecodeError:
            status = "FAIL" if result.returncode else "PASS"
        results.append({"validator": name, "status": status,
                        "returncode": result.returncode,
                        "output": (result.stdout + result.stderr).strip()[:4000]})
    return results


def artifact_paths(root: Path, req_root: Path, record: dict) -> set[str]:
    req_rel = Path(req_root).relative_to(root).as_posix()
    paths = {f"{req_rel}/{RECORD_FILE}", f"{req_rel}/{REQUIREMENT_DOC_FILE}",
             f"{req_rel}/{REQUIREMENT_ROOT_ITEMS_FILE}", f"{req_rel}/{record['report']['path']}"}
    for document in record.get("documents", []):
        paths.add(document["path"])
    return paths


def required_staged_paths(root: Path, req_root: Path, record: dict) -> set[str]:
    paths = {(Path(req_root) / RECORD_FILE).relative_to(root).as_posix()}
    for document in record.get("documents", []):
        if document.get("before_sha256") != document.get("after_sha256"):
            paths.add(document["path"])
    req_rel = Path(req_root).relative_to(root).as_posix()
    for rel in (f"{req_rel}/{REQUIREMENT_DOC_FILE}", f"{req_rel}/{REQUIREMENT_ROOT_ITEMS_FILE}",
                f"{req_rel}/{record['report']['path']}"):
        tracked = _run(root, ["git", "ls-files", "--error-unmatch", "--", rel],
                       check=False).returncode == 0
        changed = _run(root, ["git", "diff", "--cached", "--quiet", "HEAD", "--", rel],
                       check=False).returncode != 0
        if not tracked or changed:
            paths.add(rel)
    return paths


def _legacy_artifact_paths(root: Path, req_root: Path, record: dict) -> set[str]:
    paths = {(Path(req_root) / RECORD_FILE).relative_to(root).as_posix()}
    paths.update(item["path"] for item in record.get("documents", []))
    return paths


def review_anchor(root: Path, req_root: Path, record: dict, *, legacy: bool = False) -> dict:
    paths = _legacy_artifact_paths(root, req_root, record) if legacy else artifact_paths(root, req_root, record)
    artifacts = []
    for rel in sorted(paths):
        path = root / rel
        artifacts.append({"path": rel, "sha256": sha256_bytes(path.read_bytes())})
    deleted = []
    for item in record.get("source", {}).get("implementation_files", []):
        if item["new_oid"] == "0" * len(item["new_oid"]):
            deleted.append({"path": item["path"], "old_oid": item["old_oid"]})
    anchor = {
        "record_sha256": record["content_sha256"],
        "artifacts": artifacts,
        "history": [{"seq": event["seq"], "event_sha256": event["event_sha256"]}
                    for event in record.get("history", [])],
        "deleted_files": deleted,
    }
    return anchor if legacy else {"anchor_version": 2, **anchor}


def validate_review_anchor(review_data: dict, root: Path, req_root: Path,
                           record: dict) -> list[str]:
    current = review_data.get("change_backflow")
    legacy = review_data.get("bug_backflow")
    if current is not None and legacy is not None:
        return ["review.json 同时含 change_backflow 与 bug_backflow，语义不唯一"]
    if current is not None:
        if not isinstance(current, dict) or current.get("anchor_version") != 2:
            return ["review.json.change_backflow 缺 anchor_version=2"]
        expected = review_anchor(root, req_root, record)
        label = "change_backflow"
    elif legacy is not None:
        if not isinstance(legacy, dict):
            return ["review.json.bug_backflow 不是 object"]
        expected = review_anchor(root, req_root, record, legacy=True)
        label = "bug_backflow"
        legacy_paths = _legacy_artifact_paths(root, req_root, record)
        uncovered = sorted(artifact_paths(root, req_root, record) - legacy_paths)
        for rel in uncovered:
            tracked = _run(root, ["git", "ls-files", "--error-unmatch", "--", rel],
                           check=False).returncode == 0
            changed = _run(root, ["git", "diff", "--cached", "--quiet", "HEAD", "--", rel],
                           check=False).returncode != 0
            if not tracked or changed:
                return [f"legacy bug_backflow 未覆盖 canonical 产物且已变化：{rel}；必须 reverify"]
    else:
        return ["review.json 缺 change_backflow 独立锚"]
    if (current if current is not None else legacy) != expected:
        return [f"review.json.{label} 与当前台账/产物/历史/删除锚不一致"]
    scope = review_data.get("review_scope")
    if review_data.get("schema_version") != 4:
        return ["change finish 要求 schema_version=4 审查报告"]
    if not isinstance(scope, dict) or not isinstance(scope.get("sha256"), str) or not scope["sha256"]:
        return ["change finish 要求带 sha256 的 v4 review_scope"]
    if not isinstance(scope.get("files"), list):
        return ["change finish 要求 v4 review_scope.files"]
    reviewed = {item.get("path") for item in scope["files"] if isinstance(item, dict)}
    missing = [item["path"] for item in record["source"]["implementation_files"]
               if item["new_oid"] != "0" * len(item["new_oid"]) and item["path"] not in reviewed]
    if missing:
        return ["实现文件未进入实审集：" + "、".join(sorted(set(missing)))]
    return []


def validate_backflow(root: Path, task: dict, review_data: dict | None = None) -> dict:
    root = Path(root).resolve()
    req_ref = task.get("requirement_root")
    if not req_ref:
        return {"applicable": False, "findings": [], "cause": "", "artifacts": {}}
    req_root = resolve_defect_root(root, Path(str(req_ref)).name)
    if req_root is None:
        return {"applicable": True, "findings": ["需求落点无法解析"], "cause": "bug_backflow_missing",
                "artifacts": {}}
    fields, field_findings = strict_requirement_fields(req_root)
    declared = fields.get("类型")
    if declared and declared not in REQUIREMENT_TYPES:
        return {"applicable": True, "findings": [f"需求类型非法：{declared!r}"],
                "cause": "bug_backflow_invalid", "artifacts": {}}
    if declared not in CHANGE_TYPES:
        if defect_intent(req_root):
            return {"applicable": True, "findings": ["record/变更或缺陷报告存在但类型不是需求变更/缺陷"],
                    "cause": "bug_backflow_invalid", "artifacts": {}}
        return {"applicable": False, "findings": [], "cause": "", "artifacts": {}}
    findings = list(field_findings)
    record = read_record(req_root)
    if record is None:
        return {"applicable": True, "findings": [f"{declared}未执行 atlas change：缺 record.json"],
                "cause": "bug_backflow_missing", "artifacts": {}}
    findings.extend(validate_record(record, requirement_root=req_root, root=root))
    findings.extend(dedupe_findings(root, record, req_root))
    if findings:
        return {"applicable": True, "findings": findings, "cause": "bug_backflow_invalid",
                "artifacts": {}}
    if record["backflow_status"] in ("pending", "needs_decision"):
        return {"applicable": True, "findings": [f"{declared}回推待完成或待签字"],
                "cause": "bug_backflow_pending", "artifacts": {}}
    if record["backflow_status"] == "not_applicable":
        return {"applicable": True, "findings": ["not_applicable 不得用于任务卡收口"],
                "cause": "bug_backflow_invalid", "artifacts": {}}
    if record["source"]["mode"] != "staged":
        return {"applicable": True, "findings": ["range 回推记录不能用于 finish，请 --from staged 重跑"],
                "cause": "bug_backflow_mode_not_finish_ready", "artifacts": {}}
    artifacts = artifact_paths(root, req_root, record)
    legacy_implementation_artifacts = {
        item["path"] for item in record["source"].get("implementation_files", [])
        if item.get("path") in artifacts
    }
    try:
        snapshot = source_snapshot(root, "staged", None,
                                   artifacts - legacy_implementation_artifacts)
    except BackflowError as exc:
        return {"applicable": True, "findings": [str(exc)], "cause": exc.cause,
                "artifacts": {}}
    if snapshot["sha256"] != record["source"]["sha256"]:
        return {"applicable": True, "findings": ["实现 diff 已变化，回推记录过期"],
                "cause": "bug_backflow_stale", "artifacts": {}}
    findings.extend(index_worktree_findings(root, snapshot, artifacts))
    if findings:
        return {"applicable": True, "findings": findings,
                "cause": "bug_backflow_worktree_diverged", "artifacts": {}}
    staged = staged_paths(root)
    required = required_staged_paths(root, req_root, record)
    missing_staged = sorted(required - staged)
    if missing_staged:
        return {"applicable": True, "findings": ["回推产物未暂存：" + "、".join(missing_staged)],
                "cause": "bug_backflow_unstaged", "artifacts": {}}
    for document in record["documents"]:
        path = root / document["path"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != document["after_sha256"]:
            return {"applicable": True, "findings": [f"回推文档已变化：{document['path']}"],
                    "cause": "bug_backflow_stale", "artifacts": {}}
        if document.get("change_ref") and document["change_ref"] not in path.read_text(encoding="utf-8"):
            return {"applicable": True, "findings": [f"回推变更记录缺失：{document['path']}"],
                    "cause": "bug_backflow_invalid", "artifacts": {}}
    if review_data is not None:
        findings.extend(validate_review_anchor(review_data, root, req_root, record))
        if findings:
            return {"applicable": True, "findings": findings,
                    "cause": "bug_backflow_stale", "artifacts": {}}
    return {"applicable": True, "findings": [], "cause": "",
            "artifacts": {rel: sha256_bytes((root / rel).read_bytes()) for rel in sorted(artifacts)}}


def _dedupe_fingerprint(identity: tuple[str, str, str, str]) -> tuple[str, str, str, str]:
    """报告路径归一为文件名：work/ 与落点根扁平是同一份证据，不得各记一条。"""
    kind, report_path, related, digest = identity
    return kind, Path(report_path).name, related, digest


def dedupe_findings(root: Path, record: dict, req_root: Path) -> list[str]:
    identity = dedupe_identity(record.get("dedupe_key"))
    if identity is None:
        return []
    fingerprint = _dedupe_fingerprint(identity)

    def same(other: dict | None) -> bool:
        other_identity = dedupe_identity(other.get("dedupe_key")) if other else None
        if other_identity is None:
            return False
        return (other_identity == identity
                or _dedupe_fingerprint(other_identity) == fingerprint)

    base = load_layout(root).assets_root / "requirements"
    duplicates: list[str] = []
    for candidate in base.glob("*/record.json") if base.is_dir() else []:
        if candidate.parent == req_root:
            continue
        if same(read_record(candidate.parent)):
            duplicates.append(candidate.parent.name)
    for candidate in (base / "archive").glob("*/*/record.json") if (base / "archive").is_dir() else []:
        if candidate.parent == req_root:
            continue
        if same(read_record(candidate.parent)):
            duplicates.append(candidate.parent.parent.name + "/" + candidate.parent.name)
    return [f"dedupe_key 与其它变更/缺陷重复：{name}" for name in sorted(set(duplicates))]
