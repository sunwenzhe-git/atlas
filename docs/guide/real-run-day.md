# 真跑日协议(real-run day)——一次重装配 + 真跑,把「已立待咬」的能力一次咬合

> 决策行:`DESIGN.md` D148(2026-10-24)。适用对象:任一已装配 atlas 的采纳仓(下称靶场仓)。
> 本页是操作 runbook:按序执行、逐项勾咬合、当日留档。**它不是新门**——每一项咬合的证据都回写到既有登记面(`shared/gates.md` 对应行 / `duty-review/bugs.md` / QUEUE)。

## 0. 隔离口径(2026-10-24 维护者拍板)

- 维护者/使用者正在用的 checkout **不碰**(分支可能被占用)。真跑日在靶场仓的 **detached worktree** 里执行:`git worktree add --detach <独立目录> <基线 ref>`——不建分支、不切用户分支、**不提交**;产物(重装配、`.atlas-run/`)全部留在 worktree,用完即弃或留观察。
- 登录态 `state.json` 若被 gitignore(通常如此):从用户 checkout **只读复制**到 worktree 对应位置(不覆盖、不删除原文件;会话短命,复制后立即用)。
- 会写盘的动作(重装配、跑 E2E、复制登录态)按报备规矩在执行前说明。

## 1. 前置

1. 靶场可达且**关键 API 实响应**——根路径 200 ≠ 服务就绪(2026-10-25 实测:网关 200、业务微服务悬挂 ⇒ 页面白屏;探针更探不到,先用 curl 打一条真实业务 API 确认有响应);**本地 dev server 不是真跑通道**(采纳仓 `product/e2e/README.md` 的「切测试环境」节才是正统:profile `app_base_url` 临时指向测试环境、**不提交**,`ATLAS_BASE_URL` 只覆盖 prepare 钩子且两者必须一致;登录态按该 README 录制);2. atlas 源包 = 最新发行版(`npm 全局 atlas upgrade`);3. 靶场仓的用例分片与索引在基线 ref 上是绿的或已知态。

## 2. 流程(顺序硬)

1. **重装配**:靶场仓(或其 worktree)里跑 `install.sh --update`(等价 `atlas update`)——副本、装配戳、MANIFEST 一次到位。
2. **装配基线校验**:跑 `atlas check`,确认「装配版本」行 ok(D145 manifest 配对校验先行;`manifest.digest ≠ 装配戳 ⇒ WARN 指名重装`,逐文件指名差异)。
3. **生成物重生成 + 对账**:分片重生成;对账旧失败构件目录(`.atlas-run/`)——**Playwright 每次起跑会清空它**(留证留存窗口 = 到下一次起跑,跨轮取证先归档)。
4. **净场协议**(先例 2026-10-17):清零 → 静置 >15s 节流窗 → 复清,再起跑。
5. **真跑**:按分片跑 E2E(全局兜底链路按 gates 2.2 口径)。
6. **留档**:证据落 `product/e2e/reviews/<日期>/`(README + results.json;留证产物路径一并登记)。

## 3. 咬合清单(七项,逐项勾;咬合一处、回写一处)

| # | 咬合对象 | 判「咬到」的证据 | 回写面 |
|---|---|---|---|
| 1 | D108 失败留证 | 注红/失败轮 ⇒ `.atlas-run/<用例目录>/` 出 trace.zip+截图成对(2026-10-25 首轮实测:红 28 构件);随后全绿轮 ⇒ 零新增(实测 2 passed 零构件) | gates 2.2 行 |
| 2 | adapters 面(D70/F42 `adapter_gaps`) | `atlas check` 的 adapter_gaps 行现状与升档规则比对(逐格,不预填) | gates 对应行 |
| 3 | hover 未解观察(bugs 未解段) | 若复现:trace 在手 ⇒ 按「复现 ≥2 次 + 固定节拍证据」判升/出 | bugs.md 该行 |
| 4 | goto 计数递增(bugs 未解段) | 复跑对照:递增仍在/消失 | bugs.md 该行 |
| 5 | e2e_index WARN 基线 | 同类 WARN 是否仍 ≥3 且形态重复 ⇒ 转 DR2 判修/接受 | QUEUE 观察室 |
| 6 | D80② app_login not_ready 升档(D149) | 已声明靶场:行为不变(无 not_ready);未声明靶场:退出码 3 + 机读键 `app_login`(D103 排除类在文案指路) | gates 2.2 行 |
| 7 | 副本漂移正式解法 | `--update` 重装配后 manifest 配对 ok、旧手工补丁态被清 | bugs.md 安装与装配段 |

附:D124 就绪门浏览器判据(`probe_browser`)同轮顺带看一眼(勾选行,不单列)。

## 4. 注红条款(硬)

**注红用例是取证动作,不是缺陷证据**:它只验「留证机制生效」,其 red **不计入缺陷判据、不进 bugs.md 复发计数、不触发巡检升判**。注红用例跑完即删(或留在 worktree 随弃)。

## 5. 不做什么

不借真跑日顺手改用例语义/产品代码(那是另外的案);不在用户 checkout 上留任何痕迹;不把 worktree 产物提交进靶场仓。
