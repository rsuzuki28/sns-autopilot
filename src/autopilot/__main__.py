"""コマンド: python -m autopilot <generate|publish|analytics|report|preview>"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .config import load_account, target_date


def main() -> None:
    ap = argparse.ArgumentParser(prog="autopilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="リサーチ→台本→画像/動画→投稿キュー作成")
    g.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は翌日）")
    p = sub.add_parser("publish", help="予約時刻を過ぎた投稿を公開")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("analytics", help="数値を収集")
    sub.add_parser("report", help="週次レポートと学びを更新")
    pv = sub.add_parser("preview", help="台本JSONから画像/動画だけ作る（APIキー不要の確認用）")
    pv.add_argument("plan_json")
    pv.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()

    if a.cmd == "generate":
        from . import drafts, planner, research
        day = date.fromisoformat(a.date) if a.date else target_date(load_account())
        print(f"== {day} のリサーチ")
        notes = research.run(day)
        print("== 台本作成")
        plan = planner.plan(day, notes)
        print("== 画像・動画の生成")
        out = drafts.build(day, plan, notes)
        print(f"完了: {out}")
    elif a.cmd == "publish":
        from . import publish
        publish.run(dry_run=a.dry_run)
    elif a.cmd == "analytics":
        from . import analytics
        analytics.collect()
    elif a.cmd == "report":
        from . import analytics
        analytics.weekly_report()
    elif a.cmd == "preview":
        from . import drafts
        plan = json.loads(Path(a.plan_json).read_text(encoding="utf-8"))
        print(drafts.build(date.fromisoformat(a.date), plan, research_notes=""))


if __name__ == "__main__":
    main()
