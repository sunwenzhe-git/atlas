# 跨仓 AC crosswalk

> 本表是**方案 AC → 成员 AC** 的唯一映射资产（RFC-20261111-03 §1.2 / §2.1）。
> 唯一键：`(方案AC, 成员, 成员PRD, 成员AC)`；同一键重复 ⇒ `crosswalk_duplicate_row` FAIL。
> `方案AC` 只允许 `AC-SOLUTION-NNN`；`契约AC`（`AC-CONTRACT-*`）不得出现在本表任何 AC 列。
> `成员PRD` 是成员仓内的相对路径（以 `-prd.md` 结尾），用于多 PRD 消歧；
> `成员域` 必须与 `成员AC` 前缀一致，并与该 PRD front matter 的 `domain` 一致。
> 一个成员 AC 可以回指两个方案 AC（两行合法）；孤儿成员 AC 默认不判。

| 方案AC | 成员 | 成员PRD | 成员域 | 成员AC | 依据 |
|---|---|---|---|---|---|
| `AC-SOLUTION-001` | `backend` | `product/prd/auth-prd.md` | `auth` | `AC-AUTH-012` | [必填：契约 / 规则编号或一句依据] |
