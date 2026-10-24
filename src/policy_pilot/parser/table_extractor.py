"""政策附表多模态理解管道（创新 B / docs/08-G2）。

赛题任务1原文："对文本、表格、图文等多元行业数据的统一识别、理解与资产标识"。

设计：
  1. HTML 表格抽取（parse_html_tables）——政策正文中的补贴标准表/条件表是
     条款的规整化表达，信息密度高于正文
  2. 表格类型分类（classify_table）——补贴标准表 / 条件矩阵 / 其他
  3. 表格 → 本体实例（table_to_structured）——补贴标准表直接生成
     Subsidy + Condition 候选，绕过 LLM 抽取（表格是结构化的，
     准确率天然高于正文 LLM 抽取——这是"多模态价值"的实证点）

血缘：每个表格/每行都携带 asset_id（源文件）+ table_index + row_index，
可回溯到原始文件的原始行（对接创新 A 资产目录）。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup

# 表格类型判定关键词
_SUBSIDY_HINTS = ("补贴", "奖励", "资助", "标准", "金额", "万元", "额度", "扶持")
_CONDITION_HINTS = ("条件", "范围", "对象", "要求", "资质", "规模")
_CAPTION_HINTS = ("标准", "一览", "清单", "目录", "矩阵")


def table_asset_id(source_file: str, table_index: int) -> str:
    """表格级资产 ID（对接创新 A 资产目录）。"""
    h = hashlib.md5(f"{source_file}#T{table_index}".encode()).hexdigest()[:8]
    return f"AST-TBL-{h}"


def parse_pdf_tables(pdf_path, source_file: str = "") -> list[dict[str, Any]]:
    """PDF 附件表格抽取（pdfplumber）。附件是补贴标准表的主战场。"""
    import pdfplumber

    tables = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            global_idx = 0
            for page_no, page in enumerate(pdf.pages, 1):
                for tbl in page.extract_tables() or []:
                    grid = [[(c or "").strip() for c in row] for row in tbl]
                    grid = [r for r in grid if any(r)]
                    if len(grid) < 2:
                        continue
                    tables.append({
                        "asset_id": table_asset_id(source_file, global_idx),
                        "table_index": global_idx,
                        "page": page_no,
                        "headers": grid[0],
                        "rows": grid[1:],
                        "n_rows": len(grid) - 1,
                        "caption_text": "",
                    })
                    global_idx += 1
    except Exception:
        return tables
    return tables


def parse_html_tables(soup: BeautifulSoup, source_file: str = "") -> list[dict[str, Any]]:
    """抽取 HTML 全部表格为统一结构。

    返回 [{asset_id, table_index, headers, rows, n_rows, caption_text}]
    """
    tables = []
    for idx, tbl in enumerate(soup.find_all("table")):
        rows_raw = tbl.find_all("tr")
        if len(rows_raw) < 2:
            continue
        grid: list[list[str]] = []
        for tr in rows_raw:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                grid.append(cells)
        if len(grid) < 2:
            continue
        # 表头=首行（HTML th 优先，否则取第一行）
        header_cells = tbl.find_all("th")
        if header_cells:
            headers = [c.get_text(" ", strip=True) for c in header_cells]
            body = grid[1:] if grid and grid[0] == headers else grid
        else:
            headers, body = grid[0], grid[1:]
        caption_el = tbl.find("caption") or tbl.find_previous(["p", "h2", "h3"])
        tables.append({
            "asset_id": table_asset_id(source_file, idx),
            "table_index": idx,
            "headers": headers,
            "rows": body,
            "n_rows": len(body),
            "caption_text": caption_el.get_text(strip=True)[:60] if caption_el else "",
        })
    return tables


def classify_table(table: dict[str, Any]) -> str:
    """表格类型：subsidy_std 补贴标准表 / condition 条件表 / other。"""
    header_text = " ".join(table.get("headers", []))
    caption = table.get("caption_text", "")
    full = header_text + " " + caption
    if any(k in full for k in _SUBSIDY_HINTS):
        return "subsidy_std"
    if any(k in full for k in _CONDITION_HINTS):
        return "condition"
    # 正文兜底扫描
    body_text = " ".join(" ".join(r) for r in table.get("rows", []))[:500]
    hits = sum(1 for k in _SUBSIDY_HINTS if k in body_text)
    if hits >= 2:
        return "subsidy_std"
    return "other"


_MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:万元|万|元)")
_COND_FIELD_MAP = (
    (r"成立|注册.{0,4}(\d)年|年限", "founded_years"),
    (r"(?:员工|职工|人员|从业).{0,6}(\d+)", "employees"),
    (r"营收|营业收入|产值", "revenue_wan"),
    (r"高新|高企", "qualifications"),
    (r"专精特新", "qualifications"),
)


def table_to_structured(table: dict[str, Any], policy_id: str) -> dict[str, Any]:
    """补贴标准表 → Subsidy/Condition 候选（绕过 LLM，零幻觉）。

    返回 {subsidies: [...], conditions: [...], coverage: float}
    coverage = 成功映射到本体字段的行占比（多模态价值实证指标）。
    """
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    # 定位关键列：名称列 / 金额列 / 条件列
    name_col, amount_col, cond_col = None, None, None
    for i, h in enumerate(headers):
        if name_col is None and any(k in h for k in ("事项", "项目", "名称", "类别", "内容", "补贴", "奖励")):
            name_col = i
        if amount_col is None and any(k in h for k in ("金额", "标准", "额度", "万元")):
            amount_col = i
        if cond_col is None and any(k in h for k in ("条件", "对象", "范围", "要求")):
            cond_col = i
    if name_col is None and headers:
        name_col = 0

    subsidies, conditions = [], []
    mapped = 0
    for ri, row in enumerate(rows):
        get = lambda c: (row[c] if c is not None and c < len(row) else "")  # noqa: E731
        title = get(name_col).strip()
        if not title or len(title) < 2:
            continue
        sid = f"{policy_id}#TBL{table['table_index']}R{ri}"
        amount = get(amount_col)
        m = _MONEY_RE.search(amount) if amount else None
        subsidies.append({
            "subsidy_id": sid,
            "title": title[:40],
            "amount_max_wan": float(m.group(1)) if m else None,
            "raw_amount_text": (amount or "")[:30],
            "source": "table",  # 区别于正文 LLM 抽取
            "asset_id": table["asset_id"],
            "row_index": ri,
            "evidence": " | ".join(x for x in row if x)[:80],
        })
        cond_text = get(cond_col) or title
        hit_field = None
        for pat, field in _COND_FIELD_MAP:
            if re.search(pat, cond_text):
                hit_field = field
                break
        if hit_field:
            mapped += 1
            conditions.append({
                "condition_id": f"{sid}#C1",
                "field": hit_field,
                "op": "GTE" if hit_field in ("revenue_wan", "employees") else "CONTAINS",
                "value_raw": cond_text[:40],
                "source": "table",
                "asset_id": table["asset_id"],
                "evidence": cond_text[:60],
            })
    n = max(len(subsidies), 1)
    return {"subsidies": subsidies, "conditions": conditions, "coverage": round(mapped / n, 3)}
