"""最新ニュース・キャンペーンのリサーチ（Claude + Web検索）。"""
from __future__ import annotations

from datetime import date

from . import llm
from .config import RESEARCH_DIR, load_account

SYSTEM = """あなたは日本のクレジットカード・マイル・旅行業界のリサーチャーです。
SNS投稿のネタになる最新情報を、Web検索で一次情報（カード会社・航空会社・ポイント運営の公式発表やプレスリリース）を優先して集めます。
推測で数字を書かないこと。確認できた事実だけを、出典URLと発表日つきで書きます。"""


def run(day: date) -> str:
    cfg = load_account()
    prompt = f"""今日は {day.isoformat()} です。直近2週間を中心に、次のテーマの新しい情報を調べてください。

テーマ: {cfg['account']['niche']}
ターゲット: {cfg['account']['target']}

調べる観点:
- クレジットカードの入会キャンペーン、特典・年会費・還元率の改定（改悪・改善）
- ANA/JALなどのマイル関連ニュース（キャンペーン、特典航空券、ルール変更）、航空会社のセール
- ポイントプログラムの交換レート変更・増量キャンペーン
- 空港ラウンジ、旅行系サービスの新情報
- いまSNSで話題になっているクレカ・マイル系の話題

出力形式（Markdown）:
## ネタ候補
各項目について:
- 見出し
- 事実（数字は公式発表どおりに）
- 発表日 / 期間
- 出典URL
- SNSでの切り口のアイデア（1行）

## 注意が必要な情報
（期限切れ間近・条件が複雑・情報が錯綜しているもの）

最大10件。確認できなかったことは書かないでください。"""
    text = llm.research(SYSTEM, prompt)
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    path = RESEARCH_DIR / f"{day.isoformat()}.md"
    path.write_text(f"# リサーチ {day.isoformat()}\n\n{text}\n", encoding="utf-8")
    return text
