# Competition Project：基于 Nexent 的领域资产认知与决策系统

本目录是华为 ICT 大赛创新赛题三的参赛实现，总蓝图与验收标准见
[`docs/master-plan.md`](docs/master-plan.md)（下称"计划"，原文件位于 nexent 仓库 `doc/` 目录）。

## 与计划文档的映射

| 计划阶段 | 内容 | 状态 |
|---|---|---|
| G0 任务与证据基线 | 任务规范、数据盘点、upstream 锁定、数据契约 | **完成**（基线已对齐 5336b77；试标案例待双人标注） |
| G1 最小完整闭环 | 多模态导入 → 决策证据包（真实 Nexent 执行） | **完成**（离线闭环 + **Nexent 平台真实执行验证**，见 `docs/platform-integration.md`） |
| G2 本体与双驱动 | 低资源本体构建、标准映射、受限计划、补证 | **完成**（本体流水线 + 受限计划 + 补证闭环；标准映射的候选映射层待标准概念库） |
| G3 动态更新 | 版本、影响分析、局部重算、回滚 | **核心完成**（时间视图/diff/影响闭包/局部重算/发布门槛/回滚已验证） |
| G4 Skill 演化与迁移 | 受限优化、发布门槛、第二模板迁移 | **完成**（演化闭环 + 组织 B 第二模板迁移实验，见 `docs/migration-report.md`） |
| G5 开放复现 | 公开源码/样例/评测，独立环境复现 | 部分（样例与评测可复现；公开 release 待团队决策） |

G0 产出物：

- `docs/g0-baseline/upstream-lock.md` — N03：Nexent 基线锁定记录
- `docs/g0-baseline/task-spec.md` — N01：T1–T3 任务规范与试标案例模板
- `docs/g0-baseline/data-manifest-template.md` — N02：资产盘点模板
- `src/competition/contracts/` — N04：计划 5.2 节 12 类数据对象契约

G1 产出物（离线部分，N05/N09 的最小实现）：

- `data/scenario_d/` — 计划 3.3 节贯穿样例的合成数据（图纸A/检验表B/校准C/规范D-v1→v2，`synthetic: true`）
- `src/competition/pipeline/` — 入库（锚点保留）、精确业务键实体链接、三值逻辑规则求值、T1 决策证据包
- 已验证的降级路径：校准过期→unknown（数值不作裁决依据）；单位混用→确定性换算；新标准版本→结论随适用谓词改变；冲突测量→conflict；撤证→unknown 且撤销锚点不泄漏进证据包

G2 产出物（工作包 D 的计划层，N09/N13 的最小实现）：

- `src/competition/planning/operations.py` — 受限计划表示：6 个注册操作、参数签名校验、步数预算、模板形状校验（计划 9.2：LLM 只能实例化计划，不能发明操作或自由查询）
- `src/competition/planning/executor.py` — 先校验后执行：非法计划在执行前整体拒绝；每步留痕（状态、摘要、触及锚点）；计划路径与直接评估产出一致决策包
- `src/competition/planning/retrieval.py` — 证据缺口驱动补证（计划 9.1/9.4）：unknown 结论生成类型化补检索任务（资产类别+对象+时间窗+用途）；补入缺失证书后重跑计划，unknown → refuted 闭环已验证

G3 产出物（工作包 C，N14/N15 的最小实现，T2 任务）：

- `src/competition/evolution/changeset.py` — 条款级 diff：6 类变更（add/replace/retire/attribute_change/scope_change/cosmetic），仅排版变化不触发重审
- `src/competition/evolution/impact.py` — 影响闭包两条路径取并集：依赖边传播（决策版本集合引用被替代版本）+ 新适用谓词扫描（覆盖从未引用旧规则的对象）；无法识别的适用范围表达式保守扩大为待审
- `src/competition/evolution/replay.py` — 时间视图（v2 发布前的历史判定）、局部重算对照全量重算（H2 验证方式）、发布门槛三重检查（新条款锚点可用、局部=全量等价、**影响漏检检测**——未受影响批次在全量重算中变化则整体回滚）、旧文件重入不复活已废止规则
- 已验证的完整故事：v2 发布 → L-13 从 supported（v1 下合格）重审为 refuted（v2 缩紧容差）、L-14 从 supported 变 conflict；L-10/11/12（9 月订单）保持原判且决策记录原对象逐字保留

G4 产出物（工作包 E 前半，N10/N16 的最小实现）：

- `skills/cross-document-check/`、`skills/standard-change-impact/` — 两个 Nexent 原生 Skill 包：SKILL.md（仅用 Nexent 允许的 5 个元数据键，已用**真实 SkillLoader** 解析验证兼容）、manifest.json（版本/依赖/权限/限额/副作用/验收/回滚契约）、schemas/、config/domain.yaml、可执行 scripts/、活验收 evals/、CHANGELOG
- `src/competition/skills/` — manifest 契约模型（副作用分级：`writes_published` 被模型层禁止——发布必须走 ChangeSet 门禁；`read_only` 与写资源互斥）、包加载器、验证适配器
- 验证器负例覆盖：未注册工具/本体/标准版本、版本漂移、契约键藏进 SKILL.md（Nexent 会静默丢弃→警告）、缺 schema/eval/入口脚本
- evals 是活验收：测试直接通过入口脚本执行案例并断言 expected（T1 两例 + T2 一例），入口脚本可独立子进程运行

G2 本体流水线产出物（工作包 B，N07/N12 的最小实现）：

- `src/competition/ontology/model.py` — 制造业种子本体（9 类 6 关系 2 互斥约束，源自能力问题而非大而全图谱）+ 确定性单位别名表
- `src/competition/ontology/extractors.py` — 候选抽取：LLM 抽取器协议接口（`CandidateExtractor`）+ 离线规则抽取器；每个候选必须带证据锚点，confidence 仅为审核排序信号
- `src/competition/ontology/validators.py` — 约束校验：未知父类/继承环/非法域值域/类型互斥，校验失败的候选不进专家队列
- `src/competition/ontology/competency.py` — 可执行能力问题（CQ1/CQ2/CQ9）：用与决策流水线相同的求值代码测试本体行为，而非数节点
- `src/competition/ontology/pipeline.py` — 八步流水线编排：自动审核策略（高置信+校验通过）+ 审核队列按"不确定性×影响"排序 + 人工决定带理由保留为困难样本 + 发布门槛（全部候选状态明确且 CQ 全过才 published，否则带阻塞原因保持 candidate）

G4 后半产出物（工作包 F，N17 的最小实现，研究假设 H3）：

- `data/scenario_d_opt/` — 优化集场景（与锁定集 scenario_d 分离，含 micron 单位拼写的新批次，作为演化触发案例）
- `src/competition/adaptation/diagnose.py` — 失败轨迹责任层定位：单位问题→受限补丁建议；校准缺失→路由补检索而非改 Skill（计划 11.2 第 2 步：不用改提示词掩盖数据问题）
- `src/competition/adaptation/patches.py` — 受限补丁契约：仅 4 类白名单（单位别名/领域配置/提示词片段/检索参数）；权限、工具契约、验收集、数据划分、判定语义永不可自动补丁；审计三规则（白名单类型/锁定测试来源/答案型 payload 键）
- `src/competition/adaptation/gating.py` — 隔离验证双门槛：目标案例必须修复（新收益）+ 基线案例状态逐字保持（零回归，任何变化都算副作用）；通过才发布新 SkillRelease（0.1.0→0.2.0，supersedes），失败保留旧版（坏更新拦截）；漂移回退
- 已验证故事：micron 批次 unknown → 诊断单位层 → 补丁 micron→mm → 隔离验证通过 → Skill 0.2.0 发布；答案走私/锁定测试来源/错误因子三类坏补丁全部被拦截

领域 MCP 工具层（工作包 E 服务边界，N08）：

- `src/competition/mcp/` — 协议无关工具注册表 + 权限模型 + FastMCP 桥
- 三个逻辑服务边界共 7 个工具：资产与证据（`search_assets`/`get_evidence`/`resolve_entity`/`read_table_region`）、本体与标准（`analyze_change_impact`）、决策与验证（`execute_plan`/`replay_decision`）
- 身份与可见范围服务端注入：工具参数携带 `tenant`/`labels`/`permissions` 直接被拒绝（LLM 无法自扩权限）；受限证据返回与不存在**不可区分**的 `not_found`（不泄漏存在性）
- 权限联动决策：受限校准证书在决策执行中等同撤证 → 结论降级 unknown，受限锚点不进入证据包
- 统一调用留痕：每次调用记录 run_id/trace_id/耗时/状态/证据引用
- `server.py` FastMCP stdio 桥（可选依赖 `uv sync --extra mcp`）：7 个工具真实挂载并通过 MCP 协议调用验证——这是接入运行中 Nexent 的入口

第二模板迁移（N18，`docs/migration-report.md`）：

- `data/scenario_e/` — 组织 B 传动轴模板：自有表头拼写（lot_no/article/reading…）、量具编号、SPEC-E 标准、原生 mm 记录
- `ingestion.py` 列映射配置化（manifest `inspection_columns`，声明即完整映射、缺字段快速失败；锚点保留文件自身表头拼写）
- 复用证据：T1/T2 全链路零代码迁移；核心源码不含模板 B 任何字面量（硬断言）；Skill 入口脚本换数据目录即可运行

Nexent 平台真实接入（B0 证据，`docs/platform-integration.md`）：

- 领域 MCP server（http transport，:8765）注册进运行中的 Nexent（基线 5336b771）：7 工具入库（tool_id 79–85）、Agent「质量证据审核智能体」绑定工具与租户模型
- 平台级双场景验证：L-2026-10 → supported（三源锚点证据表 + replay_decision 复算）；L-2026-11 → unknown（校准过期正确降级，缺失项逐字引用）
- 接入过程修复的问题（schema 迁移重放、租户解析、模型类型、模型裁判偏差）全部如实记录于 platform-integration.md

## 目录结构

```text
competition/
  src/competition/
    contracts/        # 领域数据契约（Asset、EvidenceAnchor、DecisionRecord 等）
  tests/              # 契约单元测试
  docs/
    g0-baseline/      # G0 阶段产出物
```

后续按计划 14.3 逐步扩展 services/、skills/、benchmarks/ 等目录。

## 开发

使用 uv（Python ≥ 3.11）：

```bash
cd competition
uv sync                 # 创建虚拟环境并安装依赖
uv sync --extra mcp     # 可选：安装 FastMCP 以运行 MCP server 桥
uv run pytest           # 运行单元测试
uv run python src/competition/mcp/server.py   # 启动 MCP stdio server
```

## 证据边界

- 契约模型与单元测试已落地并通过；这证明数据对象定义自洽，不证明业务闭环可运行。
- G0 的 B0 基线（原始 Nexent 运行证据）尚未建立，见 upstream-lock.md 的行动项。
