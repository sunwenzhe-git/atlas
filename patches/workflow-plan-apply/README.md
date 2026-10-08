# patches/workflow-plan-apply

把 `atlas apply` 挂进目标项目 `.trellis/workflow.md` 的 **Phase 1 Plan**（步骤 `#### 1.6` + 面包屑 enforcement 行），实现「需求 → 项目级资产」的单向衔接（`DESIGN.md` §7、决策 D22/D64/D66）。

## 内容

| 文件 | 作用 |
|---|---|
| `spec.json` | 补丁载荷：4 条锚点补丁（定义文件、模式、锚点、片段） |
| `apply-patches.py` | 锚点式**版本化**应用器（缺省 dry-run，`--apply` 才写；已落块正文与当前片段不符 ⇒ 整块替换） |
| `1.6-plan-apply.insert.md` | `#### 1.6 项目级资产更新` 步骤块 |
| `phase-index-1.6.insert.md` | Phase Index 的 1.6 行（人读总览） |
| `breadcrumb-planning.insert.md` | `[workflow-state:planning]` 面包屑 enforcement 行 |
| `breadcrumb-planning-inline.insert.md` | `[workflow-state:planning-inline]` 同上（Codex inline） |

## 用法

```bash
# 干跑（看将插入什么，不写文件）
python3 apply-patches.py --target <项目根>

# 应用（幂等：已打过则跳过）
python3 apply-patches.py --target <项目根> --apply
```

`install.sh` 在装配时自动以 `--apply` 调用；`--no-patch` 可跳过。

## 版本化与可重放（2026-09-27 改，原「见标记即跳过」见 `3509 §B93`）

- 只做**外科式插入 / 整块替换**，不整体覆盖 `workflow.md`。块形态：
  ```
  <!-- atlas:apply:<id>@<片段正文 sha256 前 8 位> -->
  <片段正文>
  <!-- /atlas:apply:<id> -->
  ```
  结束标记由应用器统一追加（片段文件保持纯正文）。
- 判据 = **块内正文是否仍等于当前片段**：
  | 情形 | 结果 |
  |---|---|
  | 指纹相同、有结束标记 | `skipped` |
  | 指纹不同 | `replaced`（整块替换为当前片段） |
  | 旧式块（无指纹 / 无结束标记） | `upgraded`（仅补格式）或 `replaced`（正文不符） |
- **旧式块的安全迁移**：`insert_before*` 的块紧邻锚点 ⇒ 边界 = 重算的锚点位置（精确）；`insert_after*` 且正文不符 ⇒ **报 error 且不改文件**（不做「删到下一个小节」这种会误伤内容的猜测）。
- 锚点缺失 / 歧义 / 替换未改变字节 → 该条报 `error` 且**不修改文件**，退出码 1。
- **可重放**：Trellis 升级、上游模板变更、**或本包片段自身更新**后，重跑 `install.sh`（或本应用器 `--apply`）即对齐；`install.sh` 按真实计数回报（`applied / replaced / upgraded / skipped`），**不把「跳过」报成成功**。

## 前置告警（未决 B2）

全局 `trellis` CLI 版本落后于项目 `.trellis/.version` 时，`trellis update` 的模板行为不代表项目版本，**补丁可能被 `trellis update` 冲掉**。打补丁前应先 `trellis upgrade` 升到项目版本，升级后重跑本补丁（幂等，安全）。

本工作区已于 2026-09-20 把全局 CLI 与项目 `.trellis/.version` 同步到 `0.7.0-beta.4`；**换机 / 换工作区后须重做**，见 `../../RUNBOOK.md` §0。

## 确认门

应用本补丁会改 `.trellis/workflow.md`，属 `shared/global-rules.md` §7 的确认门动作；由 `install.sh` 在用户显式安装时执行。

## 回归测试

`atlas/tests/test_apply_patches.py`：对合成 fixture 与（若指定 `ATLAS_REAL_WORKFLOW`）真实项目的 `.trellis/workflow.md`，验证「插入正确 / 版本化（指纹 + 结束标记）/ **片段改了 ⇒ 整块替换** / 旧式块迁移与安全拒绝 / 再次运行幂等 / dry-run 不写 / 锚点缺失报错且不改」。
