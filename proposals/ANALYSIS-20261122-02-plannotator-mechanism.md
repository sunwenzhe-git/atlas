# 调研备忘：backnotprop/plannotator 人机异步评审面机制深度评估（Atlas 吸收分析）

> 类型：外部机制调研备忘（非 RFC，不立项不落刀；结论三段式见 §6–§8）
> 来源仓：[backnotprop/plannotator](https://github.com/backnotprop/plannotator)（TS/Bun monorepo，Apache-2.0 OR MIT 双许可，14.3k★）
> 快照：`main` @ 2026-11-22（502 文件；package 版本 `apps/hook/.claude-plugin/plugin.json` v0.29.2）
> 访问通道与限制：api.github.com 双出口（直连 39.183.121.75 与代理出口 18.181.78.24）均 403 限流 ⇒ 走 **raw.githubusercontent.com + data.jsdelivr.com 经 7897 代理**（镜像纪律备选通道）；`plannotator/guides` 独立仓的 guided-review SKILL.md 原文件 raw 404（jsdelivr 分支索引为空，仓状态存疑），分章协议以官方文档侧证据闭环。
> **开源/闭源边界（先读这个）**：**Inbox 本体、评审 agent/guided review 的 job 提示词、MCP 服务器实现均不在开源仓**（502 文件树无 inbox//mcp/ 目录；README.md:100 与 docs.plannotator.ai 明言 "The Inbox ships in the plannotator binary"）。开源面 = plan-review hook 服务器（`apps/hook/server/`，index.ts ≈159KB）、review/annotate 服务器（`packages/server/`）、各宿主插件/扩展（`apps/pi-extension`、`apps/opencode-plugin` 等）、guided-review 的**数据格式与 CLI 校验器**（`plannotator guide export` 在 hook 服务器内，`apps/hook/server/index.ts:2568-2576`）。凡涉 Inbox 运行时的结论均标注「文档口径」。
> 关联：QUEUE.md 观察室 66 行（2026-11-22 Trending 收录）；D204 atlas workflow 回收面（`scripts/atlas_workflow.py`）；并行在飞批 `RFC-20261122-07`（executor 回收面硬化，吸收 bmad-loop 失败分类学——与本备忘零重叠，其不解决异步注入语义，见 §7.1 定位声明）。

---

## 1. Inbox 异步闭环会话协议（Q1）

### 1.1 收件面：agent 主动投递的结构化词表（文档口径）

- 投递 = 一个工具 `plannotator_inbox`（单工具多 action；Claude Code 由 mod 注入，其余宿主走 `plannotator inbox mcp` 的 stdio MCP）。会话开始注入一行协议提醒（可按 runtime 定制，见 §1.5）。
- **问题块 `:::question`** 携带两级阻塞语义（markdown 正文内联声明）：
  - `Stopped: <why>` —— agent 真不能继续（线程置顶 "Stopped on you" 分区）；**负值词表**（no/none/n/a/短横）读作无阻塞；
  - `Holds up: <work>` —— 列出等待中的工作但 agent 继续干活（"Holding up work" 分区，不置顶）。
  - docs 明言 "Agents are told to write Stopped: only when they truly cannot continue" —— 词表是封闭语义 + 提示词教写法（`send_message` 工具的 body 字段与 `plannotator inbox --help` 双承载）。
- **动作块 `:::action`**：真人必须去会话外做的事（如线上审批），带 `Where:`（链接→按钮）/`Stopped:`/`Watching:`——`Watching:` 让 agent 自行观察完成并凭 `done` 字段自闭动作项。
- **线程分区**：Stopped on you / Holding up work / Waiting on you / New since you looked / Sent / Quiet——按「谁欠谁」分区而非按时间。

### 1.2 回程路由：三态注入 + 一条铁律（文档口径）

- **态①插件直连宿主**（Claude Code mod / Pi / OpenCode 2 / DSH / Hermes / Codex 0.149+ / Qwen 0.24+）：reply 作为**idle 后的新 turn** 注入原 session；运行中按默认排队（"Queued · is working; it gets this when its turn ends"），**"Send now" 可插入运行中 turn 的下一 step**。
- **态②纯 MCP 宿主**（Cursor/Amp/Cline 等）：不唤醒，"Saved for … It sees it when it next reads this thread"（`read_thread` 拉取式）。
- **态③session 已死**：线程标 "Session ended"，回复框上方提示，**"Send to another session" 必须人显式拣选**——"Nothing is ever sent to another session unless you pick it"；被拣的新 session 被告知「这是写给已结束 session 的回复，先读线程」，并继承线程归属；原 session 若 resume 仍可收到。无运行中 session 时 Send 只存草稿，草稿永不自动发送。
- 判定 session 存活：插件宿主 1 分钟无心跳即判 ended；纯 MCP 宿主「不可判死」，永不标 ended。

### 1.3 送达一次与多窗口仲裁（文档口径）

同一 session 双窗口（`pi -c` / OpenCode 2 同库双 server）：持信进程每 5 秒心跳，退出即刻接管、崩溃约 20 秒接管，**"A reply is delivered once either way"**——at-least-once 视图 + 去重由持有权租约保证。

### 1.4 上下文压缩存活（开源 hooks.json 直接可见）

`apps/hook/hooks/hooks.json:29-40`：`SessionStart(matcher: compact)` 钩子打印 `$PLANNOTATOR_INBOX_REMINDER`——mod 在每次压缩**前**把该会话开放线程清单写进环境变量，压缩后回注提醒行 + 线程清单（hooks.json:2 描述原文）。同时 hooks.json:17-27 保留经典阻塞钩子 `PermissionRequest(ExitPlanMode)` `timeout: 345600`（4 天）作为 mod 关闭时的回落（`apps/hook/README.md:90`）。

### 1.5 会话开始提醒行与双通道去重纪律（文档口径）

提醒行全文可见（docs "The reminder at session start" 节），核心纪律四条：
1. "send it with plannotator_inbox send_message（每个决策一个 :::question）**and keep going**"；
2. "Be proactive… don't batch updates to send later"；
3. "One thread per work stream"；
4. **双通道去重**："A decision in the Inbox stays there: when the person writes here, say what waits and link its thread, **but never also ask it in the chat with a blocking question tool (AskUserQuestion or similar)**"——决策一旦进了收件箱就不得在会话里重复阻塞提问。
提醒行文本**会话内永不变更**（"The text never changes during a session, so it costs little and does not invalidate the prompt cache"；工具开关同样只在 session start 读）——**prompt-cache 不变量是其会话协议的一等工程约束**。可按 runtime 覆写（`prompts.inbox.runtimes.<agent>`，docs 给出 worker-session 变体："report to your upstream session first. Use plannotator_inbox send_message only when it is gone"）。

### 1.6 显式人控语义清单（与防复读机裁决对齐检查）

- **Send 不跳过未答问题**："The questions you did not answer stay open, and the reply tells the agent how many and not to ask again, because you will answer in the Inbox"——跳过必须显式按 Skip；
- **Mark read = 显式 NACK**：关闭未答问题并给 agent 一条 "Set aside for now; don't wait on these: …"；
- **👍 Looks good = 显式放行**（"Take it as a go"），可撤销直到送达；
- 全程**无任何自动重试/自动转投/自动关闭语义**——与 QUEUE.md:102 防复读机裁决（失败自动重试不采）同向，非冲突项；恰恰相反，其「answered-when-you-can + 不占住会话」正是「不把红灯训练成噪声」的人机版实现。

## 2. Atlas 回收面对照与改造面评估（Q1 后半）

**Atlas 现状（file:line）**：
- 派工 = 写盘后同步等待：`scripts/atlas_workflow.py:214-216`（"派工单就绪…请依据派工单实现代码，完成后暂存并运行 `atlas workflow verify`"）；`scripts/atlas_workflow.py:497-502`（run 闭环在暂存区空时打印指引并 `return 2` 停在 Dispatch 后）；
- 审查侧已有**最小会话内异步交接原语**：`scripts/atlas_review.py:446-459` 会话执行器 PENDING 路径——写 `review-request.md` 派工包落盘 + 指示「派 fresh-context 子代理写 cli.json 后复跑」，exit 2 退出（不是通过）。**包在盘上、会话稍后拾取**，这就是无传输层的收件箱雏形；
- 台账 = 纯文件状态机：task.json `todo→in_progress→completed`（`_support/workflow_dispatch.py:158` 原子写；`_support/workflow_finish.py:608`），轮次产物 append-only 目录（`_support/workflow_finish.py:162-192` scan_review_rounds + review.json 判收）。

**task.json/reviews/ 能否直接当 Inbox 存储**：**能承载语义件、不需要新存储**。轮次目录已是 thread 雏形（按轮 append、不可覆盖——`atlas_review.py:263-270` 同轮 findings 不覆盖自动递增）；缺的是三件**语义件**：①问题/回答的机器可读落点（现在 findings→resolves 声明文件是单向处置，没有「人答完回注」的回程）；②阻塞分级词表（Atlas 已有 Critical/Major/Minor 分级与 WARN/FAIL 两态，但没有「这项阻塞推进 / 这项不阻塞可继续」的**流程语义**承载——verify 红 = 整个 run 停）；③回程路由纪律（谁捡、何时捡、死了怎么办）。

**真正缺口（形态性，须如实呈报）**：plannotator 的核心收益「人不在线时 agent 不空转 + reply 变新 turn」依赖**宿主会话控制面**（mod 注入工具/唤醒 idle session）。Atlas 是仓内治理线束，无宿主 turn 注入能力——「新 turn 注入」只能靠人回到会话后自然接续（Atlas 的 PENDING+复跑已是这个形态）。故 Atlas 可吸收的是**协议语义件**（§6.1），不是传输实现（服务/浏览器/多宿主接线）。

## 3. guided review 分章策略（Q2）

- **排序学说**（`apps/marketing/src/content/docs/commands/code-review.md:332-334`）："an agent organizes the diff into sections — **the heart of the change first, consequences next, glue last**"——每章 prose overview + per-file summaries + 可标注 diff；章节带 per-section "reviewed" 状态支持按序攻大变更。
- **分章产物是机器可读 JSON 且过确定性校验**（docs.plannotator.ai Portable guides 参考页）：guide.json = `{title, intent, sections:[{title, overview, diffs:[{file, summary}]}], unplacedFiles[]}`；`plannotator guide export` **校验「guide 点名的每个文件必须在 patch 里且只点名一次」，违规 exit 1 且把修法印出来**；patch 里没被分进任何章的文件进 `unplacedFiles` 显式核算（不隐身）；文件过时 → 渲染成 "outdated" chip 而非崩坏；快照 v1 严格 JSON「unknown fields are rejected so a file is never silently misread」。
- **生成通道分离**（code-review.md:348）：评审 agent/guide job 外壳 out 到宿主 CLI——**"Plannotator controls the user message and output schema; the CLI's own harness owns the system prompt"**；独立 `guided-review` skill（`npx skills add plannotator/guides`）让任意 agent 自己产出 guide.json。
- **对照 Atlas**：`atlas_review.py` 实审集封口（scope manifest `selected[]` 应审 N 不可得即拒）已保证「不隐身」；分章的 UI 价值面（人读大 diff）在 Atlas 机器对机器产物（review.json v4）里不存在。**可吸收的只有排序学说**：把「heart→consequences→glue 的审查顺序」写进派工包一行指令（`scripts/atlas_review.py:236-262` 的 write_review_request 文本），对冲 fresh-context 子代理「先易后难/切角」偏置；与 OCR 案一 plan 阶段（先规划后细读）同构互证。成本一行字，收益待实测。

## 4. 多宿主接线组织方式（Q3）

- **装配矩阵**（README.md:250-262 + docs Inbox 节连接表）：一个 installer 探测已装 agent，按宿主分三种接线形态——①插件直连（Claude Code plugin/hooks、Pi extension、OpenCode plugin、DSH/Amp/Droid plugin）②宿主 MCP 注册（`codex mcp add` / `gemini mcp add -s user` / 各家 settings.json 写 `plannotator-inbox` key）③指令文件托管注记。每宿主带**版本地板**（Pi 0.99+/Codex 0.35+（MCP 连接）/0.149+（新 turn 唤醒）/Gemini CLI 0.1.19+/Qwen 0.24+），地板之下写明降级行为（"older Pi has no pi mcp: connect it by hand"）。
- **外科手术式编辑承诺**（docs Inbox 节，多处原文）："In a JSON file only that one entry is added; every other byte of the file stays as it was, and removing it gives the file back exactly as it was"；Qwen settings.json 含注释时保留全部注释、绕开 `qwen mcp add`（因其会把 `${VAR}` 展开回写）；"A file that is not valid JSON or is read-only is left as it was, and the terminal says why"；宿主自身命令执行前先 `--version` 探测，"a different program with the same name is never handed it"；**已有同名 entry 永不替换**。
- **卸载记账**：`~/.plannotator/inbox/agents.json` 记录「它加了什么」——"plannotator uninstall removes every entry it recorded adding (never one you added yourself). If its record is gone, it removes none"；宿主 config 不可读时保 binary 不删、点名文件与原因（README.md:296-300）；`--dry-run` 预览、purge 需强确认词、数据目录 symlink/root 防护（README.md:286-328）。
- **指令文件托管注记**：marker lines 之间的受管块，"Plannotator never overwrites a note you edited, and removing it removes only that section"；OpenCode 的 AGENTS.md 仅在已存在时写入（创建它会遮蔽其读 ~/.claude/CLAUDE.md 的行为——副作用感知）。
- **per-host 默认值由 token 成本定**：Pi/OpenCode/DSH/Hermes 的 inbox 工具默认关，因为"Pi sends every tool's full definition with each request: the inbox tool adds about 15 KB to every request, roughly 3,906 tokens"（Board 开则 16KB/4,492）——**每请求全量带工具定义的宿主，工具面即 token 税**，默认值跟着税走。
- **对照 Atlas 装配器**：`install.py:431-438` 平台 skill 目录探测（.agents/skills 缺省兜底）、`install.py:646-660` agent md 三落点复制（.agents/.claude/agents/.codex/agents）、`install.py:864+` AGENTS.md 集成——**装配时一次性静态适配**，无运行时 registry、无逐 entry 卸载记账。AGENTS.md 手写区/托管区纪律（RFC-20261122-03 手写区同步清单、机制文档分诊迁移）已是 marker-lines 同族思想。多宿主自动接线（11 宿主矩阵）与 Atlas「装配 ≠ 开户」两态纪律方向相反，不取。

## 5. 附带发现（不立项，记录备查）

- **反馈后缀自带核verify义务**：`review.denied` 内建后缀 "Validate each submitted finding against the code and report your verdict before changing anything"，且 "Plannotator adds the suffix only when the submitted review has annotations"（docs Prompts 参考页）——与 OCR 案一反思过滤同一思想（防人标错被静默吸收），Atlas 的 `--resolves` 词表（fixed/false_positive/intentional/ignored）已覆盖，仅作旁证。
- **产物快照随 guide 钉死 diff**：portable guide 内嵌 "the exact unified diff the guide was generated against (captured when the guide was generated)" + 生成者 provenance（engine/model/customInstructions）——与 Atlas 评审轮次封口（scope_sha256）同构，旁证。
- 归档面 `plannotator archive`（README.md:194）只读浏览历史决策——Atlas `.atlas/tasks/archive/<YYYY-MM>` 同构。

## 6. 结论三段——可抄面

按价值排序（只记落点与判据方向，不铸造新编号）：

1. **异步回收的语义件四条（最有价值，直接服务 D204 回收面下一代设计）**：
   ① **问题两级阻塞词表**（Stopped:/Holds up: + 负值词表）——Atlas 侧等价物 = findings/verify 产物加「阻塞推进 vs 不阻塞可继续」的流程语义承载位（现在 verify 红 = run 停，粒度过粗）；与并行在飞的 RFC-20261122-07 暂停原因封闭词表**正交互补**（它管「为什么停」，本件管「停了谁欠谁、什么不算停」）。
   ② **回程路由三态纪律**（idle 新 turn / 运行中插 step / 死 session 绝不自动转投、必须人拣）——Atlas 落点 = task.json 状态机旁的「等待人语义词」+ 派工包/审查产物里的路由指示文本；PENDING+复跑（`atlas_review.py:446-459`）已是最小实现，缺的只是词表化。
   ③ **送达一次/显式 NACK/不跳问三件人控语义**——判收面引用（防复读机同向）。
   ④ **双通道去重纪律**（决策留在收件箱就不再会话内阻塞重问）——Atlas 落点 = verify/finish 文案纪律（与 user-facing-hint 纪律同族）。
   ⑤ **压缩存活回注**（hooks.json:29-40）——Atlas 会话内长任务跨压缩丢上下文是已知痛点，此机制以「环境变量 + SessionStart 钩子回注」实现，Atlas 装配面已支持宿主 hooks（`install.py` hooks 平台化先例），可作远期观察件。
2. **分章排序学说一行字**：review-request.md 派工单加「heart→consequences→glue 审查顺序」指令行（§3）。
3. **卸载记账思想**：装配器卸载面将来若立项，引用 §4 的 agents.json 记账 + 「只删自己加的、record 丢了什么都不删」不变式。

## 7. 不抄面

1. **传输实现整体**（本地 server/随机端口/浏览器 UI/cookie 设置/多宿主 MCP 接线矩阵）——Atlas 无 UI 层无宿主控制面，产品形态不同层；且 Inbox 运行时闭源，本就无可抄本体（§0 边界）。
2. **ask-when-idle/唤醒宿主机制**——依赖 mod/插件 API，Atlas 形态不可达；PENDING+复跑已是 Atlas 形态下的等价物。
3. **Skills-in-replies / Ask this session / AI 侧栏 / Board 看板**——产品功能面，非治理机制。
4. **多宿主自动接线矩阵**——与「装配 ≠ 开户」两态纪律冲突风险（自动改宿主全局配置 `~/.codex`、`~/.gemini` 等，Atlas 装配器只动采纳仓内文件），方向相反。
5. **plannotator/guides 独立仓的 skill 本体**——原文件 404 未取得（§0 限制），仅 schema 与校验器口径可引用；且 Atlas 评审产物是 JSON 非浏览 HTML，guide 渲染面无消费方。

## 8. 是否值得立 RFC

**值得一件轻量 RFC（语义件，非传输件）**，但**建议排在 RFC-20261122-07 落刀之后**：其暂停原因词表与预算分类学与本件 §6.1-①② 共享落点（task.json/退出码/失败台账），同锚别动两次（2026-11-22 需求落点批已立此规矩）。本备忘 §6.1 四条语义件 + §2 的缺口对照可直接作其 §1 现象取证；判据方向 = findings/verify 产物加流程阻塞语义位 + 派工包路由词表，全部 WARN/文本纪律面起步、不设新机器门（与「判据可被形态满足」族防御一致）。分章一行字（§6.1-2）可随任一派工包触碰批顺带落，不独立立项。

## 9. 拍板记录（2026-11-22 · tech-proposal-reviewer 对抗评审后拍板）

评审对原 §8「值得立轻量 RFC」建议**反对成立**，最终拍板 = **撤销立 RFC 建议，维持 QUEUE.md:66 观察行**（升室判据原文「回收面改造立项时 ⇒ 按 DR2 对照起决策行」继续有效）。裁决依据（评审 M-4，逐件核验，全部采纳）：

- **① Stopped:/Holds up: 两级词表**——「Stopped」面 **RFC-07 已交付**：`paused_reason` 封闭词表 + 退出码 3「停下要求人工」+ PENDING exit 2（在飞新文件 `_support/workflow_causes.py` CAUSES 注释明写覆盖「会话待审 PENDING」）——**实质同物非正交互补**，本备忘原判「正交互补」过乐观，撤回。「Holds up（不阻塞可继续）」**无机器消费方**：Atlas 单宿主会话顺序派工（RFC-07 §4 明写无并行单元合回形态），没有「单元 A 等人、单元 B 继续跑」的调度器，该词表是给不存在的并发形态准备的元数据。
- **② 回程三态纪律**——Atlas 单会话，盘上状态机天然支持（人开新会话重跑 `atlas workflow status` 即可拾取），纪律无增量。
- **③ 送达一次/显式 NACK**——Atlas 无投递层（文件落盘、下次命令读），at-least-once/去重语义无承载物；「不跳问」至多是 verify 文案纪律一行。
- **④ 双通道去重**——Atlas 只有一条通道（会话本身），无第二条需要去重。
- **⑤ 压缩存活回注**——**唯一有远期消费方的件**（`atlas_review.py` 长任务跨压缩确是痛点），原备忘把它排最后系排序倒挂，更正为**远期观察件首位**。
- **重开判据**：未来出现 DAG 并行派工或多会话消费形态 ⇒ 按 DR2 以 QUEUE:66 为锚重开，届时新词表才有真实消费方，且不与 RFC-07 新锚抢刀。
- **决策点 4 修订（m-1）**：分章排序学说一行字的落点从「随任一派工包触碰批」改判**「随 RFC-A 实施批」**落（同函数 `write_review_request` 同文件一次落刀；详见案一备忘 §7 拍板记录）。
- 「不抄面」（传输件/多宿主接线/闭源边界）经评审复核**维持**；§2「真正缺口」自我呈报段被评审评为全备忘最清醒一段。

---

*本备忘为纯只读调研产物，未改代码/契约/测试；外部引用以 2026-11-22 快照为准（Inbox 运行时结论均为官方文档口径，未运行验证）；Atlas 行号以 HEAD `1235c89` 工作树为准，§9 拍板记录中的 RFC-07 在飞批核验出自评审轮同日实况。*
