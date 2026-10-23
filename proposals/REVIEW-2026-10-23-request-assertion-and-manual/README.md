# REVIEW-2026-10-23 · RFC-20261023-01 设计评审轮记

> 评审对象：`proposals/RFC-20261023-01-request-assertion-and-manual-structure.md`（D140/D141 草案）
> 评审实例：④ 设计决策（骨架 `.atlas/shared/independent-review.md` §8）
> 评审方式：fresh-context 子代理独立评审；先对开放问题独立给结论，再与 RFC 推荐比对
> 风险档：**高风险**——改动通用契约 / 校验器 / 生成器 / 控制台模板，命中 `global-rules.md §7` 第 4 条
> 结论：**需修改**；高风险不自动通过，最终须维护者人工签字

---

## 1. 审查总结

方向成立，但当前稿存在两条会导致**假绿**的设计缺口（请求时序、路径缺席语义），且改动面清单漏了 `validate_testids`、零步基线解析、人工块解析与决策号冲突。修订后需重审。

| 项 | 结论 |
|---|---|
| 总体 | **需修改** |
| 阻断性 Critical | 2（F1/F2） |
| Major | 4（F3–F6） |
| 是否可自动通过 | **否**（高风险，维护者签字） |
| 是否记 calibration | 否（atlas 自身设计，§7 适用范围） |

## 2. 独立结论（先于推荐）与比对

| # | 议题 | 独立结论 | 与 RFC 推荐 |
|---|---|---|---|
| 1 | API 匹配 | 后缀可用，但须按 `?api=` 取值做点边界精确匹配（`==` / `endswith('.'+suffix)`），歧义拒绝；禁止 `includes` | 一致（补边界） |
| 2 | JSON 路径 | v1 点号 + `[N]` + `[key=value]` 合理；必须区分「缺失 / null / 空串」；中间段缺失、过滤 0/多命中、越界 = **解析错误** | **不一致**：RFC 的 `(空)` 合并缺失与 null，且未定义过滤/越界错误语义 |
| 3 | 多次请求 | 默认「最近一次」会让历史请求秒过；应记录动作前请求序号，断言「该 step 后**新出现**且匹配」的第一条；无新请求 ⇒ 失败 | **不一致**：RFC 默认最近一次 |
| 4 | 隐私 | 默认连 expected/actual 都不能打印；trace 会存请求体，RFC 的「不落盘」不成立 | **不一致**：RFC 只承诺不打印完整载荷，未处理 trace |
| 5 | 零步基线 / after | `request` 不进基线正确；但 `after:N` 只给时点，不给「新请求」保证 | 一致（需配合序号门） |
| 6 | 人工结构 | 用例级账本不变、步骤仅面板进度正确 | 一致 |
| 7 | 请求 vs 响应 | 只做请求正确；响应/SSE 另起 RFC | 一致 |

## 3. 问题清单

### Critical

**F1 · 请求断言时序可假绿**
- 位置：RFC §2.1「捕获与解码」、§5 Q3；`scripts/gen_e2e_scripts.py` 断言发射面
- 问题：默认取「最近一次匹配请求」，动作没发请求时历史请求（自动保存/重试/首屏）会满足断言；`after:N` 只描述断言时点，不证明请求发生在第 N 步之后。
- 建议：动作前记录请求序号，断言「该 step 后新出现的第一条匹配请求」；无新请求 ⇒ 失败；多条请求要么失败要么显式序位；解码失败必须 fail-loud，不得折叠为 absent。
- 回退环：决策本身

**F2 · 路径缺席语义与解析错误混同**
- 位置：RFC §2.1 `<json-path>/<expected>`；`validators/validate_e2e_index.py`、`scripts/gen_e2e_scripts.py`
- 问题：`(空)` 同时表示「键不存在」和「值为 null」；中间路径写错、过滤 0 命中、`[N]` 越界都可能被当作「字段缺席」通过；RFC 示例 `JSON.parse(decodeURIComponent(payload))` 对完整 `params=...` 体会失败/双重解码。
- 建议：区分 `(缺席)` / `null` / `""`；只有叶子可缺席；过滤必须恰一命中；越界/解码失败 = 解析错误；解码用 `URLSearchParams.get('params')` 后 `JSON.parse`。
- 回退环：决策本身

### Major

**F3 · 隐私承诺与 trace 冲突**
- 位置：RFC §2.1 与 §5 Q4；生成配置 `trace: 'retain-on-failure'`
- 问题：失败消息/`expect.poll` 可能打印 expected/actual；失败 trace 会保存请求体，「不落盘」承诺不成立。
- 建议：自定义错误只给 api/path/类型/长度；actual 永不打印；request 用例关闭 trace 或做脱敏；测试注记只记 api/path。
- 回退环：决策本身

**F4 · 改动面漏了 testid 提取与基线解析**
- 位置：RFC §3 批 1；`validators/validate_testids.py::case_testid_usage`、`scripts/gen_e2e_scripts.py` 零步基线
- 问题：`validate_testids` 把 expected 第二个 token 当 testid，`request app.updateApp` 会把 `app.updateApp` 误算为应然 testid；零步基线对 expected 逐条 `parse_line`，未跳过 `request` 会抛未知动词；`verbs_by_slice` 同源。
- 建议：把 `request` 加入所有「无 testid / 不进基线」的单一判定函数，逐消费点补测试；不要只改 `ASSERT_VERBS`。
- 回退环：决策本身

**F5 · 决策号/变异号已被占用**
- 位置：RFC 头部与 §4；`DESIGN.md:607-610`
- 问题：D140 = write_claim、D141 = validate_testids 性能批；M143/M144 也已占用。按现稿落盘会重号。
- 建议：改用下一个空闲号（建议 D142/D143，变异 M145+），同步 RFC、gates、测试与 CHANGELOG。
- 回退环：决策本身

**F6 · 结构化人工块与现有解析面不闭合**
- 位置：RFC §2.1 批 2、§3；`scripts/e2e_console.py::read_manual`、`_support/case_block.py`、`templates/e2e/console/app.js`
- 问题：`case_block` 只支持扁平数组，嵌套 `steps` map + `command: |` 块标量需新解析器；`read_manual` 逐行扫 `- `，块内带 `|` 的行可能被误吸；新增校验器未登记 `atlas_check`/`install.sh`/`gates`；标题与块内 id/title 是两处真相。
- 建议：单一 `_support/manual_block.py` 供控制台与校验器共用；先剥 fence 再扫旧行；明确块标量语法；注册新校验器；标题与块字段二选一或做一致性校验。
- 回退环：决策本身

### Minor

无（本轮不凑数；其余为建议，见 §4）。

## 4. 优化建议与替代方案（带代价）

- **动作包裹 `waitForRequest`**：天然保证「新请求」，但生成器需为每个 `after:N` 动作做 Promise 包装，发射面更复杂。
- **人工块复用扁平行式**（`action | expect | command`）：少一个解析器和一套语法，代价是 schema 不如嵌套直观。
- **v1 直接支持 `request[1]` 序位并强制 `after:N`**：确定性最好，代价是多一个语法位、作者要多写锚。
- **请求/响应分离**：保持只做请求；响应与 SSE/WebSocket 另起 RFC，避免动词语义膨胀。

## 5. 结论

**需修改后重审。** 修订至少覆盖：F1 新请求时序、F2 三态路径语义、F3 trace 隐私、F4 testid/基线消费点、F5 编号、F6 人工块解析。高风险：审查员只压缩阅读量，不替代维护者签字。
