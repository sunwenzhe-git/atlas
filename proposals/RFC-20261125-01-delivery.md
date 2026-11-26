# RFC-20261125-01 最终交付与取证

## 结论

P0–P5 已在独立工作树 `/tmp/atlas-rfc-20261125-01`（分支 `feat/rfc-20261125-01`）实现并接线。默认保持 shadow；未提供真实项目域 scorer 预测与模块校准账本，因此不宣称任何治理模块已达到 enforce 门槛。错误码、配置键、CLI 参数、关键状态流转与 AC 观测 尚无现有 adapter 生产者，schema 已保留但对应契约明确 UNVERIFIED，不用假 PASS 冒充覆盖。

未提交、未推送、未发版；未修改 `AGENTS.md`、活需求正文/schema、`changes/`、`bugs/`，未实现 RFC 明确排除的 Ops Runbook、Skill Registry、Policy 新引擎、Deprecation/Frozen Path Guard、diff 修复回推或 finish 回推门。

最终实现评审冻结输入：`proposals/RFC-20261125-01-final-review-input.json`，114 文件，SHA256 `d6ce3275fc5e0e3f06d3d5ed6d01a32c6f32a26e3511e8d561357dcdb11f9491`。已快照合并并行 main 的 beta.9/beta.10/beta.11 已提交增量（至 `5e695a3`），未并入主工作区未提交改动。

## 分阶段交付

| 阶段 | 已实现内容 | 阶段评审冻结输入 | 未解决项 / 回滚 |
|---|---|---|---|
| P0 | 能力矩阵、来源清单、版本化 schema、排除清单、接线矩阵、黄金语料与 held-out 规格 | `e1a96c446975aeccba89abeed6ccef45ffebd8689578c9942779bf337bb9ebaf` | 冻结契约后续实现若变更须重新冻结；删除新增 schema/语料并恢复接线即可回滚代码 |
| P1 | OpenSpec/Trellis/legacy docs/code/tests 代码优先迁移、代际 manifest、真实 pytest 节点证据、自动 STALE/UNVERIFIED | `79217f05434e4ccb58b5d559394175fc0e7698a2aab860b6af8cca2a8a90f11f` | 参数化 case 已要求 collect-only 与 JUnit 全量匹配，skip/xfail/子集不 verified；validator 仍只复核已绑定证据而非重跑命令；非 Python 测试节点仍 UNVERIFIED。运行 `atlas migrate --rollback` 只切上一代指针 |
| P2 | Incident 时间线/证据/根因/验收/行动项与 close/finish 共用 validator；Docs 显式登记、来源摘要、证据绑定 touch | `2162c2611294182596a49ae563ee8d77768736685cb2fb7249c65eac08d67bfc` | Incident 时间线为 append-only 权威，代码回滚不删历史；Docs 账本保留审计事件 |
| P3 | Compose/Helm/Kong 静态拓扑、structure chain 渲染、源 hash/文件集 stale 对账、动态字段级 UNVERIFIED | `2b4c3a2f5ef6a2c7fe11e1fd88807f65948c0710314e4702542b251a88a45c85` | Compose override 尚未语义合并，sorted-first 且 identity UNVERIFIED。运行 `atlas topology rollback` 只切上一代指针 |
| P4 | expected/observed/graph 三库、现有 adapter 消费、staged index 物化与重投影、head/staged blob 绑定、receipt base+binary patch+tree 重建、重建 tree 读取 semantic/origin、review artifact、分类结果/证据重放 | `fe98e197707382aeb9408bb4e312dd47bc41830638943cc4c19eac0fdbecca6c` | receipt 非数字签名，只防无意绕过；恶意伪造 origin 属显式盲区。错误码/config/CLI/state/AC 无生产者时 UNVERIFIED。运行态 receipt 可移除后由 workflow 重生成 |
| P5 | 外部分类输出契约、双候选置信度、calibration 选阈值、冻结 held-out 重放、治理度量与 N/A 语义 | `21ae7e7a88963ed4da8e022049ff01e90d8b31dbcad69115bc988cfc5fcce998` | 无真实项目域预测/业务校准账本；Semantic/Incident/Docs/Topology 的 §15 独立校准未完成；全部保持 shadow。校准账本与预测 artifact 可整体移出后重跑 |

P4/P5 的上述冻结哈希是阶段评审输入；最终 Critical/Major 修复后的整体冻结以 `d6ce3275…` 为准。

## 最终验证

### 全量回归

```text
pytest -q
=> 2468 passed, 6 skipped, 12 subtests passed in 660.41s (0:11:00)
```

完整输出：`.atlas/runs/final-full-test.txt`。该运行覆盖 beta.11 合并后的代码面；最终仅追加地图锚语法反例与删除自建临时文件，定向复验 34 条全绿。

### 定向回归

```text
pytest -q tests/test_map_anchors.py tests/test_canonical_consistency.py
=> 34 passed in 4.37s
```

最终评审 Critical 反例另跑：

```text
pytest -q tests/test_runtime_topology.py::test_dynamic_exemption_requires_explicit_owner_and_due \
  tests/test_runtime_topology.py::test_dynamic_cli_returns_two_and_missing_artifact_is_unverified \
  tests/test_governance_wiring.py::test_topology_and_semantic_clis_honor_environment_off
=> 3 passed in 0.57s
```

### 假绿 / 变异证明

M245–M251 均按“基线绿 → 注入红 → 逐字节还原 → 复绿”执行，证据位于 `.atlas/runs/mutation-proof/`。M245–M251 均在最终目标文件哈希上重新生成；运行器清除同秒同长度变更可能复用的 Python 字节码缓存，避免假红/假绿。

| 门 | 被咬判据 | 最终目标 SHA256 |
|---|---|---|
| M245 | 旧文档候选与代码冲突自动 STALE | `2bad4b3274058718e02af30c29da50ee6e94095735f0ba1846337e997f0892c3` |
| M246 | resolved/closed 验证证据引用 | `9a8a0a3164b06a9d8a9a5a5249d4a94ad8b1c92a54d8d86b4ab04a634b21531d` |
| M247 | 正文未变化不得普通 touch 清 source stale | `429500514ecbf7d5f86bdc32981ca38bddec6c7e38169ad3efd0bdb36f740c85` |
| M248 | 源文件变化未刷新 topology 必须红 | `1705e58178cd7d4b82a3b0c578aa415e16c7a477f855a41bf45f3da8837b8feb` |
| M249 | Semantic 字段类型对账 | `be7b25b4af5bf4ada06c31ca6cb341bcc8e097f4026165e72a3cb4864479fbb1` |
| M250 | receipt 临时索引 write-tree 对拍 | `319b598b6ad180d7492e9f05fa053ee2d5bd552a67ee09ad5c5736d3dcb0cfec` |
| M251 | 分类 top1 与 margin 双门槛 | `b100a0ffebec465a95e554160427268a23ad13347dc3b6dc053f8f904d97fc84` |

### 安装副本烟测

```text
python3 install.py --target /tmp/atlas-rfc-20261125-smoke-r20 --profile strict
=> 120 项安装自检 OK，0 失败
```

安装后的 migration/incident/docs/topology/contracts/receipt/metrics/classification 在 off 模式均返回 `UNVERIFIED`、rc2；held-out 元数据为 bug/change/initial 各 50 且 `tuning_allowed=false`；空项目 `atlas check --fast` 按预期因 stack-profile 占位符与缺 PRD 返回 rc1，migration 无 manifest 时正确 SKIP。机器证据：`.atlas/runs/installed-smoke-r20.json`。

### 工作区完整性

```text
git diff --check
=> 退出码 0
```

主工作树仍由并行 agent 独立修改，主 HEAD 为 `5e695a3`；本实施树未提交，HEAD 仍为基线 `1477ca1`，beta.9–beta.11 已提交增量以快照方式合并但未冒充本分支提交。

地图另用应用内浏览器做结构走查：beta.11 全景与图例已呈现，console error/warn 均为 0；内联脚本 `node --check` 通过。截图未采集（应用内浏览器视口 0×0/隐藏），证据见 `.atlas/runs/map-browser-check.json`。

## 最终双评与处置

首轮双评冻结 `c8e3976…`，两位 reviewer 独立命中 staged Semantic 假绿；合并后另有 receipt fresh-checkout、分类 mode、Topology glob/豁免继承、迁移参数化证据、Semantic 维度覆盖等 Major。原始意见见 `RFC-20261125-01-final-review-a.md` 与 `RFC-20261125-01-final-review-b.md`。

后续 r17 双评发现 off 绕过、孤儿代际 SKIP、receipt origin 重放、symlink T 类型、Docs/Incident verify 接线、Kong/Helm 静态解析、Semantic 混代与 metrics N/A 责任字段，均逐项补反例并修复。beta.10/beta.11 快照合并双评确认代码功能保留，并发现地图合并重复块、脚本语法、旧计数与弱锚点；已重建地图、清理重复、补 `node --check`、整词/显式符号锚与未纳管锚点反例。最终甲评补充的 7 个旧锚点已修正，乙评通过。处置汇总见 `RFC-20261125-01-final-review-disposition.md`。

已落实：

- Semantic 只在 base=head 时从 staged index 物化投影；head≠base 时物化 head tree，check 重投影并比对；三库写入新代目录后以 manifest 为最后提交点，失败保留 last-known-good；节点级测试无 adapter 时 UNVERIFIED。
- receipt 从 base+patch 重建 tree 后读取 semantic 与无自引用 origin；review 原文随 receipt artifact 保存，不进入正式暂存面；verify 写 workflow 来源标记，finish enforce 拒绝直跑 review；fresh checkout 物化重建树并重跑全部 in-scope validator（Incident 逐 ID 用共享关闭判据后聚合）、按 module mode/task scope 重放、拒绝 evidence 覆盖树中已有路径并绑定 support/adapter/validator/schema 运行时闭包；Semantic base/head 必须等于 receipt base；任务分类 input digest/scorer_version/阈值与校准证据分别绑定并重放，shadow/abstain/off/空或空白 evidence 不得形成 enforce receipt；构建使用临时 index，不污染真实暂存区，current-tree 校验排除 receipt origin；构建失败恢复旧 artifact，finish 后真实索引保持不变。
- Topology verify 复用 `scan_sources` 与 staged index 快照，直接匹配 staged glob，覆盖根目录新增/删除/修改；finish 同样从暂存快照刷新；动态 namespace/app/identity 均记字段级 UNVERIFIED，同 ID 不同来源不合并，逐条按 source_file 裁决，来源不明保持 UNVERIFIED，暂存面读取失败不降级；暂存路径统一 `-z` + NUL，非 ASCII 不转义；坏 JSON 结构化 rc2 并入 attempts；finish/chain 不再继承旧 owner/due；同代 refresh 先验旧指针；回滚验完整目录与 source_files/canonical digest。
- 迁移测试证据要求 collect-only 节点与 JUnit 全参数 case 一一匹配，函数/模块/类级 skip/xfail/XPASS/子集均不 verified；git 仓中 HEAD/index/inventory 共用同一 recognized+unknown 谓词双向核对，index-only 新增/删除、HEAD 源暂存删除、OpenSpec/Trellis 未知格式遗漏及工作树差异均拒绝出证据，docs 非 Markdown 不误判；损坏 Git 元数据显式 UNVERIFIED；发布新代前验旧 pointer/文件/hash/canonical digest；migration rollback off 不切指针，CLI 异常保留请求 mode；证据绑定 HEAD/staged tree/运行环境；回滚验完整文件集合与 canonical digest。
- Docs `--no-impact` 的 commit 证据必须实际触及允许来源，且当前来源字节与 commit blob 一致；裸 hash 不再可清 stale；相对链接只按文档目录解析。Docs/Incident/Topology 的真实 I/O 异常在模块边界保留为 UNVERIFIED/rc2，不再降成确定性 stale/evidence-missing，Docs `docs_unverified` 已进入 common schema 且 CLI 保留请求 mode；Incident 空白 verified_by/waiver 不得关闭，finish consumer 对缺失 resolves_incidents 默认 enforce，批量 check 优先保留 UNVERIFIED。
- 收口/CLI 反例补齐：migration 与 receipt off 不扫描、不执行测试、不发布、不完成或归档；孤儿 migration/contracts 资产不被前置 SKIP；receipt 重放索引排除 receipt-only origin；普通文件转 symlink 纳入 T 类型 scope；classification off 直调也返回 UNVERIFIED/rc2；Docs/Incident 在 verify 审查前执行共享校验；Kong 无 upstream 的 URL 保留显式目标节点；Helm 控制流拒绝静态猜测；Semantic expected 单字节快照、同锁投影/发布与 CAS；metrics 所有 N/A 含 owner/due。
- 治理 UNVERIFIED 保留原 cause 与 rc2，不映射为 freshness_fail/rc1；workflow cause 词表同步扩展。
- 无现有 producer 的 Semantic 维度保留 schema 并显式 UNVERIFIED；Semantic 发布前验旧代文件/hash/canonical digest，symlink pointer 拒绝，manifest 缺失时 observed/graph 不回退固定投影，非对象 pointer 返回 FAIL1，check 同步验完整代际与 expected 快照，并保存 previous pointer 提供原子 rollback；rollback off 不切指针；校准三件写入新代目录，ledger pointer 最后原子切换，validator 从 generation 读取并重算 generation/path/hash，非对象 pointer 返回 UNVERIFIED2，receipt 携带 generation 证据，校准亦保存 previous pointer 提供 rollback 且 off 不切换；分类落盘 I/O 返回 JSON UNVERIFIED/rc2。

## 回滚

- 代码级：移除本工作树新增文件并恢复 tracked diff；不触碰主工作区或其它 worktree。
- 迁移/拓扑：各自执行 `--rollback` / `rollback`，只原子切回上一代 manifest，不删除旧代目录。
- 运行态：receipt、calibration 账本与预测 artifact 可整体移出后重新生成；Incident/Docs 账本作为审计历史保留，不因代码回滚而删除。
- 未执行任何 git commit、push、release、reset、clean 或主工作区覆盖操作。
