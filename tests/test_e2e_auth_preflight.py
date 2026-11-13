#!/usr/bin/env python3
"""E2E 登录态预检 / 一次性登录内核（RFC-20261112-01 v1：C + D）的回归测试。

覆盖范围：

* 四种状态（`none` / `fabricated` / `real` / `imported`）× 过期 / 无法判定 / 可用；
* `real` 必填 probe；probe 拒绝 HTML 200 登录页、非期望状态码、`expect_json` 不符、超时；
* `source` / `base_url_fingerprint` / `state_sha256` 一致性；
* 落盘卫生：`0600`、meta 只含哈希与指纹、原子写；
* RFC §11.2 两条 dogfood 中**可自动化**的部分：
  1. 构造「可解析但已过期」的 state ⇒ 预检拦截，执行入口不得变绿；
  2. 登录产物指纹绑定完整 `app_base_url`（含 organId）⇒ 换租户 / 换端口即拒绝。

不启动浏览器、不执行 E2E 用例。
"""
from __future__ import annotations

import base64
import http.server
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
CONSOLE = PKG_ROOT / "scripts" / "e2e_console.py"
AUTH = PKG_ROOT / "_support" / "auth_state.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("atlas_auth_state_test", AUTH)


def _b64(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def jwt(exp: float, sub: str = "tester") -> str:
    return f"{_b64({'alg': 'none'})}.{_b64({'sub': sub, 'exp': exp})}.sig"


BASE = "http://127.0.0.1:8000/?organId=7"


def make_root(tmp: Path, mode: str = "real", base_url: str = BASE, probe: str | None = None) -> Path:
    profile = f"""product: demo
e2e:
  runner: node-playwright
  scripts_dir: product/e2e/scripts
  app_base_url: {base_url}
  app_login:
    mode: {mode}
"""
    if probe:
        profile += probe
    path = tmp / "product" / "stack-profile.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile, encoding="utf-8")
    return tmp


def state_local(token: str, origin: str = "http://127.0.0.1:8000") -> dict:
    return {"cookies": [], "origins": [{"origin": origin, "localStorage": [
        {"name": "token", "value": token},
    ]}]}


def state_cookie(value: str = "abc", expires: float = -1, name: str = "token") -> dict:
    return {"cookies": [{"name": name, "value": value, "domain": "127.0.0.1",
                         "path": "/", "expires": expires, "httpOnly": True}], "origins": []}


REAL_PROBE = """    probe:
      path: /api/session
      expect_status: 200
      expect_content_type: application/json
"""


def write_state_file(root: Path, state: dict, meta: dict | None = None) -> None:
    state_path, meta_path = A.state_paths(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if meta is not None:
        meta_path.write_text(json.dumps(meta), encoding="utf-8")


# ---------------------------------------------------------------- 形态 / 过期

def test_classify_three_forms() -> None:
    assert A.classify(state_local(A.FABRICATED_TOKEN)) == "fabricated"
    assert A.classify(state_cookie()) == "imported"
    assert A.classify(state_local(jwt(time.time() + 3600))) == "real"
    assert A.classify({}) == "empty"


def test_expired_localstorage_state_blocked_dogfood() -> None:
    """dogfood ①：过期但可解析的 state 必须被拦，执行入口不得变绿。"""
    console = _load("atlas_console_preflight_test", CONSOLE)
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        write_state_file(root, state_local(jwt(time.time() - 60)))
        verdict = A.preflight(root)
        assert verdict["ok"] is False
        assert verdict["code"] == "state_expired"
        assert "过期" in verdict["reason"] and "atlas e2e login" in verdict["reason"]
        # 执行入口（控制台 Runner）在预检处即返回，不起子进程、不产生绿色结果。
        runner = console.Runner(root=root, ledger=None, timeout=10, head=False)
        ok, reason = runner.start({"id": "E2E-X", "title": "x"}, "E2E-X", 0, "x.md", BASE)
        assert ok is False and "过期" in reason
        assert runner.running is False


def test_unknown_expiry_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        write_state_file(root, state_local("opaque-token-without-exp"))
        verdict = A.preflight(root)
        assert verdict["ok"] is False and verdict["code"] == "state_unknown"


def test_imported_cookie_session_without_expiry_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        write_state_file(root, state_cookie(expires=-1))
        verdict = A.preflight(root)
        assert verdict["ok"] is False and verdict["code"] == "state_unknown"


def test_real_mode_rejects_fabricated_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        write_state_file(root, state_local(A.FABRICATED_TOKEN))
        verdict = A.preflight(root)
        assert verdict["ok"] is False and verdict["code"] == "fabricated_in_real"


def test_none_mode_needs_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), mode="none")
        assert A.preflight(root)["ok"] is True


def test_fabricated_mode_accepts_literal_and_preserves_real_session() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), mode="fabricated")
        write_state_file(root, state_local(A.FABRICATED_TOKEN))
        assert A.preflight(root)["ok"] is True
        # §8.2：setup 幂等守卫保留人工录制的真实会话；fabricated 下只查过期、不 probe。
        write_state_file(root, state_local(jwt(time.time() + 3600)))
        assert A.preflight(root)["ok"] is True
        write_state_file(root, state_local(jwt(time.time() - 60)))
        assert A.preflight(root)["code"] == "state_expired"


def test_missing_state_real_mode_asks_for_login() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        verdict = A.preflight(root)
        assert verdict["code"] == "state_missing" and "atlas e2e login" in verdict["reason"]


# ---------------------------------------------------------------- probe

class _ProbeHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默
        pass

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/html"):
            body, ctype, status = b"<html>login</html>", "text/html", 200
        elif self.path.startswith("/api/json"):
            body = json.dumps({"data": {"organId": "7", "ok": True}}).encode()
            ctype, status = "application/json", 200
        elif self.path.startswith("/api/unauth"):
            body, ctype, status = b'{"error":"unauthorized"}', "application/json", 401
        elif self.path.startswith("/api/slow"):
            time.sleep(1.2)
            body, ctype, status = b"{}", "application/json", 200
        else:
            body, ctype, status = b"{}", "application/json", 200
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def probe_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/?organId=7"
    finally:
        srv.shutdown()
        srv.server_close()


def test_probe_contract(probe_server: str) -> None:
    state = state_cookie(expires=time.time() + 3600)
    ok, reason, status = A.run_probe(probe_server, {"path": "/api/json", "expect_json": {"/data/organId": "7"}}, state)
    assert ok and status == 200, reason
    ok, reason, _ = A.run_probe(probe_server, {"path": "/api/html"}, state)
    assert not ok and "HTML" in reason
    ok, reason, _ = A.run_probe(probe_server, {"path": "/api/unauth"}, state)
    assert not ok and "401" in reason
    ok, reason, _ = A.run_probe(probe_server, {"path": "/api/json", "expect_json": {"/data/organId": "8"}}, state)
    assert not ok and "≠" in reason
    ok, reason, _ = A.run_probe(probe_server, {"path": "/api/slow", "timeout_ms": 200}, state)
    assert not ok and ("超时" in reason or "timed out" in reason.lower())


def test_probe_url_keeps_full_base_query(probe_server: str) -> None:
    url = A.probe_url(probe_server + "&x=1", {"path": "/api/json?y=2"})
    assert "organId=7" in url and "x=1" in url and "y=2" in url


def test_real_requires_probe_config() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=None)  # 无 probe
        write_state_file(root, state_local(jwt(time.time() + 3600)))
        verdict = A.preflight(root)
        assert verdict["code"] == "probe_invalid" and "probe" in verdict["reason"]


def test_probe_failure_blocks_execution(probe_server: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), base_url=probe_server, probe=REAL_PROBE)
        write_state_file(root, state_local(jwt(time.time() + 3600)))
        verdict = A.preflight(root)
        # probe_server 的 /api/session 回 JSON（handler 兜底分支）⇒ 通过
        assert verdict["ok"] is True, verdict
        # 换成 HTML 200 登录页 ⇒ 必须拒绝
        html_root = make_root(Path(td) / "h", base_url=probe_server,
                              probe="    probe:\n      path: /api/html\n")
        write_state_file(html_root, state_local(jwt(time.time() + 3600)))
        verdict = A.preflight(html_root)
        assert verdict["ok"] is False and verdict["code"] == "probe_failed"


# ---------------------------------------------------------------- 指纹 / 哈希

def test_fingerprint_covers_host_port_path_query() -> None:
    same = A.fingerprint(BASE)
    assert same == A.fingerprint(BASE)
    assert same != A.fingerprint("http://127.0.0.1:8000/?organId=8")       # 租户
    assert same != A.fingerprint("http://127.0.0.1:8001/?organId=7")       # 端口
    assert same != A.fingerprint("http://127.0.0.1:8000/other?organId=7")  # path
    assert A.normalize_url("http://LOCALHOST:80/a?b=2&a=1") == "http://localhost/a?a=1&b=2"
    # ATLAS_BASE_URL 只覆盖 host：query / path 不被冲掉
    assert A.fingerprint(BASE, "http://127.0.0.1:9000") == A.fingerprint(
        "http://127.0.0.1:9000/?organId=7")


def test_fingerprint_mismatch_rejects_wrong_tenant_dogfood() -> None:
    """dogfood ② 可自动化部分：登录产物绑定 organId，换租户即拒绝（不落错误租户）。"""
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        state = state_local(jwt(time.time() + 3600))
        A.write_state(root, state, source="imported", base_url=BASE, probe={"ok": True, "status": 200})
        wrong = make_root(Path(td) / "w", base_url="http://127.0.0.1:8000/?organId=8", probe=REAL_PROBE)
        state_path, meta_path = A.state_paths(root)
        (wrong / "product" / "e2e" / "scripts" / ".atlas-auth").mkdir(parents=True)
        (wrong / "product" / "e2e" / "scripts" / ".atlas-auth" / "state.json").write_bytes(
            state_path.read_bytes())
        (wrong / "product" / "e2e" / "scripts" / ".atlas-auth" / "state.meta.json").write_bytes(
            meta_path.read_bytes())
        verdict = A.preflight(wrong)
        assert verdict["ok"] is False and verdict["code"] == "fingerprint_mismatch"


def test_tenant_url_declared_cookie_mismatch_warns_only() -> None:
    """URL 声明 `organId` ⇒ URL 参数为唯一租户依据；cookie 不一致只告警、不阻断。

    实测请求头以 URL 参数为准，旧 cookie 不影响实际租户（4194 的 005/006 即如此跑通）。
    """
    state = state_cookie(expires=-1)
    state["origins"] = [{"origin": "http://127.0.0.1:8000", "localStorage": [
        {"name": "token", "value": jwt(time.time() + 3600)},
    ]}]
    state["cookies"].append({"name": "Amp-Organ-Id", "value": "2498172061581504512",
                             "domain": "127.0.0.1", "path": "/", "expires": -1})
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), mode="fabricated")
        write_state_file(root, state)
        verdict = A.preflight(root)
        assert verdict["ok"] is True, verdict
        assert "2498172061581504512" in " ".join(verdict["warnings"])
        assert A.effective_tenant(state, BASE) == ("url", "7")
        state["cookies"][-1]["value"] = "7"
        write_state_file(root, state)
        assert A.preflight(root)["ok"] is True
        assert A.preflight(root)["warnings"] == []


def test_tenant_falls_back_to_cookie_when_url_has_no_organ_id() -> None:
    """URL 未声明 organId ⇒ 退回 state 的 `Amp-Organ-Id` 作为租户依据，并纳入指纹。"""
    url = "http://127.0.0.1:8000/"
    state = state_cookie(expires=time.time() + 3600)
    state["origins"] = [{"origin": "http://127.0.0.1:8000", "localStorage": [
        {"name": "token", "value": jwt(time.time() + 3600)},
    ]}]
    state["cookies"].append({"name": "Amp-Organ-Id", "value": "222",
                             "domain": "127.0.0.1", "path": "/", "expires": -1})
    assert A.effective_tenant(state, url) == ("cookie", "222")
    assert A.tenant_warning(state, url) == ""
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), mode="fabricated", base_url=url)
        write_state_file(root, state)
        assert A.preflight(root)["ok"] is True
        assert A.fingerprint(url, tenant="222") != A.fingerprint(url, tenant="333")
        # 换一个租户 cookie 的 state 到同一 URL ⇒ 指纹不一致，拒绝串租户
        state["cookies"][-1]["value"] = "333"
        write_state_file(root, state)
        meta_path = A.state_paths(root)[1]
        meta_path.write_text(json.dumps({
            "source": "imported",
            "base_url_fingerprint": A.fingerprint(url, tenant="222"),
        }), encoding="utf-8")
        assert A.preflight(root)["code"] == "fingerprint_mismatch"


def test_meta_hash_and_source_mismatch() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        state = state_local(jwt(time.time() + 3600))
        write_state_file(root, state, meta={
            "source": "imported",
            "base_url_fingerprint": A.fingerprint(BASE, tenant="7"),
            "state_sha256": "deadbeef",
        })
        assert A.preflight(root)["code"] == "hash_mismatch"
        write_state_file(root, state, meta={
            "source": "fabricated",
            "base_url_fingerprint": A.fingerprint(BASE, tenant="7"),
        })
        assert A.preflight(root)["code"] == "source_mismatch"


# ---------------------------------------------------------------- 落盘卫生

def test_write_state_is_private_and_meta_only_has_hashes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td), probe=REAL_PROBE)
        state = state_local(jwt(time.time() + 3600))
        meta = A.write_state(root, state, source="imported", base_url=BASE,
                             probe={"ok": True, "status": 200})
        state_path, meta_path = A.state_paths(root)
        assert (state_path.stat().st_mode & 0o777) == 0o600
        assert (meta_path.stat().st_mode & 0o777) == 0o600
        assert set(meta) == {"source", "written_at", "expires_at", "base_url_fingerprint",
                             "probe", "state_sha256"}
        text = meta_path.read_text(encoding="utf-8")
        assert "token" not in text and state["origins"][0]["localStorage"][0]["value"] not in text
        assert meta["state_sha256"] == A.sha256_bytes(state_path.read_bytes())
