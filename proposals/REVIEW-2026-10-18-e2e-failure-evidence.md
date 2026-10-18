# REVIEW-2026-10-18 · RFC-20261018-01(E2E 真跑失败自动留证)评审轮记

评审人 = `tech-proposal-reviewer` 子代理(只读:Read + git/ls 类 Bash,无改文件权限)。
对象 = 2026-10-18 外部发版雷达首跑五条机制级情报。同日维护者拍板「可以,按你推荐的继续」。

## 轮 1(2026-10-18):五条分级 + 仓库实证

| 条目 | 来源 | 判 | 一句话理由 |
|---|---|---|---|
| 4② 真跑失败自动留证 | OpenHands v1.26(`browser record`) | **改造后采纳 ⇒ RFC-20261018-01** | 仓库实锤:两轨 config 模板无 trace/screenshot 键(`gen_e2e_scripts.py:1549/1580`);失败取证上限 = 文本 80 行(`e2e_console.py:520/582/591`);D98 与案 6 两次探针考古(`/tmp` 不可复算);`bugs.md:17` 升判条件悬空在等证据源 |
| 4① 按键三态原语 | OpenHands v1.27 | 存档观察 | 词表值为域封闭(`rings/e2e` 词表「固定、封闭」);无现场证据证明 `click`/`native`/`dispatch` 三动能表达不了;升室条件 = 三动能均不可证的用例 ≥2 例(D98 先例路径) |
| 4③ mock-LLM e2e 复跑+gap 清单 | OpenHands | 已有等价、勿重复建设 | Atlas 变异证明四段协议(基线绿→注入红→还原→再绿,含注入 diff)是它的更严版本 |
| 1=spec-kit 五子项 | 执行树/扩展 catalog/适配器安装/lifecycle hooks/版本化 governance | 存档观察(1②③⑤ 面) | ① 门册即编排件;④ 缺陷生命周期 duty-review 三件套更强;⑤ 共享件整戳版本化 + D99 字段集冻结;②③ 单人仓不需要社区目录规模;「条目逐版本化」与「条件级执行树」进观察室 |
| 2=claude-code 五子项 | OTel 分账/agent 跳步修/禁 file-mentions/idle compaction/输入框 hook | 存档观察 / 已有等价 | 门册 `[机器]/语义项` 两列 + 上报五分类 = 分账等价;「跳步仍报成功」类缺陷已以契约预防版治死(`agents/atlas-reviewer.md:19` 硬约束第 4 条「判不了就说判不了,绝不要按常识补全」+ `inheritProjectContext: false`);出站只传路径对应上报「零业务上下文」立法;idle compaction 与输入框 hook 的受益方是 LLM 运行时,Atlas 零运行时 |
| 3=codex 五子项 | 并行只读/级联打断/DNS 前查权限/授权恢复/优雅排水 | 存档观察 | 全部受益方为长驻运行时进程;Atlas 执行件是短命脚本,无现场不立项(D102 教训) |
| 5② base URL 原样 | cline v4.1.25 | 已有等价 | `DESIGN.md` D104 已定案「host 同参异 query」口径(`_support/url_merge.py` 单源,ATLAS_BASE_URL 只覆盖 host) |
| 5③ 流中断自动重试 | cline | **明示不采(已落 QUEUE 归档区,防复读机)** | 与「节拍类首跑不坐实、复跑复现才改判」(`duty-review/bugs.md:16`)方向相反;重试会把真缺陷静默吸收成绿 |
| 5① 托管云沙盒会话 | cline Cloud | 否决 | 违「项目自足」真判据(本机全局 Playwright 兜底只配 WARN,托管沙盒更甚) |

**轮 1 结论**:1 立项 / 3 观察室(升判条件写实于 `duty-review/QUEUE.md`) / 2 明示不采;其余「已有等价」。本期不做 LLM 运行时系(会话压缩、输入面 hook、agent 生命周期、云会话、重试、优雅排水)。

## 引用核验(维护侧,同日抽查)

`gen_e2e_scripts.py` reporter 行现状(1549/1580,确无 trace/screenshot)、`bugs.md:16`(节拍类)/`:17`(hover 升判条件)、`atlas-reviewer.md:19`(硬约束第 4 条)、`QUEUE.md` 案 6(/tmp 探针三件)、`DESIGN.md:573`(D104)——**全部属实**。

## 轮 2 对账(甲 → 乙四点修订)

1. **A 引用复核**:评审引 `e2e_console.py:582` 被要求精确复引;直核成立并补 `:520`(80 行在采集点就发生)/ `:591-592`(落账条件)两个更硬节点。
2. **B 并入动机证据(评审轮 1 漏)**:`bugs.md:17` 未解观察的升判条件原文含「trace / 连续截图」——留证不是新需求,是已登门、就差证据源的悬空判据;写进 RFC §1.3 / §4.4。
3. **C 咬合点补齐**:v3 副本有手工移植前科(`bugs.md` 安装与装配段)⇒ 能力生效于**下一次 `install.sh --update` 重装配**;重装配前「契约已声明而现场无」属如实态、巡检不得误报(RFC §2.3①,对齐 `single-source.md` §3 迁移仪式)。
4. **D video 取舍**:维护方裁定缓行;评审补两条加固理由(trace 自带回放器;多一键 = 同构面 +2 无收益),写进 RFC §2.2 被否区并留缓行条件。

**轮 2 结论**:无未分局。RFC 定稿落盘 `proposals/RFC-20261018-01-e2e-failure-evidence.md`。

## 变异实跑(同日,`scripts/mutation_proof.py` 四段协议,命令 = `pytest -k failure_evidence`)

- **MB10**(摘掉 none 轨 trace 键行,`proof()` 注入 `MutationNotApplied` 通道防锚点失效):基线 GREEN(`3 passed`)→ 注入 RED(`rc=1`)→ **还原逐字节一致(sha256 = `bbaafe4a…32f71`,True)**→ 复绿(rc=0)。✅
- **MB11**(`retain-on-failure` 改 `on`,首轨):基线 GREEN → 注入 RED(rc=1)→ 还原一致 True → 复绿 rc=0。✅
- 完整四段原始输出落 `/tmp/mb_evidence/`(会话临时);**注入 diff 摘录**(证据自包含)如下,红因 = §4.1 各钉对双轨的门条断言:

  MB10(none 轨两行被摘,钉 1 对 none 轨断言失踪 ⇒ 红):

  ```diff
  -            "    trace: 'retain-on-failure',\n"
  -            "    screenshot: 'only-on-failure',\n"
  +                        "    screenshot: 'only-on-failure',\n"
  ```

  MB11(`retain-on-failure` → `on`,首轨,钉 2 值形态封闭 ⇒ 红):

  ```diff
  -            "    trace: 'retain-on-failure',\n"
  +            "    trace: 'on',\n"
  ```
