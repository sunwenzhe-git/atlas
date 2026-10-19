# 提案标题：五个自感知 issue 的修复批（#25 / #27 / #28 / #29 / #30）

> 提案编号：`RFC-20261019-02`
> 提案作者：@xiaobin
> 关联状态：已定案 (Accepted)
> 影响范围：核心契约 (shared) + 环契约 (rings) + 校验器 (validators) + 脚本工具 (scripts) + 模板 (templates)

> **本记录合并一批**：五案均由 `atlas report` 自感知上报（kind: `tool-semantic` / `design-conflict`），
> 现象与取证已逐案写在 GitHub issue 正文（#25 / #27 / #28 / #29 / #30），此处**不复制正文**，
> 只记「决策 + 否决理由 + 钉子 + 落地面」——符合 `single-source.md` §1「同一信息不写两处正文」。

---

## 1. 现象与取证 (The Problem & Evidence)

| issue | 类别 | 病灶一句话 | 取证 |
|---|---|---|---|
| #27 | `tool-semantic` | 实然扫描含测试文件 ⇒ 测试里的选择器字符串被计进「声明处计数」 | 门报「testid 全站唯一 —— 重复=[…]」，而页面侧只有一处声明 |
| #29 | `design-conflict` | 章节存在性只对全局 PRD 判 ⇒ 域级缺三/六/七/八 全绿 | `validate_prd.py` 参数 4 只校验 FN/R/AC 编号集合非空 |
| #25 | `design-conflict` | A/H 真相源写死项目根 `README.md` ⇒ 无 README 的项目无合法落点 | `shared/layout.md` §4 与 `single-source.md` §1 的硬编码落点 |
| #28 | `design-conflict` | 走查单确认门与真跑前提互锁，存量接入恒不可推进 | 域级 PRD 无走查节 + 该页零 testid ⇒ 分片可落、真跑必然定位不到 |
| #30 | `tool-semantic` | 独立审查在「子代理无读取手段」的宿主下无法执行 | 三次派发同一根因（工具名解析失败）；降级到自愈基线后门显示 ok 带警告 |

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 #27 —— 测试面不入实然扫描

- **定案**：`_scan_files` 跳过 `__tests__` / `test` / `tests` / `__mocks__` 目录与 `*.test.*` / `*.spec.*` / `*.cy.*` 文件。
- **为何**：测试里的 `querySelector('[data-testid=x]')` 是**页面元素的回声**，不是声明处；「声明处计数」的唯一性判据因此被污染。
- **否决**：① 只把「测试文件回声」降级为 WARN —— 回声仍会让跨文件重复判据失真，根因没堵；② 让测试文件里的字符串不参与计数但仍参与其它判据 —— 半通状态（两套口径），比全排除更难排查。

### 2.2 #29 —— 域级 PRD 章节存在性按形态分级

- **定案**：新增 `参数4 域级 PRD 章节` 一行，判据复用全局同源的 `section_of`；need 集合按形态：`增量起步` / adopt 开户 = 契约 §4「开户最小集」四节严判、其余节缺省合法记 `WARN`；其余形态要齐模板八节，缺任一节 `FAIL`。
- **为何**：issue 自己点明的风险是「开局即红而被迫批量补写」—— 八节一刀切会把存量接入项目全部打红。
- **否决**：① 八节一律 FAIL —— 违反既有「开户最小集」裁决；② 一次性豁免位（新字段）—— 为一次过渡引入永久配置面，且豁免位本身会成为新的可绕门通道。

### 2.3 #25 —— A/H 的 `off-site` 第三态

- **定案**：`categories.A/H` 合法取值扩一态 `off-site`（内容已写、落在指定落点之外，取证须带落点路径 + 不可复现说明），渲染面判 `WARN`。
- **为何**：旧词表只给「写 README」或「恒 FAIL」两条路，而写 README 本身可能违反项目约定；`off-site` 让「已写」这件事可登记，同时**按缺口记账**（WARN）而不是伪装成覆盖。
- **否决**：① 引入 `apps[].truth_sources` 自定义真相源路径 —— 新增可配置面 + 迁移仪式（`single-source.md` §3）成本远大于收益；② `off-site` 判 PASS —— 那正是 issue 指出的「把缺口伪装成已覆盖」。

### 2.4 #28 —— 走查门「应然未变」旁路 + 零 testid 推进链

- **定案**：① 前置门增设旁路：本轮只是把实现纠回**既有应然**（AC 已写明被测行为）时不走门，判据 = 可机检的 **AC 回指**；② 补三步推进链（分片落笔 → 派生薄桩 + 实现侧补齐 → 复跑真跑）与完成锚（**该页双向差集为空**），真跑遇依赖未就绪按「推进未完成」措辞报出。
- **为何**：削弱的是「重复确认」而不是「确认」—— 判断权交给 AC 回指（可机检），而不是再造一道散文确认；推进链把责任方与完成判据写死，接入者据此能判断自己在第几步。
- **否决**：① 直接豁免所有存量项目的走查门 —— 把设计期门整体拆掉；② 取消「未实现页 SKIP」让门先红 —— 会把「实现还没落地」与「真缺陷」混成同一信号。

### 2.5 #30 —— 执行可达性两条前提 + `executed` 机读锚

- **定案**：① **连通性探针** = 派发后的准入判据（探针失败 ⇒ lane 基础设施阻塞、停止同根因重试）；② **输入注入通道**（被审对象与契约源可作为上下文文本投喂，fresh context 要求的是「会话干净」，与输入来源无关）；③ 自愈基线报告补 **`executed` 布尔**（`missing` ⇒ 未执行 / `invalid` ⇒ 跑过但产物不合格），纳入基线形状锁，门文案两态分报。
- **为何**：前两条是让该环在受限宿主下**仍可执行**的唯一改动（审查能力不再与同一个工具可用性绑死）；第三条堵住「最强的人工兜底失效时反而显示为 ok 带警告」。
- **否决**：① 允许改写提示词重试直到成功 —— 同一根因会耗尽重试配额，且把执行侧故障误判成任务描述不清；② 让基线报告直接 FAIL —— 会让存量 adopt 项目在装配新版本后全部阻断写盘，超出本次修复范围。

---

## 3. 钉子与取证等级

| issue | 钉子 | 变异方向（未跑，登记待跑） |
|---|---|---|
| #27 | `test_testids_test_files_are_not_page_declarations` | 摘掉测试目录/命名过滤 ⇒ 钉红 |
| #29 | `test_prd_domain_required_sections_are_machine_checked` | 把 need 集合退回空 ⇒ 钉红 |
| #25 | `test_issue25_off_site_is_accepted_and_warned_not_silently_covered`（正反两侧） | 从 `_CAT_TOKENS` 摘 `off-site` ⇒ 正面钉红 |
| #30 | `test_review_baseline_separates_not_reviewed_from_invalid_product` | 把 `executed` 恒写 False ⇒ 第二个夹具红 |
| #28 | 无机器判据（纯契约条款）—— 如实登记为**纪律与盲区面**，不假装是门 | — |

---

## 4. 验证与测试结果 (Verification)

```bash
pytest tests/            # 521 passed / 0 failed / 4 skipped
python3 scripts/atlas_check.py --fast   # OK（本仓无 product/，各门 SKIP 属如实态）
```

**落地面**：契约 `rings/e2e/reference.md`（§4 / §5.4 / §6.2 / §12.6 / §12.7）、`rings/prd/reference.md`（§4 / §7）、
`rings/structure/reference.md`（§4 / §7）、`shared/independent-review.md`（§4 / §5）、`shared/layout.md` §4、
`shared/single-source.md` §1、`templates/structure/_meta.json`；校验器三器 + `scripts/gen_e2e_scripts.py`；
门册 `shared/gates.md` 2.1 四行登记判据与钉；`CHANGELOG.md` + `docs/guide/changelog.md` 同步。

**未做（如实登记）**：`DESIGN.md §12` 未新增 D 决策行（决策行是维护者的台账面，本次只落地 issue 正文已给出的定案）；
变异四段协议未逐条跑（钉子本身已落，变异方向登记在 §3）。
