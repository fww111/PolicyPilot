"""
政策文件爬虫骨架。

数据源选择原则（写进初赛文档"原始数据说明"）：
  1. 全公开政府官网/惠企平台，零合规风险，评委可复现
  2. 优先覆盖 文本+附表+图文 三种形态（多模态题眼）
  3. 建议首批聚焦一个城市 300~500 份，第二城市留给"迁移验证"附加分

礼貌爬取三原则：遵守 robots.txt、限速（默认 3s）、真实 UA 说明用途。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os

load_dotenv()

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

# TODO: 逐个核实列表页 URL 与翻页参数后填入 targets 字段
SOURCES: list[dict] = [
    {
        "name": "国务院政策文件库",
        "url": "https://www.gov.cn/zhengce/zuixin/",
        "doc_types": ["html"],
        "note": "国家级政策，层级维素材",
    },
    {
        "name": "深圳市政府门户-规范性文件",
        "url": "https://www.sz.gov.cn/cn/xxgk/zfxxgj/zfgb/",
        "doc_types": ["pdf", "html"],
        "note": "市级主力数据源（首发城市）",
    },
    {
        "name": "深圳i企平台-惠企政策",
        "url": "https://sqzc.sz.gov.cn/",
        "doc_types": ["html"],
        "note": "已标签化政策条目，可做抽取结果交叉验证",
    },
    {
        "name": "工业和信息化部-政策文件",
        "url": "https://www.miit.gov.cn/jgsj/wjgs/index.html",
        "doc_types": ["html", "pdf"],
        "note": "专精特新等资质类政策",
    },
    {
        "name": "国家税务总局-税费优惠",
        "url": "https://www.chinatax.gov.cn/",
        "doc_types": ["html"],
        "note": "税收优惠方向",
    },
]


def polite_headers() -> dict[str, str]:
    return {"User-Agent": os.getenv("CRAWLER_USER_AGENT", "PolicyPilot-Research/0.1")}


def file_id_from_url(url: str) -> str:
    """URL -> 稳定文件 ID（去重键）。"""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def download_file(url: str, dest_dir: Path = RAW_DIR) -> Path:
    """下载单个政策文件（PDF/Word/HTML），限速 + 去重。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{file_id_from_url(url)}_{url.split('/')[-1].split('?')[0][:80]}"
    dest = dest_dir / fname
    if dest.exists():
        return dest
    time.sleep(float(os.getenv("CRAWLER_DELAY_SECONDS", "3")))
    with httpx.Client(follow_redirects=True, timeout=30, headers=polite_headers()) as c:
        resp = c.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def extract_doc_links(list_url: str) -> list[str]:
    """从列表页抽取政策详情页/附件链接。骨架实现：取所有 <a> 中含政策特征的链接。

    TODO: 按各源页面结构定制选择器与翻页逻辑（第 2 周任务）。
    """
    time.sleep(float(os.getenv("CRAWLER_DELAY_SECONDS", "3")))
    with httpx.Client(follow_redirects=True, timeout=30, headers=polite_headers()) as c:
        resp = c.get(list_url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(ext in href.lower() for ext in (".pdf", ".doc", ".docx", ".wps")):
            links.append(httpx.URL(list_url).join(href).__str__())
    return sorted(set(links))


if __name__ == "__main__":
    # 冒烟：打印数据源清单
    for s in SOURCES:
        print(f"[{s['name']}] {s['url']} -> {s['note']}")
    print(f"原始文件落盘目录: {RAW_DIR}")
