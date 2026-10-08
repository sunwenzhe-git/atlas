# atlas 共享契约 — 知识库（Obsidian）维护

> atlas 三环（`structure` / `prd` / `e2e`）与 `apply` **共同遵守**的知识库同步规则（原型环已移除，2026-09-27，`3508 §92`）。
> 正文只此一份；各环按路径引用 `.atlas/shared/knowledge.md`，**不得在环契约里复制**。
> 本文件是**契约**；具体 vault 路径与作用域由目标项目的 `product/stack-profile.yaml` 的 `knowledge` 段提供。

## 1. 定位

知识库（Obsidian vault）保存 atlas 的**设计依据与讨论**——「为什么这么定」。
它与产物**分层**，不重复产物正文：

| 层 | 落点 | 回答的问题 |
|---|---|---|
| 产物（应然/实然） | 目标项目内（`product/`、`.trellis/spec/`） | 是什么、长什么样、怎么算做对了 |
| 设计依据 | 知识库（vault 内单一 atlas 目录） | 为什么这么定、备选与被否原因、用户纠正 |

**权威顺序**：产物契约（`shared/` + `rings/*/reference.md`）> `DESIGN.md` > 知识库。
冲突时以契约为准，并顺手修正另两处。

## 2. 声明（stack-profile）

知识库是**可选增强**：未声明时本契约整体降级为「跳过」，**不阻断任何环**。

```yaml
knowledge:
  tool: open-zk-kb        # 固定；atlas 依赖该 MCP 写入/检索
  vault: <vault 根绝对路径>
  dir: atlas              # vault 内**唯一**的 atlas 设计目录（相对 vault 根）
  project: <open-zk-kb 的 project 作用域，可选>
```

- **唯一目录**：所有项目、所有环的 atlas 设计文档都写入同一个 `dir`，**不按项目分目录**。
- 该目录与各项目的产物目录**分离**；项目产物不进 vault。

## 3. 工具（硬依赖）与双通道（2026-09-29 修订，`3509 §B116` 拍板）

**双通道，按 note 形态选**——两者都是正道，不存在「违规手写」：

| 通道 | 适用 | 收口义务 |
|---|---|---|
| **MCP**（`knowledge-store` / `knowledge-get`） | **短 note** 的创建与整篇更新（`disposition` 显式 create/update/skip；先 `search` 防重、`get` 后再 `store`） | `knowledge-context` 确认已索引 |
| **直接编辑文件** | **长 note**（台账 / 纪要 / 环文档，数百行起）的定点与批量修订——MCP 只能整篇重写，做不了定点改 | 跑 `bun atlas/scripts/kb_index_refresh.mjs` + `bun atlas/scripts/kb_projection_check.mjs`（投影 ⇔ 本体对账必须绿；open-zk-kb 无文件监听，手改不会被重索引，2026-09-29 实证 `3508 §135`） |

| 工具 | 用途 |
|---|---|
| `knowledge-store` | 短 note 新建 / 整篇更新（`disposition` 显式 create/update/skip） |
| `knowledge-get` | 按 ID 精确读取既有 note（改前先读） |
| `knowledge-search` | 按主题检索，避免重复建 note |
| `knowledge-context` | 收口自检：确认新 note 已被索引 |

- `knowledge-store` 缺失或不可用时：短 note 改走直接编辑通道并履行上表对账义务，同时在产出说明里提示本机 MCP 不可用。
- **禁止**用 `knowledge-store` 另建与 vault `dir/` 下既有 note 重复的副本（双份漂移）——与通道选择无关，始终适用。

## 4. 写什么 / 不写什么

**写**（持久的设计与依据）：

- 新增/修改任何一环、适配器、校验器、模板的**设计**；
- **决策**（含被否方案与理由）；
- **用户的纠正**（必须记，单独成条或进讨论纪要）；
- **跨环未决问题**的登记与关闭。

**不写**：

- 进度、完成汇报、临时调研、会话流水；
- 产物正文（正文在项目内；知识库只做**引用/索引**）；
- 密钥、令牌。

## 5. 何时写（触发点）

**收口必做**，且同一轮内完成：

| 触发 | 动作 |
|---|---|
| 任一环 / `apply` 收口 | 本轮新增或变更的设计与决策写入 note；未决变化更新未决清单 note |
| 新增/修改契约、模板、校验器 | 更新对应环 note + 决策记录 note + 讨论纪要 note |
| 用户纠正 | 记入讨论纪要 note（置顶「关键纠正」区） |
| 新增环 / 新增文档 | 更新总览 note 的「文档地图」+ 讨论纪要 |

## 6. Note 契约（照抄，否则索引会丢）

- **路径**：`<vault>/<dir>/<16位ID>-<ascii-slug>.md`
- **ID**：`YYYYMMDDHHMMSS` + 2 位序号（同秒内递增）。
- **frontmatter**：

```yaml
---
id: <16位ID>
title: <中文标题>
kind: reference
status: permanent
lifecycle: living
type: atomic
tags:
  - atlas
  - <主题标签>
created: YYYY-MM-DD
updated: YYYY-MM-DD
tagline: <一句话，显示在目录表里>
summary: <一两句展开>
source_type: manual
up: "[[<dir>/<总览 note 的路径>|<总览标题>]]"
aliases:
  - <中文别名>
---

# <标题>

> <tagline>

<正文>

## Guidance

<给未来 agent 的祈使句：动手前先读什么、什么不能做>
```

- **总览 note 唯一**：每个 `dir` 有一份总览，承载「文档地图」；其余 note 的 `up:` 指向它。
- **作用域 = 全局**：`dir` 下所有 note 标 `scope:global`、**不带任何 `project:*` 标签**（atlas 设计跨项目共用）。缺 `project:*` 又不带 `scope:global` 的 note 会被判为「未分类」而不可见，禁止。
- **更新而非新建**：同主题先 `knowledge-search`，命中则 `knowledge-get` 后 `knowledge-store(disposition: update)`；禁止建重复 note。

## 7. 文档映射（仓库 ↔ 知识库）

契约变更时**两处都改**，映射表登记在总览 note 内：

| 仓库（canonical） | 知识库 note |
|---|---|
| `DESIGN.md` | 总览 note + 决策记录 note |
| `shared/*.md` | 各环 note + 分发 note |
| `rings/<ring>/reference.md` + `skills/atlas-<ring>/SKILL.md` | 对应环 note |
| `apply/reference.md` | apply 环 note |
| `README.md` / `install.sh` / `templates/` / `adapters/` / `validators/` | 分发 note |
| 每轮头脑风暴的问答 | 讨论纪要 note |
| 跨环未决问题与建议开工顺序 | 未决问题 note |

## 8. 收口自检

- `knowledge-context(project: <project>)` 能看到本 `dir` 下的 note（数量与新增一致）。
- **投影对账**（2026-09-29 起）：`bun atlas/scripts/kb_projection_check.mjs` 退出码 0——直接编辑通道后**必跑**（登记于 `shared/gates.md` 2.1）。
- 无重复 note、无断链（`knowledge-maintain(action: "link-health")` 无新增告警）。
- 契约变更已在仓库与知识库**两处**同步。

## 9. 台账卷（未决 / 已决归档）

跨环未决问题与决策登记在 vault 里，**分两卷**（`3509 §97` 定形）：

| 卷 | 角色声明（正文行，必填） | 内容 |
|---|---|---|
| 未决卷 | `> 卷角色：未决` | **只放开着的条目** |
| 已决归档卷 | `> 卷角色：已决归档` | 已解决条目 + 解决方式 + 取证（append-only） |

- **卷角色由卷自身声明**（**正文行**，不是 frontmatter —— frontmatter 可能被工具重写）：`validators/validate_ledger.py` 据此判断「哪些条目仍开着」；未声明的卷**不进台账统计**（标题含「清单 / 台账」却缺声明的记 WARN，其余不报——否则讨论纪要引用 `| B31 | … |` 会永久 WARN）。
- **编号纪律（机器判据）**：`B<NN>` 在**两卷间唯一**（`max+1` 只管本卷 ⇒ 跨卷必撞，实测发生过，`3509 §B94`）；**新条目一律用轮次前缀形态 `B<纪要轮次>-<序号>`**（如 `B139-1`；2026-09-29 `§B94` 发号侧落地——发号 = 当前纪要轮次 + 序号，无需中心分配，撞号检测按**整串**唯一、两种形态通吃），裸 `B<NN>` 为遗留形态、不再新增；纪要卷 `## <N>.` 在**一卷内唯一**（第二次出现用**子号** `92.1`，先例 `91.1`/`91.2`）。
- **发号机制（`§B94` 半条清偿，2026-10-06）**：取号前跑 `python3 .atlas/scripts/issue_ledger_ids.py --root .` —— 读**当前**文件尾求各号空间真 max（纪要轮次含历史卷 / 台账号 / 回灌批号 / 项目侧 P 号），`--check <候选>` 按**整串**精确核对占用（`B139` ≠ `B139-1`；正文引用也算占用，保守侧）。动机 = 三次实测：模式匹配 grep 有盲区（`14[89]` 漏 146/147 段）、并发会话各取一次（2026-10-04 两会话同写 `## 179.`）、正文举例污染 max。**只读直查，不是互斥锁**：检查与写入间的并发窗口由「落笔当轮取号 + `validate_ledger` 撞号门事后必咬 ⇒ 后写者让号」兜底。
- **条目 schema（八字段，`3508 §97` 定形；机器判据 2026-10-06 落，`§B112` 残留清偿）**：未决条目八字段 = **ID / 类型 / 优先级 / 问题 / 选项 / 推荐+理由 / 影响 / 状态**。现表形态已承载其余六项（ID / 问题 / 影响 列 + 状态 = 卷角色 + 选项与推荐并入建议动作列），**类型与优先级以行内标签承载**：条目行内必须含 `类型：`（四闭集：产品裁定 / 流水线决策 / 台账处置 / 确认门）与 `优先级：P0|P1|P2`（P0 阻塞中 / P1 下批 / P2 随时）。`validate_ledger.py` 对未决卷逐条判缺（缺 ⇒ WARN 列名），待裁决汇总按优先级分行计数（`§97` ④ 裁决面「报告先行」：`未决 N 项：P0×M、P1×K…`）。标签取值对不对（语义）归人终审。
- **收口时跑**：`python3 .atlas/validators/validate_ledger.py --root .` —— 输出「未决 N 项 / 疑似已落地 M 项（机器缩围、人终审）/ 撞号 K 处」。
- **「疑似已落地」不是结论**：它只按「未决条目里引用的**包内路径**是否已存在」缩围（项目侧路径引用只计数不列名）；**是否真落地仍由人逐条读**（`3509 §97` 收口 ③：机器缩围 + 人终审）。
- **项目产物侧条目不进全局台账**（2026-09-29 补，`3507 AO`）：条目若属某项目的**产物补齐 / 实现 backlog**（判据：不是 atlas 契约缺口），登记在该项目**仓库内**的项目侧台账（先例：Polyvoice `product/issues.md`），不进本 `dir` 的全局台账——全局台账只留契约缺口与治理项。迁移时保留原条号、原位留指针（先例：`3509 §B37`/`§B60`/`§B61`/`§B97`/`§D`/`§E` → `product/issues.md`）。

## Guidance

动手前先读总览 note + 未决问题 note；改契约先改仓库 canonical，再同一轮写知识库；**不要**用 `knowledge-store` 建与 `dir` 下重复的 note，**不要**跑会打乱 `dir` 布局的批量迁移。
