"""冒烟测试：本体实例化、置信度分流、解析回退、评测打分逻辑。不依赖外部服务。"""

from pathlib import Path

from policy_pilot.extraction.triple_extractor import (
    ExtractionResult,
    split_by_confidence,
    _load_json_array,
)
from policy_pilot.ontology.policy_ontology import (
    EXAMPLE_CONDITION,
    EXAMPLE_ENTERPRISE,
    EXAMPLE_TRIPLES,
    RelationType,
)
from policy_pilot.eval.benchmark import EvalItem, load_benchmark, score


def test_ontology_examples_valid():
    assert len(EXAMPLE_TRIPLES) == 3
    assert any(t.relation == RelationType.CONFLICTS_WITH for t in EXAMPLE_TRIPLES)
    assert EXAMPLE_CONDITION.op == "LTE"
    assert EXAMPLE_ENTERPRISE.industry_gb_code == "I65"


def test_confidence_split():
    result = ExtractionResult(
        file_id="t",
        triples=[
            EXAMPLE_TRIPLES[0].model_copy(update={"confidence": 0.9}),
            EXAMPLE_TRIPLES[1].model_copy(update={"confidence": 0.5}),
        ],
    )
    auto, review = split_by_confidence(result)
    assert len(auto) == 1 and len(review) == 1


def test_llm_output_parsing():
    raw = '```json\n[{"subject_id":"a","subject_type":"Policy","relation":"废止替代","object_id":"b","object_type":"Policy","confidence":0.9}]\n```'
    items = _load_json_array(raw)
    assert items and items[0]["relation"] == "废止替代"


def test_benchmark_scoring():
    items = load_benchmark()
    assert len(items) >= 4  # 正式评测集80题（生成后）；无则回退4题样例
    answers = {i.item_id: {"answer": i.gold_answer, "cited_policy_ids": i.gold_policy_ids} for i in items}
    result = score("dual_drive", answers, items)
    assert result.total == len(items) and result.accuracy == 1.0  # 金标准自答应满分


def test_parser_fallback_on_html(tmp_path: Path):
    from policy_pilot.parser.doc_parser import parse_any

    f = tmp_path / "abc123_测试政策.html"
    f.write_text("<html><body>中小企业扶持政策全文</body></html>", encoding="utf-8")
    doc = parse_any(f)
    assert doc.engine == "bs4" and "中小企业" in doc.full_text
