"""
多模态政策文件解析层。

双引擎策略：
  - MinerU（可选，按 API 调用）：复杂版面 PDF / 扫描件 / 大表格 —— 多模态识别主力
  - pdfplumber（本地回退）：文本型 PDF 直接抽取，零成本

统一输出 ParsedDocument（中间格式），下游抽取器只认这个结构。
"""

from __future__ import annotations

import json
from pathlib import Path

import pdfplumber
from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    """解析产物统一中间格式。"""

    file_id: str = Field(..., description="与爬虫 file_id 一致")
    source_file: str
    engine: str = Field("", description="mineru / pdfplumber")
    full_text: str = ""
    tables: list[list[list[str]]] = Field(default_factory=list, description="表格（二维数组），附表是政策额度/条件的载体")
    image_notes: list[str] = Field(default_factory=list, description="图片版面说明（MinerU 图文识别结果）")
    metadata: dict = Field(default_factory=dict)


def parse_pdf_local(pdf_path: Path) -> ParsedDocument:
    """本地回退引擎：文本型 PDF 直抽。"""
    tables: list[list[list[str]]] = []
    texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            for t in page.extract_tables() or []:
                tables.append([[cell or "" for cell in row] for row in t])
    return ParsedDocument(
        file_id=pdf_path.stem.split("_")[0],
        source_file=pdf_path.name,
        engine="pdfplumber",
        full_text="\n".join(texts),
        tables=tables,
    )


def parse_with_mineru(pdf_path: Path) -> ParsedDocument:
    """MinerU 解析（多模态主力引擎）。

    TODO: 接入 MinerU 官方 API（https://mineru.net 开放平台），
    流程：申请 key -> 上传文件 -> 轮询任务 -> 拉取 markdown+表格 JSON。
    未配置 MINERU_API_KEY 时抛 NotImplementedError，由上层回退到 parse_pdf_local。
    """
    import os

    if not os.getenv("MINERU_API_KEY"):
        raise NotImplementedError("未配置 MINERU_API_KEY，请回退 parse_pdf_local")
    raise NotImplementedError("MinerU API 对接在第 2 周完成（见 docs/02-六周作战计划.md）")


def parse_any(path: Path) -> ParsedDocument:
    """入口：优先 MinerU，失败/未配置则本地回退。HTML/Word 后续按需扩展。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            return parse_with_mineru(path)
        except NotImplementedError:
            return parse_pdf_local(path)
    if suffix == ".html":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        return ParsedDocument(
            file_id=path.stem.split("_")[0] if path.stem[:3] != "sz_" else path.stem,
            source_file=path.name,
            engine="bs4",
            full_text=extract_gov_body(soup),
        )
    raise ValueError(f"暂不支持的文件类型: {suffix}")


def extract_gov_body(soup: "BeautifulSoup") -> str:
    """政府网站详情页正文提取：选择器优先，回退到"低链接密度最长块"启发式。

    选择器经第 1 周试爬验证：苏州 .detail-mod（1340字纯正文/0链接）。
    新站点接入时在此追加选择器即可。
    """
    for sel in (".detail-mod", ".container.article", "#UCAP-CONTENT", ".pages_content", ".article"):
        el = soup.select_one(sel)
        if el:
            text = el.get_text("\n", strip=True)
            if len(text) > 200 and len(el.find_all("a")) < len(text) / 400:
                return text
    # 回退启发式：文本长且链接稀疏的块；再兜底 body 全文
    best, score = "", 0
    for d in soup.find_all(["div", "article", "td"]):
        text = d.get_text(strip=True)
        links = max(len(d.find_all("a")), 1)
        s = len(text) / links
        if len(text) > 400 and s > score:
            best, score = text, s
    return best or soup.get_text("\n", strip=True)


def save_parsed(doc: ParsedDocument, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{doc.file_id}.json"
    out.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return out


def load_parsed(file_id: str, in_dir: Path) -> ParsedDocument:
    return ParsedDocument.model_validate_json((in_dir / f"{file_id}.json").read_text(encoding="utf-8"))
