"""メインブログの記事一覧を取得する（SNSからブログへ誘導するため）。"""
from __future__ import annotations

import html
import json
import re

import requests

from .config import DATA_DIR, load_account

CACHE = DATA_DIR / "blog_posts.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; sns-autopilot)"}


def _text(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def fetch(max_pages: int = 20) -> list[dict]:
    cfg = load_account()["blog"]
    base = cfg["url"].rstrip("/")
    exclude = cfg.get("exclude_keywords", [])
    posts: dict[str, dict] = {}
    for n in range(1, max_pages + 1):
        url = base + "/" if n == 1 else f"{base}/page/{n}/"
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code != 200:
            break
        # Cocoonテーマの記事カード: <a href="記事URL" class="entry-card-wrap ..." title="タイトル">
        found = re.findall(r'<a href="(https?://[^"]+)"[^>]*class="[^"]*entry-card-wrap[^"]*"[^>]*title="([^"]*)"', r.text)
        if not found:
            found = [(u, _text(t)) for u, t in re.findall(
                r'<a href="(https?://[^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*<h2[^>]*entry-card-title[^>]*>(.*?)</h2>', r.text, re.S)]
        new = 0
        for link, title in found:
            title = html.unescape(title).strip()
            if link not in posts:
                posts[link] = {"url": link, "title": title,
                               "sns_ok": not any(k in title for k in exclude)}
                new += 1
        if new == 0:
            break
    out = list(posts.values())
    if out:
        CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load(refresh: bool = True) -> list[dict]:
    if refresh:
        try:
            return fetch()
        except Exception as e:  # ブログが落ちていても台本作成は止めない
            print(f"⚠ ブログ記事の取得に失敗: {e}")
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return []
