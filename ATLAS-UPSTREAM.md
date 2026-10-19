# ATLAS-UPSTREAM 回灌登记台账

> 本文件是**源包 → 副本**方向的回灌登记点（`shared/closeout.md` §2 步骤 5）。
> 副本 → 源包方向（把线上/副本侧发现的问题带回源包）同样登记在此，四要素齐全才收口。
> 判定依据：`shared/global-rules.md` §11「传播义务」——**回灌完成前不算结束**。

## 登记条目

| # | 变更 | 原因取证 | 落地物 | 状态 |
|---|---|---|---|---|
| 1 | `scripts/e2e_console.py` 的 `snapshot()` 增加索引存在性守卫，缺文件时抛 `SnapshotError` 而非穿透为裸 `FileNotFoundError`；`tests/test_e2e_console.py` 补对应回归用例 | 现场：控制台取用例时 `snapshot()` 直接 `index.read_text()`，索引不存在时 `FileNotFoundError` 穿透 HTTP handler 线程打出 traceback，页面拿不到 JSON。同文件 `page_routes()` 早有 `is_file()` 守卫 ⇒ 缺守卫是遗漏而非设计。契约面：`SnapshotError` docstring 明令「不得静默降级为空列表」，空列表会让读者误判成「索引里没有这条用例」而非「索引不存在」 | `scripts/e2e_console.py`、`tests/test_e2e_console.py` | 已回灌 |

## 传播义务四件套（`global-rules.md` §11）

| 环节 | 状态 |
|---|---|
| ① 源包改动 | 已完成（git 工作树待提交） |
| ② 副本重装对账 | 已完成：`diff -q` 源包 vs 副本 `e2e_console.py` 无输出；空目录探针 `install.sh --target /tmp/atlas-probe --force` EXIT=0 |
| ③ 变异证明 | 已完成：基线 GREEN（15 passed）→ 注入删除守卫 430 字节 → RED（`test_snapshot_missing_index_fails_loud_not_empty_list` 失败，抛 FileNotFoundError）→ 逐字节还原（内容比对一致）→ GREEN（15 passed） |
| ④ 出厂测试套件 | 已完成：`tests/test_canonical_consistency.py` + `test_install_selfcheck.py` 18 passed；`test_e2e_console.py` + `test_validators.py` + `test_gen_e2e_scripts.py` 226 passed |

## 本轮回灌的环境事实（与后续回灌相关）

- **`atlas update` 不可用于本地源包开发后的回灌**：该命令执行的是 **npm 全局包** 内��� `install.sh`（本机为 `0.1.0-beta.26`），而本地源包为 `0.1.0-beta.29`；直接跑会把项目副本**降级**并覆盖源包侧的新改动。源包开发后的回灌须显式调用源包的 `install.sh`：

  ```bash
  ATLAS_ALLOW_OVERWRITE=1 bash <源包>/install.sh --target <项目根>
  ```

- 副本 `.atlas/VERSION` 第 3 行记录的是**装配时的源包路径**；源包目录改名后该行会失效（表现为 `atlas check` 的「装配版本」SKIP「源包路径不可达」）。重跑源包 `install.sh` 会刷新该行。
