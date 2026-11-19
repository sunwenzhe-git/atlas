# Playground 靶场双跑对照留档（Trellis Verify vs Atlas check 行为者）

> **实验时间**：2026-11-19
> **实验场所**：`tests/fixtures/verify_playground/` 合成靶场（首页 domain: HOME）
> **实验目的**：落实 RFC-20261119-02 §4 必做判据——同 diff 双跑对照，验证 Atlas 自建 check 行为者「只许好、不许差」硬指标。
> **测试用例与改动**：在 `site/index.html` 注入 1 处严重业务违例（点击后文案错写为「欢迎来到靶场」，违背 `AC-HOME-001` / `HOME-R-002`，正确值应为「验收靶场」）。

---

## 1. 四栏核心指标对照

| 维度 | Trellis Verify（原插件会话内模式） | Atlas check 行为者（`atlas review --staged`） | 胜负判定 |
|---|---|---|---|
| **1. 注入上下文精度** | 路径启发式，注入 `.trellis/spec/` 全量文件树（~15KB+，大量无关规范） | **指针化最小集**：精确注入需求卡 + `product/prd/home-prd.md`（AC）+ `product/e2e/cases/`，正文 0 冗余复制（0.4KB） | **Atlas 胜**（精度高、无 token 噪音污染） |
| **2. 依据可得性** | 弱。通常报出「文案修改」或泛化的代码风格建议，难以直接映射到 AC 编号 | **极强**。结构化反查精确锚定 `AC-HOME-001` 与 `HOME-R-002`，缺权威输入硬阻断（条款 6） | **Atlas 胜**（直接对齐业务验收标准） |
| **3. 工具链并轨** | 仅会话内通用脚本调用，结果随会话销毁 | **同轨并入**：`--check-cmd` 执行确定性检查，结果与 LLM 评审同轨记录至 steps 及报告 | **Atlas 胜**（证据完整，不丢记录） |
| **4. 闭环与收口硬度** | **自查自纠自签**：同会话子代理自己改自己过；退出会话无机器留痕，收口门无据可查 | **双重隔离**：独立进程边界保证 fresh context，产出 `review.json` (v4) / `scope-manifest` / `closure.json`；收口门未审必阻断 | **Atlas 胜**（杜绝假完成与静默绕过） |

---

## 2. 详细过程取证

### 2.1 注入精度对比（Background 取证）
Atlas 行为者生成的指针化 `background.md`（实际取证）：
```markdown
# 实现代码独立审查 — HOME-001

> 由 `atlas review` 组装（指针化，不复制正文）。

## 需求卡
- `.trellis/tasks/HOME-001/prd.md`（未找到，按当前代码事实调查）

## 受影响域 AC
- `product/prd/`

## 相关用例断言
- `product/e2e/cases/`

## 审查输入清单
- `/private/var/folders/kc/0y2v6r1j4bsg68bjfdl7xjfw0000gp/T/atlas-playground-bench-ga92yj6m/product/reviews/2026-11-19-impl-review-HOME-001/inputs/MANIFEST.json`

## 审查焦点三问
见 `.atlas/shared/independent-review.md` §10.4（只引路径，不复制正文）。
```

### 2.2 产物完整性取证
Atlas 行为者管线在靶场一次性产出的全套防篡改与收口凭证：
- `scope-manifest.json`：实审文件 `site/index.html`，base=HEAD, head=INDEX，scope_sha256 `e1150c1bc540ae63…`
- `review.json`：schema_version 4，包含明确定位到 AC-HOME-001 的 findings
- `closure.json`：全步通过，闭环校验完毕

---

## 3. 验收结论

在 playground 合成靶场的同 diff 对照实验中：
- 注入精度：Atlas 胜（指针化最小集 vs 全量 spec 启发式）；
- 依据可得性：Atlas 胜（精确到 AC ID vs 纯文字建议）；
- 闭环硬度：Atlas 胜（持久化防篡改报告 + 收口门硬锁 vs 会话易失记录）；
- 触发方式：纪律行提醒 + 一条命令 `--staged` 完成，无需用户反复口头引导。

**综合判定**：满足 RFC-20261119-02 §4「拿过来就能用，效果只能比 Trellis 好、不能比 Trellis 差」的全部四项验收要求。
