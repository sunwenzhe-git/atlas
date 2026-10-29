#!/usr/bin/env python3
"""外部 AC extractor 运行器（通用协议，不含任何具体框架知识）。

协议：`extractor_command` 是 argv 字符串（`shlex.split`，禁止 shell），Atlas 追加
`--root <项目根> --test-dir <扫描根> --json`，命令向 stdout 输出：

```json
{
  "schema_version": 1,
  "input_state": "present",
  "tests": [ { "name": "...", "file": "...", "line": 1, "acs": [], "...": "..." } ],
  "parse_errors": [],
  "scan_face": []
}
```

失败（非 0 / 超时 / 非法 JSON / schema 不合法）一律抛 `ExtractError`，由 AC 门报
`[EXTRACTOR]` FAIL；不静默降级。
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from . import ExtractResult

TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 10_000_000


class ExtractError(Exception):
    pass


def _tail(text: str, n: int = 3) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])


def run(command: str, root: Path, test_dir: Path, timeout: int = TIMEOUT_SECONDS) -> ExtractResult:
    argv = shlex.split(command)
    if not argv:
        raise ExtractError("extractor_command 为空")
    argv = argv + ["--root", str(root), "--test-dir", str(test_dir), "--json"]
    try:
        proc = subprocess.run(
            argv, cwd=str(root), capture_output=True, text=True,
            timeout=timeout, shell=False,
        )
    except FileNotFoundError as exc:
        raise ExtractError(f"命令不存在：{argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractError(f"命令超时（{timeout}s）：{argv[0]}") from exc
    except OSError as exc:
        raise ExtractError(f"命令启动失败：{exc}") from exc

    if len(proc.stdout.encode("utf-8", errors="ignore")) > MAX_OUTPUT_BYTES:
        raise ExtractError("stdout 超过 10MB 上限")
    if proc.returncode != 0:
        raise ExtractError(f"退出码 {proc.returncode}：{_tail(proc.stderr or proc.stdout)}")
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        raise ExtractError(f"stdout 非合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise ExtractError("JSON 顶层必须是对象")
    if payload.get("schema_version") != 1:
        raise ExtractError("schema_version 必须为 1")
    tests = payload.get("tests")
    if not isinstance(tests, list):
        raise ExtractError("tests 必须是数组")
    parse_errors = payload.get("parse_errors", [])
    scan_face = payload.get("scan_face", [])
    if not isinstance(parse_errors, list) or not all(isinstance(x, str) for x in parse_errors):
        raise ExtractError("parse_errors 必须是字符串数组")
    if not isinstance(scan_face, list) or not all(isinstance(x, str) for x in scan_face):
        raise ExtractError("scan_face 必须是字符串数组")
    input_state = payload.get("input_state", "present" if tests else "absent")
    if input_state not in ("present", "absent"):
        raise ExtractError("input_state 必须是 present 或 absent")
    return ExtractResult(
        tests=tests,
        parse_errors=parse_errors,
        scan_face=scan_face,
        input_state=input_state,
    )
