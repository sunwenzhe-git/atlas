"""M248: RFC-20261125-01 P3 static Runtime Topology core.

First paragraph declaration: removing source hash/file-set comparison, dynamic
field tracking, or dangling-edge validation must turn tests/test_runtime_topology.py
red. The real four-stage mutation_proof is .atlas/runs/mutation-proof/M248.txt.

The scanner reads whitelisted deployment facts only. It never evaluates templates,
reads environment/secret values, or invokes deployment and cluster commands.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from _support.docs_governance import DocsGovernanceError, parse_docs_yaml
from _support.governance_io import (
    GovernancePathError,
    atomic_write_bytes,
    atomic_write_json,
    load_json,
    safe_path,
)
from _support.governance_schema import canonical_bytes, canonical_digest, validate_topology
from _support.layout import load_layout

VERSION = "0.1.0"
MODES = ("shadow", "enforce", "off")


def topology_mode(root: str | Path) -> str:
    selected = os.environ.get("ATLAS_TOPOLOGY_MODE", "shadow")
    if selected not in MODES:
        raise TopologyError("ATLAS_TOPOLOGY_MODE 非法")
    return selected

DEFAULT_GLOBS = (
    "**/compose*.yaml", "**/compose*.yml", "**/docker-compose*.yaml", "**/docker-compose*.yml",
    "**/kong*.yaml", "**/kong*.yml", "**/Chart.yaml", "**/values.yaml", "**/templates/*.yaml",
    "**/templates/*.yml",
)
_DYNAMIC = re.compile(r"\{\{|\}\}|\$\{[^}]*\}|\$\([^)]*\)|\$[A-Za-z_][A-Za-z0-9_]*")
_MISSING = object()


class TopologyError(ValueError):
    """Invalid topology inputs or an unsafe generation operation."""


def dynamic(value) -> bool:
    return isinstance(value, str) and bool(_DYNAMIC.search(value))


def find_line(text: str, key: str, start: int = 0, end: int | None = None,
              indent: int | None = None) -> int:
    pattern = rf"^(\s*){re.escape(key)}\s*:"
    for index, raw in enumerate(text.splitlines()[start:end], start + 1):
        match = re.match(pattern, raw)
        if match and (indent is None or len(match.group(1)) == indent):
            return index
    return start + 1


def find_item_line(text: str, key: str, start: int, end: int) -> int:
    pattern = rf"^\s*-\s*{re.escape(key)}\s*:"
    for index, raw in enumerate(text.splitlines()[start:end], start + 1):
        if re.match(pattern, raw):
            return index
    return start + 1


def block_end(text: str, start: int, indent: int) -> int:
    lines = text.splitlines()
    for index in range(start, len(lines)):
        raw = lines[index]
        if raw.strip() and not raw.lstrip().startswith("#") and len(raw) - len(raw.lstrip(" ")) <= indent:
            return index
    return len(lines)


def node(inputs: dict, kind: str, name: str, source_file: str, line: int, sha256: str,
         *, namespace: str | None = None, app: str | None = None, image: str | None = None,
         ports: list | None = None) -> dict:
    if not isinstance(name, str) or not name or ":" in name:
        raise TopologyError(f"静态节点名非法：{name!r}")
    identity = ":".join((inputs["project"], inputs["environment"], inputs["cluster"],
                         inputs["release"], namespace or "none", name))
    return {"node": True, "id": identity, "kind": kind, "name": name,
            "namespace": namespace, "app": app, "image": image,
            "ports": sorted(ports or [], key=lambda value: json.dumps(value, sort_keys=True)),
            "source_file": source_file, "line": line, "sha256": sha256}


def edge(source: dict, target: dict, kind: str, relation: str, source_file: str,
         line: int, sha256: str, port=_MISSING) -> dict:
    port_key = "<missing>" if port is _MISSING else json.dumps(port, ensure_ascii=False, sort_keys=True)
    identity = "edge:" + kind + ":" + hashlib.sha256(
        (source["id"] + "\0" + target["id"] + "\0" + relation + "\0" + port_key).encode()
    ).hexdigest()[:24]
    value = {"edge": True, "id": identity, "kind": kind, "from": source["id"], "to": target["id"],
             "relation": relation, "source_file": source_file, "line": line, "sha256": sha256}
    if port is not _MISSING:
        value["port"] = port
    return value


def unverified(coverage: dict, identity: str, fields: list[str], owner: str | None,
               due: str | None, source_file: str | None = None) -> None:
    if not isinstance(owner, str) or not owner.strip() or not isinstance(due, str) or not due:
        raise TopologyError("动态字段豁免必须显式提供 owner 与 due")
    fields = sorted(set(fields))
    if not fields:
        return
    item = {"id": identity, "fields": fields, "owner": owner, "due": due}
    if source_file:
        item["source_file"] = source_file
    for existing in coverage["unverified_fields"]:
        if existing["id"] == identity and existing.get("source_file") == source_file:
            existing["fields"] = sorted(set(existing["fields"]) | set(fields))
            return
    coverage["unverified_fields"].append(item)


def parse_error(coverage: dict, path: str, message: str) -> None:
    coverage["parse_errors"].append({"path": path, "message": message})


def _family(text: str, rel: str) -> str | None:
    name = Path(rel).name.lower()
    if name == "values.yaml":
        return None
    if re.search(r"(?m)^kind\s*:\s*(Deployment|StatefulSet|Service)\s*$", text):
        return "helm"
    if re.search(r"(?m)^_format_version\s*:", text) or re.search(r"(?m)^upstreams\s*:", text) or name.startswith("kong"):
        return "kong"
    if re.search(r"(?m)^services\s*:", text) or name.startswith(("compose", "docker-compose")):
        return "compose"
    return None


def _quote_dynamic_scalars(text: str) -> str:
    """Keep template scalars parseable without evaluating or normalizing them."""
    lines = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        ending = raw[len(body):]
        dynamic_key = re.match(r"^(\s*)(-\s+)?(\{\{.*\}\}|\$\{[^}]+\})(\s*:\s*.*)$", body)
        dynamic_value = re.match(r"^(\s*(?:[^:\n]+|-\s+)\s*:\s*)(\{\{.*\}\}|\$\{[^}]+\})(\s*)$", body)
        dynamic_item = re.match(r"^(\s*-\s+)(\{\{.*\}\}|\$\{[^}]+\})(\s*)$", body)
        if dynamic_key:
            body = dynamic_key.group(1) + (dynamic_key.group(2) or "") + json.dumps(dynamic_key.group(3)) + dynamic_key.group(4)
        elif dynamic_value:
            body = dynamic_value.group(1) + json.dumps(dynamic_value.group(2)) + dynamic_value.group(3)
        elif dynamic_item:
            body = dynamic_item.group(1) + json.dumps(dynamic_item.group(2)) + dynamic_item.group(3)
        lines.append(body + ending)
    return "".join(lines)


def _documents(text: str, family: str) -> list[tuple[dict, int]]:
    if family != "helm":
        return [(parse_docs_yaml(_quote_dynamic_scalars(text)), 0)]
    markers = list(re.finditer(r"(?m)^---\s*$", text))
    starts = [0] + [marker.end() for marker in markers]
    ends = [marker.start() for marker in markers] + [len(text)]
    result = []
    for start, end in zip(starts, ends):
        segment = text[start:end]
        if re.search(r"\{\{[-+\s]*(?:if|else|end|range|with|define|include|tpl)\b", segment):
            raise DocsGovernanceError("Helm 模板控制流不可静态判定，拒绝猜测条件分支")
        # Helm control statements are not YAML facts. Blank, never evaluate them.
        clean = re.sub(r"(?m)^\s*\{\{[-\s]*(?:if|else|end|range|with|define|include|tpl)[^\n]*$",
                       lambda match: " " * len(match.group(0)), segment)
        clean = _quote_dynamic_scalars(clean)
        try:
            value = parse_docs_yaml(clean)
        except DocsGovernanceError as exc:
            if re.search(r"(?m)^kind\s*:\s*(Deployment|StatefulSet|Service)\s*$", segment):
                raise DocsGovernanceError(f"manifest 文档解析失败（起始行 {start + 1}）：{exc}") from exc
            continue
        if isinstance(value, dict) and value.get("kind") in ("Deployment", "StatefulSet", "Service"):
            result.append((value, text.count("\n", 0, start)))
        elif isinstance(value, dict) and value.get("kind"):
            raise DocsGovernanceError(f"不支持的 Kubernetes kind：{value.get('kind')}")
    return result


def _validate_identity(inputs: dict) -> None:
    for key in ("project", "environment", "cluster", "release"):
        if not isinstance(inputs.get(key), str) or not inputs[key] or ":" in inputs[key]:
            raise TopologyError(f"inputs.{key} 必须为非空且不含冒号的字符串")


def scan_sources(root: str | Path, scan_globs: list[str], *, source_root: str | Path | None = None) -> tuple[dict[str, bytes], list[dict]]:
    root = Path(root).absolute()
    source_root = Path(source_root).absolute() if source_root is not None else root
    safe_path(root, ".")
    if not scan_globs or any(not isinstance(item, str) or not item for item in scan_globs):
        raise TopologyError("scan_globs 必须是非空字符串数组")
    files: dict[str, bytes] = {}
    errors = []
    for pattern in scan_globs:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise TopologyError(f"scan_glob 必须为项目根内相对路径：{pattern}")
        for matched in glob.glob(pattern, root_dir=source_root, recursive=True):
            rel = Path(matched).as_posix()
            try:
                path = safe_path(source_root, rel)
                if not path.is_file():
                    raise GovernancePathError("扫描目标不是普通文件")
                files[rel] = path.read_bytes()
            except (OSError, ValueError, GovernancePathError) as exc:
                errors.append({"path": rel, "message": f"扫描路径不安全或不可读取：{exc}"})
    return dict(sorted(files.items())), errors


def collect_topology(root: str | Path, *, project: str, environment: str, cluster: str,
                     release: str, scan_globs: list[str], owner: str | None = None,
                     due: str | None = None, adapter: str = "all",
                     source_root: str | Path | None = None) -> tuple[dict, dict[str, bytes]]:
    inputs = {"project": project, "environment": environment, "cluster": cluster,
              "release": release, "scan_globs": list(scan_globs)}
    _validate_identity(inputs)
    if adapter not in ("all", "compose", "helm", "kong"):
        raise TopologyError("adapter 必须为 all/compose/helm/kong")
    sources, errors = scan_sources(root, scan_globs, source_root=source_root)
    coverage = {"parsed": 0, "unverified_fields": [], "parse_errors": errors}
    items: list[dict] = []
    for rel, payload in sources.items():
        family = _family(payload.decode("utf-8", errors="replace"), rel)
        if family is None:
            if Path(rel).name.lower() not in ("values.yaml", "chart.yaml"):
                parse_error(coverage, rel, "无法识别的部署文件格式")
            continue
        if adapter not in ("all", family):
            continue
        try:
            text = payload.decode("utf-8")
            if family == "compose":
                from adapters.topology_compose import parse
            elif family == "helm":
                from adapters.topology_helm import finalize, parse
            else:
                from adapters.topology_kong import parse
            documents = _documents(text, family)
            if not documents:
                raise DocsGovernanceError("未解析到支持的部署文档")
            parsed_items = []
            for value, offset in documents:
                parsed, partial = parse(text, rel, hashlib.sha256(payload).hexdigest(), inputs,
                                        owner=owner, due=due, document=value, offset=offset)
                parsed_items.extend(parsed)
                by_id: dict[str, list[dict]] = {}
                for item in parsed_items:
                    by_id.setdefault(item.get("id"), []).append(item)
                for field in partial["unverified_fields"]:
                    if field.get("source_file"):
                        continue
                    if field["id"].startswith(rel + ":"):
                        field["source_file"] = rel
                    else:
                        matches = by_id.get(field["id"]) or []
                        source_names = {item.get("source_file") for item in matches if item.get("source_file")}
                        if len(source_names) == 1:
                            field["source_file"] = next(iter(source_names))
                coverage["parsed"] += 1
                coverage["unverified_fields"].extend(partial["unverified_fields"])
                coverage["parse_errors"].extend(partial["parse_errors"])
            items.extend(parsed_items)
        except (DocsGovernanceError, TopologyError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
            parse_error(coverage, rel, f"{family} 解析失败：{exc}")
    if adapter in ("all", "helm"):
        from adapters.topology_helm import finalize
        items = finalize(items)
    seen: dict[str, str | None] = {}
    unique_items = []
    for item in items:
        identity = item.get("id")
        if identity in seen:
            for source_file in {seen[identity], item.get("source_file")}:
                unverified(coverage, identity, ["identity"], owner, due, source_file=source_file)
            continue
        seen[identity] = item.get("source_file")
        unique_items.append(item)
    node_ids = {item["id"] for item in unique_items if item.get("node") is True}
    items = [item for item in unique_items if item.get("node") is True
             or (item.get("from") in node_ids and item.get("to") in node_ids)]
    coverage["unverified_fields"].sort(key=lambda item: (item["id"], item["fields"]))
    topology = {"category": "topology", "items": items, "source_files": list(sources),
                "adapter_version": VERSION, "coverage": coverage, "inputs": inputs}
    return topology, sources


def _render(topology: dict) -> bytes:
    lines = ["# Runtime Topology", "", "> 静态拓扑事实；动态字段以 UNVERIFIED 标注，不猜模板值。", ""]
    for field in topology["coverage"]["unverified_fields"]:
        lines.append(f"- UNVERIFIED `{field['id']}`: {', '.join(field['fields'])}（owner={field['owner']}；due={field['due']}）")
    for error in topology["coverage"]["parse_errors"]:
        lines.append(f"- UNVERIFIED `{error['path']}`: {error['message']}")
    lines.extend(["", "| 类型 | ID | 关系/镜像 | 端口 | 来源 |", "|---|---|---|---|---|"])
    for item in topology["items"]:
        if item.get("node") is True:
            lines.append(f"| node | {item['id']} | {item['image'] or item['kind']} | "
                         f"{', '.join(str(port) for port in item['ports'])} | {item['source_file']}:{item['line']} |")
        else:
            lines.append(f"| edge | {item['id']} | {item['from']} -{item['relation']}-> {item['to']} | "
                         f"{item.get('port', '')} | {item['source_file']}:{item['line']} |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _result(mode: str, verdict: str, cause: str | None, findings: list[dict],
            *, generation: str | None = None, metrics: dict | None = None) -> dict:
    if mode == "off":
        verdict, cause, rc = "UNVERIFIED", None, 2
    else:
        rc = 0 if mode == "shadow" else 2 if verdict == "UNVERIFIED" else 1 if verdict in ("FAIL", "STALE") else 0
    value = {"schema_version": 1, "module": "topology", "mode": mode, "verdict": verdict,
             "cause": cause, "rc": rc, "findings": findings, "metrics": metrics or {}}
    if generation:
        value.update(generation=generation, path=f".adapter-out/topology/generations/{generation}")
    return value


def _paths(root: Path) -> tuple[Path, Path, Path, Path]:
    layout = load_layout(root)
    fixed = safe_path(root, ".adapter-out/topology.json")
    pointer = safe_path(root, ".adapter-out/topology/manifest.json")
    generations = safe_path(root, ".adapter-out/topology/generations")
    rendered = safe_path(root, layout.spec_dir.relative_to(root).as_posix() + "/global/runtime-topology.md") \
        if hasattr(layout, "spec_dir") else safe_path(root, ".atlas/spec/structure/global/runtime-topology.md")
    return fixed, pointer, generations, rendered


def _generation(root: Path, digest: str, payload: dict[str, bytes]) -> None:
    final = safe_path(root, f".adapter-out/topology/generations/{digest}")
    if final.exists():
        if not final.is_dir() or final.is_symlink():
            raise TopologyError(f"代际路径不是普通目录：{digest}")
        entries = list(final.iterdir())
        if {entry.name for entry in entries} != set(payload) \
                or any(not entry.is_file() or entry.is_symlink() for entry in entries):
            raise TopologyError(f"代际目录含额外或非普通文件，拒绝替换 last-known-good：{digest}")
        for name, expected in payload.items():
            path = safe_path(root, f".adapter-out/topology/generations/{digest}/{name}")
            if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
                raise TopologyError(f"代际内容损坏，拒绝替换 last-known-good：{digest}")
        return
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=str(final.parent)))
    try:
        for name, data in payload.items():
            atomic_write_bytes(temporary / name, data)
        os.rename(temporary, final)
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink()
            temporary.rmdir()


def _verify_generation(root: Path, pointer: dict) -> tuple[dict, bytes]:
    digest = pointer.get("generation")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise TopologyError("manifest generation 非法")
    directory = safe_path(root, f".adapter-out/topology/generations/{digest}")
    if not directory.is_dir() or directory.is_symlink():
        raise TopologyError("代际目录缺失或为符号链接")
    bound_files = pointer.get("files")
    if not isinstance(bound_files, dict) or set(bound_files) != {"topology.json", "runtime-topology.md"}:
        raise TopologyError("manifest files 清单不完整")
    entries = list(directory.iterdir())
    if {entry.name for entry in entries} != set(bound_files) \
            or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise TopologyError("代际目录含缺失、额外或非普通文件条目")
    for name, expected in bound_files.items():
        path = safe_path(root, f".adapter-out/topology/generations/{digest}/{name}")
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise TopologyError(f"代际产物校验失败：{name}")
    topology_path = safe_path(root, f".adapter-out/topology/generations/{digest}/topology.json")
    value = load_json(topology_path)
    errors = validate_topology(value)
    if errors:
        raise TopologyError("topology schema: " + "; ".join(errors))
    source_files = pointer.get("source_files")
    if not isinstance(source_files, dict) or set(source_files) != set(value["source_files"]) \
            or any(not re.fullmatch(r"[0-9a-f]{64}", str(digest)) for digest in source_files.values()):
        raise TopologyError("manifest source_files 与 topology 文件集不一致")
    if pointer.get("business_digest") != digest:
        raise TopologyError("manifest business_digest 必须等于 generation")
    rendered = (directory / "runtime-topology.md").read_bytes()
    expected = canonical_digest({"topology": value,
                                 "sources": pointer.get("source_files") or {},
                                 "rendered": rendered.decode("utf-8")})
    if pointer.get("business_digest") != expected:
        raise TopologyError("manifest business_digest 与代际内容不一致")
    return value, rendered


def refresh_topology(root: str | Path, *, project: str | None = None, environment: str = "dev",
                     cluster: str = "local", release: str = "default", scan_globs: list[str] | None = None,
                     owner: str | None = None, due: str | None = None, mode: str = "shadow",
                     adapter: str = "all", source_root: str | Path | None = None) -> dict:
    """Build a complete new generation, then expose it by one manifest rename."""
    if mode not in MODES:
        raise TopologyError("mode 必须为 shadow/enforce/off")
    if mode == "off":
        return _result(mode, "UNVERIFIED", None,
                       [{"cause": "observation", "message": "Topology 已关闭；in-scope 不可判定"}])
    root = Path(root).absolute()
    project = project or root.name
    globs = list(scan_globs or DEFAULT_GLOBS)
    topology, sources = collect_topology(root, project=project, environment=environment, cluster=cluster,
                                         release=release, scan_globs=globs, owner=owner, due=due,
                                         adapter=adapter, source_root=source_root)
    if topology["coverage"]["parse_errors"]:
        findings = [{"cause": "topology_unverified", "path": item["path"], "message": item["message"]}
                    for item in topology["coverage"]["parse_errors"]]
        return _result(mode, "UNVERIFIED", "topology_unverified", findings,
                       metrics={"parsed": topology["coverage"]["parsed"]})
    if topology["coverage"]["parsed"] == 0 or not topology["items"]:
        return _result(mode, "UNVERIFIED", "topology_unverified",
                       [{"cause": "topology_unverified", "message": "未解析到任何静态拓扑节点"}])
    errors = validate_topology(topology)
    if errors:
        return _result(mode, "FAIL", "topology_stale",
                       [{"cause": "topology_stale", "message": "topology schema: " + "; ".join(errors)}])
    rendered = _render(topology)
    payload = {"topology.json": canonical_bytes(topology) + b"\n", "runtime-topology.md": rendered}
    business = canonical_digest({"topology": topology,
                                 "sources": {rel: hashlib.sha256(data).hexdigest() for rel, data in sources.items()},
                                 "rendered": rendered.decode("utf-8")})
    fixed, pointer_path, _, rendered_path = _paths(root)
    previous_pointer = load_json(pointer_path) if pointer_path.exists() else None
    if previous_pointer:
        _verify_generation(root, previous_pointer)
    _generation(root, business, payload)
    if previous_pointer and previous_pointer.get("generation") == business:
        if previous_pointer.get("mode") == mode:
            # A same-business refresh must not churn the pointer or any generation byte.
            atomic_write_bytes(fixed, payload["topology.json"])
            atomic_write_bytes(rendered_path, rendered)
            return _result(mode, "UNVERIFIED" if topology["coverage"]["unverified_fields"] else "PASS",
                           "topology_unverified" if topology["coverage"]["unverified_fields"] else None,
                           [] if not topology["coverage"]["unverified_fields"] else
                           [{"cause": "topology_unverified", "message": "动态字段见 coverage.unverified_fields"}],
                           generation=business,
                           metrics={"nodes": sum(bool(item.get("node")) for item in topology["items"]),
                                    "edges": sum(bool(item.get("edge")) for item in topology["items"]),
                                    "parsed": topology["coverage"]["parsed"]})
    previous_generation = previous_pointer.get("generation") if previous_pointer else None
    old_fixed = fixed.read_bytes() if fixed.exists() else None
    old_rendered = rendered_path.read_bytes() if rendered_path.exists() else None
    manifest = {"schema_version": 1, "module": "topology", "mode": mode, "generation": business,
                "business_digest": business, "path": f"generations/{business}",
                "previous_generation": previous_generation, "previous_pointer": previous_pointer,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())},
                "source_files": {rel: hashlib.sha256(data).hexdigest() for rel, data in sources.items()},
                "adapter": adapter}
    try:
        # The manifest is the commit point. Projections are repairable snapshots.
        atomic_write_json(pointer_path, manifest)
        try:
            atomic_write_bytes(fixed, payload["topology.json"])
            atomic_write_bytes(rendered_path, rendered)
        except OSError as exc:
            try:
                if previous_pointer is None:
                    pointer_path.unlink(missing_ok=True)
                else:
                    atomic_write_json(pointer_path, previous_pointer)
                for path, old in ((fixed, old_fixed), (rendered_path, old_rendered)):
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(path, old)
            except OSError as restore_exc:
                raise TopologyError(f"pointer 已切换且投影/指针恢复失败：{exc}; {restore_exc}") from exc
            raise TopologyError(f"pointer 已切换但投影写入失败，已恢复上一指针：{exc}") from exc
    except OSError as exc:
        raise TopologyError(f"pointer 切换失败，保留 last-known-good：{exc}") from exc
    findings = [] if not topology["coverage"]["unverified_fields"] else \
        [{"cause": "topology_unverified", "message": "动态字段见 coverage.unverified_fields"}]
    return _result(mode, "UNVERIFIED" if findings else "PASS",
                   "topology_unverified" if findings else None, findings, generation=business,
                   metrics={"nodes": sum(bool(item.get("node")) for item in topology["items"]),
                            "edges": sum(bool(item.get("edge")) for item in topology["items"]),
                            "parsed": topology["coverage"]["parsed"]})


def _load_pointer(root: Path) -> dict:
    _, pointer_path, _, _ = _paths(root)
    if not pointer_path.is_file() or pointer_path.is_symlink():
        raise TopologyError("缺少 topology manifest；请先 atlas topology refresh")
    return load_json(pointer_path)


def scope_topology_result(result: dict, topology: dict, staged_paths: list[str] | set[str]) -> dict:
    if result.get("verdict") != "UNVERIFIED" or result.get("cause") != "topology_unverified" \
            or not result.get("generation") or result.get("metrics", {}).get("parsed", 0) <= 0:
        return result
    fields = topology.get("coverage", {}).get("unverified_fields") or []
    if not fields:
        return result
    staged = set(staged_paths)
    for field in fields:
        source = field.get("source_file")
        if not source or source in staged:
            return result
    return {**result, "verdict": "WARN", "cause": None, "rc": 0,
            "findings": [{"cause": "observation", "message": "动态拓扑字段不在本任务暂存面"}]}


def check_topology(root: str | Path, mode: str = "shadow", *, source_root: str | Path | None = None) -> dict:
    """Recompute schema, generation integrity, file set and source hashes read-only."""
    if mode not in MODES:
        raise TopologyError("mode 必须为 shadow/enforce/off")
    if mode == "off":
        return _result(mode, "UNVERIFIED", None,
                       [{"cause": "observation", "message": "Topology 已关闭；in-scope 不可判定"}])
    root = Path(root).absolute()
    try:
        pointer = _load_pointer(root)
        fixed, _, _, rendered_path = _paths(root)
        if not fixed.is_file() or fixed.is_symlink():
            raise TopologyError(".adapter-out/topology.json 缺失或为符号链接")
        current = load_json(fixed)
        errors = validate_topology(current)
        if errors:
            raise TopologyError("topology schema: " + "; ".join(errors))
        baseline, rendered = _verify_generation(root, pointer)
        if canonical_bytes(current) != canonical_bytes(baseline):
            raise TopologyError("固定产物与 manifest 指向代际不一致")
        if not rendered_path.is_file() or rendered_path.is_symlink() or rendered_path.read_bytes() != rendered:
            raise TopologyError("runtime-topology.md 与 manifest 指向代际不一致")
        inputs = baseline["inputs"]
        sources, scan_errors = scan_sources(root, inputs["scan_globs"], source_root=source_root)
        if scan_errors:
            return _result(mode, "UNVERIFIED", "topology_unverified",
                           [{"cause": "topology_unverified", **item} for item in scan_errors])
        old_sources = pointer.get("source_files") or {}
        if set(sources) != set(old_sources):
            changed = sorted(set(sources) ^ set(old_sources))
            raise TopologyError("scan_globs 文件集变化未刷新：" + ", ".join(changed))
        changed = [rel for rel in sources if hashlib.sha256(sources[rel]).hexdigest() != old_sources.get(rel)]
        if changed:
            raise TopologyError("源文件 hash 变化未刷新：" + ", ".join(changed))
        if pointer.get("adapter") not in ("all", "compose", "helm", "kong"):
            raise TopologyError("manifest adapter 非法")
        fields = baseline["coverage"]["unverified_fields"]
        if fields:
            return _result(mode, "UNVERIFIED", "topology_unverified",
                           [{"cause": "topology_unverified", "message": "动态字段见 coverage.unverified_fields"}],
                           generation=pointer["generation"],
                           metrics={"nodes": sum(bool(item.get("node")) for item in baseline["items"]),
                                    "edges": sum(bool(item.get("edge")) for item in baseline["items"]),
                                    "parsed": baseline["coverage"]["parsed"]})
        return _result(mode, "PASS", None, [], generation=pointer["generation"],
                       metrics={"nodes": sum(bool(item.get("node")) for item in baseline["items"]),
                                "edges": sum(bool(item.get("edge")) for item in baseline["items"]),
                                "parsed": baseline["coverage"]["parsed"]})
    except TopologyError as exc:
        if "缺少 topology manifest" in str(exc):
            return _result(mode, "UNVERIFIED", "topology_unverified",
                           [{"cause": "topology_unverified", "message": str(exc)}])
        return _result(mode, "FAIL", "topology_stale", [{"cause": "topology_stale", "message": str(exc)}])
    except OSError as exc:
        return _result(mode, "UNVERIFIED", "topology_unverified",
                       [{"cause": "topology_unverified", "message": f"拓扑 I/O 不可判定：{exc}"}])
    except (ValueError, KeyError, TypeError, GovernancePathError) as exc:
        return _result(mode, "FAIL", "topology_stale",
                       [{"cause": "topology_stale", "message": f"拓扑产物不可判定：{exc}"}])


def rollback_topology(root: str | Path, mode: str = "shadow") -> dict:
    """Switch only the manifest pointer; immutable generations are never rewritten."""
    if mode not in MODES or mode == "off":
        raise TopologyError("rollback mode 必须为 shadow/enforce")
    root = Path(root).absolute()
    current = _load_pointer(root)
    previous = current.get("previous_pointer")
    if not isinstance(previous, dict) or previous.get("generation") != current.get("previous_generation"):
        raise TopologyError("没有可回滚的上一代指针")
    topology, rendered = _verify_generation(root, previous)
    _, pointer_path, _, rendered_path = _paths(root)
    fixed = safe_path(root, ".adapter-out/topology.json")
    old_fixed = fixed.read_bytes() if fixed.exists() else None
    old_rendered = rendered_path.read_bytes() if rendered_path.exists() else None
    restored = dict(previous, mode=mode)
    try:
        atomic_write_json(pointer_path, restored)
        try:
            atomic_write_bytes(fixed, canonical_bytes(topology) + b"\n")
            atomic_write_bytes(rendered_path, rendered)
        except OSError as exc:
            try:
                atomic_write_json(pointer_path, current)
                for path, old in ((fixed, old_fixed), (rendered_path, old_rendered)):
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(path, old)
            except OSError as restore_exc:
                raise TopologyError(f"回滚投影/指针恢复失败：{exc}; {restore_exc}") from exc
            raise TopologyError(f"回滚投影失败，已恢复当前指针：{exc}") from exc
    except OSError as exc:
        raise TopologyError(f"回滚 pointer 失败，保留当前代：{exc}") from exc
    return _result(mode, "PASS", None, [], generation=restored["generation"],
                   metrics={"nodes": sum(bool(item.get("node")) for item in topology["items"]),
                            "edges": sum(bool(item.get("edge")) for item in topology["items"]),
                            "parsed": topology["coverage"]["parsed"]})
