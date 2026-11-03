#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
海军科技 · 赛鸽成绩实时查询服务
数据源：赛鸽资讯网 saige.com · 林甸县乐天赛鸽运动协会
自动翻页发现 2023～2026 全部成绩文章 + 实时查询
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from html import unescape
from threading import Lock

BLOG_ID = "18346655209"
BASE = f"http://www.saige.com/blog/{BLOG_ID}/"
LIST_URLS = [
    f"http://www.saige.com/blog/{BLOG_ID}/article.aspx?itemid=023",  # 赛绩快报（有分页）
    f"http://www.saige.com/blog/{BLOG_ID}/article.aspx?itemid=021",  # 动态
    f"http://www.saige.com/blog/{BLOG_ID}/index.aspx",
]

SEED_RACES = [
    {"name": "2026秋季560km", "url": BASE + "article-2262472.aspx"},
    {"name": "2026秋季500km(3)", "url": BASE + "article-2262425.aspx"},
    {"name": "2026秋季500km(2)", "url": BASE + "article-2262402.aspx"},
    {"name": "2026秋季500km(1)", "url": BASE + "article-2262368.aspx"},
    {"name": "2026秋季360km", "url": BASE + "article-2262344.aspx"},
    {"name": "2026秋季260km", "url": BASE + "article-2262333.aspx"},
    {"name": "2026秋季180km鸽钟测试", "url": BASE + "article-2262309.aspx"},
]

_race_cache = {"races": list(SEED_RACES), "updated": 0}
_cache_lock = Lock()
CACHE_TTL = 1800  # 30分钟


def fetch(url: str, data: bytes | None = None, timeout=15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": url,
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    for enc in ("gbk", "gb2312", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def cell_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _get_field(name: str, html: str) -> str:
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    if not m:
        m = re.search(rf'id="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _extract_races_from_html(html: str) -> dict:
    races = {}
    skip_words = ("规程", "通知", "明细", "售环", "编组", "变更", "简介",
                  "名单", "录入", "缴费", "预告", "号段", "奖金", "社会组织")
    keep_words = ("成绩", "成绩单", "比赛", "关", "km", "公里", "测试",
                  "综合", "鸽王", "鸽钟", "特比", "月月加", "竞翔单")
    for href, title in re.findall(r'href="(article-\d+\.aspx)"[^>]*>([\s\S]*?)</a>', html, re.I):
        t = cell_text(title)
        if not t or len(t) < 4:
            continue
        if any(x in t for x in skip_words) and "成绩" not in t and "成绩单" not in t:
            continue
        if not (any(x in t for x in keep_words) or re.search(r"202[2-6]", t)):
            continue
        full = BASE + href
        races[full] = {"name": t[:50], "url": full}
    return races


def _crawl_paged_list(list_url: str, max_pages: int = 12) -> dict:
    """支持 ASP.NET __doPostBack 分页的列表抓取"""
    races = {}
    try:
        html = fetch(list_url)
    except Exception as e:
        print(f"[发现] 打开列表失败 {list_url}: {e}")
        return races

    races.update(_extract_races_from_html(html))

    for page in range(2, max_pages + 1):
        vs = _get_field("__VIEWSTATE", html)
        vsg = _get_field("__VIEWSTATEGENERATOR", html)
        ev = _get_field("__EVENTVALIDATION", html)
        if not vs:
            break
        fields = {
            "__EVENTTARGET": "ctl00$cphMain$pager",
            "__EVENTARGUMENT": str(page),
            "__VIEWSTATE": vs,
            "__VIEWSTATEGENERATOR": vsg,
            "__EVENTVALIDATION": ev,
        }
        for m in re.finditer(r'<input[^>]+type="hidden"[^>]*>', html, re.I):
            tag = m.group(0)
            nm = re.search(r'name="([^"]+)"', tag)
            val = re.search(r'value="([^"]*)"', tag)
            if nm and nm.group(1) not in fields:
                fields[nm.group(1)] = val.group(1) if val else ""
        try:
            data = urllib.parse.urlencode(fields).encode("utf-8")
            html = fetch(list_url, data=data)
        except Exception as e:
            print(f"[发现] 第{page}页失败: {e}")
            break
        page_races = _extract_races_from_html(html)
        new_count = sum(1 for u in page_races if u not in races)
        races.update(page_races)
        if new_count == 0:
            break
    return races


def discover_races(force=False) -> list:
    now = time.time()
    with _cache_lock:
        if not force and _race_cache["races"] and (now - _race_cache["updated"] < CACHE_TTL):
            return list(_race_cache["races"])

    races = {r["url"]: r for r in SEED_RACES}

    for list_url in LIST_URLS:
        found = _crawl_paged_list(list_url)
        races.update(found)

    result = list(races.values())

    def sort_key(r):
        m = re.search(r"article-(\d+)", r["url"])
        return int(m.group(1)) if m else 0

    result.sort(key=sort_key, reverse=True)

    with _cache_lock:
        _race_cache["races"] = result
        _race_cache["updated"] = now

    print(f"[发现] 当前共 {len(result)} 场成绩文章（含分页往年）")
    return result


def find_ring_in_page(html: str, ring: str) -> dict | None:
    short = ring[2:] if ring.startswith("20") and len(ring) > 10 else ring
    tail = re.sub(r"^20?\d{2}-?\d{0,2}-?", "", ring)
    variants = {ring, short, ring.replace("-", ""), short.replace("-", "")}
    if tail and len(tail) >= 5:
        variants.add(tail)

    rows = re.findall(r"<tr[^>]*>[\s\S]*?</tr>", html, re.I)
    for row in rows:
        if not any(v in row for v in variants):
            continue
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, re.I)
        texts = [cell_text(c) for c in cells]
        texts = [t for t in texts if t]
        if len(texts) < 3:
            continue

        rank = texts[0] if re.match(r"^\d+$", texts[0]) else ""
        owner = sex = color = speed = ""
        for t in texts:
            if re.match(r"^\d{2,4}\.\d+", t):
                speed = t
            elif t in ("雄", "雌"):
                sex = t
            elif any(c in t for c in ("雨", "灰", "红", "白", "绛", "点", "条", "砂", "黄", "花", "麒麟")) and len(t) <= 12:
                color = t
            elif (re.search(r"[\u4e00-\u9fff]{2,12}", t)
                  and not re.match(r"^\d", t)
                  and "26-" not in t and "202" not in t
                  and "名次" not in t and "比赛" not in t
                  and "会员" not in t and "足环" not in t):
                if not owner:
                    owner = t

        return {"rank": rank, "owner": owner, "sex": sex, "color": color, "speed": speed}
    return None


def query_ring(ring: str) -> dict:
    races = discover_races()
    results = []
    errors = []

    for race in races:
        try:
            html = fetch(race["url"])
            info = find_ring_in_page(html, ring)
            if info:
                results.append({
                    "race": race["name"],
                    "rank": info["rank"],
                    "owner": info["owner"],
                    "sex": info["sex"],
                    "color": info["color"],
                    "speed": info["speed"],
                    "source": race["url"],
                })
        except Exception as e:
            errors.append(f"{race['name']}: {str(e)[:60]}")

    return {
        "ring": ring,
        "count": len(results),
        "results": results,
        "races_scanned": len(races),
        "errors": errors[:5],
        "source": "赛鸽资讯网 · 林甸县乐天赛鸽运动协会（自动翻页含往年）",
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(os.path.abspath(__file__)), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/query":
            qs = parse_qs(parsed.query)
            ring = (qs.get("ring") or [""])[0].strip()
            if not ring or not re.search(r"\d{4,}", ring):
                self._json(400, {"error": "请输入有效足环号"})
                return
            try:
                data = query_ring(ring)
                self._json(200, data)
            except Exception as e:
                self._json(500, {"error": str(e)})
            return

        if parsed.path == "/api/races":
            races = discover_races()
            self._json(200, {"count": len(races), "races": races})
            return

        if parsed.path == "/api/refresh":
            races = discover_races(force=True)
            self._json(200, {"msg": "已强制刷新", "count": len(races)})
            return

        if parsed.path in ("/", "/index.html"):
            self.path = "/index.html"
        return super().do_GET()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[请求] {args[0] if args else ''}")


def main():
    port = int(os.environ.get("PORT", 8080))
    print("正在自动发现成绩文章（含分页）…")
    races = discover_races(force=True)
    print(f"已发现 {len(races)} 场成绩")

    server = HTTPServer(("0.0.0.0", port), Handler)
    print("=" * 52)
    print("  海军科技 · 赛鸽成绩实时查询服务")
    print(f"  地址: http://0.0.0.0:{port}")
    print("  /api/query?ring=足环号")
    print("  /api/races   /api/refresh")
    print("=" * 52)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
