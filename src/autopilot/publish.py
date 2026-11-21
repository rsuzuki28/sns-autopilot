"""予約時刻を過ぎた承認済み投稿を公開する。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from . import platforms as pf
from .config import POSTED_LOG, QUEUE_DIR, append_jsonl, load_account, now, read_jsonl

GRACE = timedelta(hours=6)  # これより古い予約は投稿しない（止まっていた後の一斉投稿を防ぐ）


def due_items(cfg) -> list:
    posted = {r["key"] for r in read_jsonl(POSTED_LOG)}
    t = now(cfg)
    items = []
    for f in sorted(QUEUE_DIR.glob("*/*/post.json")):
        item = json.loads(f.read_text(encoding="utf-8"))
        key = f"{f.parent.parent.name}/{item['id']}"
        at = datetime.fromisoformat(item["scheduled_at"])
        if key in posted or at > t:
            continue
        if t - at > GRACE:
            continue
        items.append((key, f.parent, item))
    return items


def run(dry_run: bool = False) -> int:
    cfg = load_account()
    count = 0
    for key, folder, item in due_items(cfg):
        summary = item.get("text") or item.get("caption", "")
        print(f"→ {key} ({item['platform']}/{item['kind']})")
        if dry_run:
            continue
        try:
            if item["platform"] == "x":
                imgs = [folder / m for m in item.get("media", [])]
                ids = pf.x_post_thread(item["text"], item.get("thread", []), imgs)
                remote_id = ids[0]
                extra = {"thread_ids": ids[1:]}
            elif item["kind"] == "carousel":
                urls = [pf.public_url(folder / m) for m in item["media"]]
                remote_id = pf.ig_post_carousel(urls, item["caption"])
                extra = {"permalink": pf.ig_permalink(remote_id)}
            elif item["kind"] == "reel":
                cover = pf.public_url(folder / item["cover"]) if item.get("cover") else None
                remote_id = pf.ig_post_reel(pf.public_url(folder / item["media"][0]), item["caption"], cover)
                extra = {"permalink": pf.ig_permalink(remote_id)}
            else:
                raise RuntimeError(f"未対応の種類: {item['kind']}")
        except Exception as e:  # 1件の失敗で他を止めない
            print(f"  ✗ 失敗: {e}")
            append_jsonl(POSTED_LOG.with_name("errors.jsonl"),
                         {"key": key, "at": now(cfg).isoformat(), "error": str(e)[:1000]})
            continue
        append_jsonl(POSTED_LOG, {
            "key": key, "platform": item["platform"], "kind": item["kind"], "remote_id": remote_id,
            "posted_at": now(cfg).isoformat(), "theme": item.get("theme", ""), "intent": item.get("intent", ""),
            "summary": summary[:200], "blog_url": item.get("blog_url", ""),
            "materials": item.get("materials", []), "url": _url(item["platform"], remote_id, extra), **extra,
        })
        print(f"  ✓ 投稿しました id={remote_id}")
        count += 1
    return count


def _url(platform: str, remote_id: str, extra: dict) -> str:
    if platform == "x":
        return f"https://x.com/i/web/status/{remote_id}"
    return extra.get("permalink", "")


if __name__ == "__main__":
    run(dry_run=os.environ.get("DRY_RUN") == "1")
