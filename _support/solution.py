#!/usr/bin/env python3
"""atlas solution —— 多仓方案层（federated + pinned workspace）。

Phase 1 提供只读整合：清单 / 锁解析、成员 git 状态、ignore / gitlink / 非 git 守卫、
跨仓契约指纹、`status` / `check` / `lock` / `init` / `adopt`。

本次增量（Unreleased）把锁升级为可复现基线：
- 清单可记录 `members[].url`；URL 做 scheme 白名单并拒绝内嵌凭据；
- 锁记录成员 `url / branch / head(commit)`，作为 `check --strict` 的判据；
- `check --strict` 把锁缺失 / 锁未跟踪 / 版本或契约漂移 / dirty / 缺 URL 升为 FAIL；
- `diff` 只读对账：成员相对锁的提交 / diffstat 与工作区改动。

CI 按锁还原由流水线自行 clone + checkout 承担（见 `shared/solution.md` §5.1），本模块不提供自动还原命令。

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
from urllib.parse import urlsplit, urlunsplit

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

# 用例 ID 文法单源（`rings/e2e/reference.md` §5.3）。
# 取用者必须登记进 `_support/case_id.py::CONSUMERS`（`tests/test_tools.py` 普查钉）。
case_id = _load_sibling("case_id", "_atlas_solution_case_id")


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


_URL_SCHEMES = ("http", "https", "ssh", "git", "file")
_CREDENTIAL_QUERY = re.compile(
    r"(?:^|[?&])(?:access_token|private_token|token|auth|key|sig|signature|"
    r"x-amz-signature|x-amz-credential|x-amz-security-token)=", re.I)
_SCP_LIKE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^/].*$")


def _redact_url(raw: str) -> str:
    """错误信息里的脱敏展示：只遮蔽 userinfo 与 token 查询参数。"""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "<redacted>"
    netloc = parts.netloc
    if "@" in netloc:
        user = netloc.rsplit("@", 1)[0]
        masked = "***" if ":" not in user else f"{user.split(':', 1)[0]}:***"
        netloc = f"{masked}@{netloc.rsplit('@', 1)[1]}"
    query = re.sub(
        r"(?i)((?:access_token|private_token|token|auth|key|sig|signature|"
        r"x-amz-signature|x-amz-credential|x-amz-security-token)=)[^&]*",
        r"\1***", parts.query)
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _validate_url(raw, field: str) -> str | None:
    """成员仓远端地址：scheme 白名单 + 拒绝内嵌凭据 / 参数注入。

    允许 http/https/ssh/git/file、SCP 形式 `user@host:path`、本地绝对或 ./ 路径；
    拒绝 `ext::`（git 可执行命令）、前导 `-`、控制字符 / 空白。
    http(s) 的 userinfo 与常见 token 查询参数一律拒绝，避免凭据落进清单与锁。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("-") or re.search(r"[\x00-\x1f\s]", s):
        raise SolutionError(f"{field} 含非法字符（控制字符 / 空白 / 前导 -）: {raw!r}")
    parts = urlsplit(s)
    scheme = parts.scheme.lower()
    if scheme:
        if scheme not in _URL_SCHEMES:
            raise SolutionError(
                f"{field} 的 scheme 不在白名单（{'/'.join(_URL_SCHEMES)}）: {raw!r}")
        if scheme in ("http", "https", "file") and (parts.username or parts.password):
            raise SolutionError(
                f"{field} 含内嵌凭据（userinfo），禁止写入清单/锁；"
                f"请改用 SSH 或凭据管理器: {_redact_url(s)!r}")
        if parts.password:
            raise SolutionError(
                f"{field} 含密码，禁止写入清单/锁；请改用 SSH 或凭据管理器: "
                f"{_redact_url(s)!r}")
        if _CREDENTIAL_QUERY.search(parts.query):
            raise SolutionError(
                f"{field} 查询参数含 token/签名，禁止写入清单/锁: {_redact_url(s)!r}")
        return s
    if _SCP_LIKE.match(s):
        # SCP 形式只允许 user@host:path；出现 user:pass@ 视为密码。
        userinfo = s.split("@", 1)[0]
        if ":" in userinfo:
            raise SolutionError(
                f"{field} 含内嵌密码，禁止写入清单/锁: {_redact_url(s)!r}")
        return s
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return s
    raise SolutionError(
        f"{field} 不是受支持的仓库地址（需要 scheme 白名单、SCP 形式或本地路径）: {raw!r}")


def parse_manifest_text(text: str) -> dict:
    """解析 `atlas.solution.yaml` 的受限 YAML 子集。

    支持：顶层标量；`members:` / `contracts:` / `requirements:` 的 `- key: value`
    列表（`requirements` 逐行解析 `id / acs / member / task_slug / assignee / scope /
    case_ids / cross_repo_e2e`）。不支持嵌套列表 / 多行标量。
    """
    data: dict = {"members": [], "contracts": [], "requirements": [],
                  "requirements_present": False, "unknown": []}
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
                elif section not in ("members", "contracts", "requirements"):
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
                if val not in (None, "[]"):
                    raise SolutionError("requirements 必须是列表（空值写 requirements: []）")
            else:
                data["unknown"].append(key)
            section = None
            cur = None
            continue
        if section == "__unknown__":
            continue
        if section in ("members", "contracts", "requirements"):
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
            known = {
                "members": ("name", "path", "url", "assets", "kind", "stack_profile"),
                "contracts": ("id", "producer", "producer_path", "consumer", "consumer_path"),
                "requirements": ("id", "acs", "member", "task_slug", "assignee", "scope",
                                 "case_ids", "cross_repo_e2e"),
            }[section]
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
            "url": _validate_url(item.get("url"), f"members[{mname}].url"),
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

    requirements: list[dict] = []
    seen_req_keys: set[tuple[str, str]] = set()
    for item in data.get("requirements") or []:
        if not isinstance(item, dict):
            raise SolutionError("requirements 项必须是映射")
        rid = _validate_name(item.get("id"), "requirements[].id")
        member = str(item.get("member") or "").strip()
        if member not in seen_names:
            raise SolutionError(f"requirement {rid} 的 member 必须是 members 名称")
        acs_raw = item.get("acs")
        if isinstance(acs_raw, list):
            acs = [str(a).strip() for a in acs_raw if str(a).strip()]
        else:
            acs = [a.strip() for a in re.split(r"[、,，]", str(acs_raw or "")) if a.strip()]
        if not acs:
            raise SolutionError(f"requirement {rid} 缺少 acs")
        for ac in acs:
            if not re.fullmatch(r"AC-[A-Z0-9]+-\d{3}", ac):
                raise SolutionError(f"requirement {rid} 的 AC ID 非法: {ac!r}")
        slug = str(item.get("task_slug") or "").strip()
        if not _valid_task_slug(slug):
            raise SolutionError(f"requirement {rid} 的 task_slug 非法: {slug!r}")
        scope = str(item.get("scope") or "").strip()
        if not scope:
            raise SolutionError(f"requirement {rid} 缺少 scope")
        assignee = str(item.get("assignee") or "").strip()
        if assignee:
            _validate_name(assignee, "requirements[].assignee")
        # 选择器（一期）：`case_ids` 是**需求级**属标量，逗号/顿号分隔；`cross_repo_e2e`
        # 唯一合法值 `none`。文法 / 去重在这里；「多成员必须 case_ids / 单成员二选一」
        # 是跨行语义，归 `solution check`（不在此抛 SolutionError，避免清单加载提前打断）。
        case_ids_present = "case_ids" in item
        raw_case_ids = item.get("case_ids")
        if isinstance(raw_case_ids, list):
            case_ids = [str(c).strip() for c in raw_case_ids if str(c).strip()]
        else:
            case_ids = [c.strip() for c in re.split(r"[、,，]", str(raw_case_ids or ""))
                        if c.strip()]
        seen_case_ids: set[str] = set()
        for cid in case_ids:
            if not re.fullmatch(case_id.GRAMMAR, cid):
                raise SolutionError(f"requirement {rid} 的 case_id 文法非法: {cid!r}")
            if cid in seen_case_ids:
                raise SolutionError(f"requirement {rid} 的 case_ids 重复: {cid!r}")
            seen_case_ids.add(cid)
        cross_present = "cross_repo_e2e" in item
        cross_repo_e2e = str(item.get("cross_repo_e2e") or "").strip() or None
        if cross_repo_e2e is not None and cross_repo_e2e != "none":
            raise SolutionError(
                f"requirement {rid} 的 cross_repo_e2e 只能是 none: {cross_repo_e2e!r}")
        key = (rid, member)
        if key in seen_req_keys:
            raise SolutionError(f"requirements 重复（id+member）: {rid} / {member}")
        seen_req_keys.add(key)
        requirements.append({
            "id": rid,
            "acs": acs,
            "member": member,
            "task_slug": slug,
            "assignee": assignee or None,
            "scope": scope,
            "case_ids": case_ids,
            "case_ids_present": case_ids_present,
            "cross_repo_e2e": cross_repo_e2e,
            "cross_repo_e2e_present": cross_present,
            "unknown": list(item.get("unknown") or []),
        })

    # 选择器互斥（清单内语义）：同一 `requirement.id` 最多一行携带 `case_ids`、
    # 最多一行携带 `cross_repo_e2e`，且两者不得同时出现。
    by_req: dict[str, list[dict]] = {}
    for req in requirements:
        by_req.setdefault(req["id"], []).append(req)
    for rid, rows in by_req.items():
        case_rows = [r for r in rows if r["case_ids_present"]]
        none_rows = [r for r in rows if r["cross_repo_e2e_present"]]
        if len(case_rows) > 1:
            raise SolutionError(f"requirement {rid} 有多行携带 case_ids（选择器歧义）")
        if len(none_rows) > 1:
            raise SolutionError(f"requirement {rid} 有多行携带 cross_repo_e2e")
        if case_rows and none_rows:
            raise SolutionError(f"requirement {rid} 同时出现 case_ids 与 cross_repo_e2e")

    return {
        "version": SCHEMA_VERSION,
        "solution": name.strip(),
        "mode": mode,
        "members": members,
        "contracts": contracts,
        "requirements": requirements,
        "requirements_present": bool(requirements) or bool(data.get("requirements_present")),
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


def _git_lines(cwd: Path, *args: str, timeout: int = 15) -> list[str] | None:
    rc, out, _ = _git(cwd, *args, timeout=timeout)
    return out.splitlines() if rc == 0 else None


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


def _member_url(path: Path) -> str | None:
    if not _is_git(path):
        return None
    rc, out, _ = _git(path, "remote", "get-url", "origin")
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


def _ignore_sources(root: Path, rel: str) -> list[tuple[str, Path]]:
    """成员路径上所有可能生效的 ignore 文件：根级 + 逐级祖先目录。

    `.gitignore` / `.ignore` / `.rgignore` 在子目录同样生效；只查根级会漏掉
    `apps/.ignore` 这类嵌套规则。返回 (相对该 ignore 文件的目录, 文件路径)。
    """
    sources: list[tuple[str, Path]] = []
    for name in (".gitignore", ".ignore", ".rgignore"):
        path = root / name
        if path.is_file():
            sources.append(("", path))
    base = PurePosixPath()
    for part in PurePosixPath(rel).parts[:-1]:
        base = base / part
        for name in (".gitignore", ".ignore", ".rgignore"):
            path = root / base / name
            if path.is_file():
                sources.append((base.as_posix(), path))
    exclude = root / ".git" / "info" / "exclude"
    if exclude.is_file():
        sources.append(("", exclude))
    return sources


def _ignored_by_file(root: Path, rel: str) -> list[str]:
    reasons: list[str] = []
    rel_path = PurePosixPath(rel)
    for base, path in _ignore_sources(root, rel):
        sub = rel if not base else rel_path.relative_to(base).as_posix()
        ignored = False
        for pattern in _ignore_patterns(path):
            neg = pattern.startswith("!")
            body = pattern[1:].strip() if neg else pattern
            if _pattern_matches(body, sub):
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


def _assert_members_untracked(root: Path, entries: list[dict]) -> None:
    """init/adopt 写清单前硬拒绝：成员路径已被父仓跟踪（含 submodule gitlink）。

    只 WARN 会让“父仓 diff 看不到成员内容”的假象被带进新方案；
    这里要求先解除跟踪，工作区文件保留。
    """
    for m in entries:
        tracked = _tracked_member_paths(root, m["path"])
        if not tracked:
            continue
        gitlinks = [ln for ln in tracked if ln.split(maxsplit=1)[0] == "160000"]
        if gitlinks:
            raise SolutionError(
                f"成员 {m['name']} 路径 {m['path']} 已被 solution 仓登记为 submodule/gitlink"
                f"（mode 160000，{len(gitlinks)} 条）。请先执行 `git rm --cached {m['path']}` "
                f"并删除 .gitmodules 中对应条目（保留工作区文件），再重试；"
                "不要把 submodule 与 solution 混用。")
        raise SolutionError(
            f"成员 {m['name']} 路径 {m['path']} 已被 solution 仓跟踪（{len(tracked)} 条）。"
            f"请先执行 `git rm -r --cached {m['path']}`（保留工作区），"
            "确认 .gitignore/.ignore/.rgignore 不命中该路径，再重试。")


def member_state(root: Path, member: dict) -> dict:
    path = (root / member["path"]).resolve()
    state = {
        "name": member["name"],
        "path": member["path"],
        "url": member.get("url") or None,
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
        if not state["url"]:
            try:
                # origin 可能内嵌凭据：非法地址不进入状态，避免 status --json 泄露。
                state["url"] = _validate_url(_member_url(path), f"member {member['name']}.url")
            except SolutionError:
                state["url"] = None
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


def _safe_member_file(root: Path, member_rel: str, file_rel: str) -> Path | None:
    """契约文件必须落在 solution 根内；symlink 指向根外时返回 None，不读外部文件。"""
    root_r = root.resolve()
    member_dir = (root / member_rel).resolve()
    try:
        member_dir.relative_to(root_r)
    except ValueError:
        return None
    target = (member_dir / file_rel).resolve()
    try:
        target.relative_to(root_r)
    except ValueError:
        return None
    return target


def contract_states(root: Path, data: dict) -> list[dict]:
    by_name = {m["name"]: m for m in data["members"]}
    out: list[dict] = []
    for c in data.get("contracts") or []:
        producer = _safe_member_file(root, by_name[c["producer"]]["path"], c["producer_path"])
        consumer = _safe_member_file(root, by_name[c["consumer"]]["path"], c["consumer_path"])
        out.append({
            "id": c["id"],
            "producer": c["producer"],
            "producer_path": c["producer_path"],
            "producer_sha256": _sha256_file(producer) if producer else "missing",
            "consumer": c["consumer"],
            "consumer_path": c["consumer_path"],
            "consumer_sha256": _sha256_file(consumer) if consumer else "missing",
        })
    return out


def lock_payload(root: Path, data: dict) -> dict:
    members: list[dict] = []
    for m in data["members"]:
        s = member_state(root, m)
        if s["git"] and s.get("branch") == "HEAD":
            raise SolutionError(
                f"成员 {s['name']} 处于 detached HEAD（branch=HEAD）；"
                "请先切回分支再执行 lock --update，避免锁里写入不可复现的分支名")
        members.append({
            "name": s["name"],
            "path": s["path"],
            "url": m.get("url"),
            "branch": s["branch"],
            "head": s["head"],
            "atlas_baseline": s["atlas_baseline"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "solution": data["solution"],
        "mode": data["mode"],
        "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "members": members,
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


def lock_tracking(root: Path) -> dict:
    """锁文件是否被父仓跟踪、且与父仓 HEAD 一致（CI 复现的前提）。"""
    if not _is_git(root):
        return {"tracked": False, "consistent": None}
    rc, _, _ = _git(root, "ls-files", "--error-unmatch", "--", LOCK_NAME)
    tracked = rc == 0
    consistent = None
    if tracked:
        rc2, _, _ = _git(root, "diff", "--quiet", "HEAD", "--", LOCK_NAME)
        consistent = rc2 == 0
    return {"tracked": tracked, "consistent": consistent}


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


def _member_entries(members: list[tuple], root: Path | None = None) -> list[dict]:
    out: list[dict] = []
    for item in members:
        name, path, kind = item[0], item[1], item[2]
        explicit_url = item[3] if len(item) > 3 else None
        rel = _safe_rel(path, f"member {name}.path")
        url = explicit_url
        if not url and root is not None:
            url = _member_url(Path(root) / rel)
        out.append({"name": name, "path": rel,
                    "url": _validate_url(url, f"member {name}.url"),
                    "assets": "member", "kind": kind or "fullstack"})
    return out


def _valid_task_slug(slug: str) -> bool:
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        return False
    if re.match(r"^\d{2}-\d{2}-", slug):
        return False
    return True


def _yaml_value(value: str) -> str:
    """清单值：含 `#` 时加引号，避免被行内注释截断。"""
    s = str(value)
    return f'"{s}"' if "#" in s else s


def _manifest_text(name: str, members: list[dict], contracts: list[dict] | None = None,
                   requirements: list[dict] | None = None) -> str:
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
        ]
        if m.get("url"):
            lines.append(f"    url: {_yaml_value(m['url'])}")
        lines += [
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
    if requirements:
        lines.append("requirements:")
        for r in requirements:
            acs = r["acs"] if isinstance(r["acs"], list) else [
                a.strip() for a in re.split(r"[、,，]", str(r["acs"])) if a.strip()]
            lines += [
                f"  - id: {r['id']}",
                f"    acs: {','.join(acs)}",
                f"    member: {r['member']}",
                f"    task_slug: {r['task_slug']}",
                f"    scope: {_yaml_value(r['scope'])}",
            ]
            if r.get("assignee"):
                lines.append(f"    assignee: {r['assignee']}")
            case_ids = r.get("case_ids") or []
            if isinstance(case_ids, str):
                case_ids = [a.strip() for a in re.split(r"[、,，]", case_ids) if a.strip()]
            if case_ids:
                lines.append(f"    case_ids: {','.join(case_ids)}")
            if r.get("cross_repo_e2e"):
                lines.append(f"    cross_repo_e2e: {r['cross_repo_e2e']}")
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


def init_solution(root: Path, name: str, members: list[tuple],
                  assets_root: str = "product", install: bool = True,
                  contracts: list[dict] | None = None,
                  requirements: list[dict] | None = None) -> Path:
    root = Path(root).resolve()
    if manifest_path(root).exists():
        raise SolutionError(f"{MANIFEST_NAME} 已存在：{manifest_path(root)}")
    name = _validate_name(name, "solution 名称")
    entries = _member_entries(members, root)
    if not entries:
        raise SolutionError("Phase 1 至少需要一个成员仓（--member name=path）")
    # 写清单前硬拒绝：成员已被父仓跟踪（含 gitlink）时不进入 solution 模型。
    _assert_members_untracked(root, entries)
    validate_manifest({
        "version": SCHEMA_VERSION,
        "solution": name,
        "mode": "federated",
        "members": entries,
        "contracts": contracts or [],
        "requirements": requirements or [],
        "requirements_present": bool(requirements),
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
    tmp.write_text(_manifest_text(name, entries, contracts, requirements), encoding="utf-8")
    tmp.replace(path)
    # 成员齐全且不在 detached HEAD 时立即写入首版锁：
    # init 即钉住一组可复现版本；成员尚未 clone 时暂不写，避免 head=None 的“假锁”。
    data = load_manifest(root)
    states = [member_state(root, m) for m in data["members"]]
    if all(s["git"] and s.get("branch") not in (None, "HEAD") for s in states):
        write_lock(root, data)
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
    entries = _member_entries(members or detect_members(root), root)
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
    for s in states:
        prev = _lock_member(lock, s["name"])
        s["locked_head"] = (prev or {}).get("head")
        s["head_drift"] = bool(prev and prev.get("head")
                               and prev.get("head") != s.get("head"))
        s["dirty_count"] = len(s["dirty"]) if isinstance(s.get("dirty"), list) else None
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


def check_solution(root: Path, strict: bool = False) -> dict:
    root = Path(root).resolve()
    data = load_manifest(root)
    results: list[dict] = []
    level = "FAIL" if strict else "WARN"
    add = lambda name, status, detail: results.append(
        {"check": name, "status": status, "detail": detail})

    add("清单 schema", "PASS", f"{data['solution']} / {data['mode']} / {len(data['members'])} 成员")
    if not _is_git(root):
        add("solution 根", level, "不是 git 仓；成员 untracked 没有基线，建议先 git init")
    rc, cfg_out, _ = _git(root, "config", "--get", "status.showUntrackedFiles")
    if rc == 0 and cfg_out.strip().lower() == "no":
        add("git 配置", level,
            "status.showUntrackedFiles=no 会盲掉 _graph / atlas_check / e2e_console")
    if data.get("unknown"):
        add("清单未知键", "WARN", "；".join(data["unknown"]))
    if data.get("requirements"):
        try:
            task_core = _load_sibling("solution_task", "_atlas_solution_task_check")
            for warning in task_core.check_requirements(root, data):
                add("跨仓任务", "WARN", warning)
        except Exception as exc:  # noqa: BLE001 - 对账不可用要显式出声
            add("跨仓任务", "WARN", f"对账不可用: {type(exc).__name__}: {exc}")
        for req in data.get("requirements") or []:
            if req.get("unknown"):
                add("跨仓任务", "WARN",
                    f"{req['id']} 未知键: {'、'.join(req['unknown'])}")

    # 父仓跨仓 E2E（RFC-20261108-02 一期）：索引存在性 / 选择器 / 引用 / 接线 / 需求列一致性。
    e2e_audit = None
    try:
        e2e_core = _load_sibling("solution_e2e", "_atlas_solution_e2e")
        e2e_audit = e2e_core.check(root, data)
        for item in e2e_audit["checks"]:
            add(item["check"], item["status"], item["detail"])
    except Exception as exc:  # noqa: BLE001 - 专门检查不可用必须出声
        add("父仓 E2E", "FAIL", f"检查不可用: {type(exc).__name__}: {exc}")

    lock = read_lock(root)
    contracts_now = contract_states(root, data)
    if lock is not None:
        tracking = lock_tracking(root)
        if not tracking["tracked"]:
            add("契约锁跟踪", level,
                f"{LOCK_NAME} 未被父仓 Git 跟踪；CI 无法从父仓 commit 还原锁定版本")
        elif tracking["consistent"] is False:
            add("契约锁跟踪", level,
                f"{LOCK_NAME} 与父仓 HEAD 不一致；请提交锁文件后再跑 CI")
    if lock is None:
        add("契约锁", level, f"缺少 {LOCK_NAME}；运行 atlas solution lock --update")
    else:
        for s in data["members"]:
            prev = _lock_member(lock, s["name"])
            cur = member_state(root, s)
            if prev is None:
                add(f"锁/{s['name']}", level, "锁中没有该成员")
                continue
            if not prev.get("head"):
                add(f"锁/{s['name']}", level, "锁中没有 commit，无法复现成员版本")
            if prev.get("head") != cur.get("head"):
                add(f"锁/{s['name']}", level,
                    f"HEAD 漂移：锁定 {str(prev.get('head'))[:12]} → 当前 {str(cur.get('head'))[:12]}")
            if prev.get("branch") != cur.get("branch"):
                add(f"锁/{s['name']}", level,
                    f"分支漂移：锁定 {prev.get('branch')!r} → 当前 {cur.get('branch')!r}")
            if prev.get("atlas_baseline") != cur.get("atlas_baseline"):
                add(f"锁/{s['name']}", level,
                    f"成员 Atlas baseline 漂移：锁定 {str(prev.get('atlas_baseline'))[:12]} → "
                    f"当前 {str(cur.get('atlas_baseline'))[:12]}")
            if prev.get("path") != s["path"]:
                add(f"锁/{s['name']}", level,
                    f"锁中 path={prev.get('path')!r} 与清单 {s['path']!r} 不一致")
            manifest_url = s.get("url") or ""
            lock_url = prev.get("url") or ""
            if not manifest_url and not lock_url:
                if strict:
                    add(f"锁/{s['name']}", "FAIL",
                        "清单与锁都没有 url；新机器 / CI 无法 bootstrap 成员")
            elif lock_url != manifest_url:
                add(f"锁/{s['name']}", level,
                    "锁中 url 与清单不一致；重新执行 lock --update 并提交")
        for c in contracts_now:
            prev = _lock_contract(lock, c["id"])
            if prev is None:
                add(f"锁/契约 {c['id']}", level, "锁中没有该契约")
                continue
            for side in ("producer_sha256", "consumer_sha256"):
                if prev.get(side) != c[side]:
                    add(f"锁/契约 {c['id']}", level, f"{side} 漂移（需人工确认跨仓影响）")
        member_names = {m["name"] for m in data["members"]}
        contract_ids = {c["id"] for c in contracts_now}
        for lm in lock.get("members") or []:
            if lm.get("name") not in member_names:
                add("锁", level, f"锁中成员已不在清单: {lm.get('name')}")
        for lc in lock.get("contracts") or []:
            if lc.get("id") not in contract_ids:
                add("锁", level, f"锁中契约已不在清单: {lc.get('id')}")
    for c in contracts_now:
        missing = [side for side in ("producer_sha256", "consumer_sha256")
                   if c[side] == "missing"]
        if missing:
            add(f"契约 {c['id']}", level,
                "文件缺失：" + "、".join(side.replace("_sha256", "") for side in missing))

    for m in data["members"]:
        s = member_state(root, m)
        prefix = f"成员 {s['name']}"
        if not s["exists"]:
            add(prefix, level, f"路径不存在: {s['path']}")
            continue
        if s["escaped"]:
            add(prefix, level, "成员路径 resolve 后逃逸出 solution 根（symlink？）")
        if not s["git"]:
            add(prefix, level, "不是 git 仓")
        if not s["atlas_assets"]:
            add(prefix, "WARN", "未检测到 Atlas 资产（atlas.config.yaml / product/stack-profile.yaml / 结构 meta）")
        if s["ignored"]:
            add(prefix, level, "成员路径命中 ignore：" + "、".join(s["ignored"]))
        if s["tracked"]:
            add(prefix, level, f"成员路径已被 solution 仓跟踪（{len(s['tracked'])} 条，疑似 gitlink）")
        if strict and s["git"]:
            if s["dirty"] is None:
                add(prefix, "FAIL", "无法判断工作区是否 dirty（git status 失败）")
            elif s["dirty"]:
                add(prefix, "FAIL",
                    f"工作区有 {len(s['dirty'])} 处未提交改动；strict 要求成员干净")
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

    if any(r["status"] == "FAIL" for r in results):
        overall = "FAIL"
    elif any(r["status"] == "WARN" for r in results):
        overall = "WARN"
    else:
        overall = "PASS"
    return {"solution": data["solution"], "mode": data["mode"],
            "overall": overall, "checks": results, "e2e": e2e_audit}


def diff_solution(root: Path) -> dict:
    """只读对账：每个成员相对锁的提交、diffstat 与工作区改动。"""
    root = Path(root).resolve()
    data = load_manifest(root)
    lock = read_lock(root)
    members: list[dict] = []
    for m in data["members"]:
        path = (root / m["path"]).resolve()
        prev = _lock_member(lock, m["name"]) or {}
        entry = {
            "name": m["name"],
            "path": m["path"],
            "git": _is_git(path),
            "branch": None,
            "head": None,
            "locked_head": prev.get("head"),
            "lock_commit_present": None,
            "commits": [],
            "diffstat": [],
            "staged": [],
            "unstaged": [],
            "worktree": [],
            "worktree_ok": None,
        }
        if entry["git"]:
            entry["branch"] = _branch(path)
            entry["head"] = _head(path)
            locked = prev.get("head")
            if locked:
                rc, _, _ = _git(path, "cat-file", "-e", f"{locked}^{{commit}}")
                entry["lock_commit_present"] = rc == 0
                if rc == 0 and locked != entry["head"]:
                    entry["commits"] = _git_lines(
                        path, "log", "--oneline", "--max-count=50",
                        f"{locked}..HEAD") or []
                    entry["diffstat"] = _git_lines(
                        path, "diff", "--stat", f"{locked}..HEAD") or []
            entry["staged"] = _git_lines(path, "diff", "--cached", "--stat") or []
            entry["unstaged"] = _git_lines(path, "diff", "--stat") or []
            worktree = _status_lines(path)
            entry["worktree_ok"] = worktree is not None
            entry["worktree"] = worktree or []
        members.append(entry)
    return {"solution": data["solution"], "mode": data["mode"], "members": members}


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
        dirty_n = s.get("dirty_count")
        dirty = "clean" if dirty_n == 0 else (f"dirty:{dirty_n}" if dirty_n else "n/a")
        ignored = "ignored" if s.get("ignored") else "ok"
        if s.get("head_drift"):
            drift = "drift"
        elif s.get("locked_head"):
            drift = "locked"
        else:
            drift = "no-lock"
        lines.append(
            f"  {s['name']:<16} {s['path']:<20} git={str(s['git']).lower():<5} "
            f"branch={s.get('branch') or '—':<12} head={head:<12} {dirty:<8} "
            f"{drift:<7} atlas={'yes' if s['atlas_assets'] else 'no':<3} {ignored}")
    lines.append(f"lock: {'present' if data['lock']['present'] else 'missing'}"
                 + (f" ({data['lock']['locked_at']})" if data['lock'].get('locked_at') else ""))
    return "\n".join(lines)


def render_check(data: dict) -> str:
    lines = [f"solution check: {data['overall']}"]
    for r in data["checks"]:
        lines.append(f"  [{r['status']}] {r['check']}: {r['detail']}")
    return "\n".join(lines)


def render_diff(data: dict) -> str:
    lines = [f"solution diff: {data['solution']} ({data['mode']})"]
    for m in data["members"]:
        if not m["git"]:
            lines.append(f"  [{m['name']}] {m['path']}  ! 不是 git 仓")
            continue
        locked = (m.get("locked_head") or "—")[:12]
        lines.append(
            f"  [{m['name']}] {m['path']} branch={m.get('branch') or '—'} "
            f"head={(m.get('head') or '—')[:12]} locked={locked}")
        if not m.get("locked_head"):
            lines.append("    lock=—（未锁定，仅显示工作区）")
        elif m.get("lock_commit_present") is False:
            lines.append("    ! 锁中 commit 不在本地；请先 fetch 对应成员")
        elif m["commits"]:
            lines.append(f"    自锁以来提交 {len(m['commits'])} 条:")
            lines += [f"      {c}" for c in m["commits"]]
            if m["diffstat"]:
                lines.append("    自锁以来 diffstat:")
                lines += [f"      {c}" for c in m["diffstat"]]
        if m["staged"]:
            lines.append("    已暂存:")
            lines += [f"      {c}" for c in m["staged"]]
        if m["unstaged"]:
            lines.append("    未暂存:")
            lines += [f"      {c}" for c in m["unstaged"]]
        if m["worktree"]:
            lines.append(f"    工作区 {len(m['worktree'])} 项:")
            lines += [f"      {c}" for c in m["worktree"][:30]]
            if len(m["worktree"]) > 30:
                lines.append(f"      …（其余 {len(m['worktree']) - 30} 项省略）")
        if m.get("worktree_ok") is False:
            lines.append("    ! git status 失败，无法判断工作区")
        if not any((m["commits"], m["staged"], m["unstaged"], m["worktree"])):
            lines.append("    clean（相对锁无差异）")
    return "\n".join(lines)
