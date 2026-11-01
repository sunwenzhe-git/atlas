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
  `has_signed_disposition(container, by_key, evidence_key)`：**必须是非空字符串**；四处旧调用统一改齐
  （`is_blocking_critical` / `validate_v2_finding` 的 fixed|false_positive / `verification.by` /
  台账 `has_evidence` + `declares_close`）。
- `resolves_shape_errors`（单源形状判据）新增：`by` / `evidence` 若给了但不是字符串 ⇒ 形状错。
  ⇒ 转换器 `--resolves` 直接拒绝产出；中间轮 ⇒ 该条不作关闭证据 + warnings；最新轮 ⇒ exit 2。
- 语义不变：`fixed`/`false_positive` 仍要求「两者齐备」；Critical 仍不接受 `intentional`/`ignored`。

**被否**：① 只改台账不改形态门（同一判据两处口径 ⇒ 门绿台账红的分裂）；
② 接受数字/数组签名并「靠人看」（承重件形式化即可，不必留宽松口子）；
③ 新增「签名者需在名册里」的校验（无权威名册，属臆造硬门）。

## 3. 改动面

- [x] `_support/review_policy.py`（`signed_str` / `has_signed_disposition` + 四处改齐 + `resolves` 形状）
- [x] `scripts/review_closure.py`（`has_evidence` / `declares_close` 走内核）
- [x] `tests/test_review_closure.py`（M17 数字签名不算关闭 + 字符串签名的正例对照）
- [x] `tests/test_review_report.py`（M48 形态门两侧：`by` 数字、`evidence` 为 0）
- [x] `tests/test_cli_review_convert.py`（`--resolves` 非字符串签名 ⇒ 拒绝产出）
- [x] 契约 §3 字段条 / §11、`shared/gates.md` 两行 + §4 条、`DESIGN.md` D181、两处 changelog、`docs/map/*`

## 4. 兼容与验证

- **零回扫风险**（实测）：全仓 + 真实四轮语料的 `review.json` / `findings/*.rN.json` 里
  非字符串签名或取证字段命中 **0 处** ⇒ 收紧属「纠错」而非「破坏存量」；语料台账仍
  `PASS rounds 4 prior 16 resolved 16`、形态门仍 `PASS`。
- 用例数：`test_review_closure.py` 37 → **39**（M17）、`test_review_report.py` 41 → **42**（M48）、
  `test_cli_review_convert.py` 49 → **50**。
- 行数：`_support/review_policy.py` **360**、`scripts/review_closure.py` **404**；
  锚点 `signed_str:45` / `has_signed_disposition:55` / `compute_fingerprint:98` / `resolves_shape_errors:230`。
- 四段变异协议：M17 把 `has_signed_disposition` 退回 `str()` 宽松 ⇒ 数字签名用例红；
  M48 同理退回 ⇒ 形态门用例红；日志 `/tmp/atlas-rfc03-evidence/`。
- 全量 / 安装自检 / 真实语料回路复跑见 §4.1。

### 4.1 结果实录（2026-11-01，分支 `rfc-20261101-03-signer-strictness`）

* 用例：`test_review_closure.py` **39**、`test_review_report.py` **42**、`test_cli_review_convert.py` **50**；
  全量 `pytest tests/` ⇒ **1014 passed / 5 skipped**；`test_shared_kernel.py`（单源结构门）随新内核件通过。
* 三枚钉四段协议（基线 → 注入 → sha256 逐字节还原 → 复绿，日志 `/tmp/atlas-rfc03-evidence/mutation-proof.log`）：
  * **M17 + M48**（把 `signed_str` 退回 `bool(str(value or "").strip())`）⇒ 恰红 2 条
    （`test_numeric_signature_does_not_close` / `test_numeric_disposition_by_fails_validator`）；
  * **M49**（摘掉 `resolves_shape_errors` 的字符串判据）⇒ 恰红 1 条
    （`test_resolves_numeric_signer_refused`）——两处判据独立，各配一枚钉，不靠一次注入蒙过三处。
* 零回扫实测：全仓 + 真实四轮语料（`review.json` 与 `findings/*.rN.json`，含 `verification` / `disposition_*` /
  `resolves[].by|evidence`）非字符串签名命中 **0 处**；语料四轮台账仍 `PASS rounds 4 prior 16 resolved 16`、
  形态门仍 `PASS`。
* 行为差异（收紧前后）：`disposition_by: 123` 的 Critical 报告此前「脱离阻断 + 台账判已关」，
  现两侧同时判为未关闭 ⇒ 门红 / 台账 `carried`。

## 5. 开放问题

1. `disposition_by` 是否需要格式约束（如必须是 `@git-handle` 或 `agent:<id>`）——现在只判「非空字符串」，
   有真实滥用再加，不臆造。
2. `verification.by` 同步收紧后，历史走查账本若有数字签名会在再校验时变红——本批实测 0 命中，
   若外部项目命中，按其「不回扫」口径只影响新落盘。
