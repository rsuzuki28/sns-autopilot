"""Googleスプレッドシート「SNS運用レポート」への書き込み。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import google_api as g
from .config import DATA_DIR, append_jsonl, load_account, now, read_jsonl

POST_METRICS = DATA_DIR / "post_metrics.json"   # 投稿ごとの最新の数値（30日を過ぎても最後の値を保持）
DAILY_TOTALS = DATA_DIR / "daily_totals.jsonl"   # 日ごとの累計（前日との差＝その日の伸び）

X_KEYS = ["impression_count", "like_count", "retweet_count", "bookmark_count", "reply_count", "quote_count"]
IG_KEYS = ["reach", "views", "likes", "saved", "shares", "comments"]


def engagement_rate(platform: str, m: dict) -> float:
    if platform == "x":
        base = m.get("impression_count") or 0
        eng = sum(m.get(k, 0) or 0 for k in ("like_count", "retweet_count", "reply_count", "bookmark_count", "quote_count"))
    else:
        base = m.get("reach") or 0
        eng = sum(m.get(k, 0) or 0 for k in ("likes", "comments", "saved", "shares"))
    return round(eng / base * 100, 2) if base else 0.0


def merge_post_metrics(posts: list[dict]) -> dict:
    store = json.loads(POST_METRICS.read_text(encoding="utf-8")) if POST_METRICS.exists() else {}
    for p in posts:
        store[p["key"]] = p
    POST_METRICS.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    return store


def snapshot_totals(store: dict, stats: dict) -> dict:
    """今日時点の累計を記録し、前日との差分を返す。"""
    t = now()
    tot = {"date": t.date().isoformat()}
    for key in X_KEYS:
        tot[f"x_{key}"] = sum((p["metrics"].get(key) or 0) for p in store.values() if p["platform"] == "x")
    for key in IG_KEYS:
        tot[f"ig_{key}"] = sum((p["metrics"].get(key) or 0) for p in store.values() if p["platform"] == "instagram")
    tot["x_followers"] = (stats.get("x") or {}).get("followers_count")
    tot["ig_followers"] = (stats.get("instagram") or {}).get("followers_count")
    rows = [r for r in read_jsonl(DAILY_TOTALS) if r["date"] != tot["date"]]
    prev = rows[-1] if rows else None
    rows.append(tot)
    DAILY_TOTALS.write_text("", encoding="utf-8")
    for r in rows:
        append_jsonl(DAILY_TOTALS, r)
    diff = {k: (v - (prev.get(k) or 0)) if prev and isinstance(v, (int, float)) and prev.get(k) is not None else None
            for k, v in tot.items() if k != "date"}
    return {"today": tot, "diff": diff}


def _n(v):
    return "" if v is None else v


def _upsert_row(sid: str, sheet: str, key: str, row: list) -> None:
    col_a = g.sheet_get(sid, f"'{sheet}'!A:A")
    for i, r in enumerate(col_a, start=1):
        if r and r[0] == key:
            g.sheet_update(sid, f"'{sheet}'!A{i}", [row])
            return
    g.sheet_append(sid, f"'{sheet}'!A1", [row])


def write_daily(collected: dict, stats: dict) -> None:
    """毎日の収集後に呼ぶ: 日次推移・投稿別・ダッシュボードを更新。"""
    sid = load_account()["google"]["report_spreadsheet_id"]
    store = merge_post_metrics(collected["posts"])
    snap = snapshot_totals(store, stats)
    t, d = snap["today"], snap["diff"]
    today = t["date"]
    posted_today = [p for p in store.values() if p["posted_at"][:10] == today]
    row = [
        today, _n(t["x_followers"]), _n(d.get("x_followers")), _n(t["ig_followers"]), _n(d.get("ig_followers")),
        _n((t["x_followers"] or 0) + (t["ig_followers"] or 0)) if (t["x_followers"] or t["ig_followers"]) else "",
        sum(1 for p in posted_today if p["platform"] == "x"),
        _n(d.get("x_impression_count")), _n(d.get("x_like_count")), _n(d.get("x_retweet_count")),
        _n(d.get("x_bookmark_count")), _n(d.get("x_reply_count")),
        sum(1 for p in posted_today if p["platform"] == "instagram"),
        _n(d.get("ig_reach")), _n(d.get("ig_views")), _n(d.get("ig_likes")), _n(d.get("ig_saved")),
        _n(d.get("ig_shares")), _n(d.get("ig_comments")),
        "; ".join(collected.get("errors", []))[:200],
    ]
    _upsert_row(sid, "日次推移", today, row)
    write_posts(sid, store)
    write_dashboard(sid)


def write_posts(sid: str, store: dict) -> None:
    rows = []
    for p in sorted(store.values(), key=lambda r: r["posted_at"], reverse=True):
        m = p.get("metrics", {})
        if p["platform"] == "x":
            vals = [m.get("impression_count"), "", m.get("like_count"), m.get("bookmark_count"), m.get("retweet_count"), m.get("reply_count")]
        else:
            vals = [m.get("reach"), m.get("views"), m.get("likes"), m.get("saved"), m.get("shares"), m.get("comments")]
        rows.append([
            p["posted_at"][:16].replace("T", " "), "X" if p["platform"] == "x" else "Instagram",
            {"post": "ポスト", "carousel": "カルーセル", "reel": "リール"}.get(p["kind"], p["kind"]),
            p.get("theme", ""), p.get("intent", ""), (p.get("summary") or "").replace("\n", " ")[:60],
            *[_n(v) for v in vals], f"{engagement_rate(p['platform'], m)}%", p.get("score", ""),
            len(p.get("materials", [])) and f"{len(p['materials'])}点", p.get("url", ""),
        ])
    g.sheet_clear(sid, "'投稿別'!A2:P")
    if rows:
        g.sheet_update(sid, "'投稿別'!A2", rows)


def _window_sum(totals: list[dict], key: str, days: int):
    """直近days日の伸び = 最新の累計 − days日前の累計。"""
    if not totals:
        return None
    last = totals[-1]
    cutoff = (date.fromisoformat(last["date"]) - timedelta(days=days)).isoformat()
    base = [r for r in totals if r["date"] <= cutoff]
    ref = base[-1] if base else totals[0]
    if last.get(key) is None or ref.get(key) is None:
        return None
    return last[key] - ref[key]


def write_dashboard(sid: str, highlight: str | None = None) -> None:
    totals = read_jsonl(DAILY_TOTALS)
    last = totals[-1] if totals else {}

    def both(xk, ik, days):
        x, i = _window_sum(totals, xk, days), _window_sum(totals, ik, days)
        return [_n(x), _n(i), _n((x or 0) + (i or 0)) if x is not None or i is not None else ""]

    xf, igf = last.get("x_followers"), last.get("ig_followers")
    x_imp, ig_reach = _window_sum(totals, "x_impression_count", 7), _window_sum(totals, "ig_reach", 7)
    x_eng = sum(_window_sum(totals, f"x_{k}", 7) or 0 for k in ("like_count", "retweet_count", "reply_count", "bookmark_count", "quote_count"))
    ig_eng = sum(_window_sum(totals, f"ig_{k}", 7) or 0 for k in ("likes", "comments", "saved", "shares"))
    rows = [
        [_n(xf), _n(igf), _n((xf or 0) + (igf or 0)) if xf or igf else ""],
        both("x_followers", "ig_followers", 7),
        both("x_followers", "ig_followers", 30),
        both("x_impression_count", "ig_reach", 7),
        both("x_like_count", "ig_likes", 7),
        both("x_bookmark_count", "ig_saved", 7),
        [f"{round(x_eng / x_imp * 100, 2)}%" if x_imp else "", f"{round(ig_eng / ig_reach * 100, 2)}%" if ig_reach else "", ""],
        [now().strftime("%Y-%m-%d %H:%M"), "", ""],
    ]
    g.sheet_update(sid, "'ダッシュボード'!B5:D12", rows)
    if highlight:
        g.sheet_update(sid, "'ダッシュボード'!A15", [[highlight]])


def write_weekly(summary: dict) -> None:
    """週次分析の後に呼ぶ: 週次サマリー・テーマ別・ダッシュボードのハイライトを更新。"""
    sid = load_account()["google"]["report_spreadsheet_id"]
    totals = read_jsonl(DAILY_TOTALS)
    t = now()
    iso = t.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    period = f"{(t.date() - timedelta(days=7)).isoformat()}〜{(t.date() - timedelta(days=1)).isoformat()}"
    w = lambda k: _n(_window_sum(totals, k, 7))  # noqa: E731
    last = totals[-1] if totals else {}
    row = [
        week, period, w("x_followers"), w("ig_followers"),
        _n((last.get("x_followers") or 0) + (last.get("ig_followers") or 0)) if last else "",
        w("x_impression_count"), w("ig_reach"),
        sum(_window_sum(totals, k, 7) or 0 for k in ("x_like_count", "ig_likes")),
        sum(_window_sum(totals, k, 7) or 0 for k in ("x_bookmark_count", "ig_saved")),
        sum(_window_sum(totals, k, 7) or 0 for k in ("x_retweet_count", "ig_shares")),
        summary.get("top_post", ""), summary.get("top_post_reason", ""),
        "\n".join(f"・{a}" for a in summary.get("next_actions", [])),
    ]
    _upsert_row(sid, "週次サマリー", week, row)
    write_themes(sid)
    write_dashboard(sid, summary.get("highlight"))


def write_themes(sid: str, days: int = 30) -> None:
    store = json.loads(POST_METRICS.read_text(encoding="utf-8")) if POST_METRICS.exists() else {}
    cutoff = now() - timedelta(days=days)
    groups: dict[tuple, list] = defaultdict(list)
    for p in store.values():
        if datetime.fromisoformat(p["posted_at"]) >= cutoff:
            groups[(p.get("theme", "") or "（なし）", p["platform"])].append(p)
    period = f"直近{days}日（{now().date().isoformat()}時点）"
    rows = []
    for (theme, plat), ps in sorted(groups.items(), key=lambda kv: -sum(p.get("score", 0) for p in kv[1]) / len(kv[1])):
        m = [p["metrics"] for p in ps]
        avg = lambda vals: round(sum(v or 0 for v in vals) / len(vals), 1)  # noqa: E731
        reach = [x.get("impression_count") if plat == "x" else x.get("reach") for x in m]
        likes = [x.get("like_count") if plat == "x" else x.get("likes") for x in m]
        saves = [x.get("bookmark_count") if plat == "x" else x.get("saved") for x in m]
        rows.append([period, theme, "X" if plat == "x" else "Instagram", len(ps), avg(reach), avg(likes), avg(saves),
                     f"{avg([engagement_rate(plat, x) for x in m])}%", avg([p.get('score', 0) for p in ps])])
    g.sheet_clear(sid, "'テーマ別'!A2:I")
    if rows:
        g.sheet_update(sid, "'テーマ別'!A2", rows)
