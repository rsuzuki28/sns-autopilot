"""台本から投稿キュー（queue/日付/）を作り、レビュー用のまとめを書き出す。"""
from __future__ import annotations

import json
import os
import random
from datetime import date, datetime
from pathlib import Path

from . import compliance as cp
from . import render
from .config import QUEUE_DIR, load_account, load_facts, load_facts_text, tz


def _at(day: date, hhmm: str, cfg) -> str:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=tz(cfg)).isoformat()


def _cards() -> dict:
    return {c["id"]: c for c in load_facts().get("cards", []) if c.get("id")}


def build(day: date, plan: dict, research_notes: str, materials_idx: dict | None = None,
          blog_posts: list[dict] | None = None) -> Path:
    cfg = load_account()
    materials_idx = materials_idx or {}
    blog_ok = {b["url"] for b in (blog_posts or []) if b.get("sns_ok")}
    used_materials: list[tuple[str, str]] = []  # (素材ID, 投稿キー)

    def resolve(mid: str):
        """素材IDをローカルファイルに変換。使えない素材なら None。"""
        e = materials_idx.get(mid)
        if not e or e.get("deleted") or e.get("privacy_risk") or e["kind"] not in ("image", "video"):
            return None
        try:
            from . import materials
            return materials.ensure_local(e), e["kind"], e.get("text_safe_area", "middle")
        except Exception as ex:
            print(f"⚠ 素材を取得できません {mid}: {ex}")
            return None

    def check_blog(url: str, warnings: list) -> str:
        if not url:
            return ""
        if blog_posts is not None and url not in blog_ok:
            warnings.append(f"ブログ一覧に無いURLなので外しました: {url}")
            return ""
        return url

    comp = cfg["compliance"]
    cards = _cards()
    reference = load_facts_text() + "\n" + research_notes
    day_dir = QUEUE_DIR / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    review = [f"# {day.isoformat()} の投稿下書き", "",
              "内容を確認して、問題なければこのPull Requestを **マージ** してください（マージした投稿だけが予約時刻に公開されます）。",
              "投稿したくないものはファイルを削除、直したいものは `post.json` を編集してからマージしてください。", ""]
    if plan.get("notes_for_reviewer"):
        review += ["## AIからの申し送り", plan["notes_for_reviewer"], ""]

    def finish(item: dict, all_text: str) -> None:
        warnings = []
        if (nums := cp.unverified_numbers(all_text, reference)):
            warnings.append("ファクト集・リサーチで確認できない数字: " + ", ".join(nums))
        if (ng := cp.ng_hits(all_text, comp["ng_words"])):
            warnings.append("NGワード: " + ", ".join(ng))
        cid = item.get("affiliate_card_id")
        if cid and cid not in cards:
            warnings.append(f"ファクト集に無いカードID: {cid}")
        item["warnings"] = warnings
        d = day_dir / item["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- X ----
    slots = cfg["schedule"]["x"]["slots"]
    limit = 25000 if cfg["schedule"]["x"].get("premium") else 280
    for i, p in enumerate(plan.get("x_posts", [])[: len(slots)]):
        text, thread = p["text"].strip(), [t.strip() for t in p.get("thread", []) if t.strip()]
        cid = p.get("affiliate_card_id") or ""
        card = cards.get(cid)
        if card and card.get("affiliate_url"):
            text = cp.add_pr_label_x(text, comp["pr_label_x"])
            thread.append(f"{comp['pr_label_x']}{card['name']}の詳細はこちら\n{card['affiliate_url']}")
        pre_warn: list[str] = []
        blog_url = check_blog(p.get("blog_url", ""), pre_warn)
        if blog_url:
            thread.append(f"詳しくはブログにまとめています👇\n{blog_url}")
        item = {
            "id": f"x-{i + 1:02d}", "platform": "x", "kind": "post",
            "scheduled_at": _at(day, slots[i], cfg), "theme": p["theme"], "intent": p.get("intent", ""),
            "text": text, "thread": thread, "affiliate_card_id": cid, "sources": p.get("sources", []),
            "blog_url": blog_url, "media": [], "materials": [],
        }
        mid = p.get("material_id", "")
        r = resolve(mid) if mid else None
        if r and r[1] == "image":
            render.x_image(r[0], day_dir / item["id"] / "photo.jpg")
            item["media"], item["materials"] = ["photo.jpg"], [mid]
            used_materials.append((mid, f"{day.isoformat()}/{item['id']}"))
        elif mid:
            pre_warn.append(f"素材 {mid} が使えないので画像なしにしました")
        finish(item, "\n".join([text, *thread]))
        item["warnings"] = pre_warn + item["warnings"]
        (day_dir / item["id"] / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        over = [n for n, t in enumerate([text, *thread]) if cp.x_weighted_length(t) > limit]
        if over:
            item["warnings"].append(f"文字数オーバー（{', '.join(str(n + 1) for n in over)}投稿目）")
            (day_dir / item["id"] / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        review += [f"## X {slots[i]}  `{item['id']}`  ({p['theme']})", "", _quote(text)]
        if item["media"]:
            review += ["", f"![photo]({_media(item['id'], 'photo.jpg')})"]
        for t in thread:
            review += ["", "↳ " + _quote(t)]
        review += _warn_lines(item) + [""]

    # ---- Instagram ----
    ig_time = cfg["schedule"]["instagram"]["time"]
    for c in plan.get("instagram_carousel", [])[:1]:
        caption, tags = c["caption"].strip(), c.get("hashtags", [])
        cid = c.get("affiliate_card_id") or ""
        if cid and cards.get(cid, {}).get("affiliate_url"):
            caption, tags = cp.add_pr_label_ig(caption, tags, comp["pr_hashtag_instagram"])
        pre_warn = []
        c["blog_url"] = check_blog(c.get("blog_url", ""), pre_warn)
        if c["blog_url"]:
            caption += BLOG_CTA_IG
        caption = f"{caption}\n\n{comp['disclaimer']}\n\n" + " ".join(_tag(t) for t in tags[:15])
        item = {"id": "ig-carousel", "platform": "instagram", "kind": "carousel",
                "scheduled_at": _at(day, ig_time, cfg), "theme": c["theme"], "caption": caption,
                "affiliate_card_id": cid, "sources": c.get("sources", []), "blog_url": c["blog_url"], "script": c}
        mids = [m for m in [c.get("cover_material_id", ""), *[s.get("material_id", "") for s in c["slides"]]] if m]
        paths = render.render_carousel(c, cfg["design"], comp["disclaimer"], day_dir / item["id"], resolve)
        item["media"] = [p.name for p in paths]
        item["materials"] = [m for m in mids if resolve(m)]
        used_materials += [(m, f"{day.isoformat()}/{item['id']}") for m in item["materials"]]
        all_text = "\n".join([c["cover_title"], *[pt for s in c["slides"] for pt in [s["heading"], *s["points"]]], caption])
        finish(item, all_text)
        item["warnings"] = pre_warn + item["warnings"]
        (day_dir / item["id"] / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        review += [f"## Instagram カルーセル {ig_time}  ({c['theme']})", ""]
        review += [f"![{p.name}]({_media(item['id'], p.name)})" for p in paths[:3]]
        review += ["", f"（全{len(paths)}枚。残りは `{item['id']}/` フォルダ）", "", "**キャプション**", "", _quote(caption)]
        review += _warn_lines(item) + [""]

    for r in plan.get("instagram_reel", [])[:1]:
        caption, tags = r["caption"].strip(), r.get("hashtags", [])
        cid = r.get("affiliate_card_id") or ""
        if cid and cards.get(cid, {}).get("affiliate_url"):
            caption, tags = cp.add_pr_label_ig(caption, tags, comp["pr_hashtag_instagram"])
        pre_warn = []
        r["blog_url"] = check_blog(r.get("blog_url", ""), pre_warn)
        if r["blog_url"]:
            caption += BLOG_CTA_IG
        caption = f"{caption}\n\n{comp['disclaimer']}\n\n" + " ".join(_tag(t) for t in tags[:15])
        item = {"id": "ig-reel", "platform": "instagram", "kind": "reel",
                "scheduled_at": _at(day, ig_time, cfg), "theme": r["theme"], "caption": caption,
                "affiliate_card_id": cid, "sources": r.get("sources", []), "blog_url": r["blog_url"], "script": r}
        bgm = _pick_bgm(materials_idx)
        out = render.render_reel(r, cfg["design"], day_dir / item["id"], resolve, bgm)
        item["media"] = [out["video"].name]
        item["cover"] = out["cover"].name
        mids = [m for m in [r.get("hook_material_id", ""), *[s.get("material_id", "") for s in r["scenes"]]] if m]
        item["materials"] = [m for m in mids if resolve(m)]
        used_materials += [(m, f"{day.isoformat()}/{item['id']}") for m in item["materials"]]
        if not item["materials"]:
            pre_warn.append("素材の写真・動画が無いため、文字だけのリールになっています")
        all_text = "\n".join([r["hook"], *[s["text"] + s.get("narration", "") for s in r["scenes"]], caption])
        finish(item, all_text)
        item["warnings"] = pre_warn + item["warnings"]
        (day_dir / item["id"] / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        review += [f"## Instagram リール {ig_time}  ({r['theme']}, {out['duration']:.0f}秒)", "",
                   f"![cover]({_media(item['id'], 'cover.jpg')})", "", f"[▶ 動画を見る]({_media(item['id'], 'reel.mp4')})", "", "**台本**", "", f"- フック: {r['hook']}"]
        review += [f"- {s['text']}（{s['seconds']}秒）" + (f" / ナレ: {s['narration']}" if s.get("narration") else "") for s in r["scenes"]]
        review += ["", "**キャプション**", "", _quote(caption)] + _warn_lines(item) + [""]

    (day_dir / "REVIEW.md").write_text("\n".join(review), encoding="utf-8")
    if used_materials and materials_idx:
        from . import materials
        for mid, key in used_materials:
            materials.mark_used(materials_idx, [mid], key)
    return day_dir


BLOG_CTA_IG = "\n\n📝 もっと詳しい解説はプロフィールのリンク（ブログ）から"


def _pick_bgm(idx: dict):
    """ドライブのBGMフォルダから1曲選んでダウンロード。無ければ None（assets/bgm か無音）。"""
    tracks = [v for v in idx.values() if v.get("kind") == "audio" and not v.get("deleted")]
    if not tracks:
        return None
    try:
        from . import materials
        return materials.ensure_local(random.choice(tracks))
    except Exception as e:
        print(f"⚠ BGMを取得できません: {e}")
        return None


def _media(item_id: str, name: str) -> str:
    """PR本文で画像を表示するためのURL（REVIEW_MEDIA_BASE はワークフローが設定）。"""
    base = os.environ.get("REVIEW_MEDIA_BASE", "")
    return f"{base}{item_id}/{name}" + ("?raw=true" if base else "")


def _tag(t: str) -> str:
    return t if t.startswith("#") else f"#{t}"


def _quote(s: str) -> str:
    return "\n".join("> " + ln if ln else ">" for ln in s.split("\n"))


def _warn_lines(item: dict) -> list[str]:
    lines = []
    if item.get("warnings"):
        lines += ["", "⚠️ **要確認**"] + [f"- {w}" for w in item["warnings"]]
    if item.get("sources"):
        lines += ["", "出典: " + " / ".join(item["sources"])]
    return lines
