"""1日分の台本（X投稿・インスタのカルーセル/リール）をClaudeで作る。"""
from __future__ import annotations

import json
from datetime import date

from . import llm
from .config import LEARNINGS, METRICS_LATEST, POSTED_LOG, load_account, load_facts_text, read_jsonl

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


X_POST = _obj({
    "theme": _STR,
    "text": _STR,
    "material_id": _STR,        # 添付する写真の素材ID（無ければ空文字）
    "blog_url": _STR,           # 誘導するブログ記事URL（無ければ空文字）
    "thread": _STRS,            # 続きのツリー投稿（不要なら空）
    "affiliate_card_id": _STR,  # 紹介リンクを入れるカードID（無ければ空文字）
    "sources": _STRS,
    "intent": _STR,             # 狙い（保存・リポスト・プロフ誘導など）
})
CAROUSEL = _obj({
    "theme": _STR,
    "cover_title": _STR,
    "cover_subtitle": _STR,
    "cover_material_id": _STR,
    "slides": {"type": "array", "items": _obj({"heading": _STR, "points": _STRS, "material_id": _STR})},
    "blog_url": _STR,
    "closing_message": _STR,
    "caption": _STR,
    "hashtags": _STRS,
    "affiliate_card_id": _STR,
    "sources": _STRS,
})
REEL = _obj({
    "theme": _STR,
    "hook": _STR,
    "hook_material_id": _STR,
    "scenes": {"type": "array", "items": _obj({"text": _STR, "narration": _STR, "seconds": {"type": "number"}, "material_id": _STR})},
    "blog_url": _STR,
    "caption": _STR,
    "hashtags": _STRS,
    "affiliate_card_id": _STR,
    "sources": _STRS,
})
SCHEMA = _obj({
    "x_posts": {"type": "array", "items": X_POST},
    "instagram_carousel": {"type": "array", "items": CAROUSEL},
    "instagram_reel": {"type": "array", "items": REEL},
    "notes_for_reviewer": _STR,
})


def _recent_posts(days: int = 21) -> str:
    rows = read_jsonl(POSTED_LOG)[-80:]
    lines = []
    for r in rows:
        lines.append(f"- [{r.get('platform')}/{r.get('kind')}] {r.get('summary', '')[:80]}")
    return "\n".join(lines) or "（まだ投稿はありません）"


def _top_metrics() -> str:
    if not METRICS_LATEST.exists():
        return "（まだデータがありません）"
    data = json.loads(METRICS_LATEST.read_text(encoding="utf-8"))
    rows = sorted(data.get("posts", []), key=lambda r: r.get("score", 0), reverse=True)
    top = rows[:8]
    return "\n".join(f"- score={r.get('score')} [{r['platform']}/{r['kind']}] {r.get('summary','')[:80]}" for r in top) or "（なし）"


def _blog_list(posts: list[dict]) -> str:
    ok = [p for p in posts if p.get("sns_ok")]
    return "\n".join(f"- {p['title']} {p['url']}" for p in ok[:120]) or "（取得できませんでした。blog_url は空文字に）"


def build_system(cfg: dict) -> str:
    a = cfg["account"]
    c = cfg["compliance"]
    premium = cfg["schedule"]["x"].get("premium", False)
    x_limit = "長文OK（ただし冒頭2行で惹きつける）" if premium else "1投稿あたり全角140文字以内（URLは23文字換算）"
    return f"""あなたは日本のSNS運用のプロで、次のアカウントの中の人として台本を書きます。

# アカウント
- 名前: {a['name']}
- ジャンル: {a['niche']}
- ターゲット: {a['target']}
- キャラクター:
{a['persona']}

# 絶対に守るルール
1. 数字（年会費・還元率・マイル数・ポイント数・期間・倍率など）は「確認済みファクト集」と「今日のリサーチ」に書かれているものだけを使う。無い数字は書かない。
2. キャンペーン情報には期限を書く。期限がわからなければ「期間はお早めに公式で確認を」とする。
3. 誇大表現・断定表現は禁止。特に次の表現は使わない: {', '.join(c['ng_words'])}
4. リボ払い・キャッシングを勧めない。審査の通りやすさを断言しない。
5. アフィリエイト（紹介報酬）のあるカードを紹介するときは affiliate_card_id にそのカードIDを入れる（PR表記はシステムが自動で付けます）。紹介報酬の有無で評価を変えない。
6. 過去の投稿と同じ内容・同じ切り口を繰り返さない。
7. X: {x_limit}。ハッシュタグは0〜1個。絵文字は控えめ。改行で読みやすく。
8. Instagram: カルーセルのスライドは1枚あたり見出し+3〜4項目、1項目は全角25文字程度まで。キャプション末尾に保存・フォローを促す一文。
9. リール: 冒頭1秒で止まるフック。1シーン2〜4秒、全体15〜30秒。画面テキストは1シーン全角20文字以内。
10. 出典のある情報は sources にURLを入れる。
11. 体験談は「キャラクター」と「素材の説明」に書かれている事実だけを使う。行っていない旅行・持っていないカードの体験を作らない。
12. 素材（写真・動画）は「使える素材」のIDだけを指定する。内容が合う素材が無ければ空文字（文字だけのデザインになる）。同じ素材を同じ日に使い回さない。
    - カルーセル: 表紙は写真推奨。中のスライドは図解なので写真なしが基本、体験談スライドだけ写真を使う。
    - リール: 各シーンに写真か動画を割り当てる（動画素材を優先）。素材が無いシーンは空文字。
    - X: 写真付きが向く投稿（旅行記・ラウンジ・機内食など）だけ material_id を入れる。
13. ブログ誘導: 内容が合うブログ記事があれば blog_url にそのURLを入れる（記事一覧にあるURLのみ）。X ではリンクはシステムが返信欄に入れるので本文にURLを書かない。インスタはキャプションで「詳しくはプロフィールのリンクから」と誘導する。"""


def plan(day: date, research_notes: str, blog_posts: list[dict] | None = None, materials_catalog: str = "") -> dict:
    cfg = load_account()
    wd = WEEKDAYS[day.weekday()]
    ig_kind = cfg["schedule"]["instagram"]["weekly"].get(wd, "none")
    n_x = len(cfg["schedule"]["x"]["slots"])
    themes = "\n".join(f"- {k}: {v}%" for k, v in cfg["account"]["themes"].items())
    learnings = LEARNINGS.read_text(encoding="utf-8") if LEARNINGS.exists() else "（まだありません。最初の数週間は色々な切り口を試してください）"

    ig_req = {
        "carousel": "instagram_carousel に1件（スライド5〜8枚）、instagram_reel は空配列",
        "reel": "instagram_reel に1件、instagram_carousel は空配列",
        "none": "instagram_carousel と instagram_reel はどちらも空配列",
    }[ig_kind]

    prompt = f"""{day.isoformat()}（{wd}）の投稿台本を作ってください。

# 作るもの
- x_posts: {n_x}件（投稿時刻 {', '.join(cfg['schedule']['x']['slots'])} の順。朝は軽め、夜は保存されやすい有益まとめ）
- {ig_req}

# テーマ比率（1週間単位で近づける）
{themes}

# これまでの分析からの学び（必ず反映）
{learnings}

# 反応が良かった過去の投稿
{_top_metrics()}

# 最近の投稿（重複禁止）
{_recent_posts()}

# 確認済みファクト集
```yaml
{load_facts_text()}
```

# 今日のリサーチ
{research_notes}

# ブログ記事一覧（誘導先。この中のURLだけ使う）
{_blog_list(blog_posts or [])}
（目安: 投稿の{int(cfg.get('blog', {}).get('promote_ratio', 0.5) * 100)}%くらいでブログに誘導）

# 使える素材（写真・動画）
{materials_catalog or "（素材はまだありません。素材なしのデザインで作ってください）"}

notes_for_reviewer には、確認が必要な点・自信のない点を正直に書いてください。"""
    return llm.generate_json(build_system(cfg), prompt, SCHEMA)
