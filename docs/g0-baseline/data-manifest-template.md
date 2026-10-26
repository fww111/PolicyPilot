# N02：数据资产盘点模板

> 状态：**模板定稿**；盘点实例待团队用真实授权资料填写。
> 计划依据：第 13.1 节数据四层、第 13.2 节划分规则、第 15.2 节复现包要求。
> 原则：来源、许可、版本、划分用途不明确的资料一律不得进入正式评测。

## 1. 数据四层登记

每份资料在 `docs/g0-baseline/data-manifest.yaml` 中登记一条：

```yaml
- record_id: DM-001
  layer: real_domain | public_benchmark | curated_challenge | synthetic
  name: 精密结构件检验记录集
  description: 图纸/检验表/校准证书/规范四类关联资料
  source: 授权企业提供 | 公开数据集 | 人工构造
  license:
    granted: yes | no | pending
    terms: "使用范围与保密条款摘要"
    public_reproducible: full | desensitized | stats_only | no
  versioning:
    content_version: v1
    related_objects: [零件P, 批次L, 仪器M]   # 关联业务对象，划分以此为单位
  usage_split: dev | dev_val | locked_test | online_stream
  owner: 负责人
  notes: "限制与特殊说明"
```

## 2. 分配比例目标（计划 13.2，成熟版）

| 集合 | 用途 | 数量目标 |
|---|---|---|
| dev | 开发/优化（含 H1–H3 训练轨迹） | 600 决策任务 |
| dev_val | 开发验证（含演化回归门槛） | 300 |
| locked_test | 锁定测试（仅在预定审计节点使用） | 300 |
| online_stream | 时间序列版本更新事件流（在线演化评测） | 版本事件 ≥3 组 |
| migration | 第二模板迁移集 | 1 套 |

试标阶段先建 30–50 个案例完成评分规则校准，再按错误分布扩展。

## 3. 强制检查项

- [ ] 每条记录的 `usage_split` 以案件/批次/设备族/来源/时间为单位，同一单位的全部改写变体在同一集合
- [ ] 合成数据全部标注 `layer: synthetic`，不得单独支撑落地结论
- [ ] 公开基准遵守原始划分与固定版本，其分数不转写为领域收益
- [ ] 不可公开资料给出统计描述、获取条件与评价限制（复现包要求）
- [ ] 金标字段完整：结论/允许结论集合、必要证据、有效标准、可接受推导、关键错误条件、争议标签
