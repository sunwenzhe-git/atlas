#!/usr/bin/env python3
"""功能点活需求文档与 changes/bugs 请求记录。"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date
from pathlib import Path

from _support.semver import parse as parse_semver
from _support.workflow_plan import PlanError, read_requirement_fields

REQUEST_KINDS = ("需求变更", "缺陷")
REQUEST_STATUSES = ("confirmed", "implemented", "closed", "conflict", "failed")
STAGES = ("prod", "integration", "test")
ITEM_RE = re.compile(r"^\|\s*(R-\d{2,3})\s*\|", re.M)
CLAUSE_RE = re.compile(r"^###\s+(R-\d{2,3})\b[^\n]*\n(.*?)(?=^###\s+R-\d{2,3}\b|^##\s|\Z)", re.M | re.S)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_head(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
            text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def parse_request(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def request_items(meta: dict[str, str]) -> list[str]:
    raw = meta.get("items", "")
    return list(dict.fromkeys(re.findall(r"R-\d{2,3}", raw)))


def request_paths(feature_root: Path) -> list[Path]:
    paths: list[Path] = []
    changes = feature_root / "changes"
    if changes.is_dir():
        paths.extend(sorted(changes.glob("CHG-*/request.md")))
    bugs = feature_root / "bugs"
    if bugs.is_dir():
        paths.extend(sorted(bugs.glob("BUG-*.md")))
    return paths


def find_request(feature_root: Path, request_id: str) -> Path | None:
    for path in request_paths(feature_root):
        if parse_request(path).get("id") == request_id:
            return path
    return None


def find_request_by_digest(feature_root: Path, digest: str, kind: str,
                           related: str | None) -> Path | None:
    for path in request_paths(feature_root):
        meta = parse_request(path)
        if (meta.get("source_sha256") == digest and meta.get("kind") == kind
                and (related is None or meta.get("items") == related)):
            return path
    return None


def next_request_id(feature_root: Path, kind: str) -> str:
    prefix = "BUG" if kind == "缺陷" else "CHG"
    today = date.today().strftime("%Y%m%d")
    largest = 0
    for path in request_paths(feature_root):
        match = re.fullmatch(rf"{prefix}-{today}-(\d{{3}})", path.parent.name if path.name == "request.md" else path.stem)
        if match:
            largest = max(largest, int(match.group(1)))
    return f"{prefix}-{today}-{largest + 1:03d}"


def item_ids(feature_root: Path) -> list[str]:
    path = feature_root / "items.md"
    if not path.is_file():
        return []
    return list(dict.fromkeys(ITEM_RE.findall(path.read_text(encoding="utf-8", errors="replace"))))


def next_item_id(feature_root: Path) -> str:
    ids = item_ids(feature_root)
    if not ids:
        return "R-01"
    return f"R-{max(int(x.split('-')[1]) for x in ids) + 1:02d}"


def clause_text(feature_root: Path, item_id: str) -> str | None:
    path = feature_root / "requirement.md"
    if not path.is_file():
        return None
    match = CLAUSE_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    while match:
        if match.group(1) == item_id:
            return match.group(2).strip()
        match = CLAUSE_RE.search(path.read_text(encoding="utf-8", errors="replace"), match.end())
    return None


def requirement_version(feature_root: Path) -> str:
    path = feature_root / "requirement.md"
    match = re.search(r"^\*\*版本\*\*[：:]\s*(\S+)\s*$", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return match.group(1) if match else "1.0.0"


def _bump_version(raw: str, kind: str) -> str:
    parsed = parse_semver(raw or "1.0.0")
    if parsed is None:
        return "1.0.0" if kind == "初始需求" else "1.0.1"
    (major, minor, patch), pre = parsed
    if kind == "需求变更":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    suffix = "-" + ".".join(pre) if pre else ""
    return f"{major}.{minor}.{patch}{suffix}"


def _set_field(text: str, key: str, value: str) -> str:
    pattern = rf"^\*\*{re.escape(key)}\*\*[：:].*$"
    replacement = f"**{key}**：{value}  "
    if re.search(pattern, text, re.M):
        return re.sub(pattern, replacement, text, count=1, flags=re.M)
    first_line = text.split("\n", 1)
    if len(first_line) == 2 and first_line[0].startswith("#"):
        return first_line[0] + "\n\n" + replacement + "\n" + first_line[1].lstrip("\n")
    return replacement + "\n" + text


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def _append_change_record(text: str, request_id: str, kind: str, summary: str,
                          items: str, conclusion: str) -> str:
    row = f"| {request_id} | {kind} | {date.today().isoformat()} | {_md_cell(summary)} | {_md_cell(items)} | {_md_cell(conclusion)} |"
    heading = "## 变更记录"
    if heading not in text:
        text = text.rstrip() + "\n\n" + heading + "\n\n| 请求 | 类型 | 日期 | 内容 | 影响条款 | 结论 |\n|---|---|---|---|---|---|\n"
        return text.rstrip() + "\n" + row + "\n"
    start = text.index(heading) + len(heading)
    next_heading = re.search(r"^##\s", text[start:], re.M)
    end = start + next_heading.start() if next_heading else len(text)
    section = text[start:end].rstrip()
    return text[:start] + "\n\n" + section + "\n" + row + "\n\n" + text[end:].lstrip("\n")


def update_request_status(path: Path, **fields: str) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    end = text.find("\n---", 3)
    if end < 0:
        raise PlanError(f"请求记录缺 frontmatter：{path}")
    header = text[3:end]
    for key, value in fields.items():
        pattern = rf"^{re.escape(key)}:.*$"
        if re.search(pattern, header, re.M):
            header = re.sub(pattern, f"{key}: {value}", header, count=1, flags=re.M)
        else:
            header += f"\n{key}: {value}"
    path.write_text(text[:3] + header + text[end:], encoding="utf-8")


def create_feature(root: Path, feature_root: Path, text: str, slug: str,
                   request_id: str, dry_run: bool) -> None:
    if dry_run:
        return
    feature_root.mkdir(parents=True, exist_ok=False)
    title = text.splitlines()[0].strip().lstrip("#").strip()[:80] or slug
    requirement = (
        f"# {title}\n\n**类型**：初始需求  \n**状态**：已确认  \n"
        f"**版本**：1.0.0  \n**输入摘要**：{sha256_text(text)}  \n\n"
        f"## 需求条款\n\n### R-01 {title}\n\n{text}\n\n"
        "## 变更记录\n\n| 请求 | 类型 | 日期 | 内容 | 影响条款 | 结论 |\n"
        "|---|---|---|---|---|---|\n"
        f"| {request_id} | 初始需求 | {date.today().isoformat()} | 首版需求 | R-01 | 已确认 |\n"
    )
    (feature_root / "requirement.md").write_text(requirement, encoding="utf-8")
    (feature_root / "items.md").write_text(
        "| ID | 锚 | 状态 | 最近请求 |\n|---|---|---|---|\n"
        f"| R-01 | requirement.md#R-01 | active | {request_id} |\n", encoding="utf-8")
    initial = feature_root / "changes" / "CHG-000-initial"
    initial.mkdir(parents=True)
    (initial / "requirement.md").write_text(requirement, encoding="utf-8")
    (initial / "request.md").write_text(
        f"---\nid: {request_id}\nkind: 初始需求\nfeature: {slug}\nitems: R-01\n"
        f"source_sha256: {sha256_text(text)}\nbase_commit: {current_head(root)}\n"
        f"status: confirmed\nstage: test\ncreated: {date.today().isoformat()}\n---\n\n"
        f"# 初始需求\n\n{text}\n", encoding="utf-8")
    (initial / "diff.md").write_text("# 首版基线\n\n初始需求快照见 `requirement.md`。\n", encoding="utf-8")


def create_change_request(root: Path, feature_root: Path, text: str, kind: str,
                          related: str, request_id: str, dry_run: bool) -> None:
    if dry_run:
        return
    item_id = related.split("#", 1)[1]
    changes = feature_root / "changes"
    if kind == "需求变更":
        target = changes / request_id
        target.mkdir(parents=True)
        path = target / "request.md"
        before = clause_text(feature_root, item_id) or "未找到既有条款正文"
        (target / "diff.md").write_text(
            f"# 变更差异\n\n## 变更前\n\n{before}\n\n## 变更后\n\n{text}\n",
            encoding="utf-8")
    else:
        path = feature_root / "bugs" / f"{request_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {request_id}\nkind: {kind}\nfeature: {feature_root.name}\nitems: {item_id}\n"
        f"source_sha256: {sha256_text(text)}\nbase_commit: {current_head(root)}\n"
        f"status: confirmed\nstage: test\ncreated: {date.today().isoformat()}\n---\n\n"
        f"# {kind}\n\n## 用户原话\n\n{text}\n\n"
        + (f"## 关联基线\n\n`{related}`\n\n" if related else "")
        + ("## 缺陷证据\n\n- 现象：见用户原话\n- 期望：恢复关联条款的既有行为\n"
           "- 实际：用户报告与期望不一致\n- 复现：用户未提供具体操作序列\n"
           "- 环境：用户未提供\n" if kind == "缺陷" else "## 变更口径\n\n见 `diff.md`。\n"),
        encoding="utf-8")
    doc_path = feature_root / "requirement.md"
    doc = doc_path.read_text(encoding="utf-8", errors="replace")
    version = _bump_version(requirement_version(feature_root), kind)
    doc = _set_field(doc, "版本", version)
    doc = _append_change_record(doc, request_id, kind, text, item_id,
                                "待修复" if kind == "缺陷" else "待实现")
    doc_path.write_text(doc, encoding="utf-8")
    items_path = feature_root / "items.md"
    items = items_path.read_text(encoding="utf-8", errors="replace")
    pattern = rf"^(\|\s*{re.escape(item_id)}\s*\|[^|]*\|[^|]*\|)[^|]*(\|)$"
    items = re.sub(pattern, rf"\g<1>{request_id}\g<2>", items, count=1, flags=re.M)
    items_path.write_text(items, encoding="utf-8")


def update_change_conclusion(feature_root: Path, request_id: str, conclusion: str) -> None:
    path = feature_root / "requirement.md"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"| {request_id} |"):
            prefix, _old, _tail = line.rsplit("|", 2)
            lines[index] = prefix + "| " + _md_cell(conclusion) + " |"
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def request_source_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanError(f"请求记录不可读：{path}: {exc}") from exc
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end < 0:
            raise PlanError(f"请求记录缺 frontmatter：{path}")
        text = text[end + 4:].lstrip("\n")
    meta = parse_request(path)
    if meta.get("kind") == "初始需求":
        lines = text.splitlines()
        candidates = ["\n".join(lines[1:]) if lines and lines[0].startswith("#") else text]
    else:
        marker = "## 用户原话"
        if marker not in text:
            raise PlanError(f"请求记录缺用户原话：{path}")
        source = text.split(marker, 1)[1].lstrip("\n")
        candidates = [source]
        candidates.extend(source[:match.start()] for match in re.finditer(
            r"^## (?:关联基线|缺陷证据|变更口径)[ \t]*$", source, re.M))
    for candidate in candidates:
        source = candidate.strip()
        if sha256_text(source) == meta.get("source_sha256"):
            return source
    raise PlanError(f"请求原文无法与 source_sha256 对账：{path}")


def request_diff_path(request_path: Path, kind: str) -> Path:
    return request_path.with_suffix(".diff.md") if kind == "缺陷" else request_path.parent / "diff.md"


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]


def living_document_findings(feature_root: Path, request_path: Path) -> list[str]:
    findings: list[str] = []
    requirement = feature_root / "requirement.md"
    items_path = feature_root / "items.md"
    if not requirement.is_file() or not items_path.is_file():
        return ["功能活文档缺 requirement.md 或 items.md"]
    try:
        requirement_text = requirement.read_text(encoding="utf-8")
    except UnicodeError:
        requirement_text = ""
        findings.append("requirement.md 不是合法 UTF-8")
    try:
        items_text = items_path.read_text(encoding="utf-8")
    except UnicodeError:
        items_text = ""
        findings.append("items.md 不是合法 UTF-8")
    fields = read_requirement_fields(feature_root)
    if fields.get("类型", "初始需求") != "初始需求":
        findings.append("功能根类型必须保持初始需求")
    if fields.get("状态") not in ("已确认", "已拆"):
        findings.append("功能根状态非法")
    if not re.search(r"^\*\*版本\*\*[：:]\s*\d+\.\d+\.\d+", requirement_text, re.M):
        findings.append("功能根缺语义版本")
    ids = item_ids(feature_root)
    if not ids:
        findings.append("功能根无 R 条款")
    item_rows = [_table_cells(line) for line in items_text.splitlines()
                 if re.match(r"^\|\s*R-\d{2,3}\b", line)]
    item_rows = [cells for cells in item_rows if cells]
    row_ids = [cells[0] for cells in item_rows]
    if len(row_ids) != len(set(row_ids)):
        findings.append("items.md 条款 ID 重复")
    for cells in item_rows:
        if len(cells) != 4 or not all(cells):
            findings.append(f"items.md 条款行结构非法：{cells[0]}")
    requests: dict[str, dict[str, str]] = {}
    for path in request_paths(feature_root):
        request_meta = parse_request(path)
        if request_meta.get("id"):
            requests[request_meta["id"]] = request_meta
    change_section = requirement_text.split("## 变更记录", 1)[1] if "## 变更记录" in requirement_text else ""
    if not change_section:
        findings.append("requirement.md 缺变更记录")
    change_rows = [_table_cells(line) for line in change_section.splitlines()
                   if line.startswith("|")]
    change_data_rows = [cells for cells in change_rows
                        if cells and cells[0] != "请求"
                        and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)]
    for cells in change_data_rows:
        if len(cells) != 6 or not all(cells):
            findings.append(f"requirement.md 变更记录行结构非法：{cells[0]}")
        elif cells[0] not in requests:
            findings.append(f"requirement.md 变更记录请求不存在：{cells[0]}")
    change_entries = [cells for cells in change_data_rows
                      if len(cells) == 6 and cells[0] in requests]
    for change_id in requests:
        rows = [cells for cells in change_rows if cells and cells[0] == change_id]
        if len(rows) != 1 or len(rows[0]) != 6 or not all(rows[0]):
            findings.append(f"requirement.md 请求变更记录结构非法：{change_id}")
    for cells in item_rows:
        if len(cells) != 4 or not all(cells):
            continue
        item, recent = cells[0], cells[3]
        related = [entry[0] for entry in change_entries
                   if item in re.findall(r"R-\d{2,3}", entry[4])]
        if not related or recent != related[-1]:
            findings.append(f"items.md 最近请求不是该条款最新请求：{item}")
        if recent not in requests or item not in request_items(requests[recent]):
            findings.append(f"items.md 最近请求不存在或不关联该条款：{item}")
    for item in ids:
        if not (clause_text(feature_root, item) or "").strip():
            findings.append(f"items.md 条款无正文：{item}")
    meta = parse_request(request_path)
    expected_id = request_path.parent.name if request_path.name == "request.md" else request_path.stem
    if meta.get("id") != expected_id:
        findings.append("请求 ID 与文件路径不一致")
    if meta.get("kind") == "需求变更":
        diff = request_diff_path(request_path, "需求变更")
        text = diff.read_text(encoding="utf-8", errors="replace") if diff.is_file() else ""
        if "## 变更前" not in text or "## 变更后" not in text:
            findings.append("需求变更缺 diff.md 前后口径")
    if meta.get("kind") == "缺陷":
        text = request_path.read_text(encoding="utf-8", errors="replace")
        for key in ("现象", "期望", "实际", "复现", "环境"):
            if key not in text:
                findings.append(f"缺陷报告缺 {key}")
    return findings


def request_findings(feature_root: Path, request_path: Path) -> list[str]:
    meta = parse_request(request_path)
    if not meta:
        return [f"请求记录不可解析：{request_path}"]
    findings: list[str] = []
    if meta.get("kind") not in ("初始需求", *REQUEST_KINDS):
        findings.append(f"请求类型非法：{meta.get('kind')!r}")
    if meta.get("status") not in REQUEST_STATUSES:
        findings.append(f"请求状态非法：{meta.get('status')!r}")
    if meta.get("stage") not in STAGES:
        findings.append(f"请求阶段非法：{meta.get('stage')!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", meta.get("source_sha256", "")):
        findings.append("请求缺 source_sha256")
    items = request_items(meta)
    if not items:
        findings.append("请求未关联 R 条款")
    for item in items:
        if item not in item_ids(feature_root):
            findings.append(f"请求关联条款不存在：{item}")
    return findings
