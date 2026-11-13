#!/usr/bin/env python3
"""atlas 共享内核 —— E2E 登录态（`.atlas-auth/`）的单一事实源。

覆盖 RFC-20261112-01 v1 的执行前预检（D）与一次性登录入口（C）所需的全部纯逻辑：

- **state 形态识别**：`fabricated`（字面量假令牌）/ `imported`（cookie 会话）/ `real`（localStorage
  真实令牌）/ `empty`。
- **过期判定按形态分治**：JWT `exp`、`meta.expires_at`、`meta.written_at + max_session_age`、
  cookie `expires`；任一信号过期 ⇒ 不可用；全部无法判定 ⇒ 不可用（fail closed）。
- **指纹**：完整有效 URL（scheme / host / port / path / 完整 query，query 排序）的 SHA-256。
- **probe**：契约见 `rings/e2e/reference.md` §7.1；必须能拒绝「HTML 200 登录页」。
- **落盘卫生**：`state.json` / `state.meta.json` 原子写 + `0600`；meta 只放哈希与指纹。

纯标准库；不读取项目业务配置之外的任何东西。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request

STATE_NAME = "state.json"
META_NAME = "state.meta.json"
FABRICATED_TOKEN = "atlas-fabricated-token"
DEFAULT_MAX_SESSION_AGE_HOURS = 8
PROBE_TIMEOUT_MAX_MS = 10000

PROBE_KEYS = ("path", "method", "expect_status", "expect_content_type", "expect_json", "timeout_ms")
PROBE_METHODS = ("GET", "POST")

# 会话类 cookie 名（命中即视作 imported 形态）：不同应用的命名收敛在这里，宁可少判不可错判。
SESSION_COOKIE_NAMES = frozenset({
    "token", "userToken", "access_token", "accessToken", "SESSION", "JSESSIONID",
    "session", "sessionid", "Amp-Organ-Id",
})
# 租户一致性（RFC-20261112-01 §4.2「probe 与实际执行不得落错租户」的静态前哨）：
# 会话里的租户 cookie 与 `app_base_url` 的 `organId` 冲突 ⇒ 服务端按会话租户鉴权，必然 401/403。
TENANT_COOKIE_NAMES = frozenset({"amp-organ-id"})
TENANT_QUERY_KEYS = ("organId",)
DEFAULT_PORTS = {"http": 80, "https": 443}


# ---------------------------------------------------------------- 路径与读写

def state_paths(root: Path | str) -> tuple[Path, Path]:
    """`(state.json, state.meta.json)` 的绝对路径（经 `_support/layout.py` 单源解析）。"""
    import sys
    sup = Path(__file__).resolve().parent
    if str(sup.parent) not in sys.path:
        sys.path.insert(0, str(sup.parent))
    from _support.layout import load_layout  # 延迟导入：本模块也被独立测试直接加载

    auth_dir = load_layout(Path(root)).e2e_auth_dir
    return auth_dir / STATE_NAME, auth_dir / META_NAME


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_write_0600(path: Path, data: bytes) -> None:
    """同目录临时文件 + `os.replace` 原子替换；文件 `0600`、目录 `0700`；失败不碰旧文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- 指纹（RFC §7）

def normalize_url(url: str, host_override: str | None = None) -> str:
    """归一化完整 URL：scheme/host 小写、默认端口省略、path 保留、query 排序（保留重复键）。

    `host_override` 只覆盖 scheme/host/port（`ATLAS_BASE_URL` 的既有口径）；path / query /
    租户参数一律以 `e2e.app_base_url` 为准。
    """
    parts = parse.urlsplit((url or "").strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if host_override:
        o = parse.urlsplit(host_override.strip())
        if o.scheme:
            scheme = o.scheme.lower()
        if o.hostname:
            host = o.hostname.lower()
        if o.port:
            port = o.port
    netloc = host
    if port and port != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    query = "&".join(sorted(p for p in parts.query.split("&") if p))
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


def fingerprint(base_url: str, host_override: str | None = None, tenant: str = "") -> str:
    """完整有效 URL（+ 生效租户）的 SHA-256。

    租户以 `app_base_url` 的 `organId` 为唯一依据（URL 已含在 query 中）；URL 未声明时退回
    state 里 `Amp-Organ-Id` 的值（`tenant` 参数由调用方按 `effective_tenant` 传入）。
    """
    if not (base_url or "").strip():
        return ""
    raw = normalize_url(base_url, host_override)
    if tenant:
        raw += f"|tenant={tenant}"
    return sha256_bytes(raw.encode("utf-8"))


# ---------------------------------------------------------------- 形态与过期

def _local_storage(state: dict) -> list[dict]:
    out: list[dict] = []
    for origin in state.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        for item in origin.get("localStorage") or []:
            if isinstance(item, dict):
                out.append(item)
    return out


def _cookies(state: dict) -> list[dict]:
    return [c for c in (state.get("cookies") or []) if isinstance(c, dict)]


def classify(state: dict | None) -> str:
    """`fabricated` / `imported` / `real` / `empty`（只按内容形态，不看 `app_login.mode`）。"""
    if not isinstance(state, dict):
        return "empty"
    values = [str(item.get("value") or "") for item in _local_storage(state)]
    if any(v == FABRICATED_TOKEN or v.startswith(FABRICATED_TOKEN + ":") for v in values):
        return "fabricated"
    cookies = _cookies(state)
    names = {str(c.get("name") or "") for c in cookies}
    if names & SESSION_COOKIE_NAMES:
        return "imported"
    if cookies and not values:
        return "imported"
    if values or cookies:
        return "real"
    return "empty"


def session_class(source: str | None) -> str | None:
    """`source` / 形态 → 归一化会话类别（RFC §6.1 映射表）。"""
    if source in ("real", "imported"):
        return "real"
    if source == "fabricated":
        return "fabricated"
    return None


def jwt_exp(token: str | None) -> float | None:
    """不验签地读 JWT `exp`；非 JWT / 无 exp ⇒ `None`。"""
    if not isinstance(token, str):
        return None
    raw = token.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    exp = data.get("exp") if isinstance(data, dict) else None
    try:
        return float(exp) if exp is not None else None
    except (TypeError, ValueError):
        return None


def _parse_ts(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def infer_expiry(state: dict, meta: dict | None) -> tuple[str, str, float | None]:
    """`(valid|expired|unknown, 可读原因, 最早过期时刻)`。

    任一信号已过期 ⇒ `expired`；无任何信号 ⇒ `unknown`（调用方 fail closed）。
    """
    now = time.time()
    signals: list[tuple[str, float]] = []
    for item in _local_storage(state):
        exp = jwt_exp(str(item.get("value") or ""))
        if exp is not None:
            signals.append((f"localStorage {item.get('name')} JWT exp", exp))
    if isinstance(meta, dict):
        exp = _parse_ts(meta.get("expires_at"))
        if exp is not None:
            signals.append(("meta.expires_at", exp))
        written = _parse_ts(meta.get("written_at"))
        if written is not None:
            hours = meta.get("max_session_age_hours") or DEFAULT_MAX_SESSION_AGE_HOURS
            try:
                hours = float(hours)
            except (TypeError, ValueError):
                hours = DEFAULT_MAX_SESSION_AGE_HOURS
            signals.append(("meta.written_at + max_session_age", written + hours * 3600))
    for cookie in _cookies(state):
        exp = cookie.get("expires")
        if isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > 0:
            signals.append((f"cookie {cookie.get('name')} expires", float(exp)))
    if not signals:
        return "unknown", "无 JWT exp / meta / cookie expires 可判定", None
    name, earliest = min(signals, key=lambda s: s[1])
    if earliest <= now:
        return "expired", f"{name} 显示已过期（{datetime.fromtimestamp(earliest)}）", earliest
    return "valid", f"{name} 未过期（{datetime.fromtimestamp(earliest)}）", earliest


# ---------------------------------------------------------------- probe（RFC §4.2）

def _as_int(value) -> int | None:
    """profile 解析器把标量读成字符串；probe 的数值字段允许 `200` / `"200"` 两种形态。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def probe_config_errors(probe) -> list[str]:
    if not isinstance(probe, dict):
        return ["probe 必须是映射（path / method / expect_status / expect_content_type / expect_json / timeout_ms）"]
    errors: list[str] = []
    unknown = [k for k in probe if k not in PROBE_KEYS]
    if unknown:
        errors.append(f"probe 未知键={unknown} 允许={list(PROBE_KEYS)}")
    path = probe.get("path")
    if not isinstance(path, str) or not path.strip().startswith("/"):
        errors.append(f"probe.path 必填且以 / 开头，得 {path!r}")
    method = str(probe.get("method") or "GET").upper()
    if method not in PROBE_METHODS:
        errors.append(f"probe.method 非法={probe.get('method')!r} 允许={list(PROBE_METHODS)}")
    status = _as_int(probe.get("expect_status", 200))
    if status is None or not (100 <= status <= 599):
        errors.append(f"probe.expect_status 应为 100..599 的整数，得 {probe.get('expect_status')!r}")
    ctype = probe.get("expect_content_type", "application/json")
    if not isinstance(ctype, str) or not ctype.strip():
        errors.append("probe.expect_content_type 应为非空字符串")
    expect_json = probe.get("expect_json")
    if expect_json is not None:
        if not isinstance(expect_json, dict):
            errors.append("probe.expect_json 应为 `JSON Pointer → 期望值` 映射")
        else:
            bad = [k for k in expect_json if not str(k).startswith("/")]
            if bad:
                errors.append(f"probe.expect_json 的键应为 JSON Pointer（以 / 开头），非法={bad}")
    timeout_ms = _as_int(probe.get("timeout_ms", 3000))
    if timeout_ms is None or not (1 <= timeout_ms <= PROBE_TIMEOUT_MAX_MS):
        errors.append(f"probe.timeout_ms 应为 1..{PROBE_TIMEOUT_MAX_MS} 的整数，得 {probe.get('timeout_ms')!r}")
    return errors


def _cookie_header(state: dict, host: str) -> str:
    pairs: list[str] = []
    for cookie in _cookies(state):
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if domain and host and not (host == domain or host.endswith("." + domain)):
            continue
        name = cookie.get("name")
        if name:
            pairs.append(f"{name}={cookie.get('value', '')}")
    return "; ".join(pairs)


def _auth_token(state: dict) -> str:
    """localStorage 里的令牌（优先 Bearer 形态）；用于 probe 的 Authorization 头。"""
    preferred = ("token", "access_token", "accessToken", "userToken")
    items = _local_storage(state)
    for name in preferred:
        for item in items:
            if str(item.get("name") or "") == name and item.get("value"):
                value = str(item["value"])
                return value if value.lower().startswith("bearer ") else f"Bearer {value}"
    for item in items:
        value = str(item.get("value") or "")
        if value and jwt_exp(value) is not None:
            return f"Bearer {value}"
    return ""


def _json_pointer(data, pointer: str):
    cur = data
    for raw in pointer.strip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            cur = cur[int(key)]
        elif isinstance(cur, dict):
            cur = cur[key]
        else:
            raise KeyError(pointer)
    return cur


def effective_tenant(state: dict, base_url: str | None) -> tuple[str, str]:
    """生效租户的唯一依据：`("url"|"cookie"|"", 值)`。

    - `app_base_url` 声明了 `organId` ⇒ **URL 参数为唯一依据**（实测请求头按 URL 判定，
      旧 cookie 不影响实际租户）；
    - URL 未声明 ⇒ 退回 state 里的 `Amp-Organ-Id` cookie。
    """
    parts = parse.urlsplit((base_url or "").strip())
    query = parse.parse_qs(parts.query)
    for key in TENANT_QUERY_KEYS:
        if query.get(key):
            return "url", str(query[key][0]).strip()
    for cookie in _cookies(state):
        if str(cookie.get("name") or "").lower() in TENANT_COOKIE_NAMES:
            value = str(cookie.get("value") or "").strip()
            if value:
                return "cookie", value
    return "", ""


def tenant_warning(state: dict, base_url: str | None) -> str:
    """URL 声明 organId 时，cookie 的 `Amp-Organ-Id` 与之不一致**只告警**（不阻断）。

    URL 未声明 organId 时不存在冲突判定——退回 cookie 作为租户依据（见 `effective_tenant`）。
    """
    source, organ = effective_tenant(state, base_url)
    if source != "url" or not organ:
        return ""
    for cookie in _cookies(state):
        if str(cookie.get("name") or "").lower() in TENANT_COOKIE_NAMES:
            value = str(cookie.get("value") or "").strip()
            if value and value != organ:
                return (f"state 的 Amp-Organ-Id={value} 与 e2e.app_base_url 的 organId={organ} "
                        "不一致；租户以 URL 参数为唯一依据（实测请求头按 URL 判定），继续执行")
    return ""


def probe_url(base_url: str, probe: dict) -> str:
    """probe 的绝对地址：同 origin，path 取 `probe.path`，query = `app_base_url` 的完整 query。"""
    base = parse.urlsplit((base_url or "").strip())
    if not base.scheme or not base.hostname:
        return ""
    parts = parse.urlsplit(str(probe.get("path") or ""))
    query = base.query
    if parts.query:
        query = _union_query(query, parts.query)
    return parse.urlunsplit((base.scheme, base.netloc, parts.path, query, ""))


def run_probe(base_url: str, probe: dict, state: dict) -> tuple[bool, str, int | None]:
    """按契约执行 probe；返回 `(ok, 脱敏原因, HTTP 状态码)`。不写任何文件。"""
    errors = probe_config_errors(probe)
    if errors:
        return False, "probe 配置非法：" + "；".join(errors), None
    base = parse.urlsplit((base_url or "").strip())
    if not base.scheme or not base.hostname:
        return False, f"app_base_url 非法：{base_url!r}", None
    url = probe_url(base_url, probe)
    headers = {"Accept": "application/json"}
    cookies = _cookie_header(state, base.hostname.lower())
    if cookies:
        headers["Cookie"] = cookies
    token = _auth_token(state)
    if token:
        headers["Authorization"] = token
    method = str(probe.get("method") or "GET").upper()
    timeout = (_as_int(probe.get("timeout_ms", 3000)) or 3000) / 1000.0
    expect_status = _as_int(probe.get("expect_status", 200)) or 200
    expect_ctype = str(probe.get("expect_content_type") or "application/json").split(";")[0].strip().lower()
    req = request.Request(url, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            body = resp.read(65536).decode("utf-8", "replace")
            final_url = resp.geturl()
    except Exception as exc:  # 网络错误 / 超时 / 4xx / 5xx 统一 fail closed
        detail = f"{type(exc).__name__}: {exc}"
        return False, f"请求失败或超时（{detail}）", None
    if status != expect_status:
        return False, f"HTTP {status} ≠ 期望 {expect_status}", status
    if ctype != expect_ctype:
        if ctype == "text/html":
            return False, f"content-type=text/html（HTML 200 登录页）≠ 期望 {expect_ctype}", status
        return False, f"content-type={ctype or '(空)'} ≠ 期望 {expect_ctype}", status
    if body.lstrip().startswith("<"):
        return False, "响应体是 HTML（登录页 / 错误页）——probe 判为不可用", status
    redirect_path = parse.urlsplit(final_url).path.lower()
    if "login" in redirect_path and "login" not in parse.urlsplit(url).path.lower():
        return False, f"被重定向到登录路径 {redirect_path}", status
    try:
        data = json.loads(body)
    except Exception:
        return False, "响应体不是合法 JSON", status
    expect_json = probe.get("expect_json") or {}
    for pointer, expected in expect_json.items():
        try:
            actual = _json_pointer(data, pointer)
        except Exception:
            return False, f"expect_json 取不到 {pointer}", status
        if not _value_matches(actual, expected):
            return False, f"expect_json {pointer}={actual!r} ≠ 期望 {expected!r}", status
    return True, f"probe ok（HTTP {status}，{ctype}）", status


def _value_matches(actual, expected) -> bool:
    if actual == expected:
        return True
    if str(actual).lower() == str(expected).lower():
        return True
    a, e = _as_int(actual), _as_int(expected)
    return a is not None and a == e


def _union_query(base_q: str, own_q: str) -> str:
    own = [p for p in own_q.split("&") if p]
    own_keys = {p.partition("=")[0] for p in own}
    base = [p for p in base_q.split("&") if p and p.partition("=")[0] not in own_keys]
    return "&".join(base + own)


# ---------------------------------------------------------------- 预检（D）

def _fail(code: str, reason: str, detail: str = "", warnings: list[str] | None = None) -> dict:
    return {"ok": False, "code": code, "reason": reason, "detail": detail,
            "warnings": warnings or []}


def _ok(reason: str, detail: str = "", warnings: list[str] | None = None) -> dict:
    return {"ok": True, "code": "", "reason": reason, "detail": detail,
            "warnings": warnings or []}


def preflight(root: Path | str, mode: str | None = None, app_base_url: str | None = None) -> dict:
    """执行前预检。`mode` / `app_base_url` 传 `None` 时从 stack-profile 读取。

    返回 `{ok, code, reason, detail}`；`ok=False` 时 `reason` 可直接展示给用户。
    """
    root = Path(root)
    if mode is None or app_base_url is None:
        profile = None
        try:
            import sys
            sup = Path(__file__).resolve().parent
            if str(sup.parent) not in sys.path:
                sys.path.insert(0, str(sup.parent))
            from _support.layout import load_layout
            from _support.stack_profile import parse_profile

            profile_path = load_layout(root).stack_profile
            profile = parse_profile(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
        except Exception:
            profile = {}
        e2e = (profile or {}).get("e2e")
        e2e = e2e if isinstance(e2e, dict) else {}
        app_login = e2e.get("app_login")
        app_login = app_login if isinstance(app_login, dict) else {}
        if mode is None:
            if not app_login:
                return _ok("未声明 e2e.app_login（不施加登录态预检）")
            mode = str(app_login.get("mode") or "real")
        if app_base_url is None:
            app_base_url = e2e.get("app_base_url")
        probe_cfg = app_login.get("probe")
    else:
        probe_cfg = None

    if mode == "none":
        return _ok("app_login.mode=none（靶场无访问门，无需登录态）")
    if mode not in ("real", "fabricated"):
        return _fail("mode_invalid", f"e2e.app_login.mode 非法：{mode!r}（允许 real / fabricated / none）")

    state_path, meta_path = state_paths(root)
    if not state_path.is_file():
        if mode == "fabricated":
            return _ok("登录态文件缺失；fabricated setup 会写入桩令牌")
        return _fail(
            "state_missing",
            f"登录态缺失：{state_path} 不存在。先运行 `atlas e2e login` 完成一次性人工登录",
            str(state_path),
        )
    state = read_json(state_path)
    if state is None:
        return _fail("state_corrupt", f"登录态文件无法解析：{state_path}（请重跑 `atlas e2e login`）")
    form = classify(state)
    if form == "empty":
        return _fail("state_empty", f"登录态文件不含会话：{state_path}（请重跑 `atlas e2e login`）")

    meta = read_json(meta_path) if meta_path.is_file() else None
    _tenant_source, _tenant_value = effective_tenant(state, app_base_url)
    _warn = tenant_warning(state, app_base_url)
    _warnings = [_warn] if _warn else []
    if isinstance(meta, dict):
        source = meta.get("source")
        if source is not None and session_class(str(source)) != session_class(form):
            return _fail(
                "source_mismatch",
                f"state 来源不符：meta.source={source!r} 与文件形态 {form!r} 不一致（拒绝执行）",
            )
        recorded = meta.get("base_url_fingerprint")
        current = fingerprint(app_base_url or "", os.environ.get("ATLAS_BASE_URL"), _tenant_value)
        if recorded and current and recorded != current:
            return _fail(
                "fingerprint_mismatch",
                f"登录态不属于当前靶场：base_url_fingerprint={str(recorded)[:12]}… ≠ "
                f"当前 {current[:12]}…（organId / host / port / path / 生效租户任一不同即不接受）",
            )
        recorded_sha = meta.get("state_sha256")
        if recorded_sha and recorded_sha != sha256_bytes(state_path.read_bytes()):
            return _fail("hash_mismatch", "登录态内容与 meta 记录的 state_sha256 不一致（拒绝执行）")

    if form == "fabricated":
        if mode == "fabricated":
            return _ok("state 为 fabricated 桩令牌（mode=fabricated，可用）", warnings=_warnings)
        return _fail(
            "fabricated_in_real",
            "state 是 fabricated 假令牌，而 app_login.mode=real：假令牌不得当作真实会话（拒绝执行）",
        )

    expiry_state, expiry_reason, _exp = infer_expiry(state, meta)
    if expiry_state == "expired":
        return _fail(
            "state_expired",
            f"会话已过期：{expiry_reason}。先运行 `atlas e2e login` 重建登录态",
            warnings=_warnings,
        )
    if expiry_state == "unknown":
        return _fail(
            "state_unknown",
            f"无法判定会话可用性：{expiry_reason}（fail closed）。先运行 `atlas e2e login` 重建登录态",
            warnings=_warnings,
        )

    if mode == "fabricated":
        # 既有 setup 的幂等守卫会保留人工录制的真实会话（§8.2）：fabricated 下不 probe，
        # 只用过期信号判定；形态不符本身不构成拒绝。
        return _ok(f"保留已有真实会话（{form}，{expiry_reason}）；mode=fabricated 不做 probe",
                   warnings=_warnings)

    errors = probe_config_errors(probe_cfg)
    if errors:
        return _fail(
            "probe_invalid",
            "app_login.probe 缺失或非法："
            + "；".join(errors)
            + "（real / imported 形态必须能判定会话可用性，禁止只查过期放行）",
            warnings=_warnings,
        )
    ok, reason, status = run_probe(app_base_url or "", probe_cfg, state)
    if not ok:
        return _fail("probe_failed", f"会话不可用：{reason}。先运行 `atlas e2e login` 重建登录态",
                     f"probe status={status}", warnings=_warnings)
    return _ok(f"会话可用：{reason}", warnings=_warnings)


# ---------------------------------------------------------------- 写入（C）

def write_state(root: Path | str, state: dict, *, source: str = "imported",
                base_url: str = "", probe: dict | None = None) -> dict:
    """原子写 `state.json` + `state.meta.json`；meta 只放来源 / 时间 / 指纹 / probe / 哈希。"""
    state_path, meta_path = state_paths(root)
    data = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    expires_at = None
    status = None
    if isinstance(probe, dict):
        status = probe.get("status")
    expiry_state, _reason, earliest = infer_expiry(state, None)
    if earliest is not None:
        expires_at = datetime.fromtimestamp(earliest).astimezone().isoformat(timespec="seconds")
    _tenant_source, _tenant_value = effective_tenant(state, base_url)
    atomic_write_0600(state_path, data)
    meta = {
        "source": source,
        "written_at": iso_now(),
        "expires_at": expires_at,
        "base_url_fingerprint": fingerprint(
            base_url, os.environ.get("ATLAS_BASE_URL"), _tenant_value),
        "probe": ({"ok": bool((probe or {}).get("ok")), "at": iso_now(), "status": status}
                  if probe is not None else None),
        "state_sha256": sha256_bytes(data),
    }
    atomic_write_0600(meta_path, (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return meta
