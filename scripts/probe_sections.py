"""探测苏州政府真正的政策文件列表栏目。"""
from bs4 import BeautifulSoup
import httpx

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
candidates = [
    "https://www.suzhou.gov.cn/szsrmzf/zcwjk/",
    "https://www.suzhou.gov.cn/szsrmzf/gfxwj/index_1.shtml",
    "https://www.suzhou.gov.cn/szsrmzf/zwgk/gfxwj/",
    "https://www.suzhou.gov.cn/szsrmzf/zfxxgk/zfgb/",
    "https://www.suzhou.gov.cn/szsrmzf/bmzwg/",
]
with httpx.Client(headers=headers, timeout=15, follow_redirects=True, trust_env=False) as c:
    for url in candidates:
        try:
            r = c.get(url)
            r.encoding = r.charset_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "lxml")
            title = soup.title.get_text(strip=True) if soup.title else "?"
            # 政策类详情链接
            links = [
                a.get_text(strip=True)
                for a in soup.select("a[href$='.shtml']")
                if len(a.get_text(strip=True)) > 12
                and any(w in a.get_text(strip=True) for w in ("办法", "条例", "措施", "意见", "规定", "细则", "方案", "目录", "公报"))
                and "gfxwj" not in a.get("href", "")
            ]
            print(f"{url}\n  -> {r.status_code} | 标题: {title[:30]} | 政策类链接: {len(links)}")
            for t in links[:3]:
                print("     ", t[:40])
        except Exception as e:
            print(f"{url} -> {type(e).__name__}: {str(e)[:60]}")
