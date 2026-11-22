# 调研备忘：alibaba/open-code-review 混合评审管线机制深度评估（Atlas 吸收分析）

> 类型：外部机制调研备忘（非 RFC，不立项不落刀；结论三段式见 §4–§6）
> 来源仓：[alibaba/open-code-review](https://github.com/alibaba/open-code-review)（Go，Apache-2.0，55,245★，官网 open-codereview.ai）
> 快照：`main` @ 2026-11-22（git tree `284ff013f0705ae6`，tree 非截断，1,291 blobs；文件行号以该 tree 为准）
> 访问通道与限制：api.github.com contents 端点（raw Accept 头）；raw.githubusercontent.com / jsdelivr 本网络 TLS 不通（exit 35）；HuggingFace 数据集卡两次超时不可达；仓库 403 限流（共享 NAT IP）⇒ `imgs/benchmark-en.png`（基准精确数值图）未取得，基准结论以 README 文字口径为准、标注「官方口径未独立复核」。
> 关联：QUEUE.md 观察室 65 行（2026-11-22 Trending 收录）；D203/RFC-20261119-02 check 行为者（`scripts/atlas_review.py`）；D204 atlas workflow（`scripts/atlas_workflow.py`）；D206 atlas-ablate 目标函数；自感知上报族「判据可被形态满足」；atlas-playground T1–T5（`proposals/BENCHMARK-20261119-02/03`）。

---

## 1. 病灶诊断：与 Atlas 自感知上报族逐字同构（原文核实）

README.md:75-81 三痛点 + 根因判定，原文：

- **Incomplete coverage** — "On larger changesets, agents tend to 'cut corners,' selectively reviewing only some files and missing others."
- **Position drift** — "Reported issues frequently don't match the actual code location, with line numbers or file references drifting off target."
- **Unstable quality** — "Natural-language-driven Skills are hard to debug, and review quality fluctuates significantly with minor prompt variations."
- 根因：**"a purely language-driven architecture lacks hard constraints on the review process"**（README.md:81）——即 Atlas「判据可被形态满足」族（`duty-review/bugs.md` 自感知上报段，8 案同根归纳）的英文原版。

## 2. 架构切分：确定性管道 × Agent（Q1 对照 D203）

官方架构文档 `pages/src/content/docs/en/architecture.md`（468 行）给出完整管线，逐段核对源码后切分如下。

### 2.1 走确定性管道的（"must not go wrong" 的全归工程逻辑）

| 环节 | 实现 | 出处 |
|---|---|---|
| diff 解析 | 三模式 Provider（Workspace/Commit/Range=merge-base），`ParseHunks` 把 unified diff 解成 `Hunk{OldStart,NewStart,Lines[]}` 结构体，行号由 hunk 头计数器**算出**而非采信 LLM | `internal/diff/hunk.go:36-66`、`internal/diff/git.go`（architecture.md:39-55） |
| 文件选择（五门+二查） | `selectFiles` 纯函数：binary→secret 路径（压用户规则之上）→user_exclude→user_include→扩展白名单→内置排除路径（test 文件/node_modules/vendor 等），再加 deleted 与 too_large（单文件 diff 超 `max_tokens`×80%）逐文件裁定，**每文件带排除理由码** | `internal/agent/selection.go:43-102`；architecture.md:57-99 |
| preview≡真跑单一事实源 | 注释明言："`It is pure — no output, no mutation, no git or LLM access — so `--preview` and the real run consume the same answer instead of each deriving their own, **which is what let the two drift (#782)**`" | `internal/agent/selection.go:37-42` |
| 语义分组的三道确定性阀 | LLM 分组（只喂文件元数据不喂 diff）后强制：≤10 文件/束拆分、束级 token 预算超限回拆单文件、漏分配文件单开组；任何解析失败整体回退 per-file | `internal/agent/grouping.go:22,106,286-320,345-367` |
| 小变更集不花 LLM 分组 | `GroupingPlan` 按文件数+churn 阈值先行裁定，低于阈值本地分束（bundle-all 或 per-file） | `internal/agent/grouping.go:88-94` |
| 规则匹配 | 按路径 glob 四层链（system 层 `system_rules.json` + 用户层，首中即停），按文件注入命中规则文本到 `{{system_rule}}`；`.m` 歧义（MATLAB/ObjC）由只装饰 system 层的 sniffer 内容嗅探消歧——用户规则永远压过嗅探 | `internal/config/rules/system_rules.go`、`internal/config/rules/sniffer.go:26-51` |
| token 预算阀 | 发请求前 fail-fast：消息超 `max_tokens`×80% ⇒ 整组跳过并记 warning（防万行 lockfile）；selectFiles 的 too_large；grouping 的 enforceGroupTokenBudget | architecture.md:322-340 |
| 内存压缩三区 | 60% 阈值起后台异步压缩、80% 同步压缩；frozen(前 2 条)+compress(摘要回填)+active(K 轮)；重建结果**必须严格变小**，模板缺失/空摘要/不缩反原样保史不丢消息；压缩失败停 `StopCompression` 不静默丢弃 | `internal/llmloop/compression.go`、architecture.md:212-291 |
| LLM 输出形态治理 | 评论文目/severity 封闭枚举 + 归一化兜底（未知→other/low）；`comments` 传成 JSON 字符串的 schema 违规先走**确定性修复**（`comment_args_repair.go`），修复接受条件=「无 recovered 值截断」；解析失败报错措辞刻意保留 "invalid character" 原文，因为它能驱动模型重发整批 | `internal/tool/code_comment.go:16-48,101-168`、`internal/tool/comment_args_repair.go` |

### 2.2 留给 LLM 的（只留动态决策与动态上下文）

- **Plan 阶段**（可选，行数阈值 50/组阈值 100 触发）：一次调用、**不带 Tools 字段**（模型在规划期无法调工具），产出 checklist 注入 `{{plan_guidance}}`（architecture.md:134-160）。
- **主环**：每束一个子 agent，≤100 轮（`MAX_TOOL_REQUEST_TIMES`），5 个出口（task_done/轮尽/连续 3 轮空结果/cancel/压缩塞不下），空轮有 nudge；`--effort` 1/2/3 轮复评，**round 2+ 不带 plan**（"a plan tends to act as a coverage ceiling once the obvious issues are found"）且注入 `{{confirmed_comments}}` 防重复报告，无新发现即早停（architecture.md:164-210）。
- **场景调优工具集**：`code_search / file_read / file_read_diff / file_find`（规划期以纯文本呈现）+ 主环加 `task_done / code_comment`（architecture.md:155-156,344-353）——自生产数据蒸馏，非通用工具箱（README.md:101）。

### 2.3 与 D203 的对照结论

Atlas `scripts/atlas_review.py` 已对齐的：确定性编排链（toolchain/preview/scope/converter/validator/closure 七步，`atlas_review.py:2-8,347-552`）、指针化 background（`atlas_review.py:150-181`）、coverage 契约 selected/completed/failed/waived/reused（`atlas_review.py:230-234`）、会话执行器探索预算 ≤N+8（`atlas_review.py:245-250`）、scope manifest 封口 + 跨轮闭环（`atlas_review.py:468-491,530-552`）。**结构性差距在行级定位与反思过滤两环（§3、§4），Atlas 侧目前全部交给 LLM 自报行号。**

## 3. 行级定位机制（Q2：怎么治 Position drift）

四层漏斗，每层确定性优先、LLM 只做最后兜底，且**永不采信 LLM 报的行号**：

1. **L1 hunk 滑窗匹配**：评论必带 `existing_code`（评论目标代码的逐字摘录，`code_comment` 工具字段，`internal/tool/code_comment.go:142-144`）；归一化（trim、剥 `+/-` 标记、跳空行）后在 hunk 新侧（context+added，行号由 hunk 头计数器推算）连续匹配，再试去空行新侧，最后老侧——老侧行号是旧文件坐标系，刻意排最后且不重试（`internal/diff/resolver.go:155-194,199-247`）。
2. **L2 全文回退**：hunk 匹配失败滑窗扫新文件全文（空行跳过连续匹配，`resolver.go:251-296`）。
3. **跨文件重挂**：`RelocateAcrossFiles` 纯串匹配**全部在内存的 diff**（零模型调用），处理「声明/实现分离」（评论挂在头文件、代码在源文件）；**唯一命中才改挂**（Path/StartLine/EndLine 三者一起动），零命中或多命中一律拒绝——"guessing between them would trade one wrong location for another"（`resolver.go:76-140`，注释是全仓最精彩的设计论证）。
4. **LLM 重定位兜底**：仅当文本匹配失败才发起一次 `RE_LOCATION_TASK` 调用，提示词只要求「从 diff 里**逐字复制**最小连续行段、只输出 fenced code block」（`internal/config/template/prompts/re_location_task_system.md` / `re_location_task_user.md`），产出回灌 L1 重新匹配；**仍失败则还原原 snippet 放弃**（`internal/diff/relocation.go:83-95`）——fail-closed，宁缺毋错锚。
5. **硬校验兜底**：LLM 响应 JSON schema 校验 + **行号对实际 diff 区间做越界检查**（`ASSURANCE_CASE.md` T6： "line number bounds checking against actual diff ranges"）。

匹配彻底失败的评论行号置 0，0 = 「未锚定」的显式信号交人工定位（architecture.md:299-304）。**注释形态里没有「猜一个行号」这条路。**

## 4. 质量基准方法论（Q3）与 token 1/9（Q4）

### 4.1 基准（官方口径，未独立复核——见备忘头通道限制）

README.md:55-59：50 热门开源仓 × 200 真实 PR × 10 语言，80+ 资深工程师交叉标注 **1,505 条 ground-truth issues**；同底座模型下 vs Claude Code：Precision/F1 显著更高、**token 仅 ~1/9**、recall 刻意更低（"a deliberate trade-off favoring precision over noise"）。数据集开源在 HF `Alibaba-Aone/aacr-bench`（本网络不可达，方法学细节未取得）。旁证自洽：ROADMAP.md:55-60 计划中的 **Ultra Mode**（高 recall 档，明言换 token 与时延）证明 P/R 权衡是**设计出来的轴**、两档可切，不是宣传口径。

### 4.2 precision 压 recall 的操作化位置（可直接借的思维件）

- 主提示词明令："Avoid commenting on correct code or unchanged code / deleted code"、"comments must address code within `<review_files>`"（`internal/config/template/prompts/main_task_system.md:10-19`）。
- **反思过滤模块（REVIEW_FILTER_TASK）**：主环结束后一轮事实核查，提示词的不对称代价论是精髓——"Keeping an incorrect comment costs a reviewer a few seconds of attention. Removing a correct comment silently destroys a real finding" ⇒ **默认全通过**，只允许两类可证伪移除（A=目标代码不在主文件；B=某 diff 行字面反驳中心论点），另有五类「保护科目否决」（内存安全/并发/链接一致性/行为兼容变更/未用参数——"On a protected subject you do not get to be confident"），五步顺序执行且步 4 需要一步以上推理即放行（`prompts/review_filter_task_system.md` + `review_filter_task_user.md`）。
- 反思过滤只对**事实性错误**动刀、明确不裁「价值/优先级」（filter 提示词 §Not grounds）——价值判断留给人，机器只消假阳。

### 4.3 token 1/9 来源拆解（对照 D206 目标函数）

按管线逐段归因（每条均有源码出处）：

1. **输入侧裁剪**：五门+too_large 把 binary/依赖/测试/超大 diff 挡在模型外（selection.go）——通用 agent 无此闸；
2. **束共享上下文**：相关文件一束一对话，prompt 固定开销与交叉推理一次付清（grouping.go；bundle 代价已在 :121-129 注释如实记账：预算前瞻变整束 all-or-nothing + 估算对束多收费）；
3. **规则按文件命中注入**：`{{system_rule}}` 只注入命中规则文本而非全量 skill/规范（system_rules.go + main_task_user.md:17）；
4. **分组响应按索引不按路径**："an index costs a few output tokens where a path costs its full length"（grouping.go:41-49）；
5. **plan 无工具 + 小 JSON 输出**；主环轮数/预算双上界 + 无新发现早停 + confirmed_comments 防重复报告；
6. **压缩三区**把长循环 prompt 钉在 200k 输入顶内（compression.go）；
7. **工具集收敛为 6 个**（场景蒸馏）——工具定义 token 与走错路的双省；
8. **成本可估**：`estimate.go` 固定开销 2000/轮均值 7/轮输出 700 三常量做量级估算（明言是 floor，真值以 API usage 为准），behaviortask 预算客户端在 provider 不回 usage 时**本地 token 计数兜底**（`behaviortask/budget.go:70-90`，嵌 cl100k tiktoken 数据）——**token 计量本身是机制不是事后账单**。

与 D206「最快最省 token 达最佳效果」的关系：OCR 的省 token 手段几乎全部是**机制减法**（裁剪/收敛/上界/早停），与 atlas-ablate 的减法引擎同族；其差异在 OCR 把减法写死进确定性管道（进发布物），ablate 是周期性 campaign 找可摘机制（进台账）。token 面上 Atlas 当前缺的是 §4.3-8 那种「机制内建计量面」——`atlas_check.py`/审查产物里 token 不是一等字段。

## 5. 委托模式 = Atlas 会话执行器的规模化同构（附证据）

`skills/open-code-review-delegate/SKILL.md`（223 行）：OCR 侧只出两件确定性产物——`ocr delegate preview`（可审文件清单+排除理由+ref 元数据）与 `ocr delegate rule`（按规则内容分组）；宿主 agent 按固定工作流评审，硬纪律：**覆盖率强制**（"every `reviewable_files` entry must end as reviewed or explicitly skipped"，:182）、输出 schema 表（:120-129）、按 severity 分组上报、低危只在明显有价值时报、**"Discard likely false positives silently"**（:143）。

对照 Atlas：`atlas_review.py:213-265` 派工包（fresh-context 硬要求/指针清单/探索预算/输出骨架）同构成立；OCR 多出的两件可借鉴小件 = ①排除面带理由码（Atlas `--staged` 全量进 selected，无 excluded-reason 面）；②覆盖率核算含 skipped-with-reason 出口。Atlas 的 selected/completed/failed/waived 四态其实已超集覆盖。

**「不自动化」清单与在案裁决对齐**（architecture.md:424-440）：endpoint 发现 fail-fast 无兜底不猜；**子 agent 失败隔离不重试**（"Retries belong in the wrapping CI pipeline, not the agent"）——与 QUEUE.md:102 防复读机裁决（失败自动重试不采，「自动重试会把节拍类真缺陷静默吸收成绿灯」）**同向**，非冲突项，引用备查。OCR 环内的空轮 nudge / schema 违规让模型重发属同对话内恢复，非跨轮自动重试，与裁决不抵触。

## 6. 结论三段

### 6.1 可抄面（按价值排序；只记落点不铸造新编号）

1. **行级锚定硬门（最高价值，直击自感知上报族「行号漂移」病）**：评审产物形态加两条确定性判据——①评论必带逐字 `existing_code` 锚；②`start_line/end_line` 必须能被滑窗匹配复算（或显式 0=未锚定、进 WARN 面），LLM 自报行号永不直接采信。Atlas 落点：`scripts/atlas_review.py:223-228` 派工包骨架加 `existing_code` 字段 + `scripts/cli_review_convert.py`/`validate_review_report.py` 形态门（跑分锚 = 暂存区 diff hunk 区间，纯标准库可实现）。OCR 全套算法有 Apache-2.0 正本可对照（resolver.go 319 行）。
2. **反思过滤模块**：审修循环加一轮「只移除可证伪错误、默认通过、保护科目否决」过滤，落点 = `atlas_review.py` closure 前新步骤（或独立脚本）。注意 token 方向是**加一次调用换 precision**，与 D206 目标函数需 A/B 实测（见下条），不宜直接落门。
3. **评审基准方法论（记观察，随 D206 campaign 引用）**：可迁移的不是 50 仓规模，是三个方法件——①ground truth 用**已知答案注入**（atlas-playground T1–T5 的注入违例就是现成标注集起点，历史评审轮确认为真的 findings 可续充）；②指标 P/R 分报 + token/时延并报（OCR 连「recall 是刻意让步」都写进基准口径，防单指标漂移）；③成本计量机制化（estimate 常量 + usage 兜底计数），Atlas 的 ablate 测量面 A/B 产出可对齐此形态。
4. **小件**：派工包加排除面理由码；分组索引化响应；round 2+ 不带 plan 防覆盖天花板（Atlas 复审已收窄实审集，语义等价，仅作设计旁证）。

### 6.2 不抄面

1. **整仓产品形态**（viewer/IDE 插件/MCP/遥测/ACP）——与 Atlas 仓内治理线束不同层（同 QUEUE 65 行升室判据的反面：机制面之外不收）。
2. **background 复制+8000 字符截断路线**（reviewing-requirements.md:38-40）——Atlas 指针化路线（`atlas_review.py:152`）方向相反且已被 BENCHMARK-20261119-02 四栏对照判定胜出，不回退。
3. **Go 实现细节**（嵌 tiktoken 二进制、goroutine 池、embed 模板）——违背 Atlas 纯标准库纪律（`atlas_review.py:23`），思想可抄、实现必抄坏。
4. **LLM 语义分组**：Atlas 暂存区评审实审集小（≤N+8 探索预算的 N 通常个位数），GroupingPlan 阈值以下场景，收益不抵一次调用；将来大 diff 场景出现按 DR2 另议。
5. **Ultra Mode 式高 recall 档**：Atlas 评审门是「劣化即拒收」的收口门不是建议器，双档会让「哪档才算审过」变新悬案；先按 6.1-2 的 filter 观察面走。
6. **自动修复合并进评审器**（OCR ROADMAP Not Planned 明言 review-only）——Atlas `--auto-fix` 已限机械类，维持现状。

### 6.3 是否值得立 RFC

**值得，拆两件走**：
- **RFC-A（建议立）**：暂存区评审行级锚定硬门（可抄面 1）。证据链完整：Atlas 病（自感知上报族行号漂移）+ 规模化先例（OCR resolver.go 四层漏斗）+ 落点明确（convert/validator 形态门，加门不改既有判据）+ 代价小（纯标准库滑窗匹配）。建议随下一轮 check 行为者实现批走双评审。
- **RFC-B（建议观察不立）**：反思过滤 + 评审基准（可抄面 2/3）——token 方向未实测、基准属 D206 campaign 消费面，挂观察室待 ablate 下一代 campaign 设计时按 DR2 引用本备忘起决策行；本备忘 §4.2 的不对称代价论与 §4.3 八条省 token 归因可直接作其拍板材料。

## 7. 拍板记录（2026-11-22 · tech-proposal-reviewer 对抗评审后拍板）

评审（一轮对抗，29 次仓内核验）总裁决 = 四点全采纳、无驳回。最终拍板：

- **RFC-A：立，按评审重构为两段式**。修订清单（全部采纳）：
  - **【证据链降级（B-1）】** Atlas 仓内**零**行号漂移病案：`duty-review/bugs.md:61-67` 自感知上报族八案均为「判据可被形态/措辞/配置满足」，无一行号案；全仓 grep `start_line` 唯一命中即本备忘。原 §6.3「Atlas 病（自感知上报族行号漂移）」措辞撤回——「逐字同构」是对 OCR 病灶的类比，不得当已证病案引。动机改写为「OCR 规模化先例 + `_support/review_policy.py:104` 指纹刻意排除行号的设计级承认（跨轮去重不受漂移影响——行号确实易漂的仓内旁证）」。
  - **【两段式（B-1）+ 不设 FAIL 牙齿（M-3）】** 第一期只做 WARN 测量面：派工包骨架加 `existing_code` 字段 + 转换器滑窗复算 WARN + 报告记每轮锚定统计（anchored/unanchored/mismatch）。**不预设 FAIL 升档**：锚定红若进 verify 失败记账会被记成 `blocking_critical` 扣预算（语义错位——锚定缺失是评审产物形态问题非实现侧问题），且修正需动 RFC-07 刚落的 cause 词表锚（`_support/workflow_causes.py`），同锚别动两次自咬。统计驱动派工包指令改进即可。
  - **【锚定层级补全（M-1）】** pre_existing findings（`review_policy.py:120,127,286-288` 真实产物面）按定义指向 diff 外代码，纯 hunk 锚必空转误伤——锚定层级写死：hunk 新侧 → 全工作树文件回退（pre_existing/上下文发现兼容），「文件存在但行号不复算命中」与「文件不存在」分档 WARN。
  - **【契约同步面（M-2）】** 改动面补契约正本两处：`shared/independent-review.md` §10（:200,208,214）+ `shared/stack-profile.md` impl_review 契约表（:110-122）；若影响 golden 装配基线，补 golden 重录行（对已提交树录纪律）。
  - **【连续性】** `cli_review_convert.py:152-153` 已有「0/缺行号 ⇒ 人工定位」降级形态，本 RFC 与之连续非新造。
  - **【窗口（m-3）】** RFC-A 与 RFC-07 在飞批零文件交叉（git status 实证），**草案现在可起**；落刀排 RFC-07 批（含 golden 重录）提交之后，登记行提交串行。
- **RFC-B：不立，零增量动作（m-2）**：QUEUE.md:65 已是正式观察行；D206 campaign 设计时按 DR2 引用本备忘 §4.2/§4.3。反思过滤（+1 次 LLM 调用）在 A/B 实测前与 D206「全部附加物都是成本项」方向相反，观察正确。
- **§6.1-1 落点修订（M-1/m-1）**：原「跑分锚 = 暂存区 diff hunk 区间」按上述锚定层级与两段式修正；分章排序学说一行字（案二备忘 §3）的落点从「随任一派工包触碰批」改判**「随 RFC-A 实施批」**落（同函数 `write_review_request` 同文件，一次落刀防同锚两动）。

---

*本备忘为纯只读调研产物，未改代码/契约/测试；外部行号以 tree `284ff013f0705ae6` 为准，Atlas 行号以 HEAD `1235c89` 工作树为准；§7 拍板记录中的仓内核验行号出自评审轮（同日，工作树在飞批未提交）。*
