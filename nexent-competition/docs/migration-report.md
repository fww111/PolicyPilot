# N18：第二模板迁移实验报告

> 日期：2026-10-25。依据：计划 3.4 节（第二场景选同行业另一产品族/组织模板）、10.2 节（Skill 模板：领域配置与核心流程分离）、14.2 节 N18（迁移成功率与核心流程复用证据）。

## 1. 迁移目标

组织 B 模板（`data/scenario_e/`）：传动轴产品族 SHF-200、径向跳动特征 RUN-1、量具编号 INS-3x、标准 SPEC-E（v1 容差 0.010mm → v2 缩紧至 0.008mm，2026-11-15 后订单适用）、检验表使用组织 B 自己的表头拼写（lot_no / article / ordered_on / characteristic / reading / unit_of_measure / measured_on / gauge_id）、原生以 mm 记录。

与组织 A 模板（scenario_d）的差异维度：列名拼写、编号风格、标准号、产品族、单位记录习惯、校准证书编号风格。

## 2. 迁移所需产物（修改范围）

| 类别 | 内容 | 规模 |
|---|---|---|
| 新增数据 | `data/scenario_e/` 6 个文件（图纸/检验表/校准/两版标准/manifest） | 纯数据，零代码 |
| 领域配置 | scenario_e manifest 内 `inspection_columns` 列映射段（8 行） | 纯配置 |
| 一次性投资 | `ingestion.py` 列映射配置化（`DEFAULT_INSPECTION_COLUMNS` + `_load_inspections` 参数化，锚点保留文件自身表头拼写与列序） | 本次迁移引入；此后第三模板不再需要 |
| 核心代码改动 | pipeline 求值 / 受限计划 / 影响闭包 / Skill 包 / MCP 工具层 | **0 行** |

## 3. 复用证据（全部固化为测试 `tests/test_migration.py`）

1. **T1 全链路**：N-1001 supported（0.0072≤0.010，量具有效）；N-1002 refuted（超差）；N-1003 unknown（INS-32 校准 09-30 到期后测量——降级语义跨模板一致）；N-1004 refuted（订单 11-20 落入 v2 谓词，0.0090>0.008）。
2. **版本适用性改变结论**：N-1004 在 v1 视图下 supported，v2 注册后 refuted——与组织 A 的 L-2026-13 同构。
3. **T2 影响闭包**：SPEC-E v1→v2 的 diff → N-1004 needs_review，其余三批 applicable_unchanged——影响分析对新标准号零适配工作。
4. **Skill 模板复用**：`cross-document-check` 的入口脚本对 scenario_e 原样运行（换 scenario 目录即可），输出携带 SPEC-E@v1 版本集合。
5. **零专用代码断言**（硬证明）：核心源码 `src/` 中不出现模板 B 的任何字面量（SHF-200 / N-1001 / SPEC-E / lot_no / INS-31 / RUN-1）——不存在为第二模板写的分支或特例。
6. **配置错误快速失败**：manifest 列映射声明不完整（缺 measured_value）→ 加载即报错，不静默兜底。

## 4. 结论与边界

- 结论：第二模板迁移成功，核心流程复用率 100%；迁移成本 = 数据文件 + manifest 配置段。
- 边界（如实记录）：本实验为合成模板迁移，验证的是**机制可迁移性**，不等价于真实企业数据接入；JSON 资产（校准/标准）的字段名差异尚未配置化（组织 B 恰好同构），列入第三模板实验清单；跨行业迁移（医疗/金融，计划 3.4 表）是更强的后续验证，未在本次范围。
