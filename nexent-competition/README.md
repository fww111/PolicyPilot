# 基于 Nexent 的领域资产认知与决策系统

华为 ICT 大赛创新赛题三参赛实现：**「标准驱动、证据约束、可持续更新的领域资产决策系统」**——
以制造业质量证据审核为业务链，把多模态理解、低资源本体、标准版本约束、跨文档推理与 Skills
复用串成一条可验证的闭环。总蓝图与验收标准见 [`docs/master-plan.md`](docs/master-plan.md)
（下称"计划"，原文件位于 nexent 仓库 `doc/` 目录）。

## 赛题

**华为 ICT 大赛创新赛创新赛题三：「基于华为 ModelEngine Nexent 打造可进化决策智能体」**

要求矩阵归纳自计划文档第 1 节（原文以用户提供的任务正文为依据）：

| 赛题要求 | 验收证据 |
|---|---|
| 文本、表格、图文统一识别、理解与资产标识 | 同一业务实体跨文件关联；每个事实返回原文/单元格/图像区域（资产登记表、定位正确率） |
| 低资源本体半自动构建与持续动态更新、标准对齐 | 标注预算曲线、专家工时；标准条款变更定位受影响本体/事实/规则/历史决策并局部修复 |
| 深度集成 Nexent MCP 与 Skills | 实际运行 trace、MCP 工具结果、Skill 内容摘要与版本绑定 |
| 检索—推理双驱动 | 检索计划、查询、证据缺口、补检索与终止记录 |
| 跨文档多跳推理与决策溯源 | 多跳联合正确率、证据完整性、撤证测试、冲突测试 |
| 可复用且快速部署的 Skill 模板 | 干净环境部署、第二场景验证、修改范围统计 |
| Nexent 平台可运行 | 安装清单、执行日志、端到端验收 |
| 入围后开源至 GitCode/GitHub | 版本化 release、NOTICE、数据许可、结果复现 |

官方入口：[华为 ICT 大赛创新赛页面](https://e.huawei.com/cn/talent/#/ict/innovation-details?zoneCode=027425&zoneId=98269700&compId=85132021)

## 项目结构

```text
competition/
  src/competition/
    contracts/        # 12 类领域数据契约（计划 5.2：Asset/EvidenceAnchor/DecisionRecord/ChangeSet...）
    pipeline/         # G1 闭环：入库锚点、精确键实体链接、三值规则求值、T1 四态决策包
    planning/         # G2：受限计划（6 注册操作）、执行留痕、证据缺口驱动补证
    ontology/         # G2：种子本体、候选抽取、约束校验、可执行能力问题、审核队列、发布门槛
    evolution/        # G3：条款 diff、双路径影响闭包、局部重算对照全量、发布门槛与回滚
    skills/           # G4：Skill manifest 契约、包加载器、验证适配器（负例覆盖）
    adaptation/       # G4：失败诊断定责、受限补丁审计、隔离验证双门槛、发布/回退
    mcp/              # 领域 MCP 工具层：三服务边界 7 工具、服务端身份注入、FastMCP 桥
  skills/             # 两个 Nexent 原生 Skill 包（cross-document-check / standard-change-impact）
  data/               # 合成样例：scenario_d（锁定集）/ scenario_d_opt（优化集）/ scenario_e（迁移集）
  tests/              # 112 个测试（契约 25 / 端到端 11 / 计划 9 / 演化 9 / 本体 13 / 适应 10 / MCP 13 / 技能 / 迁移 7）
  docs/               # 总蓝图、G0 基线文档、迁移报告、平台接入证据、运行流归档
```

## 快速开始

```bash
cd competition
uv sync                 # 创建虚拟环境（Python ≥ 3.11）
uv sync --extra mcp     # 可选：安装 FastMCP（MCP server 桥）
uv run pytest           # 运行全部 112 个测试
```

**T1 跨文档审核演示**（合成样例：图纸 A + 检验表 B + 校准 C + 规范 D）：

```bash
echo '{"batch_no": "L-2026-10"}' > /tmp/job.json
uv run python skills/cross-document-check/scripts/run_check.py \
    --input /tmp/job.json --scenario data/scenario_d
# -> status: "supported"（0.0048mm ≤ 0.005mm，量具校准有效，三源证据锚点齐全）

echo '{"batch_no": "L-2026-11"}' > /tmp/job.json   # 换成校准过期的批次
# -> status: "unknown" + missing_items: ["re-inspection: ..."]（数值不作裁决依据）
```

**T2 标准变更影响演示**（D-v1 → D-v2 缩紧容差、限定生效日期后订单）：

```bash
echo '{"standard_id": "SPEC-D", "old_version": "v1", "new_version": "v2"}' > /tmp/job.json
uv run python skills/standard-change-impact/scripts/run_impact.py \
    --input /tmp/job.json --scenario data/scenario_d
# -> L-2026-13/14 needs_review（重算后 refuted/conflict），9 月批次保持原判
```

## Nexent 平台接入（已验证）

领域 MCP server 接入运行中的 Nexent（全链路见 `docs/platform-integration.md`）：

```bash
# http transport：容器侧 Nexent 经 host.docker.internal 访问
uv run python src/competition/mcp/server.py --transport http --host 0.0.0.0 --port 8765
```

Nexent 侧注册：`POST /api/mcp/add`（server_url=`http://host.docker.internal:8765/mcp`）→
`GET /api/tool/scan_tool` 工具入库 → 创建 Agent 绑定 7 个工具。平台已验证双场景执行：
L-2026-10 → supported（Agent 自主调用 execute_plan/get_evidence/replay_decision，回答含三源锚点证据表）；
L-2026-11 → unknown（校准过期正确降级）。对话流证据归档于 `docs/evidence/`。

## 与计划文档的映射

| 计划阶段 | 内容 | 状态 |
|---|---|---|
| G0 任务与证据基线 | 任务规范、数据盘点、upstream 锁定、数据契约 | **完成**（基线已对齐 5336b77；试标案例待双人标注） |
| G1 最小完整闭环 | 多模态导入 → 决策证据包（真实 Nexent 执行） | **完成**（离线闭环 + 平台真实执行验证） |
| G2 本体与双驱动 | 低资源本体构建、标准映射、受限计划、补证 | **完成**（标准映射的候选映射层待标准概念库） |
| G3 动态更新 | 版本、影响分析、局部重算、回滚 | **核心完成**（时间视图/diff/影响闭包/发布门槛/回滚已验证） |
| G4 Skill 演化与迁移 | 受限优化、发布门槛、第二模板迁移 | **完成**（演化闭环 + 组织 B 第二模板迁移，见 `docs/migration-report.md`） |
| G5 开放复现 | 公开源码/样例/评测，独立环境复现 | 部分（样例与评测可复现；公开 release 待团队决策） |

各阶段产出物明细：

- **G0**：`docs/g0-baseline/`（upstream-lock 任务规范 / 数据盘点模板）+ `src/competition/contracts/`（12 类契约：业务身份与文件名分离、锚点不可变、同名实体禁自动合并、四态结论强制证据、Skill 发布不可原地改写）
- **G1**：`data/scenario_d/`（计划 3.3 节贯穿样例）+ `pipeline/`。已验证降级路径：校准过期→unknown（数值不作裁决依据）、单位混用→确定性换算、新标准版本→结论随适用谓词改变、冲突测量→conflict、撤证→unknown 且撤销锚点不泄漏进证据包
- **G2**：`planning/`（受限计划：6 注册操作，静态校验拒绝未注册操作/缺参/前向依赖；非法计划零步执行）+ 补证闭环（unknown→类型化补检索任务→补入证书→重算 refuted）+ `ontology/`（种子 9 类 6 关系 2 互斥；从数据发现缺失概念；CQ 用决策流水线同源代码执行；发布门槛：候选状态全明确且 CQ 全过才 published）
- **G3**：`evolution/`。条款 diff 六类变更；影响闭包双路径（依赖传播 + 新适用谓词扫描，未知范围保守扩大）；局部重算对照全量重算；发布门槛三重检查（锚点可用/局部=全量/**影响漏检检测**）+ 回滚；旧文件重入不复活已废止规则
- **G4**：`skills/` 两个 Nexent 原生包（SKILL.md 仅用 5 个允许键，**已用真实 SkillLoader 解析验证**；manifest 副作用分级：`writes_published` 被模型层禁止）+ `adaptation/`（诊断先定责：数据问题不产生 Skill 补丁；补丁白名单 4 类 + 反答案走私/锁定测试源审计；隔离验证双门槛：目标修复 + 基线零回归；坏补丁拦截已验证）
- **MCP 工具层**：`mcp/` 三服务边界 7 工具（资产与证据 / 本体与标准 / 决策与验证）。身份服务端注入，参数携带 tenant/labels 直接拒绝；受限证据返回与不存在不可区分的 `not_found`；受限校准在决策中等同撤证→unknown
- **N18 迁移**：`data/scenario_e/` 组织 B 模板（自有表头拼写/标准号/编号风格）+ manifest 列映射配置化；核心源码不含模板 B 任何字面量（硬断言）；Skill 入口脚本换数据目录即可运行

## 完成度（对照计划第 17 节验收清单）

**机制与骨架（约 90%）**：上表全部 + upstream 基线对齐（5336b771）+ 112 测试全绿。

**证据与论证（约 20%，未完成项如实列出）**：

- 30–50 试标案例库与双人标注（N01/N02）、真实授权业务数据接入——当前全部为合成样例
- 多模态真实解析（Docling/PaddleOCR 对比、PDF/OCR、图像区域锚点，N05）
- 强基线评测 B1–B5（长上下文 LLM、调优 RAG、KAG、RAG-Anything）与 13 章指标体系（N11）
- H1–H3 的正式消融与专家工时实验（13.6）；H3 与 GEPA/ACE/MCE 对照
- Skill 包在平台的"被选择加载"链路（当前平台 Agent 走 MCP 工具；Skill 包仅过真实 SkillLoader 解析验证）
- 15.1 故障注入（超时重试、并发修改、进程恢复、缓存失效）与开源复现包（N20）

所有"优于/降低/提升"类主张在取得对比实验数据前一律不作表述（计划 18.2 精神）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/master-plan.md](docs/master-plan.md) | 总蓝图：技术评审 + G0–G5 路线 + N01–N22 任务 + H1–H3 假设 + 实验协议 |
| [docs/g0-baseline/task-spec.md](docs/g0-baseline/task-spec.md) | T1–T3 任务规范：四态结论、E1–E4 错误等级、能力问题、试标模板 |
| [docs/g0-baseline/upstream-lock.md](docs/g0-baseline/upstream-lock.md) | 基线锁定（5336b771）与团队差异清单 |
| [docs/g0-baseline/data-manifest-template.md](docs/g0-baseline/data-manifest-template.md) | 数据四层盘点模板与划分规则 |
| [docs/migration-report.md](docs/migration-report.md) | 第二模板迁移实验（N18）：修改范围与复用证据 |
| [docs/platform-integration.md](docs/platform-integration.md) | Nexent 平台接入全程：架构、修复记录、B0 运行证据 |
| docs/evidence/*.sse | 平台级执行对话流原始归档（L-2026-10 / L-2026-11） |
