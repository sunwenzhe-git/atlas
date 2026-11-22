# 提案标题：机制文档机器面（`mechanism-paths:` 声明 + verify 触及/死链提示族）

> 提案编号：RFC-20261122-04
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)——tech-proposal-reviewer 对抗评审总判「修后采纳」，三 Major 全采（合流见 §5）
> 影响范围：脚本工具 (_support 执行层) | 核心契约 (shared) | docs/map 计数锚

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

单体 Architecture.md 退役后（功能逐节拆给了事实源 / ADR / 卡 / 覆盖矩阵，见 `RFC-20261122-03` 三层词汇表延伸讨论），唯一真空 = **「这个机制怎么转」的跨文件叙事**（追踪链路 / 上传流程 / 跨服务时序）：代码散在十几个文件里，读单文件拼不出全链，**无确定性抽取面**（AI 重建叙事链会幻觉），只能手写。采纳仓实践已手搓出 `docs/architecture/` 单机制多篇（实测 15 篇 6426 行），但：

1. **零机器面**：没有任何机制保证「改了机制链的人知道有一篇指南要跟改」——文档死活全靠人记；
2. **人管不了活**（维护者判定，项目实证支撑）：纪律档存活率 ≈ 0——README 徽章漂移靠改 AST 量具收口、CHANGELOG 跳号事故靠 dist-tags 机械口径收口、atlas 自身 docs/map 锚点保活门首跑即咬出真漂移。与 §15 同构：**契约义务必须指定交付面**；
3. **分界已定案**（本批前置讨论）：`product/` 是有机器门的应然资产根，无门散文不混入；机制指南是事实但非**可机器对账的事实**——它只配「机器在改动必经之路上管」的弱活形态。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
# 某采纳仓 docs/architecture/ 实测（2026-11-22）
15 篇 .md，共 6426 行，全部无 frontmatter
其中 ≥5 篇不是机制叙事（决策/方案/改动说明类混入）：
  DUBBO_REMOVAL_FINAL_PLAN.md(895 行) / 空间管理鉴权方案.md(864) /
  Temporal解析专用Worker池-设计文档.md(701) / 运行态调用量统计技术方案.md(442) /
  20261106-沙箱图片二进制上传-改动说明.md(64)

# 结构环 paths: 语义既有约束（rings/structure/reference.md）
L74  只有 tour.md / domains/*.md / conventions/*.md 带 paths:（被注入），其余 pull-only 避撞注入预算
L105 conventions 专属纪律「禁 ** 逃逸」——domain globs 合法使用 dir/**（本批词表据此定两档）

# verify 既有形态（scripts/atlas_workflow.py）
L277/L476  cmd_verify/run 链已强制非空暂存区（git diff --cached --name-only）
           ⇒ 暂存区口径是现成管道，非新能力
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

| # | 决策 | 备选与否决理由 |
|---|---|---|
| D1 | **frontmatter key 用 `mechanism-paths:`（不复用 `paths:`）** | 复用可少一个 key，但同名 key 双语义（注入面 vs 提示面）打破结构环「仅三类文件带 paths:」规范句；机械冲突虽不存在（注入器 `SPEC_DIRS` 硬编码，`docs/` 下的 key 不可能被注入），迁移 15 篇后再改 key 成本翻倍——现在改零成本（评审 m2） |
| D2 | **发现面 = 按 key 全仓扫描，不设配置项** | 限定 docs 根目录 ⇒ 新增 atlas.config.yaml 键（违零新面偏好）；key 全仓发现 = 零配置，采纳仓落点自由（评审 m2） |
| D3 | **词表两档：字面路径（优先）与 `dir/**`（叙述整棵子树时）；单星 `*` 拒收并 WARN** | 照搬结构环「禁 ** 逃逸」⇒ 跨服务篇写不出合法 paths（domain globs 本就合法用 `dir/**`，评审 F3 证伪提案初稿口径）；放任单星 ⇒ 每次改该目录全命中 = WARN 狼来了，纪律面失效且噪音外溢殃及 #71–#74 族（评审 M3） |
| D4 | **diff 口径 = 暂存区（`--no-renames`）** | 卡 paths 是 glob×glob 双重模糊；分支基点在卡账本流无定义且两次调用间口径漂移；暂存区与 verify 两个调用时机（提交前 / run 链 finish 前）语义一致（=「本次要提交的」）且管道现成（评审 F4/F7/m1）。`--no-renames` 必带：否则改名只出新路径，恰好丢旧路径那半的命中 |
| D5 | **死 paths 判据随本批同上**（globs 对 `git ls-files` 零命中 ⇒ WARN） | paths 是本批唯一的反漂移手段，paths 自身零保活 = 提案自咬（评审 M2）；纯存在性检查不碰散文，不违反「不造 validator」承诺。残余显式接受：glob 半死（子树内单文件搬走）与绕过 verify 的直推 |
| D6 | **落 `docs/` 侧自治，atlas 侧只留判据 + 登记行** | 写法纪律进 atlas 装配面 shared ⇒ 往安装快照手写内容会漂（v3 实证）；采纳仓手写区是 #71–#74 先例的纪律落点（评审 m3） |
| D7 | **不造微环、不进 `product/`、不预造锚点门** | 微环 = 为十几篇散文造整套 reference/validator/门（过度设计，评审 m5）；锚点门等真实漂移事故触发再升格（对标 docs/map 保活门形态）；无环身份恰是正解——atlas 唯一触点 = best-effort WARN，缺席即沉默 |

---

## 3. 方案 (The Design)

### 3.1 采纳仓侧：机制篇形态

```markdown
---
mechanism-paths:
  - 'platform-agent-runtime/**'
  - 'platform-console/.../TraceController.java'
---

# <机制名>（如：分布式追踪）

（叙事血肉：为什么这么串、时序意图、边界情况——只写读代码拼不出的部分）
（可核对骨架不内联：端口见 docker-compose、配置键见 .env.example，指事实源不抄数值）
```

写法纪律三条（采纳仓手写区文本，见 §6）：
1. **骨架不内联**：端口 / 配置键 / 服务清单 / 节点清单指事实源或配置真身——正文里会漂的只有叙事，机制重设计才过时，日常改代码不漂；
2. **两档 glob**：文件级精确优先；`dir/**` 仅当该篇确实叙述整棵子树，frontmatter 旁注一句理由；单星 `*` 禁用（verify 拒收出声）；
3. **一篇一机制**：过期改一篇比改一本总览便宜；AGENTS.md 留三五句入口段指向全文。

### 3.2 atlas 侧：判据（`_support/workflow_verify.py`）

`mechanism_doc_findings(root, staged_files)`，`cmd_verify` 在独立审查通过后调用（与既有两族同位），族前缀 `WARN（机制文档）:`，stderr、不改退出码：

- **触及提示**：改动文件 × 各篇 `mechanism-paths:` 交集 ⇒ 点名（命中数 + 前 3 预览——3 秒可判误报）；措辞锁 **「查看该机制篇是否跟改」**（提示语，永不使用缺陷措辞——与缺口族分族防误升格，评审 s3）；
- **疑似死 paths**：某篇全部 globs 对 `git ls-files` 全集零命中 ⇒ WARN（治 paths 自身静默死，评审 M2）；
- **单星 glob 拒收**：含 `*`（非 `**`）的条目逐条点名且不参与命中（评审 M3）；
- **`pending` 冷启动豁免**：`mechanism-paths: [pending]` 的篇不判（新篇首跑不红，评审 s1）；
- **点名上限 5**：超出汇总一行计数（评审 M3）。

发现面：文件系统遍历（剪枝点目录 / node_modules / 构建产物）只读 `.md`，按 frontmatter key 命中即机制篇（**永不入 `.atlas/spec/`**）；glob 引擎语义对齐 `workflow_context._glob_regex`（`**` 跨目录、`a/**` 允许零段）并有跨引擎一致性钉。

### 3.3 显式不做

格式 validator（散文无结构可对账）；进 `product/`（无环身份）；预造锚点门（被真实漂移事故触发后另案升格，判据 = 留样张误报率数据 + 实际漏单）。

---

## 4. 改动清单 (The Change List)

| 落点 | 改动 |
|---|---|
| `_support/workflow_verify.py` | 新增 `mechanism_doc_findings` / `discover_mechanism_docs` / `_split_mechanism_frontmatter` / `_mech_glob_regex` / `_mech_hit` / `_globs_alive` / `_tracked_files` / `_iter_repo_files` + 常量族（key / pending / CAP）；模块 docstring 补机制文档族说明 |
| `scripts/atlas_workflow.py` | `_staged_files`（`git diff --cached --name-only --no-renames`）+ `cmd_verify` 第三 findings 块（族前缀 `WARN（机制文档）:`） |
| `shared/single-source.md` | §1 新增「机制叙事文档」登记行（真相源 = 仓库自定落点 + key 发现面；永不入 `.atlas/spec/` 注记）+ §4 新增提示族条款（升格条件） |
| `docs/map/cli.md` | `atlas_workflow.py` 行数锚 590→609 + 行描述补机制文档族 |
| `tests/test_atlas_workflow.py` | +6 测试：触及提示带文件清单 / 死 paths 与活篇对照 / pending 豁免 / 单星拒收不参与命中 / CAP+1 汇总 / 跨引擎一致性 |
| `CHANGELOG.md` | [Unreleased] 条目 |
| golden | `single-source.md` 入装配集 ⇒ 按已提交树重录（worktree 隔离录制，防并行会话在飞脏树泄入） |

**采纳仓侧另批**（不随本批）：存量 15 篇分诊三步迁移（§6）。

---

## 5. 评审记录 (Review)

tech-proposal-reviewer 对抗评审（2026-11-22）：事实核查 7 条（F1 存量实为 15 篇非 10 篇 / F3 「禁 ** 逃逸」系 conventions 专属——domain 合法用 `dir/**`，提案初稿口径证伪 / F4 暂存区口径系现成管道 / F6 v3 无 `product/adr/`——分诊迁移须先立根）；三 Major 全采（M1 分诊迁移替代整批瘦身、M2 死 paths 判据、M3 两档 glob + 命中清单 + 上限）；五 Minor 全采（暂存区 + `--no-renames` / key 换名 / 纪律落采纳仓手写区 / 族前缀 / 不造微环）；三建议全采（pending 豁免 / 留样张基线 / 措辞锁提示语）。总判「修后采纳」，本文件即修后版。

---

## 6. 采纳仓落地指引（另批执行）

**分诊三步（评审 M1，防给非机制篇装报警器）**：
1. **分诊搬家零改写**：决策类 → `product/adr/`（采纳仓先立根，当前无）；方案类 → 任务卡 `solution.md` 承接或归档；改动说明类 → 归档；
2. **只给真机制叙事篇补 frontmatter**（WARN 燃料）；
3. **骨架瘦身改 opportunistic**：WARN 命中或下次触达时顺手改，不预改 6000 行散文。

**手写区纪律文本（AGENTS.md 手写区，update 推不到须人工同步）**：

```markdown
## 机制文档纪律（docs/architecture/ 单主题指南）

- **一篇一机制**：「这个机制怎么转」的跨文件叙事（追踪链路 / 上传流程 / 跨服务时序）
  才写文档；代码里查得到的事实（有哪些服务 / API 长什么样）不手写，交给结构事实。
- **骨架不内联**：端口 / 配置键 / 服务清单指事实源或配置真身（docker-compose /
  .env.example），正文只写读代码拼不出的部分（为什么这么串 / 时序意图 / 边界）。
- **每篇 frontmatter 声明 `mechanism-paths:`**（字面路径优先；`dir/**` 仅当确实叙述
  整棵子树并旁注理由；禁单星）；没接机制的新篇写 `mechanism-paths: [pending]`。
- **改机制链必看篇**：`atlas workflow verify` 会提示「本篇可能被触及」——提示不是缺陷，
  是让你 3 分钟核对该篇跟没跟上。
- **「为什么这么定」不写这里**：进 `product/adr/`（一篇一个决策）。
```

**验收留样**（评审 s2）：上线首周用真实卡各留存一份命中 / 未命中 verify 输出，作为误报率基线——升格讨论用数据不用印象。
