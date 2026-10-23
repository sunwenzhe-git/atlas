# P2 变异证明 — M136（运行事件行）

> **性质**：`research/` 非 canonical 证据存档；不进装配、不作为执行契约。
> **对象**：`scripts/atlas_check.py`（D137 / P2 观测面）。
> **日期**：2026-10-23。**协议**：四段（基线绿 → 注入红 → 逐字节还原 → 复绿），按 `scripts/mutation_proof.py:7-21`。

## 1. 变异

摘掉 `main()` 里的事件写入调用：

```diff
--- atlas_check.py（原）
+++ atlas_check.py（M136）
@@ -758,7 +758,7 @@
     if not args.fast:
         check_e2e(root, rows, args.page)

-    _write_check_event(root, rows, fast=args.fast, page=args.page)
+    pass  # M136: event write removed

     error_log = root / ".atlas" / "runs" / "last-check-error.log"
     if rows.failed:
```

## 2. 四段实测

| 阶段 | 命令 | 结果 |
|---|---|---|
| ① 基线 | `python3 -m pytest tests/test_atlas_check.py -q --no-header` | `36 passed`，rc=0 |
| ② 注入 | 同一命令（摘掉事件写入） | `2 failed, 34 passed`，rc=1 |
| ③ 还原 | 恢复 `scripts/atlas_check.py` | sha256 `b38455fc9552a7ca326f0ebf9b910997d5ff7fbfc9ae2dd938a3d4445dc8b280` 前后一致 |
| ④ 复绿 | 同一命令 | `36 passed`，rc=0 |

**注入后失败的两条钉：**

- `tests/test_atlas_check.py::test_check_events_log_records_durations_on_fail`
- `tests/test_atlas_check.py::test_check_events_log_written_on_ok_run`

**第三条钉 `test_check_events_log_write_failure_does_not_fail_check` 在变异后仍绿**——它测的是「写失败不把检查判红」，不是「事件写入被调用」；两条钉各管一件事，不重复。

## 3. 结论

- 事件写入是**接线活着**的：摘掉调用，失败轮与全绿轮的事件行钉都会红。
- 还原逐字节一致；复绿 36 passed。评审后补的 2 条钉（序列化失败不抛 / `git_dirty` 排除 `.atlas`）不依赖这条调用，故注入后仍绿；这是预期。

> **工作区并发注记（2026-10-23）**：证明时 `scripts/atlas_check.py` sha256 为 `b38455fc…`；随后并行会话改写为 `fa0458a3…`。`git diff` 里的 P2 段未变，当前 `tests/test_atlas_check.py` 36 条 + `test_canonical_consistency.py` 9 条全绿。提交前建议在独立 worktree 复核，以复核时的 sha 为准。
- 本变异只证明「事件行被调用」；不证明 `duration_ms` 的数值准确（那由 `test_check_events_log_records_durations_on_fail` 的 `isinstance(int)` 断言守形，具体数值不设硬门）。
