"""终极端源探测：1) 苏州站内搜索接口 2) 江苏省府政策栏目真实链接 3) 深圳替代入口。"""
import re

import httpx
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 PolicyPilot-Research/0.1"}
with httpx.Client(headers=headers, timeout=15, follow_redirects=True, trust_env=False) as c:
    # 1) 苏州首页搜索表单
    r = c.get("https://www.suzhou.gov.cn/")
    r.encoding = r.charset_encoding or "utf-8"
    forms = re.findall(r'<form[^>]+action="([^"]+)"[^>]*>', r.text)
    search_js = re.findall(r'(?:so|search)[^"\']{0,60}(?:url|href|action)[^"\']*["\']([^"\']{8,80})', r.text, re.I)
    print("苏州搜索表单 action:", forms[:3])
    print("苏州搜索JS链接:", list(dict.fromkeys(search_js))[:5])

    # 2) 江苏省府首页：提取真实政策栏目链接
    r2 = c.get("https://www.jiangsu.gov.cn/")
    r2.encoding = r2.charset_encoding or "utf-8"
    soup = BeautifulSoup(r2.text, "lxml")
    print("\n江苏省府:", r2.status_code)
    for a in soup.select("a[href]"):
        t = a.get_text(strip=True)
        if t in ("政策文件", "政府文件", "省政府文件", "规范性文件", "政策文件库", "苏政发") or (
            len(t) > 14 and t.startswith("省政府") and any(w in t for w in ("办法", "意见", "措施"))
        ):
            print(f"  [{t[:22]}] -> {a['href'][:80]}")

    # 3) 深圳市工业和信息化局（委办局级，常有独立政策库）
    for url in ("https://gxj.sz.gov.cn/xxgk/zcfgj/", "https://gxj.sz.gov.cn/zcwjk/"):
        try:
            import ssl

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.set_ecdh_curve("secp384r1")  # 国密站常见曲线
            r3 = c.get(url, verify=ctx)
            r3.encoding = r3.charset_encoding or "utf-8"
            s3 = BeautifulSoup(r3.text, "lxml")
            n = sum(
                1
                for a in s3.select("a[href]")
                if len(a.get_text(strip=True)) > 12 and any(w in a.get_text(strip=True) for w in ("措施", "办法", "规定", "意见"))
            )
            print(f"\n深圳工信局 {url}: {r3.status_code} | 政策链接 {n}")
        except Exception as e:
            print(f"\n深圳工信局 {url}: {type(e).__name__} {str(e)[:50]}")
