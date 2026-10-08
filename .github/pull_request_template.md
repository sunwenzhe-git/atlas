## 🎯 本次改动摘要

一句话概括本次 PR 解决的问题与改动核心：

---

## 📋 三位一体检查清单 (Pre-flight Checklist)

流水线改动必须遵循“问题取证 + 决策记录 + 代码测试”三位一体规范：

- [ ] **问题与决策记录**：已在 `proposals/` 目录下新增记录文件（基于 `proposals/TEMPLATE.md` 编写）；
  - 📄 对应文件路径：`proposals/RFC-YYYYMMDD-XX-xxx.md`
- [ ] **测试覆盖与变异钉子**：已在 `tests/` 中为本次改动补充了测试用例或 M 系列变异证明；
- [ ] **本地全量测试通过**：本地运行 `pytest tests/` 全部绿灯（0 failed）；
- [ ] **自检命令通过**：本地运行 `python3 scripts/atlas_check.py --fast` 返回 OK。

---

## 🔍 问题现象简述 (The Problem)

简要说明在什么业务场景下发现了什么问题/误报/缺口：

---

## 💡 核心决策与权衡 (The Decision)

简要说明最终选择的解法，以及否决了哪些备选方案：

---

## 📦 涉及改动面

- [ ] 核心共享契约 (`shared/`)
- [ ] 环契约 (`rings/` 或 `apply/`)
- [ ] 适配器 (`adapters/`)
- [ ] 校验器 (`validators/`)
- [ ] 脚本工具或 CLI (`scripts/` 或 `bin/`)
- [ ] 测试用例 (`tests/`)
