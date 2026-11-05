#!/usr/bin/env python3
"""atlas solution —— 多仓方案层（Phase 1：federated）。

本模块只做 Phase 1 的只读整合：
- 清单 / 锁的解析与校验；
- 成员 git 状态、Atlas 资产存在性、ignore / gitlink / 非 git 守卫；
- 跨仓契约文件指纹；
- `status` / `check` / `lock` / `init` / `adopt`。

**不做**：unified 资产搬迁、成员代码提交（solution_commit）、impact / closeout 多根对账。
这些属于 Phase 2/3；遇到 `mode: unified` 必须显式拒绝，不得静默降级。

契约正文见 `shared/solution.md`。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

MANIFEST_NAME = "atlas.solution.yaml"
LOCK_NAME = "atlas.solution.lock.json"
CONFIG_NAME = "atlas.config.yaml"
SCHEMA_VERSION = 1
MODES = ("federated", "unified")
ASSET_OWNERS = ("member", "solution")


class SolutionError(ValueError):
    """输入 / 清单错误（CLI exit 2）。"""


def _load_sibling(name: str, key: str):
    if key in sys.modules:
        return sys.modules[key]
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


_SP = _load_sibling("stack_profile", "_atlas_solution_stack_profile")
strip_inline_comment = _SP.strip_inline_comment
yaml_scalar = _SP.yaml_scalar


# ---------------------------------------------------------------- manifest

def manifest_path(root: Path) -> Path:
    return Path(root) / MANIFEST_NAME


def lock_path(root: Path) -> Path:
    return Path(root) / LOCK_NAME


_NAME_BAD = re.compile(r"[\x00-\x1f:#\"'\\\\]")
_PATH_BAD = re.compile(r"[\x00-\x1f#\"'\\\\]")


def _validate_name(raw: str, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SolutionError(f"{field} 不能为空")
    if raw != raw.strip() or _NAME_BAD.search(raw):
        raise SolutionError(f"{field} 含非法字符（控制字符 / : / # / 引号 / 反斜杠）: {raw!r}")
    return raw


def _safe_rel(raw: str, field: str) -> str:
    if not raw or not isinstance(raw, str):
        raise SolutionError(f"{field} 不能为空")
    if _PATH_BAD.search(raw):
        raise SolutionError(f"{field} 含非法字符（控制字符 / # / 引号 / 反斜杠）: {raw!r}")
    p = PurePosixPath(raw.strip())
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise SolutionError(f"{field} 必须是 solution 内相对路径（拒绝绝对路径与 ..）: {raw!r}")
    if p.parts[0] in (".atlas", ".trellis", ".git"):
        raise SolutionError(f"{field} 不能指向 Atlas/Trellis 内部目录: {raw!r}")
    return p.as_posix()


def _scalar(raw: str):
    v = yaml_scalar(raw)
    return v


def parse_manifest_text(text: str) -> dict:
    """解析 `atlas.solution.yaml` 的受限 YAML 子集。

    支持：顶层标量；`members:` / `contracts:` 的 `- key: value` 列表；
    `requirements:` 只登记存在性（Phase 1 不解析）。不支持嵌套列表 / 多行标量。
    """
    data: dict = {"members": [], "contracts": [], "requirements_present": False,
                  "unknown": []}
    section = None
    cur: dict | None = None
    for raw in text.splitlines():
        line = strip_inline_comment(raw.rstrip())
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if indent == 0 and not s.startswith("- "):
            if s.endswith(":"):
                section = s[:-1].strip()
                cur = None
                if section == "requirements":
                    data["requirements_present"] = True
                elif section not in ("members", "contracts"):
                    data["unknown"].append(section)
                    section = "__unknown__"
                continue
            if ":" not in s:
                raise SolutionError(f"无法解析清单行: {raw!r}")
            key, val = s.split(":", 1)
            key, val = key.strip(), _scalar(val)
            if key in ("version", "solution", "mode"):
                data[key] = val
            elif key == "contracts":
                if val not in (None, "[]"):
                    raise SolutionError("contracts 必须是列表（空值写 contracts: []）")
                data["contracts"] = []
            elif key == "requirements":
                data["requirements_present"] = True
            else:
                data["unknown"].append(key)
            section = None
            cur = None
            continue
        if section == "__unknown__":
            continue
        if section in ("members", "contracts"):
            if s.startswith("- "):
                cur = {}
                data[section].append(cur)
                s = s[2:].strip()
                if not s:
                    continue
            if cur is None or ":" not in s:
                raise SolutionError(f"无法解析 {section} 列表行: {raw!r}")
            key, val = s.split(":", 1)
            key = key.strip()
            known = ("name", "path", "assets", "kind", "stack_profile") \
                if section == "members" else \
                ("id", "producer", "producer_path", "consumer", "consumer_path")
            if key not in known:
                cur.setdefault("unknown", []).append(key)
                continue
            cur[key] = _scalar(val)
            continue
        # requirements：Phase 1 只登记存在性，不解析。
        if section == "requirements":
            data["requirements_present"] = True
            continue
        raise SolutionError(f"无法解析清单行: {raw!r}")
    return data


def load_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.is_file():
        raise SolutionError(f"未找到 {MANIFEST_NAME}: {path}")
    try:
        data = parse_manifest_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SolutionError(f"清单不可读: {exc}") from exc
    return validate_manifest(data, Path(root))


def validate_manifest(data: dict, root: Path, phase1: bool = True) -> dict:
    if str(data.get("version", "")).strip() != str(SCHEMA_VERSION):
        raise SolutionError(f"清单 version 必须为 {SCHEMA_VERSION}")
    name = _validate_name(data.get("solution"), "solution 名称")
    mode = str(data.get("mode", "")).strip()
    if mode not in MODES:
        raise SolutionError(f"mode 必须是 {'/'.join(MODES)}")
    if phase1 and mode == "unified":
        raise SolutionError("unified 模式尚未交付（Phase 2）；Phase 1 只支持 federated")

    members: list[dict] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for item in data.get("members") or []:
        if not isinstance(item, dict):
            raise SolutionError("members 项必须是映射")
        mname = _validate_name(item.get("name"), "members[].name")
        mpath = _safe_rel(str(item.get("path") or ""), "members[].path")
        assets = str(item.get("assets") or "").strip()
        if mname in seen_names:
            raise SolutionError(f"members 名称重复: {mname}")
        if mpath in seen_paths:
            raise SolutionError(f"members 路径重复: {mpath}")
        if assets not in ASSET_OWNERS:
            raise SolutionError(f"members[].assets 必须是 {'/'.join(ASSET_OWNERS)}")
        if phase1 and assets != "member":
            raise SolutionError("Phase 1 只支持 members[].assets: member")
        seen_names.add(mname)
        seen_paths.add(mpath)
        members.append({
            "name": mname,
            "path": mpath,
            "assets": assets,
            "kind": str(item.get("kind") or "fullstack").strip() or "fullstack",
            "stack_profile": str(item.get("stack_profile") or "").strip(),
            "unknown": list(item.get("unknown") or []),
        })
    if not members:
        raise SolutionError("members 至少需要一个成员仓（Phase 1 不接受空方案）")

    contracts: list[dict] = []
    seen_ids: set[str] = set()
    for item in data.get("contracts") or []:
        if not isinstance(item, dict):
            raise SolutionError("contracts 项必须是映射")
        cid = _validate_name(item.get("id"), "contracts[].id")
        if cid in seen_ids:
            raise SolutionError(f"contracts[].id 重复: {cid!r}")
        producer = str(item.get("producer") or "").strip()
        consumer = str(item.get("consumer") or "").strip()
        if producer not in seen_names or consumer not in seen_names:
            raise SolutionError(f"contract {cid} 的 producer/consumer 必须是 members 名称")
        contracts.append({
            "id": cid,
            "producer": producer,
            "producer_path": _safe_rel(str(item.get("producer_path") or ""),
                                       f"contract {cid}.producer_path"),
            "consumer": consumer,
            "consumer_path": _safe_rel(str(item.get("consumer_path") or ""),
                                       f"contract {cid}.consumer_path"),
        })
        seen_ids.add(cid)

    return {
        "version": SCHEMA_VERSION,
        "solution": name.strip(),
        "mode": mode,
        "members": members,
        "contracts": contracts,
        "requirements_present": bool(data.get("requirements_present")),
        "unknown": list(data.get("unknown") or []),
    }


# ---------------------------------------------------------------- git

def _git(cwd: Path, *args: str, timeout: int = 15) -> tuple[int, str, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return p.returncode, p.stdout, p.stderr


def _is_git(path: Path) -> bool:
    """成员必须是**自己的仓根**；仅位于 solution 根工作树内不算。"""
    if not path.is_dir():
        return False
    rc, out, _ = _git(path, "rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        return False
    try:
        return Path(out.strip()).resolve() == path.resolve()
    except OSError:
        return False


def _head(path: Path) -> str | None:
    rc, out, _ = _git(path, "rev-parse", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _branch(path: Path) -> str | None:
    rc, out, _ = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if rc == 0 and out.strip() else None


def _status_lines(path: Path) -> list[str] | None:
    rc, out, _ = _git(path, "status", "--porcelain", "--untracked-files=all")
    if rc != 0:
        return None
    return [ln for ln in out.splitlines() if ln.strip()]


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atlas_baseline(member: Path) -> str | None:
    meta = _read_json(member / ".trellis" / "spec" / "structure" / "_meta.json")
    if not isinstance(meta, dict):
        return None
    baseline = meta.get("baseline")
    if isinstance(baseline, dict):
        return baseline.get("commit") or None
    return baseline if isinstance(baseline, str) else None


def _has_atlas_assets(member: Path) -> bool:
    return any((member / p).exists() for p in (
        "atlas.config.yaml",
        "product/stack-profile.yaml",
        ".trellis/spec/structure/_meta.json",
    ))


def _ignore_patterns(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = strip_inline_comment(raw).strip()
        if line:
            out.append(line)
    return out


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _pattern_matches(pattern: str, rel: str) -> bool:
    p = pattern.strip()
    if not p:
        return False
    if p.startswith("/"):
        p = p[1:]
    dir_pattern = p.endswith("/")
    if dir_pattern:
        p += "**"
    if p == "**":
        return True
    regex = _glob_regex(p)
    if dir_pattern and rel == p[:-3].rstrip("/"):
        return True
    if "/" not in p:
        return any(regex.match(seg) for seg in rel.split("/"))
    return regex.match(rel) is not None


def _ignored_by_file(root: Path, rel: str) -> list[str]:
    reasons: list[str] = []
    ignore_files = [
        root / ".gitignore", root / ".ignore", root / ".rgignore",
        root / ".git" / "info" / "exclude",
    ]
    for path in ignore_files:
        ignored = False
        for pattern in _ignore_patterns(path):
            neg = pattern.startswith("!")
            body = pattern[1:].strip() if neg else pattern
            if _pattern_matches(body, rel):
                ignored = not neg
        if ignored:
            reasons.append(str(path.relative_to(root)))
    return reasons


def _member_ignored(root: Path, rel: str) -> list[str]:
    reasons = _ignored_by_file(root, rel)
    rc, _, _ = _git(root, "check-ignore", "-q", "--", rel)
    if rc == 0 and not reasons:
        reasons.append(".gitignore（git check-ignore）")
    return reasons


def _tracked_member_paths(root: Path, rel: str) -> list[str]:
    rc, out, _ = _git(root, "ls-files", "-s", "--", rel)
    if rc != 0:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def member_state(root: Path, member: dict) -> dict:
    path = (root / member["path"]).resolve()
    state = {
        "name": member["name"],
        "path": member["path"],
        "exists": path.is_dir(),
        "git": _is_git(path),
        "branch": None,
        "head": None,
        "dirty": None,
        "atlas_baseline": None,
        "atlas_assets": False,
        "ignored": [],
        "tracked": [],
        "unknown": list(member.get("unknown") or []),
        "escaped": False,
    }
    if not state["exists"]:
        return state
    try:
        path.relative_to(root.resolve())
    except ValueError:
        state["escaped"] = True
    state["atlas_assets"] = _has_atlas_assets(path)
    state["ignored"] = _member_ignored(root, member["path"])
    state["tracked"] = _tracked_member_paths(root, member["path"])
    if state["git"]:
        state["branch"] = _branch(path)
        state["head"] = _head(path)
        state["dirty"] = _status_lines(path)
        state["atlas_baseline"] = _atlas_baseline(path)
    return state


# ---------------------------------------------------------------- contracts / lock

def _sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "missing"


def contract_states(root: Path, data: dict) -> list[dict]:
    by_name = {m["name"]: m for m in data["members"]}
    out: list[dict] = []
    for c in data.get("contracts") or []:
        producer = root / by_name[c["producer"]]["path"] / c["producer_path"]
        consumer = root / by_name[c["consumer"]]["path"] / c["consumer_path"]
        out.append({
            "id": c["id"],
            "producer": c["producer"],
            "producer_path": c["producer_path"],
            "producer_sha256": _sha256_file(producer),
            "consumer": c["consumer"],
            "consumer_path": c["consumer_path"],
            "consumer_sha256": _sha256_file(consumer),
        })
    return out


def lock_payload(root: Path, data: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "solution": data["solution"],
        "mode": data["mode"],
        "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "members": [
            {
                "name": s["name"],
                "path": s["path"],
                "branch": s["branch"],
                "head": s["head"],
                "atlas_baseline": s["atlas_baseline"],
            }
            for s in (member_state(root, m) for m in data["members"])
        ],
        "contracts": contract_states(root, data),
    }


def write_lock(root: Path, data: dict) -> Path:
    payload = lock_payload(root, data)
    path = lock_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_lock(root: Path) -> dict | None:
    data = _read_json(lock_path(root))
    if not isinstance(data, dict) or not isinstance(data.get("schema_version"), int):
        return None
    for key in ("members", "contracts"):
        val = data.get(key, [])
        if not isinstance(val, list) or any(not isinstance(item, dict) for item in val):
            return None
    return data


# ---------------------------------------------------------------- init / adopt

def _write_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_config(root: Path, assets_root: str) -> None:
    path = root / CONFIG_NAME
    if path.exists():
        return
    path.write_text(f"version: 1\nlayout:\n  assets_root: {assets_root.strip()}\n",
                    encoding="utf-8")


def _install_atlas(root: Path, assets_root: str) -> None:
    version = root / ".atlas" / "VERSION"
    contract = root / ".atlas" / "shared" / "solution.md"
    if version.is_file() and contract.is_file():
        return
    pkg = Path(os.environ.get("ATLAS_PKG_ROOT") or Path(__file__).resolve().parents[1])
    install_py = pkg / "install.py"
    if not install_py.is_file():
        raise SolutionError(
            "solution 根尚未装配 .atlas，且找不到包内 install.py；"
            "请先运行 atlas init 或从源包运行 atlas solution init"
        )
    # solution 根不要求 Trellis（Phase 1 成员各自持有 Trellis）；--no-trellis 跳过
    # Trellis 初始化/骨架，--force 兜底装配器的其他前置。.atlas 目录存在但缺
    # VERSION/shared/solution.md = 上次装配中途失败：允许覆盖重装。
    env = os.environ.copy()
    if (root / ".atlas").exists():
        env["ATLAS_ALLOW_OVERWRITE"] = "1"
    p = subprocess.run(
        [sys.executable, str(install_py), "--target", str(root),
         "--assets-root", assets_root, "--no-skill", "--no-patch", "--no-wiring",
         "--no-trellis", "--force"],
        capture_output=True, text=True, env=env,
    )
    if p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-1:]
        raise SolutionError(f"装配 .atlas 失败: {tail[0] if tail else 'exit ' + str(p.returncode)}")
    if not (version.is_file() and contract.is_file()):
        raise SolutionError("装配 .atlas 不完整（缺 VERSION 或 shared/solution.md）；请重试")


def _member_entries(members: list[tuple[str, str, str]]) -> list[dict]:
    out: list[dict] = []
    for name, path, kind in members:
        out.append({"name": name, "path": _safe_rel(path, f"member {name}.path"),
                    "assets": "member", "kind": kind or "fullstack"})
    return out


def _manifest_text(name: str, members: list[dict], contracts: list[dict] | None = None) -> str:
    lines = [
        "# atlas solution（多仓方案层；Phase 1 = federated）",
        "version: 1",
        f"solution: {name}",
        "mode: federated",
        "members:",
    ]
    for m in members:
        lines += [
            f"  - name: {m['name']}",
            f"    path: {m['path']}",
            "    assets: member",
            f"    kind: {m.get('kind') or 'fullstack'}",
        ]
    if contracts:
        lines.append("contracts:")
        for c in contracts:
            lines += [
                f"  - id: {c['id']}",
                f"    producer: {c['producer']}",
                f"    producer_path: {c['producer_path']}",
                f"    consumer: {c['consumer']}",
                f"    consumer_path: {c['consumer_path']}",
            ]
    else:
        lines.append("contracts: []")
    return "\n".join(lines) + "\n"


_PROFILE_PLACEHOLDERS = ("<产品名>", "<app 标识>")


def _write_profile(root: Path, name: str, members: list[dict], assets_root: str) -> None:
    path = root / assets_root / "stack-profile.yaml"
    text = _solution_profile(name, members, assets_root)
    if path.exists():
        if any(p in path.read_text(encoding="utf-8", errors="replace")
               for p in _PROFILE_PLACEHOLDERS):
            path.write_text(text, encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _solution_profile(name: str, members: list[dict], assets_root: str) -> str:
    lines = [
        "# atlas solution stack-profile（Phase 1：跨仓 E2E 画像）",
        f"product: {name}",
        "origin: greenfield",
        "apps:",
    ]
    for m in members:
        lines += [
            f"  - name: {m['name']}",
            f"    path: {m['path']}",
            f"    kind: {m.get('kind') or 'fullstack'}",
            "    role: landing",
            "    stack: 由成员仓维护",
        ]
    lines += [
        "adapters:",
        "  routes: null",
        "  api: null",
        "  models: null",
        "  tests: null",
        "e2e:",
        "  runner: node-playwright",
        f"  cases_dir: {assets_root}/e2e/cases",
        f"  index: {assets_root}/e2e/e2e-index.md",
        f"  scripts_dir: {assets_root}/e2e/scripts",
        "  app_base_url: null",
        "  reset: null",
        "  node_modules: null",
    ]
    return "\n".join(lines) + "\n"


def _prd_skeletons(root: Path, name: str, assets_root: str) -> None:
    prd_dir = root / assets_root / "prd"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (root / assets_root / "e2e" / "cases").mkdir(parents=True, exist_ok=True)
    (root / assets_root / "e2e" / "scripts").mkdir(parents=True, exist_ok=True)
    (root / assets_root / "reviews").mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    _write_if_missing(prd_dir / "prd.md", f"""---
doc: prd-global
product: "{name}"
version: 0.1.0
date: "{today}"
status: draft
---

# {name} — 产品需求文档（全局）

范围形态：首建

## 五、功能架构

| 域 slug | 中文名 | 一句话职责 | 域级文件 |
|---|---|---|---|
| solution | 跨仓需求 | 跨仓需求与验收 | `solution-prd.md` |
""")
    template = root / ".atlas" / "templates" / "prd" / "domain.md"
    if not template.is_file():
        template = Path(__file__).resolve().parents[1] / "templates" / "prd" / "domain.md"
    text = template.read_text(encoding="utf-8") if template.is_file() else ""
    text = text.replace('domain: "[必填：domain-slug，如 dubbing-config]"',
                        'domain: "solution"')
    text = text.replace('domain_name: "[必填：中文名]"',
                        f'domain_name: "{name} 跨仓需求"')
    text = text.replace('domain_code: "[必填：ID 前缀，如 DUBBING-CONFIG，用于 FN-/R-/AC- 编号]"',
                        'domain_code: "SOLUTION"')
    text = text.replace('date: "[必填：YYYY-MM-DD]"', f'date: "{today}"')
    _write_if_missing(prd_dir / "solution-prd.md", text)
    _write_if_missing(prd_dir / "README.md", """# PRD 追溯总表

| 域 | 域级文件 | 模块 | 页面 | 功能数 | 规则数 | AC 数 |
|---|---|---|---|---|---|---|
| solution | solution-prd.md | — | — | 0 | 0 | 0 |
""")


def init_solution(root: Path, name: str, members: list[tuple[str, str, str]],
                  assets_root: str = "product", install: bool = True,
                  contracts: list[dict] | None = None) -> Path:
    root = Path(root).resolve()
    if manifest_path(root).exists():
        raise SolutionError(f"{MANIFEST_NAME} 已存在：{manifest_path(root)}")
    name = _validate_name(name, "solution 名称")
    entries = _member_entries(members)
    if not entries:
        raise SolutionError("Phase 1 至少需要一个成员仓（--member name=path）")
    validate_manifest({
        "version": SCHEMA_VERSION,
        "solution": name,
        "mode": "federated",
        "members": entries,
        "contracts": contracts or [],
        "requirements_present": False,
        "unknown": [],
    }, root, phase1=True)
    # atlas.config.yaml 是资产根的单一来源；已存在时不得用 CLI 默认值覆盖。
    effective_assets = _assets_root(root) if (root / CONFIG_NAME).is_file() else assets_root
    if install:
        _install_atlas(root, effective_assets)
    _write_config(root, effective_assets)
    _write_profile(root, name, entries, effective_assets)
    _prd_skeletons(root, name, effective_assets)
    # 清单最后原子落盘：前面的 profile/PRD 中途失败时不留“已初始化”假象，
    # 重跑不会被 manifest 存在检查挡住。
    path = manifest_path(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_manifest_text(name, entries, contracts), encoding="utf-8")
    tmp.replace(path)
    return path


def detect_members(root: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for child in sorted(Path(root).iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not _is_git(child):
            continue
        if _has_atlas_assets(child):
            out.append((child.name, child.name, "fullstack"))
    return out


def adopt_solution(root: Path, name: str, members: list[tuple[str, str, str]] | None = None,
                   assets_root: str = "product", install: bool = True) -> tuple[Path, list[dict]]:
    root = Path(root).resolve()
    entries = _member_entries(members or detect_members(root))
    if not entries:
        raise SolutionError("未检测到带 Atlas 资产的成员仓；请用 --member name=path 显式指定")
    path = init_solution(root, name, [(m["name"], m["path"], m.get("kind", "fullstack"))
                                      for m in entries],
                         assets_root=assets_root, install=install)
    data = load_manifest(root)
    write_lock(root, data)
    return path, data["members"]


# ---------------------------------------------------------------- status / check

def status(root: Path) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    states = [member_state(root, m) for m in data["members"]]
    lock = read_lock(root)
    return {
        "solution": data["solution"],
        "mode": data["mode"],
        "members": states,
        "lock": {
            "present": lock is not None,
            "locked_at": (lock or {}).get("locked_at"),
        },
        "contracts": contract_states(root, data),
    }


def _lock_member(lock: dict | None, name: str) -> dict | None:
    for m in (lock or {}).get("members") or []:
        if m.get("name") == name:
            return m
    return None


def _lock_contract(lock: dict | None, cid: str) -> dict | None:
    for c in (lock or {}).get("contracts") or []:
        if c.get("id") == cid:
            return c
    return None


def check_solution(root: Path) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    results: list[dict] = []
    add = lambda name, status, detail: results.append(
        {"check": name, "status": status, "detail": detail})

    add("清单 schema", "PASS", f"{data['solution']} / {data['mode']} / {len(data['members'])} 成员")
    if not _is_git(root):
        add("solution 根", "WARN", "不是 git 仓；成员 untracked 没有基线，建议先 git init")
    rc, cfg_out, _ = _git(root, "config", "--get", "status.showUntrackedFiles")
    if rc == 0 and cfg_out.strip().lower() == "no":
        add("git 配置", "WARN",
            "status.showUntrackedFiles=no 会盲掉 _graph / atlas_check / e2e_console")
    if data.get("unknown"):
        add("清单未知键", "WARN", "；".join(data["unknown"]))
    if data.get("requirements_present"):
        add("requirements", "WARN", "Phase 1 不解析 requirements（仅登记存在性）")

    lock = read_lock(root)
    contracts_now = contract_states(root, data)
    if lock is None:
        add("契约锁", "WARN", f"缺少 {LOCK_NAME}；运行 atlas solution lock --update")
    else:
        for s in data["members"]:
            prev = _lock_member(lock, s["name"])
            cur = member_state(root, s)
            if prev is None:
                add(f"锁/{s['name']}", "WARN", "锁中没有该成员")
                continue
            if prev.get("head") != cur.get("head"):
                add(f"锁/{s['name']}", "WARN",
                    f"HEAD 漂移：锁定 {str(prev.get('head'))[:12]} → 当前 {str(cur.get('head'))[:12]}")
            if prev.get("branch") != cur.get("branch"):
                add(f"锁/{s['name']}", "WARN",
                    f"分支漂移：锁定 {prev.get('branch')!r} → 当前 {cur.get('branch')!r}")
            if prev.get("atlas_baseline") != cur.get("atlas_baseline"):
                add(f"锁/{s['name']}", "WARN",
                    f"成员 Atlas baseline 漂移：锁定 {str(prev.get('atlas_baseline'))[:12]} → "
                    f"当前 {str(cur.get('atlas_baseline'))[:12]}")
        for c in contracts_now:
            prev = _lock_contract(lock, c["id"])
            if prev is None:
                add(f"锁/契约 {c['id']}", "WARN", "锁中没有该契约")
                continue
            for side in ("producer_sha256", "consumer_sha256"):
                if prev.get(side) != c[side]:
                    add(f"锁/契约 {c['id']}", "WARN", f"{side} 漂移（需人工确认跨仓影响）")
        member_names = {m["name"] for m in data["members"]}
        contract_ids = {c["id"] for c in contracts_now}
        for lm in lock.get("members") or []:
            if lm.get("name") not in member_names:
                add("锁", "WARN", f"锁中成员已不在清单: {lm.get('name')}")
        for lc in lock.get("contracts") or []:
            if lc.get("id") not in contract_ids:
                add("锁", "WARN", f"锁中契约已不在清单: {lc.get('id')}")
    for c in contracts_now:
        missing = [side for side in ("producer_sha256", "consumer_sha256")
                   if c[side] == "missing"]
        if missing:
            add(f"契约 {c['id']}", "WARN",
                "文件缺失：" + "、".join(side.replace("_sha256", "") for side in missing))

    for m in data["members"]:
        s = member_state(root, m)
        prefix = f"成员 {s['name']}"
        if not s["exists"]:
            add(prefix, "WARN", f"路径不存在: {s['path']}")
            continue
        if s["escaped"]:
            add(prefix, "WARN", "成员路径 resolve 后逃逸出 solution 根（symlink？）")
        if not s["git"]:
            add(prefix, "WARN", "不是 git 仓")
        if not s["atlas_assets"]:
            add(prefix, "WARN", "未检测到 Atlas 资产（atlas.config.yaml / product/stack-profile.yaml / 结构 meta）")
        if s["ignored"]:
            add(prefix, "WARN", "成员路径命中 ignore：" + "、".join(s["ignored"]))
        if s["tracked"]:
            add(prefix, "WARN", f"成员路径已被 solution 仓跟踪（{len(s['tracked'])} 条，疑似 gitlink）")
        if s.get("unknown"):
            add(prefix, "WARN", "成员未知键：" + "、".join(s["unknown"]))

    for rel in (".atlas", f"{_assets_root(root)}/stack-profile.yaml",
                f"{_assets_root(root)}/prd/prd.md",
                f"{_assets_root(root)}/prd/solution-prd.md"):
        if not (root / rel).exists():
            add(f"solution 资产 {rel}", "WARN", "缺失")
    prd = root / _assets_root(root) / "prd" / "solution-prd.md"
    if prd.is_file() and "[必填" in prd.read_text(encoding="utf-8", errors="replace"):
        add("solution-prd.md", "WARN", "仍是模板骨架（含 [必填] 占位），需补齐完整域 PRD")
    profile = root / _assets_root(root) / "stack-profile.yaml"
    if profile.is_file():
        profile_text = profile.read_text(encoding="utf-8", errors="replace")
        if any(p in profile_text for p in _PROFILE_PLACEHOLDERS):
            add("stack-profile.yaml", "WARN",
                "仍是通用模板（含 <产品名>/<app 标识>），需换成 solution 画像")
    trellis_cfg = root / ".trellis" / "config.yaml"
    if trellis_cfg.is_file():
        trellis_text = trellis_cfg.read_text(encoding="utf-8", errors="replace")
        missing = [m["path"] for m in data["members"]
                   if f"path: {m['path']}" not in trellis_text
                   and f"path: ./{m['path']}" not in trellis_text]
        if missing:
            add("Trellis packages", "WARN",
                "未声明成员：" + "、".join(missing))
    else:
        add("Trellis packages", "SKIP",
            "solution 根无 .trellis/config.yaml（Phase 1 不生成；Phase 2）")

    overall = "WARN" if any(r["status"] == "WARN" for r in results) else "PASS"
    return {"solution": data["solution"], "mode": data["mode"],
            "overall": overall, "checks": results}


def _assets_root(root: Path) -> str:
    config = root / CONFIG_NAME
    if config.is_file():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("assets_root:"):
                v = _scalar(s.split(":", 1)[1])
                if isinstance(v, str) and v:
                    return v
    return "product"


def render_status(data: dict) -> str:
    lines = [f"solution: {data['solution']} ({data['mode']})", "members:"]
    for s in data["members"]:
        head = (s.get("head") or "—")[:12]
        dirty = "clean" if s.get("dirty") == [] else (
            "dirty" if s.get("dirty") else "n/a")
        ignored = "ignored" if s.get("ignored") else "ok"
        lines.append(
            f"  {s['name']:<16} {s['path']:<20} git={str(s['git']).lower():<5} "
            f"branch={s.get('branch') or '—':<12} head={head:<12} {dirty:<5} "
            f"atlas={'yes' if s['atlas_assets'] else 'no':<3} {ignored}")
    lines.append(f"lock: {'present' if data['lock']['present'] else 'missing'}"
                 + (f" ({data['lock']['locked_at']})" if data['lock'].get('locked_at') else ""))
    return "\n".join(lines)


def render_check(data: dict) -> str:
    lines = [f"solution check: {data['overall']}"]
    for r in data["checks"]:
        lines.append(f"  [{r['status']}] {r['check']}: {r['detail']}")
    return "\n".join(lines)
