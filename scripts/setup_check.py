"""一键健康检查：依赖、.env、LLM API、Neo4j 连通性。

用法：uv run python scripts/setup_check.py
第 1 周验收标准：四项全绿（LLM 与 Neo4j 允许第 2 周再补）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console
from rich.table import Table

console = Console()


def check_imports() -> tuple[bool, str]:
    try:
        import httpx, bs4, pydantic, openai, neo4j, pdfplumber, mcp  # noqa: F401
        import policy_pilot
        from policy_pilot.ontology.policy_ontology import EXAMPLE_TRIPLES
        assert len(EXAMPLE_TRIPLES) >= 3
        return True, "全部依赖可导入，本体示例实例化通过"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_env() -> tuple[bool, str]:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return False, ".env 不存在（cp .env.example .env 后填入你的 key）"
    from dotenv import load_dotenv

    load_dotenv(env)
    missing = [k for k in ("LLM_API_KEY", "NEO4J_PASSWORD") if not os.getenv(k)]
    if missing:
        return False, f".env 缺少配置: {missing}"
    return True, "LLM_API_KEY / NEO4J_PASSWORD 已配置"


def check_llm() -> tuple[bool, str]:
    try:
        from policy_pilot.extraction.triple_extractor import get_client

        client = get_client()
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "回复两个字：连通"}],
            max_tokens=8,
        )
        return True, f"LLM 应答: {resp.choices[0].message.content!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_neo4j() -> tuple[bool, str]:
    try:
        from policy_pilot.graph.graph_store import get_driver

        with get_driver().session() as s:
            s.run("RETURN 1")
        return True, "Neo4j 连接正常"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    table = Table(title="PolicyPilot 环境健康检查")
    table.add_column("检查项")
    table.add_column("状态")
    table.add_column("详情")
    for name, fn in [
        ("依赖与本体", check_imports),
        ("环境变量", check_env),
        ("LLM API", check_llm),
        ("Neo4j", check_neo4j),
    ]:
        ok, detail = fn()
        table.add_row(name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]", detail)
    console.print(table)
