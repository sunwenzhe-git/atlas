# patches/workflow-root-cause

把**红灯根因前置**纪律挂进目标项目 `.trellis/workflow.md` 2.2/2.3（2026-10-10，UP-192）。机制与 `workflow-plan-apply` / `workflow-skill-routing` 同构：锚点式**版本化**补丁，幂等可重放。

| 纪律 | 挂点 | 触发条件 |
|---|---|---|
| 红灯根因前置 | 2.2 末（Final pass 段与 ui-skill-note 块之后、`#### 2.3 Rollback` 之前），平台无关注 | 任何测试 / lint / 类型 / 机器门红灯 |

## 规则内容（三段）

1. **先根因后修复**：红灯修复动作之前必须先落一条根因结论（「失败在哪一层、证据是什么」，一句话，够定位即可）；没有根因结论不得动代码。
2. **改断言不走此通道**：AC 或断言本身错了 ⇒ 走 2.3 回退显式改资产并写明理由；弱化 `expected` 求绿一律禁止（对齐 `rings/e2e/reference.md` 反偏见条款：绝不改用例迁就实现）。
3. **二次未绿停手**：同一红灯修到第二次仍未绿 ⇒ 停止试错，转 `trellis-break-loop`（3.2）分类根因后再继续（把 3.2 的「反复修才触发」前移到第二次就触发）。

## 为什么挂 workflow.md

试错性乱改（加兜底吞错、放宽断言、盲改凑绿）发生在 Execute / check 的文件操作深处，没有任何事件会触发技能重评估；workflow 祈使步骤是实测最硬的软机制（与 workflow-skill-routing README 同一判据）。

## 内容

| 文件 | 作用 |
|---|---|
| `spec.json` | 补丁载荷：1 条锚点补丁（UP-192） |
| `apply-patches.py` | 锚点式版本化应用器（自包含拷贝，三处同步） |
| `root-cause-first-red.insert.md` | 2.2 末平台无关注——红灯根因前置纪律载体 |

## 用法

```bash
# 干跑（看将插入什么，不写文件）
python3 apply-patches.py --target <项目根>

# 应用（幂等：已打过则 skipped）
python3 apply-patches.py --target <项目根> --apply
```

## id 纪律

补丁 `id` 一经落地**不得改名**：workflow.md 里的版本化块按 id 寻址，id 变更会让已落块失去指纹追踪、重放变成重复插入。内容修改 = 改片段文件 + 重放（指纹不同 ⇒ 整块替换）。
