#!/usr/bin/env python3
"""自然语言需求归类、统一落点与实现前置门。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from _support.layout import LayoutError, load_layout
from _support.workflow_request import (
    create_change_request, create_feature, find_request_by_digest,
    next_request_id, parse_request, request_findings, request_paths,
)
from _support.workflow_verify import strip_fences
from _support.workflow_plan import (
    REQUIREMENT_DOC_FILE, REQUIREMENT_RELATED_RE, REQUIREMENT_TYPES,
    PlanError, read_requirement_fields, requirement_relation_findings,
    resolve_requirement_root, resolve_requirement_root_by_slug,
)

TYPE_ALIASES = {
    "initial": "初始需求", "requirement": "初始需求", "初始需求": "初始需求",
    "change": "需求变更", "requirement_change": "需求变更", "需求变更": "需求变更",
    "bug": "缺陷", "缺陷": "缺陷",
}
STRONG_BUG_RE = re.compile(
    r"bug|缺陷|报错|崩溃|打不开|不生效|线上问题|联调问题|"
    r"调用失败|请求失败|加载失败|保存失败|提交失败|操作失败",
    re.I,
)
BUG_RE = re.compile(r"偶尔|复现|回归|失败|异常", re.I)
CHANGE_RE = re.compile(r"新增|增加|支持|改为|修改|改动|调整|优化|升级|移除|删除|变更|改版")
SOURCE_DIGEST_RE = re.compile(r"^\*\*输入摘要\*\*[：:]\s*([0-9a-f]{64})\s*$", re.M)
ITEM_RE = re.compile(r"^\|\s*(R-\d{2,3})\s*\|", re.M)
INDEX_BEGIN = "<!-- atlas:requirements-index:begin -->"
INDEX_END = "<!-- atlas:requirements-index:end -->"


@dataclass(frozen=True)
class IntakeResult:
    root: Path
    rel: str
    kind: str
    related: str | None
    item_id: str
    created: bool
    request_id: str | None = None
    request_rel: str | None = None
    version: int = 2


def _normalise(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _requirements_base(root: Path) -> Path:
    root = Path(root).resolve()
    assets = load_layout(root).assets_root.resolve()
    base = (assets / "requirements").resolve()
    if base.parent != assets or root not in base.parents:
        raise LayoutError("requirements 必须位于配置资产根内且不得经 symlink 逃逸")
    return base


def _requirement_roots(root: Path) -> list[Path]:
    base = _requirements_base(root)
    roots: list[Path] = []
    if base.is_dir() and not base.is_symlink():
        roots.extend(p for p in sorted(base.iterdir())
                     if p.is_dir() and not p.is_symlink()
                     and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", p.name)
                     and (p / REQUIREMENT_DOC_FILE).is_file()
                     and not (p / REQUIREMENT_DOC_FILE).is_symlink())
    archive = base / "archive"
    if archive.is_dir() and not archive.is_symlink():
        for month in sorted(archive.iterdir()):
            if month.is_symlink() or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month.name):
                continue
            roots.extend(p for p in sorted(month.iterdir())
                         if p.is_dir() and not p.is_symlink()
                         and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", p.name)
                         and (p / REQUIREMENT_DOC_FILE).is_file()
                         and not (p / REQUIREMENT_DOC_FILE).is_symlink())
    return roots


def _title(req_root: Path) -> str:
    text = (req_root / REQUIREMENT_DOC_FILE).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    return match.group(1).strip() if match else req_root.name


def _item_ids(req_root: Path) -> list[str]:
    path = req_root / "items.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return list(dict.fromkeys(ITEM_RE.findall(strip_fences(text))))


def classify_requirement(text: str, declared: str = "auto") -> str:
    """确定性分类；语义仍模糊时由调用方要求显式 --type。"""
    if declared != "auto":
        try:
            return TYPE_ALIASES[declared]
        except KeyError as exc:
            raise PlanError(f"需求类型非法：{declared!r}（auto/initial/change/bug）") from exc
    if STRONG_BUG_RE.search(text):
        return "缺陷"
    if CHANGE_RE.search(text):
        return "需求变更"
    if BUG_RE.search(text):
        return "缺陷"
    return "初始需求"


def _mentions_root(text: str, req_root: Path) -> bool:
    normalised = _normalise(text)
    title = _normalise(_title(req_root))
    aliases = {_normalise(req_root.name), title, re.sub(r"^v\d+", "", title)}
    return any(len(alias) >= 6 and alias in normalised for alias in aliases)


def _resolve_parent(root: Path, text: str, related: str | None) -> tuple[Path, str, str]:
    if not related:
        explicit = re.search(
            r"(?<![\w-])([A-Za-z0-9][A-Za-z0-9._-]{0,63})#(R-\d{2,3})\b", text)
        if explicit:
            related = f"{explicit.group(1)}#{explicit.group(2)}"
    if related:
        match = REQUIREMENT_RELATED_RE.fullmatch(related)
        if not match:
            raise PlanError(f"关联需求形态非法：{related!r}（须为 <slug>#R-NN）")
        target = resolve_requirement_root_by_slug(root, match.group("slug"))
        if target is None:
            raise PlanError(f"关联需求找不到唯一落点：{match.group('slug')}")
        item_id = match.group("item")
        if item_id not in _item_ids(target):
            raise PlanError(f"关联需求条目不存在：{related}")
        if read_requirement_fields(target).get("状态") not in ("已确认", "已拆"):
            raise PlanError(f"关联需求基线未确认：{match.group('slug')}")
        return target, related, item_id

    mentioned = [p for p in _requirement_roots(root) if _mentions_root(text, p)]
    if len(mentioned) > 1:
        choices = "、".join(p.name for p in mentioned)
        raise PlanError(f"父需求歧义：命中多个落点（{choices}）；请用 --related <slug>#R-NN 指定")
    if mentioned:
        target = mentioned[0]
    else:
        raise PlanError(
            "请求未唯一点名父需求；需求变更/缺陷请用 --related <slug>#R-NN 指定行为基线，"
            "独立新能力请用 --type initial")

    explicit_item = re.search(r"(?<![A-Za-z0-9])R-\d{2,3}(?![0-9])", text)
    if explicit_item:
        item_id = explicit_item.group(0)
        if item_id not in _item_ids(target):
            raise PlanError(f"关联需求条目不存在：{target.name}#{item_id}")
    else:
        item_ids = _item_ids(target)
        if len(item_ids) != 1:
            raise PlanError(
                f"父需求 {target.name} 有多个行为条款，当前请求未唯一点位；"
                "请用 --related <slug>#R-NN 指定")
        item_id = item_ids[0]
    if read_requirement_fields(target).get("状态") not in ("已确认", "已拆"):
        raise PlanError(f"关联需求基线未确认：{target.name}")
    return target, f"{target.name}#{item_id}", item_id


def _source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def requirement_source_digest(req_root: Path) -> str | None:
    doc = (req_root / REQUIREMENT_DOC_FILE).read_text(encoding="utf-8", errors="replace")
    match = SOURCE_DIGEST_RE.search(doc)
    return match.group(1) if match else None


def requirement_matches_text(req_root: Path, text: str) -> bool:
    return requirement_source_digest(req_root) == _source_digest(text.strip())


def _find_existing(root: Path, text: str, kind: str | None = None,
                   related: str | None = None) -> Path | None:
    digest = _source_digest(text)
    for req_root in _requirement_roots(root):
        if requirement_source_digest(req_root) != digest:
            continue
        fields = read_requirement_fields(req_root)
        if kind is not None and fields.get("类型") != kind:
            continue
        if fields.get("状态") == "已收口":
            continue
        if related is not None and fields.get("关联需求") != related:
            continue
        return req_root
    return None


def ensure_requirement_intake(root: Path, text: str, *, declared: str = "auto",
                              related: str | None = None, slug: str | None = None,
                              dry_run: bool = False) -> IntakeResult:
    """自然语言请求落入功能活文档；变更/缺陷只新增请求，不新增功能 slug。"""
    root = Path(root).resolve()
    text = text.strip()
    if not text:
        raise PlanError("需求文本为空，无法归类")
    if declared == "initial" and related:
        raise PlanError("初始需求不能同时声明既有行为基线；请用 --type change 或 bug")
    if declared == "auto":
        existing_initial = _find_existing(root, text, "初始需求", None)
        if existing_initial is not None and (not slug or slug == existing_initial.name):
            initial_request = find_request_by_digest(existing_initial, _source_digest(text), "初始需求", None)
            if initial_request is not None:
                meta = parse_request(initial_request)
                return IntakeResult(
                    existing_initial, existing_initial.relative_to(root).as_posix(), "初始需求",
                    None, "R-01", False, meta.get("id", "CHG-000-initial"),
                    initial_request.relative_to(root).as_posix())
    kind = classify_requirement(text, declared)
    if related and kind == "初始需求":
        kind = "需求变更"
    base = _requirements_base(root)
    open_root = any(
        p.is_dir() and not p.is_symlink() and p.name != "archive"
        and (p / REQUIREMENT_DOC_FILE).is_file() and not (p / REQUIREMENT_DOC_FILE).is_symlink()
        and read_requirement_fields(p).get("状态") != "已收口"
        for p in base.iterdir()
    ) if base.is_dir() else False
    if kind == "需求变更" and declared == "auto" and not related and not open_root:
        kind = "初始需求"
    if (base / "_index.md").is_symlink():
        raise LayoutError(f"需求索引不得为 symlink：{base / '_index.md'}")

    if kind == "初始需求":
        feature = resolve_requirement_root_by_slug(root, slug) if slug else _find_existing(
            root, text, "初始需求", None)
        if feature is not None and "archive" in feature.relative_to(base).parts:
            feature = None
        if feature is not None and requirement_source_digest(feature) != _source_digest(text):
            raise PlanError(f"功能 slug 已存在且初始原文不同，拒绝复用：{feature.name}")
        request = find_request_by_digest(feature, _source_digest(text), "初始需求", None) if feature else None
        if feature is not None and request is None:
            rel = feature.relative_to(root).as_posix()
            return IntakeResult(feature, rel, kind, None, "R-01", False, version=1)
        if feature is None:
            feature_slug = slug or f"feat-{_source_digest(text)[:12]}"
            if feature_slug in ("archive", "_index") or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", feature_slug):
                raise PlanError(f"功能 slug 非法或为保留名：{feature_slug!r}")
            if resolve_requirement_root_by_slug(root, feature_slug) is not None:
                existing_root = resolve_requirement_root_by_slug(root, feature_slug)
                if existing_root and read_requirement_fields(existing_root).get("状态") == "已收口":
                    raise PlanError(f"功能需求已收口，不能重建：{feature_slug}")
                raise PlanError(f"功能 slug 已存在：{feature_slug}")
            feature = base / feature_slug
            request_id = "CHG-000-initial"
            request_path = feature / "changes" / request_id / "request.md"
            create_feature(root, feature, text, feature_slug, request_id, dry_run)
            created = True
        else:
            meta = parse_request(request)
            request_id = meta.get("id", "CHG-000-initial")
            request_path = request
            created = False
        rel = feature.relative_to(root).as_posix()
        result = IntakeResult(feature, rel, kind, None, "R-01", created,
                              request_id, request_path.relative_to(root).as_posix())
    else:
        parent, related, item_id = _resolve_parent(root, text, related)
        try:
            parent_parts = parent.relative_to(base).parts
        except ValueError as exc:
            raise PlanError("父需求必须位于配置资产根内") from exc
        if parent_parts and parent_parts[0] == "archive":
            raise PlanError("功能需求已归档，不能新增变更或缺陷请求")
        if slug and slug != parent.name:
            raise PlanError(f"功能 slug 与父需求不一致：{slug} != {parent.name}")
        digest = _source_digest(text)
        request = find_request_by_digest(parent, digest, kind, item_id)
        if request is not None:
            meta = parse_request(request)
            request_id = meta.get("id", "")
            request_path = request
            created = False
        else:
            request_id = next_request_id(parent, kind)
            request_path = (parent / "bugs" / f"{request_id}.md") if kind == "缺陷" else (
                parent / "changes" / request_id / "request.md")
            create_change_request(root, parent, text, kind, related, request_id, dry_run)
            created = True
        rel = parent.relative_to(root).as_posix()
        result = IntakeResult(parent, rel, kind, related, item_id, created,
                              request_id, request_path.relative_to(root).as_posix())
    if not dry_run:
        refresh_requirement_index(root)
    return result


def mark_requirement_split(req_root: Path) -> None:
    """已确认落点在拆卡后推进为已拆；候选态不被自动推进。"""
    path = req_root / REQUIREMENT_DOC_FILE
    text = path.read_text(encoding="utf-8")
    updated = re.sub(r"^\*\*状态\*\*[：:]\s*已确认[ \t]*$", "**状态**：已拆  ",
                     text, count=1, flags=re.M)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def refresh_requirement_index(root: Path) -> None:
    """重建派生导航；权威仍是各落点 requirement.md 与 task.json。"""
    base = _requirements_base(root)
    if not base.is_dir():
        return
    rows = ["| slug | 类型 | 关联需求 |", "|---|---|---|"]
    for req_root in _requirement_roots(root):
        fields = read_requirement_fields(req_root)
        rows.append("| " + " | ".join([
            req_root.name, fields.get("类型", "初始需求"), fields.get("关联需求", "无"),
        ]) + " |")
    block = INDEX_BEGIN + "\n" + "\n".join(rows) + "\n" + INDEX_END
    path = base / "_index.md"
    if path.is_symlink():
        raise LayoutError(f"需求索引不得为 symlink：{path}")
    text = path.read_text(encoding="utf-8") if path.is_file() else "# 需求落点索引\n\n"
    if INDEX_BEGIN in text and INDEX_END in text:
        start = text.index(INDEX_BEGIN)
        end = text.index(INDEX_END, start) + len(INDEX_END)
        text = text[:start] + block + text[end:]
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def intake_task_findings(root: Path, task: dict, *, check_status: bool = True) -> list[str]:
    """新一代任务卡的实现前置；旧卡无 intake_version 时保持原行为。"""
    version = task.get("intake_version")
    if version not in (1, 2):
        return []
    ref = task.get("requirement_root")
    if not isinstance(ref, str) or not ref:
        return ["任务未完成需求归类与落盘：缺 requirement_root"]
    try:
        req_root = resolve_requirement_root(root, ref)
    except LayoutError as exc:
        return [f"需求落点无法解析：{exc}"]
    if req_root is None:
        return [f"需求落点不存在或归档不唯一：{ref}"]
    fields = read_requirement_fields(req_root)
    closed_task = task.get("status") == "completed" and task.get("_archived") is True
    if (check_status and fields.get("状态") not in ("已确认", "已拆")
            and not closed_task):
        return [f"需求落点状态为 {fields.get('状态') or '缺失'}；先完成确认再实现"]
    if version == 2:
        request_ref = task.get("request_path")
        if not isinstance(request_ref, str) or not request_ref:
            return ["任务缺请求记录路径：request_path"]
        request_path = root / request_ref
        try:
            request_path.resolve().relative_to(req_root.resolve())
        except (ValueError, OSError):
            return ["请求记录必须位于功能落点内"]
        return request_findings(req_root, request_path)
    kind = fields.get("类型", "初始需求")
    if kind not in REQUIREMENT_TYPES:
        return [f"需求类型未归类或非法：{kind!r}"]
    findings = requirement_relation_findings(root, req_root)
    if kind == "需求变更" and not (req_root / "work" / "变更请求.md").is_file():
        findings.append("需求变更缺 work/变更请求.md")
    if not _item_ids(req_root):
        findings.append("需求落点缺 items.md 行为条目")
    return findings
