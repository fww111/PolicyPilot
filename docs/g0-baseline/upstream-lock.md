# N03：Nexent Upstream 基线锁定记录

> 状态：**基线已对齐**（2026-10-25 完成）。本记录如实陈述对齐过程与结论。
> 计划依据：第 2.2 节 P0"团队贡献边界未呈现"、第 14.2 节 N03。

## 当前锁定

| 项 | 值 | 证据 |
|---|---|---|
| 本地仓库 | `C:\Users\dell\Desktop\ICT\nexent` | detached HEAD（基线锁定语义） |
| **锁定基线** | `5336b771` `fix(frontend): preserve model controls for newly created conversations (#4203)`（2026-10-23 17:51:06 +0800） | 与计划文档 0.2 节评审基线**完全一致** |
| 远端 | gitcode 镜像（滞后）+ GitHub 官方源（本次经 GitHub 直连拉取） | `git remote -v` |

## 对齐过程（2026-10-25）

1. 前两次尝试失败：gitcode 镜像未同步到 10-17 之后；GitHub 直连中断（early EOF）。
2. 第三次 GitHub 直连成功拉取 `develop`（depth=40），`5336b77` 到达本地。
3. 关系核验：本地旧 HEAD `9ee52bc`（2026-10-17）是 `5336b77` 的**祖先**，期间 362 个提交，线性前进无分叉。
4. `git checkout 5336b771` 完成对齐；competition 全部 112 个测试在新基线回归通过（含通过真实 `skill_loader.py` 的 SKILL.md 兼容测试）。

## 期间 diff 对计划引用扩展点的影响复核（9ee52bc..5336b77）

| 扩展点 | 变化 | 对本项目的结论 |
|---|---|---|
| `sdk/nexent/skills/`（skill_loader/skill_manager） | **零变化** | SKILL.md 兼容性结论稳固，无需任何调整 |
| `backend/apps/skill_app.py` | 15 行（+/-） | 未依赖其实现细节，仅使用 Skill 装载语义，无影响 |
| `sdk/nexent/core/agents/`（nexent_agent/agent_model/prompt 组合器等） | 多文件中等变化 | 计划 2.1 引用的 MCP 绑定/上下文传递入口语义未变；本项目尚未直接集成这些内部模块，接入时按 5336b77 版本源码核对 |
| `sdk/nexent/data_process/` | 无输出（未列于 diff） | 无影响 |

结论：**计划第 2 节评审结论在 5336b77 基线上继续成立**，无需修订。

## 行动项状态

- [x] 基线对齐 `5336b77`（2026-10-25 完成）
- [x] 复核期间 diff 是否触及计划引用扩展点（上表）
- [ ] B0 运行证据：原始 Nexent + 混理合检索 + 固定 Skill 本地运行（Docker 部署进行中）
- [x] 团队差异清单基线建立（见下表，随开发持续更新）

## 团队差异清单

| 类型 | 范围 | 记录 |
|---|---|---|
| upstream 原有能力 | 全仓库 @ 5336b771（detached HEAD 锁定） | 计划 2.1 节引用的模块链接均以此提交为准 |
| 第三方组件 | competition/.venv（pydantic/pyyaml/fastmcp/charset-normalizer/pytest，均工具链性质） | 见 `competition/pyproject.toml` 与 `uv.lock` |
| 团队工程贡献 | `competition/`（2026-10-24 起，untracked 新增目录，零修改上游文件） | 契约层 + G1 闭环 + G2 计划/本体 + G3 演化 + G4 Skill/适应 + MCP 工具层 + 迁移实验；112 测试 |
| 团队方法贡献 | 四态决策聚合、影响闭包双路径+漏检检测、受限补丁双门槛等 | 详见 `competition/README.md` 与 `docs/migration-report.md` |
