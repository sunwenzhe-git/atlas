# L1 · E2E 生成与控制台子系统

> 子系统 #7 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.6(2026-10-25 复核)
> 一句话:**中文用例分片编译为 Playwright 脚本 + 纯标准库 SSE 评审控制台**——应然验收从「人写的脚本」变成「机器从资产生成的脚本」,生成器无状态、可重放、值域封闭。

## 它不是什么

- 不做语义判断:用例对不对、断言强不强,归 PRD 环与独立审查;生成器只做忠实编译。
- 不跑用例:执行归 Playwright 运行器(`e2e.reset` → 真跑),控制台只编排与留证。
- 不造资产:分片(`product/e2e/cases/`)与索引(`e2e-index.md`)是 e2e 环产物,本子系统消费它们。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `scripts/gen_e2e_scripts.py` | 2383 | 生成器本体(全仓最大单件):分片 DSL → `.spec.ts` |
| `scripts/e2e_console.py` | 1084 | 评审控制台:纯标准库 SSE 服务(默认 127.0.0.1:4190) |
| `scripts/gen_testid_stub.py` | — | testid 实然盘点薄桩生成器(adopt 开户交尾件) |
| `_support/pw_runner.py` | — | 运行器单源内核:可解析性判据 / 全局兜底修复 / 浏览器就绪探针 |
| `_support/case_block.py` / `case_id.py` / `manual_block.py` | — | 用例块解析 / 用例 ID 文法 / 手工块(共享内核件) |

## 核心机制

### 1. 用例块文法与行解析(`scripts/gen_e2e_scripts.py`)

用例以 ```atlas-case 围栏块(`CASE_BLOCK`,`scripts/gen_e2e_scripts.py:79`)声明;每行三段式(动词 · testid · 值)由 `parse_line`(`scripts/gen_e2e_scripts.py:168`)解析。行前缀 `initial:` / `unchanged:`(`PREFIXES`,`scripts/gen_e2e_scripts.py:129`)与 `after:N`(`AFTER_RE`,`scripts/gen_e2e_scripts.py:131`)表达时序;提交类词族(`SUBMITTING_WORDS`,`scripts/gen_e2e_scripts.py:136`)驱动保存后动作语义。

### 2. 动词值域封闭(D98)

`ACTION_VERBS`(`scripts/gen_e2e_scripts.py:96`)与 `ASSERT_VERBS`(`scripts/gen_e2e_scripts.py:97`)是封闭词表:陌生动词**中止生成**,不静默吸收——治旧安装副本对「新语法」的静默吞掉。`dispatch` 动词走合成事件直发(动画窗被吞 / native 挂死双灭实证);`NO_TESTID_VERBS`(`scripts/gen_e2e_scripts.py:98`)声明第二 token 不是 testid 的例外(refresh / goto)。

### 3. 登录形态三态(D80②)

`APP_LOGIN_MODES`(`scripts/gen_e2e_scripts.py:91`)= real / fabricated / none;字段族 `APP_LOGIN_FIELDS`(`scripts/gen_e2e_scripts.py:86`)。none = 显式声明无门,不是降级。消费面分型:sessionStorage=会话 / storageState=auth / 查询串=参数。

### 4. mock 外部协议(`MOCK_METHODS`,`scripts/gen_e2e_scripts.py:93`)

打桩声明(`parse_mock_line`,`scripts/gen_e2e_scripts.py:311`)编译为**单条** `context.route` 派发表:pathname+method 命中、query 免疫、前缀内未命中即红(`compile_mock_entries`,`scripts/gen_e2e_scripts.py:370`);fixture 文件随批落盘。

### 5. 双前置门:独立审查 + 就绪

`review_gate`(`scripts/gen_e2e_scripts.py:1293`)读最新审查报告(`REVIEW_LEVELS`,`scripts/gen_e2e_scripts.py:1166`),有 Critical 拒绝写盘;`NOT_READY`(`scripts/gen_e2e_scripts.py:84`,exit 3)= 前置未声明的显式跳过,不是失败。

### 6. 失败留证(D108/D142)

Playwright 配置层 `trace` / `screenshot` 两轨(`scripts/gen_e2e_scripts.py:2119`):retain-on-failure + only-on-failure——全绿轮零构件,失败即有现场。含 `request` 断言的用例单独成文件(`D142`,`scripts/gen_e2e_scripts.py:190`),顶层 `test.use` 单独控制其 trace。

### 7. 参数通道(D109)与 base query 转发(D104)

用例 `参数:` 行只声明键,值内联在首个带参 `goto` 的查询串(单一来源);守卫导航经同一来源注入(`scripts/gen_e2e_scripts.py:580`),不双写。宿主注入型 base query 转发单源在 `_support/url_merge.py`。

### 8. 评审控制台(`scripts/e2e_console.py`)

`snapshot`(`scripts/e2e_console.py:293`)聚合现场;`repo_provenance`(`scripts/e2e_console.py:153`)产评审指纹(head_sha + scripts_hash)防旧账本挂新执行;`Ledger`(`scripts/e2e_console.py:402`)落评审台账;`Runner`(`scripts/e2e_console.py:530`)做 500ms 慢动作回放 + 逐用例三值走查(pass/fail/skip),提交即解锁人工 Review;`resolve_pw`(`scripts/e2e_console.py:370`)复用运行器判据与全局兜底。

## 对外接口(谁咬它)

| 消费方 | 触点 |
|---|---|
| atlas_check 生成物门 | 干跑 diff:分片变而脚本未再生成 ⇒ WARN |
| atlas_check E2E 真跑 | TCP 探活 → e2e.reset → 运行器判据 → 浏览器探针 → 真跑 |
| validate_testids / validate_e2e_index / validate_e2e_mocks | 分片与索引、mock 声明的形态门 |
| validate_review_report | 控制台产出的审查报告落盘形态复算 |

## 显式盲区

- 登录态本身不可覆盖(D103 盲区):真跑日协议七项咬合承担。
- 生成器不判「用例是否值得测」——AC → 用例映射归 e2e 环与 AC 对账门。
- 控制台单机单用户假设(127.0.0.1),不做多会话仲裁。

## 演化锚

| 决策 | 内容 |
|---|---|
| D93 | 分片中文 DSL 定形(词表三段式) |
| D98 | dispatch 动词 + 值域封闭(双钉 + 全量绿) |
| D108 | 失败留证两轨(trace + screenshot) |
| D109 | 逐用例 URL 参数通道(白名单 ∧ 用例声明) |
| D110/D111 | prepare 钩子 + REFRESH_SETTLE(beta.25 落地) |
| D142 | request 断言单独成文件(trace 控制分离) |
| D145 | 装配基线 manifest(生成器脚本入逐文件基线) |

## 讲述时的三个抓手

1. **词表是协议**:动词值域封闭 + 陌生即中止——「旧副本静默吸收新语法」这类漂移在这里构造性不存在。
2. **生成器无状态**:同分片 + 同契约 ⇒ 同脚本(dry-run diff 即对账),资产是唯一真相源。
3. **慢动作评审台**:500ms 回放 + 评审指纹,把「跑过了」变成「人看着它跑过,且账本对得上这次执行」。
