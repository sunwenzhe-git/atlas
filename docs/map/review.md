# L1 · 评审与收口子系统(薄章)

> 子系统 #9 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.7(2026-10-25 复核)
> 一句话:**独立审查(应审 N / 实审 M 对账)+ 收口触发派生**——审查防「大模型跳文件少审」,收口把「本轮 diff」派生成必跑步骤清单。判据分散在四件脚本 + 两份契约,故本章薄:门形态细节见 [gates.md](gates.md)。

## 脚本链与契约

| 件 | 角色 |
|---|---|
| `shared/independent-review.md` | 独立审查契约:四类实例接线(§1)、骨架条款(§2)、输出双份契约(§3) |
| `shared/closeout.md` | 收口触发表:唯一真相源,派生器只解析不判定(触发表 §1) |
| `scripts/make_review_inputs.py` | 造审查输入:按模式收集文件并附摘要(`collect`,`scripts/make_review_inputs.py:50`) |
| `scripts/cli_review_convert.py` | CLI 审查输出 → `review.json` 契约 + N/M 对账(`SEVERITY_MAP`,`scripts/cli_review_convert.py:40`;缺实审数拒绝产出) |
| `scripts/validate_review_report.py` | 报告落盘形态门:分级闭集 / fingerprint 去重 / 签字取证(`validate_report`,`scripts/validate_review_report.py:71`) |
| `scripts/closeout_derive.py` | 按本轮 git diff 匹配触发表路径族,派生收口必跑步骤(`ATLAS_OWNED_PREFIXES`,`scripts/closeout_derive.py:52`) |
| `_support/review_policy.py` | 审查策略单源内核:三级闭集与处置枚举(`LEVELS`,`_support/review_policy.py:14`)、指纹去重(`compute_fingerprint`,`_support/review_policy.py:27`) |

## 两条对账平面

1. **应审 N ⇔ 实审 M**(实例⑤):独立进程只读 diff 审查,convert 阶段对账「宣称审了 N 条 ⇔ 报告里真有 N 条」,对不上拒绝产出。
2. **触发表 ⇔ 本轮 diff**:closeout 派生只做路径族匹配——表(契约)说「这类改动要跑哪几步」,派生器回答「本轮是哪几类」;表是真相源,派生不发明步骤。

## 显式盲区

- 审查**质量**本身(发现的问题对不对、漏没漏)机器不判——「不在门口信任模型结论」写进契约 §4。
- 指纹去重防重复登记,不防「同一问题换措辞重报」。

## 演化锚

| 决策/事实 | 内容 |
|---|---|
| 实例⑤ | 独立审查四类实例接线(2026-10 初) |
| D145(2026-10-23) | 收口面随装配基线批同步核验 |
| 复用 | 状态复算策略单源在 `_support/review_policy.py`(双端同错 ⇒ 门恒绿的教训,F37 族) |

## 讲述时的两个抓手

1. **N/M 对账**:「审了」必须是可数的——宣称数与实报数对不上,产物直接不出。
2. **表驱动收口**:收口步骤不是临场想的,是触发表的机械投影——人改表,机器派生。
