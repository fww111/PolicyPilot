"""最后一轮正文源探测：多个省市政府政策栏目 + 苏州站内搜索接口。"""
import re

import httpx
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
targets = {
    # (名称, URL, 正文选择器线索)
    "江苏省政策": ("https://www.jiangsu.gov.cn/col/col84096/", None),
    "南京市政府文件": ("https://www.nanjing.gov.cn/zdgk/zfxxgkml/zfwj/", None),
    "杭州市政策": ("https://www.hangzhou.gov.cn/col/col1229214212/", None),
    "宁波政策文件": ("https://www.ningbo.gov.cn/col/col1229435274/", None),
    "苏州站内搜索": ("https://suzhou.gov.cn/search?keyword=办法", None),
}
with httpx.Client(headers=headers, timeout=15, follow_redirects=True, trust_env=False) as c:
    for name, (url, _) in targets.items():
        try:
            r = c.get(url)
            r.encoding = r.charset_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "lxml")
            title = (soup.title.get_text(strip=True) if soup.title else "?")[:30]
            links = [
                (a.get_text(strip=True), a["href"])
                for a in soup.select("a[href]")
                if len(a.get_text(strip=True)) > 12
                and any(w in a.get_text(strip=True) for w in ("办法", "条例", "措施", "意见", "规定", "细则", "方案"))
            ]
            print(f"[{name}] {r.status_code} | {title} | 政策链接 {len(links)}")
            for t, h in links[:2]:
                print(f"    {t[:38]} | {h[:70]}")
        except Exception as e:
            print(f"[{name}] {type(e).__name__}: {str(e)[:70]}")
