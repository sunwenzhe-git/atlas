"""M247: RFC-20261125-01 P2 explicit document governance.

First paragraph declaration: removing the unchanged-body or objective-evidence
touch guards must turn tests/test_docs_governance.py red. The real four-stage
mutation_proof is stored under .atlas/runs/mutation-proof/M247.txt.

The registry contains declarations only. SHA-256 baselines, actors and evidence
live in an append-only JSONL ledger. This module never rewrites document bodies.
"""
from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows: O_APPEND + one os.write provides the append boundary.
    fcntl = None
import hashlib
import json
import os
import posixpath
import re
import subprocess
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from _support.governance_io import GovernancePathError, safe_path
from _support.governance_schema import load_schema, validate
from _support.layout import Layout, load_layout, strip_inline_comment

MODES = ("shadow", "enforce", "off")


def docs_mode(root: str | Path) -> str:
    selected = os.environ.get("ATLAS_DOCS_MODE", "shadow")
    if selected not in MODES:
        raise DocsGovernanceError("ATLAS_DOCS_MODE 非法")
    return selected

_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"^-?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_HEX = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class DocsGovernanceError(ValueError):
    """A registry, ledger, path or review event is invalid."""


class DocsIOError(OSError):
    """A governance input could not be read due to an I/O failure."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DocsGovernanceError(f"JSON 重复键：{key}")
        result[key] = value
    return result


def _split_top(text: str, delimiter: str, line: int) -> list[str]:
    parts: list[str] = []
    start = 0
    quote = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise DocsGovernanceError(f"第 {line} 行括号不匹配")
        elif char == delimiter and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if quote or depth:
        raise DocsGovernanceError(f"第 {line} 行引号或括号未闭合")
    parts.append(text[start:].strip())
    return parts


def _mapping_pair(text: str, line: int, flow: bool = False) -> tuple[str, str] | None:
    quote = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == ":" and depth == 0:
            # Block YAML requires whitespace after ':'; flow also accepts JSON's
            # compact form, while URLs remain scalar values.
            if flow or index + 1 == len(text) or text[index + 1].isspace():
                key = text[:index].strip()
                if not key:
                    raise DocsGovernanceError(f"第 {line} 行映射键为空")
                return key, text[index + 1:].strip()
    return None


def _scalar(raw: str, line: int):
    value = raw.strip()
    if not value:
        return None
    if value[0] in "&*!|>" or value in ("---", "..."):
        raise DocsGovernanceError(f"第 {line} 行不支持锚、标签、块标量或文档标记")
    if value[0] == '"':
        try:
            parsed = json.loads(value, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, DocsGovernanceError) as exc:
            raise DocsGovernanceError(f"第 {line} 行双引号标量非法：{exc}") from exc
        if not isinstance(parsed, str):
            raise DocsGovernanceError(f"第 {line} 行引号值必须闭合")
        return parsed
    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'":
            raise DocsGovernanceError(f"第 {line} 行单引号未闭合")
        return value[1:-1].replace("''", "'")
    if value.startswith("["):
        if not value.endswith("]"):
            raise DocsGovernanceError(f"第 {line} 行列表未闭合")
        inner = value[1:-1].strip()
        if not inner:
            return []
        parts = _split_top(inner, ",", line)
        if parts[-1] == "":
            parts.pop()
        if any(not part for part in parts):
            raise DocsGovernanceError(f"第 {line} 行列表含空项")
        return [_scalar(part, line) for part in parts]
    if value.startswith("{"):
        if not value.endswith("}"):
            raise DocsGovernanceError(f"第 {line} 行映射未闭合")
        inner = value[1:-1].strip()
        if not inner:
            return {}
        result = {}
        parts = _split_top(inner, ",", line)
        if parts[-1] == "":
            parts.pop()
        for part in parts:
            pair = _mapping_pair(part, line, flow=True)
            if pair is None:
                raise DocsGovernanceError(f"第 {line} 行 flow map 缺冒号")
            key = _scalar(pair[0], line)
            if not isinstance(key, str) or not key:
                raise DocsGovernanceError(f"第 {line} 行 flow map 键必须为非空字符串")
            if key in result:
                raise DocsGovernanceError(f"第 {line} 行重复键：{key}")
            result[key] = _scalar(pair[1], line)
        return result
    if value[0] in "[{" or value[-1] in "]}":
        raise DocsGovernanceError(f"第 {line} 行括号不匹配")
    lowered = value.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _INTEGER.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        return float(value)
    return value


def parse_docs_yaml(text: str) -> dict:
    """Parse the registry's narrow YAML subset, or an equivalent JSON object.

    Supported: block/flow maps and lists, quoted/plain scalars, integers,
    booleans and null. Anchors, tags, multiline scalars and merge keys are
    deliberately rejected rather than silently misread.
    """
    if not isinstance(text, str):
        raise DocsGovernanceError("registry 必须为文本")
    if text.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(text, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise DocsGovernanceError(f"JSON registry 非法：{exc}") from exc
        if not isinstance(value, dict):
            raise DocsGovernanceError("JSON registry 顶层必须为对象")
        return value

    rows: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip(" \t"))]:
            raise DocsGovernanceError(f"第 {number} 行缩进不得使用 Tab")
        clean = strip_inline_comment(raw.rstrip())
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        rows.append((indent, clean[indent:], number))
    if not rows:
        raise DocsGovernanceError("registry 为空")

    def block(index: int, indent: int):
        if index >= len(rows) or rows[index][0] != indent:
            raise DocsGovernanceError(f"第 {rows[index][2] if index < len(rows) else 'EOF'} 行缩进不连续")
        is_list = rows[index][1] == "-" or rows[index][1].startswith("- ")
        container = [] if is_list else {}
        while index < len(rows):
            current_indent, content, number = rows[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise DocsGovernanceError(f"第 {number} 行缩进过深")
            item_is_list = content == "-" or content.startswith("- ")
            if item_is_list != is_list:
                raise DocsGovernanceError(f"第 {number} 行 map/list 形态不一致")
            index += 1
            if is_list:
                rest = content[1:].strip()
                if not rest:
                    if index < len(rows) and rows[index][0] > indent:
                        value, index = block(index, rows[index][0])
                    else:
                        value = None
                    container.append(value)
                    continue
                pair = _mapping_pair(rest, number)
                if pair is None:
                    container.append(_scalar(rest, number))
                    if index < len(rows) and rows[index][0] > indent:
                        raise DocsGovernanceError(f"第 {rows[index][2]} 行标量列表项不得含子块")
                    continue
                key = _scalar(pair[0], number)
                if not isinstance(key, str) or not key:
                    raise DocsGovernanceError(f"第 {number} 行列表映射键必须为非空字符串")
                item = {}
                pseudo_indent = indent + 2
                if pair[1]:
                    item[key] = _scalar(pair[1], number)
                elif index < len(rows) and rows[index][0] > pseudo_indent:
                    item[key], index = block(index, rows[index][0])
                else:
                    item[key] = None
                if index < len(rows) and rows[index][0] > indent:
                    continuation_indent = rows[index][0]
                    continuation, index = block(index, continuation_indent)
                    if not isinstance(continuation, dict):
                        raise DocsGovernanceError(f"第 {rows[index - 1][2]} 行列表映射 continuation 必须为 map")
                    for child_key, child_value in continuation.items():
                        if child_key in item:
                            raise DocsGovernanceError(f"第 {number} 行重复键：{child_key}")
                        item[child_key] = child_value
                container.append(item)
                continue

            pair = _mapping_pair(content, number)
            if pair is None:
                raise DocsGovernanceError(f"第 {number} 行缺少映射冒号")
            key = _scalar(pair[0], number)
            if not isinstance(key, str) or not key:
                raise DocsGovernanceError(f"第 {number} 行映射键必须为非空字符串")
            if key in container:
                raise DocsGovernanceError(f"第 {number} 行重复键：{key}")
            if pair[1]:
                container[key] = _scalar(pair[1], number)
                if index < len(rows) and rows[index][0] > indent:
                    raise DocsGovernanceError(f"第 {rows[index][2]} 行标量不得含子块")
            elif index < len(rows) and rows[index][0] > indent:
                container[key], index = block(index, rows[index][0])
            else:
                container[key] = None
        return container, index

    if rows[0][0] != 0:
        raise DocsGovernanceError("registry 顶层不得缩进")
    value, end = block(0, 0)
    if end != len(rows) or not isinstance(value, dict):
        raise DocsGovernanceError("registry 顶层必须为完整 map")
    return value


def _paths(root: Path, layout: Layout | None = None) -> tuple[Path, Path, Path]:
    root = Path(root).absolute()
    safe_path(root, ".")
    layout = layout or load_layout(root)
    assets_rel = layout.assets_root.relative_to(root).as_posix()
    registry = safe_path(root, f"{assets_rel}/docs/governance.yaml")
    ledger = safe_path(root, f"{assets_rel}/docs/governance-events.jsonl")
    return root, registry, ledger


def _schema_errors(value, schema_name: str) -> list[str]:
    return validate(value, load_schema(schema_name))


def load_registry(root: str | Path) -> dict | None:
    """Load and schema-check declarations; a missing registry is not an error."""
    root, registry, _ = _paths(Path(root))
    if not registry.exists():
        return None
    if registry.is_symlink() or not registry.is_file():
        raise DocsGovernanceError("governance.yaml 必须是根内普通文件")
    try:
        value = parse_docs_yaml(registry.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DocsIOError(f"无法读取 governance.yaml：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise DocsGovernanceError(f"无法读取 governance.yaml：{exc}") from exc
    errors = _schema_errors(value, "docs-governance")
    if errors:
        raise DocsGovernanceError("governance.yaml schema: " + "; ".join(errors))
    return value


def list_documents(root: str | Path) -> list[dict]:
    """Return explicit declarations only; never scan or hash document bodies."""
    return list((load_registry(root) or {}).get("documents", []))


def _read_events(root: Path, ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    if ledger.is_symlink() or not ledger.is_file():
        raise DocsGovernanceError("governance-events.jsonl 必须是根内普通文件")
    try:
        raw = ledger.read_bytes()
        text = raw.decode("utf-8")
    except OSError as exc:
        raise DocsIOError(f"无法读取机器账本：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise DocsGovernanceError(f"无法读取机器账本：{exc}") from exc
    if raw and not raw.endswith(b"\n"):
        raise DocsGovernanceError("机器账本最后一行未以换行结束")
    result = []
    event_ids = set()
    latest: dict[str, dict] = {}
    schema = load_schema("docs-governance-event")
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            raise DocsGovernanceError(f"机器账本第 {number} 行为空")
        try:
            event = json.loads(line, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise DocsGovernanceError(f"机器账本第 {number} 行 JSON 非法：{exc}") from exc
        errors = validate(event, schema)
        if errors:
            raise DocsGovernanceError(f"机器账本第 {number} 行 schema: " + "; ".join(errors))
        if event["event_id"] in event_ids:
            raise DocsGovernanceError(f"机器账本 event_id 重复：{event['event_id']}")
        event_ids.add(event["event_id"])
        previous = latest.get(event["doc_id"])
        if previous is not None and event["old"] != previous["new"]:
            raise DocsGovernanceError(f"机器账本 old/new 链断裂：{event['doc_id']}")
        latest[event["doc_id"]] = event
        result.append(event)
    return result


def _dedicated_reason(root: Path, rel: str, layout: Layout) -> str | None:
    pure = PurePosixPath(rel)
    parts = tuple(part.casefold() for part in pure.parts)
    if not parts:
        return "文档路径为空"
    if parts[0] in (".atlas", ".adapter-out", "node_modules", "dist", "build", "coverage", ".next", "target"):
        return f"生成物/运行产物 {parts[0]}/ 禁止登记"
    assets = tuple(part.casefold() for part in layout.assets_root.relative_to(root).parts)
    if parts[:len(assets) + 2] == assets + ("docs", "governance.yaml") or parts[:len(assets) + 2] == assets + ("docs", "governance-events.jsonl"):
        return "Docs registry/ledger 自身禁止登记"
    if parts[:len(assets)] == assets and len(parts) > len(assets):
        specialized = parts[len(assets)]
        names = {"prd": "PRD", "e2e": "E2E", "adr": "ADR", "requirements": "活需求", "incidents": "Incident", "reviews": "专用复核", "atlas-reports": "生成报告"}
        if specialized in names:
            return f"{names[specialized]} 专用文档禁止登记，交由对应专用校验器"
    adr = tuple(part.casefold() for part in layout.adr_dir.relative_to(root).parts)
    if parts[:len(adr)] == adr:
        return "ADR 专用文档禁止登记，交由 validate_adr"
    if parts[:2] == ("docs", "map") or (parts[:len(assets) + 2] == assets + ("docs", "map")):
        return "map 专用文档禁止登记，交由 map 校验"
    return None


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document_digests(root: Path, item: dict, layout: Layout) -> tuple[dict | None, list[dict]]:
    findings = []
    doc_path = item["path"]
    reason = _dedicated_reason(root, doc_path, layout)
    if reason:
        findings.append(_finding(reason, doc_path, "docs_stale"))
        return None, findings
    try:
        path = safe_path(root, doc_path)
        if path.is_symlink() or not path.is_file():
            findings.append(_finding("文档缺失或为符号链接", doc_path, "docs_stale"))
            return None, findings
        if doc_path.lower().endswith(".md"):
            try:
                head = path.read_text(encoding="utf-8")[:4096]
            except OSError as exc:
                raise DocsIOError(f"文档无法读取：{exc}") from exc
            except UnicodeDecodeError as exc:
                findings.append(_finding(f"文档无法读取：{exc}", doc_path, "docs_stale"))
                return None, findings
            if head.startswith("---\n") and re.search(r"(?m)^mechanism-paths\s*:", head.split("\n---", 1)[0]):
                findings.append(_finding("mechanism-paths 专用机制文档禁止登记", doc_path, "docs_stale"))
                return None, findings
        document = _hash_file(path)
    except OSError as exc:
        raise DocsIOError(f"文档路径不可读取：{exc}") from exc
    except (ValueError, GovernancePathError) as exc:
        findings.append(_finding(f"文档路径不安全或不可读取：{exc}", doc_path, "docs_stale"))
        return None, findings
    sources = {}
    for rel in item["source_paths"]:
        try:
            source = safe_path(root, rel)
            if source.is_symlink() or not source.is_file():
                findings.append(_finding("来源缺失或为符号链接", rel, "docs_stale"))
                continue
            sources[rel] = _hash_file(source)
        except OSError as exc:
            raise DocsIOError(f"来源不可读取：{exc}") from exc
        except (ValueError, GovernancePathError) as exc:
            findings.append(_finding(f"来源路径不安全或不可读取：{exc}", rel, "docs_stale"))
    if findings:
        return None, findings
    return {"document": document, "sources": sources}, []


def _anchors(text: str) -> set[str]:
    result = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = re.sub(r"[`*_~]", "", match.group(1)).strip().lower()
        title = re.sub(r"[^\w\- \u0080-\uffff]", "", title)
        result.add(title.replace(" ", "-"))
    return result


def _link_findings(root: Path, item: dict, layout: Layout) -> list[dict]:
    findings = []
    try:
        doc_file = safe_path(root, item["path"])
        doc_text = doc_file.read_text(encoding="utf-8") if doc_file.is_file() else ""
        doc_anchors = _anchors(doc_text)
    except OSError as exc:
        raise DocsIOError(f"文档链接读取失败：{exc}") from exc
    except (UnicodeDecodeError, ValueError, GovernancePathError):
        doc_text, doc_anchors = "", set()
    for link in item["links"]:
        if _DRIVE.match(link) or "\\" in link or link.startswith("//"):
            findings.append(_finding(f"死链/不安全链接：{link}", item["path"], "docs_stale"))
            continue
        try:
            parsed = urlsplit(link)
        except ValueError:
            findings.append(_finding(f"死链/非法链接：{link}", item["path"], "docs_stale"))
            continue
        if parsed.scheme or parsed.netloc:
            # Remote availability is not a deterministic offline fact.
            continue
        rel = unquote(parsed.path)
        if rel.startswith("/"):
            rel = rel.lstrip("/")
        elif rel:
            rel = posixpath.normpath((PurePosixPath(item["path"]).parent / rel).as_posix())
        fragment = unquote(parsed.fragment)
        if not rel:
            if fragment and fragment not in doc_anchors:
                findings.append(_finding(f"死链锚点：{link}", item["path"], "docs_stale"))
            continue
        try:
            target = safe_path(root, rel)
            if target.is_symlink() or not target.is_file():
                findings.append(_finding(f"死链：{link}", item["path"], "docs_stale"))
                continue
            if fragment and target.suffix.lower() in (".md", ".markdown"):
                anchors = _anchors(target.read_text(encoding="utf-8"))
                if fragment not in anchors:
                    findings.append(_finding(f"死链锚点：{link}", item["path"], "docs_stale"))
        except OSError as exc:
            raise DocsIOError(f"链接目标不可读取：{exc}") from exc
        except (UnicodeDecodeError, ValueError, GovernancePathError) as exc:
            findings.append(_finding(f"死链/不安全链接 {link}：{exc}", item["path"], "docs_stale"))
    return findings


def _finding(message: str, path: str | None = None, cause: str = "observation") -> dict:
    return {"cause": cause, "message": message, **({"path": path} if path else {})}


def _result(mode: str, verdict: str, findings: list[dict], cause: str | None,
            metrics: dict | None = None) -> dict:
    if mode == "off":
        verdict, cause, rc = "UNVERIFIED", None, 2
    else:
        rc = 0 if mode == "shadow" or verdict in ("PASS", "WARN", "N/A") else 2 if verdict == "UNVERIFIED" else 1
    return {"schema_version": 1, "module": "docs", "mode": mode,
            "verdict": verdict, "cause": cause, "rc": rc, "findings": findings,
            "metrics": metrics or {}}


def _check(root: str | Path, mode: str = "shadow", doc_ids: list[str] | None = None,
           today: date | str | None = None) -> dict:
    if mode not in MODES:
        raise DocsGovernanceError("mode 必须为 shadow/enforce/off")
    if mode == "off":
        return _result(mode, "UNVERIFIED", [_finding("Docs Governance 已关闭；in-scope 不可判定", cause="observation")], None)
    current_date = date.today() if today is None else date.fromisoformat(today) if isinstance(today, str) else today
    root = Path(root).absolute()
    registry_path = "governance.yaml"
    try:
        layout = load_layout(root)
        root, registry_path, ledger_path = _paths(root, layout)
        registry = load_registry(root)
        if registry is None:
            if doc_ids:
                return _result(mode, "FAIL", [_finding(f"task doc_id 未登记：{doc_id}", cause="docs_stale") for doc_id in doc_ids], "docs_stale", {"registered": 0, "evaluated": 0})
            due = (current_date + timedelta(days=365)).isoformat()
            return _result(mode, "N/A", [{"cause": "not_applicable", "message": "无 governance.yaml；未登记文档不纳入 Docs Governance", "owner": "Atlas", "due": due}], None, {"registered": 0, "evaluated": 0})
        events = _read_events(root, ledger_path)
    except OSError as exc:
        return _result(mode, "UNVERIFIED", [_finding(f"registry/ledger I/O 不可判定：{exc}", str(registry_path), "docs_unverified")], "docs_unverified", {"registered": 0, "evaluated": 0})
    except (ValueError, GovernancePathError) as exc:
        cause = "docs_owner_missing" if ".owner" in str(exc) else "docs_stale"
        return _result(mode, "FAIL", [_finding(f"registry/ledger 不可判定：{exc}", str(registry_path), cause)], cause, {"registered": 0, "evaluated": 0})

    documents = registry["documents"]
    counts: dict[str, int] = {}
    for item in documents:
        counts[item["id"]] = counts.get(item["id"], 0) + 1
    selected = documents
    if doc_ids is not None:
        by_id = {item["id"]: item for item in documents if counts[item["id"]] == 1}
        selected = []
        findings = []
        for doc_id in dict.fromkeys(doc_ids):
            if counts.get(doc_id, 0) > 1:
                findings.append(_finding(f"重复 ID 导致 task 引用歧义：{doc_id}", cause="docs_stale"))
            elif doc_id not in by_id:
                findings.append(_finding(f"task doc_id 未登记：{doc_id}", cause="docs_stale"))
            else:
                selected.append(by_id[doc_id])
        if findings:
            cause = "docs_owner_missing" if any(item["cause"] == "docs_owner_missing" for item in findings) else "docs_stale"
            return _result(mode, "FAIL", findings, cause, {"registered": len(documents), "evaluated": 0})

    findings = []
    seen_ids = set()
    seen_paths = set()
    stale_count = 0
    latest: dict[str, dict] = {}
    for event in events:
        latest[event["doc_id"]] = event
    for item in selected:
        if item["status"] == "retired":
            continue
        doc_id = item["id"]
        if doc_id in seen_ids:
            findings.append(_finding(f"重复 ID：{doc_id}", item["path"], "docs_stale"))
            stale_count += 1
            continue
        seen_ids.add(doc_id)
        if item["path"] in seen_paths:
            findings.append(_finding(f"重复文档路径：{item['path']}", item["path"], "docs_stale"))
            stale_count += 1
        seen_paths.add(item["path"])
        if not item["owner"].strip():
            findings.append(_finding("owner 缺失或为空白", item["path"], "docs_owner_missing"))
        current, errors = _document_digests(root, item, layout)
        findings.extend(errors)
        if errors:
            stale_count += 1
        else:
            findings.extend(_link_findings(root, item, layout))
            baseline = latest.get(doc_id)
            if baseline is None:
                cause = "docs_stale" if mode == "enforce" else "observation"
                findings.append(_finding("尚无机器复核基线；请先 atlas docs touch", item["path"], cause))
                if mode == "enforce":
                    stale_count += 1
            else:
                old = baseline["new"]
                if current["document"] != old["document"]:
                    findings.append(_finding("文档正文在最后一次复核后变化，尚未 touch", item["path"], "observation"))
                if current["sources"] != old["sources"]:
                    changed = sorted(path for path in set(current["sources"]) | set(old["sources"]) if current["sources"].get(path) != old["sources"].get(path))
                    findings.append(_finding("来源变化未同步：" + ", ".join(changed), changed[0] if changed else item["path"], "docs_stale"))
                    stale_count += 1
                if baseline["kind"] == "attestation" and not _objective_evidence(
                        root, baseline["evidence"], item["source_paths"], baseline.get("evidence_sha256")):
                    findings.append(_finding("attestation 的客观证据现已不可复核", item["path"], "docs_stale"))
                    stale_count += 1
        try:
            due = date.fromisoformat(item["review_due"])
        except ValueError:
            due = current_date
        if due < current_date:
            findings.append(_finding(f"复核已超期：review_due={item['review_due']}", item["path"], "observation"))
    hard = [item for item in findings if item["cause"] in ("docs_stale", "docs_owner_missing")]
    cause = "docs_owner_missing" if any(item["cause"] == "docs_owner_missing" for item in hard) else "docs_stale" if hard else None
    verdict = "FAIL" if hard else "WARN" if findings else "PASS"
    return _result(mode, verdict, findings, cause, {"registered": len(documents), "evaluated": len(selected), "stale": stale_count})


def check_docs(root: str | Path, mode: str = "shadow", today: date | str | None = None) -> dict:
    """Pure whole-registry check; repeated calls do not write any bytes."""
    try:
        return _check(root, mode=mode, today=today)
    except OSError as exc:
        return _result(mode, "UNVERIFIED", [_finding(f"Docs I/O 不可判定：{exc}", cause="docs_unverified")],
                       "docs_unverified", {"registered": 0, "evaluated": 0})


def check_docs_for_ids(root: str | Path, doc_ids: list[str], mode: str = "shadow",
                       today: date | str | None = None) -> dict:
    """Pure verify/finish projection for only the task's explicit doc_ids."""
    try:
        return _check(root, mode=mode, doc_ids=list(doc_ids), today=today)
    except OSError as exc:
        return _result(mode, "UNVERIFIED", [_finding(f"Docs I/O 不可判定：{exc}", cause="docs_unverified")],
                       "docs_unverified", {"registered": 0, "evaluated": 0})


def _objective_evidence(root: Path, evidence: str, allowed_paths: list[str] | None = None,
                        expected_sha256: str | None = None) -> bool:
    value = evidence.strip()
    if _HEX.fullmatch(value):
        try:
            checked = subprocess.run(["git", "cat-file", "-e", f"{value}^{{commit}}"],
                                     cwd=root, capture_output=True, timeout=10)
            if checked.returncode != 0:
                return False
            if allowed_paths is None:
                return True
            changed = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r",
                                      f"{value}^", value], cwd=root, capture_output=True,
                                     text=True, timeout=10)
            if changed.returncode != 0 or not set(changed.stdout.splitlines()) & set(allowed_paths):
                return False
            for rel in allowed_paths:
                path = safe_path(root, rel)
                if not path.is_file() or path.is_symlink():
                    return False
                committed = subprocess.run(["git", "show", f"{value}:{rel}"], cwd=root,
                                           capture_output=True, timeout=10)
                if committed.returncode != 0 or committed.stdout != path.read_bytes():
                    return False
            return True
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DocsIOError(f"commit 证据不可读取：{exc}") from exc
        except GovernancePathError:
            return False
    candidate = value
    for prefix in ("test:", "file:"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    candidate = re.split(r"::|#L\d+$", candidate, maxsplit=1)[0]
    if not candidate or "://" in candidate:
        return False
    try:
        if allowed_paths is not None and candidate not in allowed_paths:
            return False
        path = safe_path(root, candidate)
        if not path.is_file() or path.is_symlink():
            return False
        actual = _hash_file(path)
        return expected_sha256 is None or actual == expected_sha256
    except OSError as exc:
        raise DocsIOError(f"来源证据不可读取：{exc}") from exc
    except (ValueError, GovernancePathError):
        return False


def _evidence_digest(root: Path, evidence: str) -> str:
    candidate = evidence.strip()
    for prefix in ("file:", "test:"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    candidate = re.split(r"::|#L\d+$", candidate, maxsplit=1)[0]
    if candidate and "://" not in candidate:
        try:
            path = safe_path(root, candidate)
            if path.is_file() and not path.is_symlink():
                return _hash_file(path)
        except OSError as exc:
            raise DocsIOError(f"证据摘要不可读取：{exc}") from exc
        except (ValueError, GovernancePathError):
            pass
    return hashlib.sha256(evidence.strip().encode()).hexdigest()


def touch_document(root: str | Path, doc_id: str, actor: str, evidence: str,
                   no_impact: bool = False) -> dict:
    """Atomically append one review event; never modify registry or body bytes."""
    if not actor or not actor.strip():
        raise DocsGovernanceError("actor 必须为非空署名")
    if not evidence or not evidence.strip():
        raise DocsGovernanceError("touch 必须提供证据")
    if no_impact:
        selected = next((item for item in (load_registry(root) or {}).get("documents", [])
                         if item["id"] == doc_id), None)
        if selected is None or not _objective_evidence(Path(root).absolute(), evidence, selected["source_paths"]):
            raise DocsGovernanceError("--no-impact 必须给客观证据：来源文件或可验证 commit/hash")
    root = Path(root).absolute()
    layout = load_layout(root)
    root, registry_path, ledger_path = _paths(root, layout)
    registry = load_registry(root)
    if registry is None:
        raise DocsGovernanceError("governance.yaml 不存在")
    matches = [item for item in registry["documents"] if item["id"] == doc_id]
    if len(matches) != 1:
        raise DocsGovernanceError(f"doc_id 不存在或重复：{doc_id}")
    item = matches[0]
    if not item["owner"].strip():
        raise DocsGovernanceError("owner 缺失，不能 touch")
    current, errors = _document_digests(root, item, layout)
    if errors:
        raise DocsGovernanceError("；".join(error["message"] for error in errors))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(ledger_path, flags, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
            previous_events = _read_events(root, ledger_path)
        previous = next((event for event in reversed(previous_events) if event["doc_id"] == doc_id), None)
        old = previous["new"] if previous else current
        source_drift = old["sources"] != current["sources"]
        if source_drift and not no_impact and current["document"] == old["document"]:
            raise DocsGovernanceError("正文未变化，不得清除 source stale；请更新正文或带客观证据使用 --no-impact")
        if no_impact and not source_drift:
            raise DocsGovernanceError("--no-impact 仅适用于存在来源变化的 stale 文档")
        kind = "attestation" if no_impact else "touch"
        event = {
            "schema_version": 1,
            "event_id": f"EVT-{uuid.uuid4().hex}",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "actor": actor.strip(),
            "doc_id": doc_id,
            "kind": kind,
            "evidence": evidence.strip(),
            **({"evidence_sha256": _evidence_digest(root, evidence)} if no_impact else {}),
            "old": old,
            "new": current,
        }
        errors = _schema_errors(event, "docs-governance-event")
        if errors:
            raise DocsGovernanceError("event schema: " + "; ".join(errors))
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        return event
    finally:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
