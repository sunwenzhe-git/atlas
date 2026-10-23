# P5-A 变异证明 — M137（`validate_testids` 剥注释复用）

> **性质**：`research/` 非 canonical 证据存档；不进装配、不作为执行契约。
> **对象**：`validators/validate_testids.py`（D141 / P5-A 性能优化）。
> **日期**：2026-10-23。**协议**：四段（基线绿 → 注入红 → 逐字节还原 → 复绿），按 `scripts/mutation_proof.py:7-21`。

## 1. 变异

还原第二次 `strip_comments` 调用（即撤销 P5-A），让每个源文件重新剥两次注释：

```diff
--- validate_testids.py（原）
+++ validate_testids.py（M137）
@@ -396,11 +396,10 @@
-    # 剥注释只做一次：第一次循环就把 clean 文本存进 texts，第二次循环复用。
-    # 此前每文件调两次 strip_comments（同一份文本，纯重复）；输出逐字不变，实测省约 110ms/14%（P5-A，D141）。
-    texts = [(f, strip_comments(f.read_text(encoding="utf-8", errors="ignore"))) for f in files]
+    texts = [(f, f.read_text(encoding="utf-8", errors="ignore")) for f in files]
     all_tids: set[str] = set()
-    for _f, clean in texts:
+    for _f, text in texts:
+        clean = strip_comments(text)
         all_tids.update(TESTID_ATTR.findall(clean))
@@ -413,7 +412,8 @@
-    for f, clean_text in texts:
+    for f, text in texts:
+        clean_text = strip_comments(text)
         rel = f.relative_to(root).as_posix()
```

## 2. 四段实测

| 阶段 | 命令 | 结果 |
|---|---|---|
| ① 基线 | `python3 -m pytest tests/test_validators.py -q --no-header` | `140 passed`，rc=0 |
| ② 注入 | 同一命令（还原二次调用） | `1 failed, 139 passed`，rc=1 |
| ③ 还原 | 恢复 `validators/validate_testids.py` | sha256 `81ae61b4fb5f90123550b61827f5c52dc2714afc710444dd3e0f4be037d7b31e` 前后一致 |
| ④ 复绿 | 同一命令 | `140 passed`，rc=0 |

**注入后失败的一条钉：** `tests/test_validators.py::test_validate_testids_strip_comments_once_per_file`。

## 3. 结论

- 调用次数钉能咬：二次调用恢复后，每文件调用数从 1 变 2，测试立即红。
- 还原逐字节一致；复绿 140 passed。
- 这条钉只守「每文件只剥一次」这一结构性质；判据语义仍由既有的 `test_validate_testids_strip_comments` / F22 抽取测试守。
- 性能收益来自隔离副本的 5 轮交错实测（796.5ms → 686.4ms，-110.1ms / -13.8%，输出逐字不变），不是从这条变异推出来的。

> **工作区并发注记（2026-10-23）**：本证明运行期间，并行会话在改写同一工作区；证明时文件哈希为 `81ae61b4…`，并发期间又观测到 `4b76c747…`。两者 `git diff` 都是同一份 10 行 P5-A 改动，且两版 `tests/test_validators.py` 均 **140 passed**。提交前建议在独立 worktree 复核一次，以复核时的 sha 为准，避免并行改动混入。
