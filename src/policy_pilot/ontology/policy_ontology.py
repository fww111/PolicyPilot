"""
政策领域本体（Policy Ontology）—— 创新点1的落地载体。

三维设计（区别于现有"要素标签式"政策产品的核心）：
  1. 时效维：SUPERSEDES 废止链，支撑"这政策还在不在"的多跳推理
  2. 冲突维：CONFLICTS_WITH 互斥关系，支撑"市区两级能否重复申领"
  3. 层级维：BELONGS_TO 政策层级树（国家-省-市-区），支撑上级政策穿透

对齐标准：Industry.gb_code 对齐 GB/T 4754《国民经济行业分类》，
本体概念可通过 ALIGNS_WITH 关系挂接到国标/行标条款。

该文件同时承担两个角色：
  a) Pydantic 数据模型 —— 全 pipeline 的统一数据结构
  b) ONTOLOGY_PROMPT —— 嵌入 LLM 抽取提示词的"本体约束"（创新点2：本体引导抽取）
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- 实体定义


class PolicyStatus(str, Enum):
    ACTIVE = "现行有效"
    REPEALED = "已废止"
    EXPIRED = "已失效"
    REPLACED = "已被替代"
    DRAFT = "征求意见稿"


class PolicyLevel(str, Enum):
    NATIONAL = "国家"
    PROVINCIAL = "省级"
    CITY = "市级"
    DISTRICT = "区县"


class SupportForm(str, Enum):
    CASH = "资金资助"
    TAX = "税收优惠"
    RENT = "租金减免"
    LOAN = "贷款贴息"
    TALENT = "人才补贴"
    QUALIFICATION = "资质认定"
    OTHER = "其他"


class Policy(BaseModel):
    """政策文件实体。policy_id 用发文文号保证唯一（如 深府规〔2024〕3号）。"""

    policy_id: str = Field(..., description="发文文号，唯一标识；无文号时用 标题+发布日期 哈希")
    title: str
    issuing_authority: str = Field("", description="发布机关，如 深圳市人民政府")
    level: PolicyLevel = PolicyLevel.CITY
    region_code: str = Field("", description="行政区划代码，对齐 GB/T 2260")
    publish_date: date | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    status: PolicyStatus = PolicyStatus.ACTIVE
    authority_level: int = Field(5, ge=1, le=5, description="效力层级：1法律 2行政法规 3部门规章 4省级法规/规章 5规范性文件")
    policy_types: list[str] = Field(default_factory=list, description="如 [中小企业, 科技创新, 专精特新]")
    source_url: str = ""
    raw_file: str = Field("", description="对应 data/raw 下的文件名")


class Enterprise(BaseModel):
    """企业画像实体。字段化谓词是推理匹配的基础。"""

    name: str = ""
    industry_gb_code: str = Field("", description="GB/T 4754 行业分类代码，如 I65 软件和信息技术服务业")
    industry_name: str = ""
    size: str = Field("", description="大型/中型/小型/微型（对齐工信部联企业〔2011〕300号划型标准）")
    founded_years: int | None = None
    region_code: str = ""
    qualifications: list[str] = Field(default_factory=list, description="高新技术企业/专精特新/科技型中小企业等")
    employees: int | None = None
    revenue_wan: float | None = Field(None, description="年营收（万元）")


class Article(BaseModel):
    """条款实体（审查场景一等公民）：条款级合规冲突审查的决策对象。"""

    article_id: str = Field(..., description="格式 {policy_id}#A{n}，如 深府规〔2024〕3号#A3")
    policy_id: str = ""
    article_no: str = Field("", description="条款号，如 第三条")
    text: str = Field("", description="条款原文（溯源与逐字核验的锚点）")
    topic: str = Field("", description="条款主题，如 行政处罚/资质条件/资金支持")


class Subsidy(BaseModel):
    """政策中的具体支持事项（一条政策可含多项）。"""

    subsidy_id: str = Field(..., description="格式：{policy_id}#S{n}，如 深府规〔2024〕3号#S1")
    policy_id: str = ""
    title: str = Field("", description="事项名，如 研发费用补贴")
    support_form: SupportForm = SupportForm.CASH
    amount_max_wan: float | None = None
    amount_min_wan: float | None = None
    ratio: str = Field("", description="比例型支持，如 按研发费用30%给予补贴")


class Material(BaseModel):
    material_id: str = Field(..., description="格式：M-{名称哈希8位}")
    name: str = Field(..., description="申报材料名，如 营业执照复印件")


class Department(BaseModel):
    dept_id: str = Field(..., description="格式：D-{机关名哈希8位}")
    name: str = Field(..., description="受理部门，如 深圳市工业和信息化局")


class Condition(BaseModel):
    """
    字段化申报条件（可执行谓词）—— 推理 Agent 做匹配判断的最小单元。
    例："成立年限不超过3年" -> field=founded_years, op=LTE, value=3
    """

    condition_id: str = Field(..., description="格式：{subsidy_id}#C{n}")
    field: str = Field(..., description="企业画像字段名（Enterprise 的字段或枚举值）")
    op: str = Field(..., description="EQ / NE / GT / GTE / LT / LTE / IN / CONTAINS")
    value: str | int | float | list[str]
    description: str = Field("", description="政策原文表述，供溯源展示")


# ---------------------------------------------------------------- 关系定义


class RelationType(str, Enum):
    """三维关系 + 基础关系。前三个是本工作的领域创新点。"""

    # —— 时效维 ——
    SUPERSEDES = "废止替代"  # Policy -> Policy：新政策废止旧政策
    # —— 冲突维 ——
    CONFLICTS_WITH = "互斥"  # Subsidy -> Subsidy：同类支持不可重复申领
    # —— 层级维 ——
    BELONGS_TO = "隶属"  # Policy -> Policy：区级政策隶属市级政策体系
    SUPERIOR_TO = "上位"  # Policy/Article -> Policy/Article：效力层级（上位法优先原则）
    HAS_ARTICLE = "含条款"  # Policy -> Article：条款级拆分（审查场景）
    # —— 基础关系 ——
    APPLIES_TO = "适用于"  # Subsidy -> 行业/规模/区域 等企业类别
    HAS_SUBSIDY = "含支持事项"  # Policy -> Subsidy
    REQUIRES = "需提交"  # Subsidy -> Material
    ACCEPTED_BY = "受理于"  # Subsidy -> Department
    ISSUED_BY = "发布于"  # Policy -> Department（元数据层直出）
    ALIGNS_WITH = "对齐标准"  # 本体概念 -> 国标/行标条款
    LOCATED_IN = "注册于"  # Enterprise -> Region
    QUALIFIED_AS = "具备资质"  # Enterprise -> 资质类型


class Triple(BaseModel):
    """知识图谱最小单元。confidence 由抽取 LLM 自评，低于阈值者进入人工复核队列。"""

    subject_id: str
    subject_type: str
    relation: RelationType
    object_id: str
    object_type: str
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="LLM 自评置信度")
    evidence: str = Field("", description="政策原文片段，溯源链的终点")
    source_policy_id: str = ""

    @field_validator("relation", mode="before")
    @classmethod
    def _normalize_relation(cls, v):
        """兼容 LLM 输出英文枚举名（HAS_SUBSIDY）或中文值（含支持事项）两种形式。"""
        if isinstance(v, str):
            key = v.strip().upper()
            if key in RelationType.__members__:
                return RelationType[key]
        return v


# ---------------------------------------------------------------- LLM 抽取用的本体约束提示词（创新点2种子）

ONTOLOGY_PROMPT = """你是一个政策文件知识抽取器。严格遵循以下本体约束，不得输出本体之外的实体类型或关系类型。

【实体类型】
- Policy（政策文件）：policy_id=发文文号, title, issuing_authority, level(国家/省级/市级/区县), publish_date, effective_date, expiry_date, status(现行有效/已废止/已失效/已被替代/征求意见稿), policy_types
- Subsidy（支持事项）：subsidy_id={policy_id}#S{n}, title, support_form(资金资助/税收优惠/租金减免/贷款贴息/人才补贴/资质认定/其他), amount_max_wan, amount_min_wan, ratio
- Material（申报材料）：name
- Department（受理部门）：name
- Condition（申报条件）：field(必须是企业画像字段: industry_gb_code/industry_name/size/founded_years/region_code/qualifications/employees/revenue_wan), op(EQ/NE/GT/GTE/LT/LTE/IN/CONTAINS), value, description=政策原文表述

【实体类型补充】
- Article（条款）：article_id={policy_id}#A{n}, article_no=条款号, text=条款原文, topic=条款主题。政策文件含"第X条"结构时，逐条拆分为 Article 实体。

【关系类型】（只能从这些中选）
- SUPERSEDES 废止替代：Policy->Policy，"本文件废止X文件"时建立
- CONFLICTS_WITH 互斥：Subsidy->Subsidy，"不得重复享受/就高不重复"时建立
- BELONGS_TO 隶属：Policy->Policy，"依据X文件制定/落实X文件"时建立
- SUPERIOR_TO 上位：Policy->Policy 或 Article->Article，"依据上位法/根据《X法》第X条"时建立（效力层级）
- HAS_ARTICLE 含条款：Policy->Article，政策正文逐条拆分时建立
- APPLIES_TO 适用于：Subsidy->企业类别（行业/规模/资质/区域）
- HAS_SUBSIDY 含支持事项：Policy->Subsidy
- REQUIRES 需提交：Subsidy->Material
- ACCEPTED_BY 受理于：Subsidy->Department

【输出格式】JSON 数组，每个元素：{"subject_id","subject_type","relation","object_id","object_type","confidence":0~1,"evidence":"政策原文片段"}
【硬性要求】
1. evidence 必须是原文摘录（可截断），这是溯源依据，禁止编造
2. 拿不准的条目 confidence 给 0.6 以下，不要为了好看调高
3. 金额统一换算为万元
"""


# ---------------------------------------------------------------- 示例（单元测试与 Few-shot 素材）

EXAMPLE_TRIPLES: list[Triple] = [
    Triple(
        subject_id="深府规〔2024〕3号",
        subject_type="Policy",
        relation=RelationType.HAS_SUBSIDY,
        object_id="深府规〔2024〕3号#S1",
        object_type="Subsidy",
        confidence=0.95,
        evidence="对符合条件的软件企业给予最高100万元研发补贴",
        source_policy_id="深府规〔2024〕3号",
    ),
    Triple(
        subject_id="深府规〔2024〕3号#S1",
        subject_type="Subsidy",
        relation=RelationType.CONFLICTS_WITH,
        object_id="深府规〔2023〕10号#S2",
        object_type="Subsidy",
        confidence=0.85,
        evidence="同一事项已享受市级同类补贴的，不再重复享受",
        source_policy_id="深府规〔2024〕3号",
    ),
    Triple(
        subject_id="深府规〔2024〕3号#S1",
        subject_type="Subsidy",
        relation=RelationType.APPLIES_TO,
        object_id="行业:I65",
        object_type="EnterpriseCategory",
        confidence=0.9,
        evidence="适用于软件和信息技术服务业企业",
        source_policy_id="深府规〔2024〕3号",
    ),
]

EXAMPLE_ENTERPRISE = Enterprise(
    name="示例科技有限公司",
    industry_gb_code="I65",
    industry_name="软件和信息技术服务业",
    size="小型",
    founded_years=2,
    region_code="440305",
    qualifications=["科技型中小企业"],
    employees=50,
)

EXAMPLE_CONDITION = Condition(
    condition_id="深府规〔2024〕3号#S1#C1",
    field="founded_years",
    op="LTE",
    value=3,
    description="成立不超过3年的软件企业",
)
