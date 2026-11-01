# 签字与取证必须是非空字符串（收紧台账与形态门的共同承重件）

> 提案编号：RFC-20261101-03
> 提案作者：@sunwenzhe-git
> 关联状态：已定案 (Accepted)（用户 2026-11-01「还有没做的，给个推荐一起做了」批次）
> 关联：`RFC-20261101-02` §4.9（本条曾被第三轮评审列为「不改」，主审推翻）
> 影响范围：脚本工具 (scripts) | 单源内核 (_support/review_policy.py) | 门册 (shared/gates.md)

---

## 1. 现象

`disposition_by` / `disposition_evidence` / `resolves[].by` / `resolves[].evidence` / `verification.by`
此前的判据都是 `bool(str(x or "").strip())` —— 于是：

```python
{"disposition": "false_positive", "disposition_by": 123,
 "disposition_evidence": ["外层网关已校验"]}      # ⇒ 经 str() 变非空，算「已签字 + 已取证」
```

**Critical 靠这一条脱离阻断**（`is_blocking_critical` 的豁免支），**台账靠这一条把义务判成 `resolved`**。
也就是整条闭环的承重件是「谁签的、凭什么关」，而它可以被一个整数满足。
第三轮评审把这条列进「不改」，理由是把真实性归人判——但「归人判」说的是**内容**是否成立，
不是**格式**可以是数字；这是两件事，故主审推翻。

## 2. 定案

- `_support/review_policy.py` 新增 `signed_str(container, key)` 与
  `has_signed_disposition(container, by_key, evidence_key)`：**必须是非空字符串**；五处旧调用统一改齐
  （`is_blocking_critical` / `validate_v2_finding` 的 fixed|false_positive / `verification.by` /
  台账 `has_evidence` + `declares_close`）。
- `resolves_shape_errors`（单源形状判据）新增：`by` / `evidence` 若给了但不是字符串 ⇒ 形状错。
  ⇒ 转换器 `--resolves` 直接拒绝产出；中间轮 ⇒ 该条不作关闭证据 + warnings；最新轮 ⇒ exit 2。
- 语义不变：`fixed`/`false_positive` 仍要求「两者齐备」；Critical 仍不接受 `intentional`/`ignored`。

**被否**：① 只改台账不改形态门（同一判据两处口径 ⇒ 门绿台账红的分裂）；
② 接受数字/数组签名并「靠人看」（承重件形式化即可，不必留宽松口子）；
③ 新增「签名者需在名册里」的校验（无权威名册，属臆造硬门）。

## 3. 改动面

- [x] `_support/review_policy.py`（`signed_str` / `has_signed_disposition` + 五处改齐 + `resolves` 形状 + 逐条判据 `resolves_entry_errors`）
- [x] `scripts/review_closure.py`（`has_evidence` / `declares_close` 走内核）
- [x] `tests/test_review_closure.py`（M17 数字签名不算关闭 + 字符串签名的正例对照）
- [x] `tests/test_review_report.py`（M48 形态门两侧：`by` 数字、`evidence` 为 0）
- [x] `tests/test_cli_review_convert.py`（`--resolves` 非字符串签名 ⇒ 拒绝产出）
- [x] 契约 §3 字段条 / §11、`shared/gates.md` 两行 + §4 条、`DESIGN.md` D181、两处 changelog、`docs/map/*`

## 4. 兼容与验证

- **零回扫风险**（实测）：全仓 + 真实四轮语料的 `review.json` / `findings/*.rN.json` 里
  非字符串签名或取证字段命中 **0 处** ⇒ 收紧属「纠错」而非「破坏存量」；语料台账仍
  `PASS rounds 4 prior 16 resolved 16`、形态门仍 `PASS`。
- 用例数（合并前两路评审补账后的**终值**，见 §4.2）：`test_review_closure.py` 37 → **40**（M17 / M98 / 正例改名）、
  `test_review_report.py` 41 → **45**（M48 / M99 / M100 / M101）、`test_cli_review_convert.py` 49 → **51**（M49 / M51）。
- 行数（终值）：`_support/review_policy.py` **371**、`scripts/review_closure.py` **423**、
  `scripts/cli_review_convert.py` **372**；锚点 `signed_str:45` / `has_signed_disposition:55` /
  `count_floor:61` / `compute_fingerprint:98` / `resolves_entry_errors:230` / `resolves_shape_errors:254` /
  `state_of:77` / `load_prior_rounds:101` / `last_close:183`。
- 四段变异协议：M17 把 `has_signed_disposition` 退回 `str()` 宽松 ⇒ 数字签名用例红；
  M48 同理退回 ⇒ 形态门用例红；日志 `/tmp/atlas-rfc03-evidence/`。
- 全量 / 安装自检 / 真实语料回路复跑见 §4.1。

### 4.1 结果实录（2026-11-01，分支 `rfc-20261101-03-signer-strictness`）

* 用例：`test_review_closure.py` **39**、`test_review_report.py` **42**、`test_cli_review_convert.py` **50**；
  全量 `pytest tests/` ⇒ **1014 passed / 5 skipped**；`test_shared_kernel.py`（单源结构门）随新内核件通过。
* 三枚钉四段协议（基线 → 注入 → sha256 逐字节还原 → 复绿，日志 `/tmp/atlas-rfc03-evidence/mutation-proof.log`）：
  * **M17 + M48**（把 `signed_str` 退回 `bool(str(value or "").strip())`）⇒ **distinct 测试**恰红 2 条
    （`test_numeric_signature_does_not_close` / `test_numeric_disposition_by_fails_validator`）；
    全量 node-id 口径实为 **4 条** —— playground 内嵌的 `.atlas/tests` 会把同两枚钉再跑一遍（§4.2 更正）；
  * **M49**（摘掉 `resolves_shape_errors` 的字符串判据）⇒ 恰红 1 条
    （`test_resolves_numeric_signer_refused`）——两处判据独立，各配一枚钉，不靠一次注入蒙过三处。
* 零回扫实测：全仓 + 真实四轮语料（`review.json` 与 `findings/*.rN.json`，含 `verification` / `disposition_*` /
  `resolves[].by|evidence`）非字符串签名命中 **0 处**；语料四轮台账仍 `PASS rounds 4 prior 16 resolved 16`、
  形态门仍 `PASS`。
* 行为差异（收紧前后）：`disposition_by: 123` 的 Critical 报告此前「脱离阻断 + 台账判已关」，
  现两侧同时判为未关闭 ⇒ 门红 / 台账 `carried`。

### 4.2 合并前只读评审两轮的补账（2026-11-01）

两路独立只读评审（一重在回扫与咬合，一重在旁路与测试空洞）都打出同一个 **Critical blocker**。

- **B1（Critical）**：`load_resolves` 先跑形状校验，随后 `default_by = str(raw.get("by") or "").strip()`
  ⇒ `{"by": 123}` 被洗成 `"123"` 并**继承进每一条声明**。端到端复现（`/tmp/atlas-rfc03-blocker-repro.py`）：
  r1 一条 Critical + r2 `--resolves {"by":123,"resolves":[{fp,status:"fixed",evidence:"…"}]}`
  ⇒ 转换器 rc=0、`review.json` 落 `"by": "123"`、台账 **`PASS resolved 1`** —— 闭环承重件「谁签的」
  仍被一个整数满足，laundering 只是从条目级上移到批级入口。M49 只钉条目级，顶层当时**无任何钉**。
  → 修：顶层 `by` 若给了就必须是非空字符串（数字 / 数组 / 纯空白 / `true` 全拒），拒绝且不留半截产物；
  新钉 **M51**（四侧），正例对照沿用 `test_resolves_object_form_inherits_default_signer`。
- **B2（Major）**：`round_declares` 遇一条坏形状 `return [], errs` ⇒ **整批没收**，同轮合法声明一起清零
  （实测 `unaccounted 2`）。历史里一个 `by: 123` 就把该轮所有关闭证据抹掉 = **假失忆**，比响亮更糟。
  → 修：内核拆出 `resolves_entry_errors`（逐条判据；列表级 = 逐条 + 重复指纹），台账**逐条取舍**：
  坏的那条不作关闭证据 + 进 warnings，其余照常承重。新钉 **M98**。
- **B3（Major｜测试空洞）**：把 `is_blocking_critical` 退回 `bool(str(...))` 宽松版，三个测试文件 **131 条全绿**
  —— 非字符串签字在 CLI 侧先被 M48 的形状判据拒掉，这层收紧当时**没有独立钉子**。
  → 修：加**内核级**钉子 **M100**（直接断言 `is_blocking_critical` / `calculate_status` 两侧：数字签字仍
  `FAIL`、合法签字只剩 `WARN` 下限），并在 gates 行 54 的假绿测试格里写明「CLI 侧被 M48 遮蔽」。
- **B4（Minor）**：`verification.evidence` 与 `escalation.approved_by` 仍 `str()` 判 —— 同一对象里 `by` 已严、
  这两处松（实测 `evidence: ["green"]` / `approved_by: 123` 都过）。→ 修：两处走 `signed_str`；
  新钉 **M99** / **M101**，各配合法字符串的正例。注：`verification` 不喂关闭也不喂阻断，属**口径分裂**修正。
- **B5（Minor）**：`test_resolves_entry_still_needs_string_signer` 文档串写「数字签名」而体内用 `by: "lead"`
  ⇒ 它从来不是拒绝侧钉子。→ 改名 `test_resolves_entry_with_string_signer_closes`（正例对照），拒绝侧
  由 M98 / M49 / M51 承担；台账 `parse_resolves` 里重复的 `str()` 宽松也改走 `has_signed_disposition`（单源）。
- **B6–B8（文档与门册）**：`docs/map/review.md` 的 `count_floor` 锚指 `:45`（实为 `signed_str`，
  `count_floor` 在 `:61`）—— 锚门启发式（取上方最近 def）判绿，故人工补正并加 `signed_str` /
  `has_signed_disposition` / `resolves_entry_errors` 锚；`shared/gates.md` 计数行写 `M42–M48`（实为
  M42–M46 + M49 + M51，**M48 属报告形态门文件**）、`test_review_closure.py` 写 `M1–M17`（**M15/M16 属
  `tests/test_validators.py`**）⇒ 全部按「编号 + 所属文件」去歧义；`shared/independent-review.md` 的
  `verification` / `resolves` / `escalation` 三条字段口径补齐「非空字符串」。
- **门册盲区新增**：形态门**不查** `review.json.resolves` 的条目形状 —— 手写报告绕开转换器时由
  `review_closure.py` 最新轮 exit 2 兜底出声（此前只散落在代码注释，未进「不查什么」列）。
- **计数白名单踩坑**：`test_registry_counts_match_reality` 的句式白名单按「文件名 … NN 条」就近配对，
  在计数句里夹入别的测试文件名会把别人的 `NN 条` 误配过来（实测报「`tests/test_validators.py` 51 条」≠182）。
  ⇒ 计数句保持「文件名 + 条数」紧邻，交叉引用另起一句。
- **复核**：五枚新钉四段协议（基线 136 绿 → 注入 → sha256 逐字节还原 → 复绿）在隔离副本
  `/tmp/atlas-mut-rfc03r2` 里 **5/5 按预期红且还原一致**；blocker 复现脚本在修后转换器 rc=2 且不留产物。

## 5. 开放问题

1. `disposition_by` 是否需要格式约束（如必须是 `@git-handle` 或 `agent:<id>`）——现在只判「非空字符串」，
   有真实滥用再加，不臆造。
2. `verification.by` 同步收紧后，历史走查账本若有数字签名会在再校验时变红——本批实测 0 命中，
   若外部项目命中，按其「不回扫」口径只影响新落盘。
