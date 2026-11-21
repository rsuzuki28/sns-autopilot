"""数値の収集と、週次の分析レポート（次の台本に反映する「学び」の更新）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import llm
from . import platforms as pf
from .config import (ACCOUNT_STATS, LEARNINGS, METRICS_LATEST, POSTED_LOG, REPORTS_DIR, append_jsonl,
                     load_account, now, read_jsonl)


def score(platform: str, m: dict) -> float:
    """投稿の良さを1つの数字にする（保存・シェアを重く評価）。"""
    if platform == "x":
        imp = m.get("impression_count", 0) or 1
        eng = m.get("like_count", 0) + 3 * m.get("retweet_count", 0) + 2 * m.get("reply_count", 0) \
            + 4 * m.get("bookmark_count", 0) + 2 * m.get("quote_count", 0)
        return round(eng / imp * 1000 + imp / 1000, 2)
    reach = m.get("reach") or m.get("views") or 1
    eng = (m.get("likes") or 0) + 5 * (m.get("saved") or 0) + 4 * (m.get("shares") or 0) + 2 * (m.get("comments") or 0)
    return round(eng / reach * 1000 + reach / 1000, 2)


def collect(days: int = 30) -> dict:
    cfg = load_account()
    t = now(cfg)
    rows = [r for r in read_jsonl(POSTED_LOG) if t - datetime.fromisoformat(r["posted_at"]) <= timedelta(days=days)]
    out = []
    errors = []
    x_rows = [r for r in rows if r["platform"] == "x"]
    if x_rows:
        try:
            mx = pf.x_metrics([r["remote_id"] for r in x_rows])
            for r in x_rows:
                if r["remote_id"] in mx:
                    out.append({**r, "metrics": mx[r["remote_id"]], "score": score("x", mx[r["remote_id"]])})
        except Exception as e:
            errors.append(f"X: {e}")
    for r in [r for r in rows if r["platform"] == "instagram"]:
        try:
            m = pf.ig_insights(r["remote_id"])
            out.append({**r, "metrics": m, "score": score("instagram", m)})
        except Exception as e:
            errors.append(f"IG {r['remote_id']}: {e}")
    stats = {"at": t.isoformat()}
    for name, fn in (("x", pf.x_account), ("instagram", pf.ig_account)):
        try:
            stats[name] = fn()
        except Exception as e:
            errors.append(f"{name} account: {e}")
    append_jsonl(ACCOUNT_STATS, stats)
    data = {"updated_at": t.isoformat(), "posts": out, "errors": errors}
    METRICS_LATEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for e in errors:
        print("⚠", e)
    print(f"{len(out)}件の投稿の数値を更新しました")
    return data


REPORT_SYSTEM = """あなたはSNSグロースのアナリストです。クレカ・マイル・旅行ジャンルのX/Instagramアカウントの数値を分析し、
次の1週間の台本作りに直接使える、具体的で検証可能な示唆を出します。データが少ないときは断定せず「仮説」として扱います。"""


def weekly_report() -> str:
    cfg = load_account()
    t = now(cfg)
    data = json.loads(METRICS_LATEST.read_text(encoding="utf-8")) if METRICS_LATEST.exists() else {"posts": []}
    stats = read_jsonl(ACCOUNT_STATS)[-30:]
    prev = LEARNINGS.read_text(encoding="utf-8") if LEARNINGS.exists() else "（なし）"
    posts = [{k: p.get(k) for k in ("platform", "kind", "theme", "intent", "posted_at", "summary", "metrics", "score")}
             for p in data["posts"]]
    prompt = f"""# 直近30日の投稿と数値
```json
{json.dumps(posts, ensure_ascii=False)}
```

# フォロワー数などの推移
```json
{json.dumps(stats, ensure_ascii=False)}
```

# 先週までの学び
{prev}

# 収益化の目標
将来的にクレカ・旅行系のアフィリエイトで収益化したい。今はフォロワーと信頼を積み上げる段階。

次の2つを、区切り線「=====LEARNINGS=====」で分けて出力してください。

1つ目: 週次レポート（Markdown）
- サマリー（数字で）
- 伸びた投稿 / 伸びなかった投稿とその理由の仮説
- テーマ別・形式別・時間帯別の傾向
- 来週試すこと（3〜5個、検証方法つき）
- 収益化に向けた進捗と次の一手

2つ目: 台本AIに渡す「学び」（箇条書き30行以内。具体的な指示の形で。古くなった学びは消す）"""
    text = llm.generate_text(REPORT_SYSTEM, prompt)
    report, _, learnings = text.partition("=====LEARNINGS=====")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    iso = t.isocalendar()
    path = REPORTS_DIR / f"{iso.year}-W{iso.week:02d}.md"
    path.write_text(report.strip() + "\n", encoding="utf-8")
    if learnings.strip():
        LEARNINGS.write_text(f"<!-- 更新: {t.date().isoformat()} -->\n{learnings.strip()}\n", encoding="utf-8")
    print(f"レポートを書きました: {path}")
    return report
