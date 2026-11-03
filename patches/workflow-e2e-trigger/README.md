# workflow-e2e-trigger — E2E 触发段挂载补丁

把「实现完成 → 用例执行 → 人 review」的触发点挂进 Trellis 的 `.trellis/workflow.md`
（`RFC-20261103-07`）。**只挂触发点，不新增门。**

## 落地内容

| 补丁 id | 落点 | 作用 |
|---|---|---|
| `e2e-trigger-before-final-pass` | `**Final pass (before Phase 3.4 commit)**` 之前 | 最后一轮质量检查之前执行 `e2e_trigger.py --run`（归因 + 委托既有执行器） |
| `e2e-console-at-3-5` | `#### 3.5 Wrap-up reminder` 之后 | 收尾给出控制台命令（人工 review），不自动启动 |
| `e2e-breadcrumb-in-progress` | `[/workflow-state:in_progress]` 之前 | 执行期每轮提醒触发段 |
| `e2e-breadcrumb-in-progress-inline` | `[/workflow-state:in_progress-inline]` 之前 | inline 变体同样提醒 |

## 边界

- 触发器**不**调用 `gen_e2e_scripts.py --apply`：生成前必须有 E2E 环独立审查报告（`rings/e2e/reference.md` §12）。
- 未就绪（靶场未声明 / 脚本未生成 / 不可达 / 未接入）只打印待办并 `exit 0`，**不阻塞**收尾。
- 真跑仍由 `atlas_check` / `atlas_verify` 判定；控制台仍由人启动。

## 应用与幂等

```bash
python3 patches/workflow-e2e-trigger/apply-patches.py --target <项目根> --apply
```

块形态与判据同 `patches/workflow-plan-apply/`：带正文指纹的开始/结束标记；正文一致 ⇒ `skipped`，
不一致 ⇒ 整块替换；旧式块 ⇒ 升级。Trellis 升级后重跑安装即对齐。

**锚点漂移**：`**Final pass (before Phase 3.4 commit)**` 与 `#### 3.5 Wrap-up reminder` 来自 Trellis 模板；
miss 时安装器只 `WARN`，此时两个面包屑补丁仍提供常驻提醒，需人工核对后更新 `spec.json` 的锚点。
