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
    sub.add_parser("materials", help="Googleドライブの素材を取り込む")
    sub.add_parser("check", help="各サービスへの接続を確認")
    sub.add_parser("sync-materials", help="素材を取り込み、説明を表示")
    ul = sub.add_parser("upload-log", help="ログを共有ドライブの作業ログフォルダへ")
    ul.add_argument("file")
    ul.add_argument("name")
    rl = sub.add_parser("reel", help="台本JSONからリールを1本作る")
    rl.add_argument("request_json")
    sub.add_parser("report", help="週次レポートと学びを更新")
    pv = sub.add_parser("preview", help="台本JSONから画像/動画だけ作る（APIキー不要の確認用）")
    pv.add_argument("plan_json")
    pv.add_argument("--date", default=date.today().isoformat())
    a = ap.parse_args()

    if a.cmd == "generate":
        from . import blog, drafts, google_api, materials, planner, research
        day = date.fromisoformat(a.date) if a.date else target_date(load_account())
        idx = {}
        if google_api.available():
            print("== 素材の取り込み（Googleドライブ）")
            idx = materials.sync()
        else:
            print("（GOOGLE_SERVICE_ACCOUNT_JSON が無いので素材なしで作ります）")
        print("== ブログ記事の取得")
        posts = blog.load()
        print(f"   {len(posts)}記事")
        print(f"== {day} のリサーチ")
        notes = research.run(day)
        print("== 台本作成")
        plan = planner.plan(day, notes, posts, materials.catalog_for_prompt(idx))

        print("== 画像・動画の生成")
        out = drafts.build(day, plan, notes, idx, posts)
        (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完了: {out}")
    elif a.cmd == "publish":
        from . import publish
        publish.run(dry_run=a.dry_run)
    elif a.cmd == "upload-log":
        from . import google_api as g
        folder = load_account()["google"]["work_folder_id"]
        print(g.upload(Path(a.file), folder, "text/plain", a.name).get("webViewLink"))
    elif a.cmd == "sync-materials":
        from . import materials
        idx = materials.sync(max_new=80)
        for v in sorted(idx.values(), key=lambda v: (v.get("folder", ""), v["name"])):
            if not v.get("deleted"):
                flag = f" ⚠使用禁止({v.get('privacy_reason', '')})" if v.get("privacy_risk") else ""
                print(f"{v['id']}\t{v['kind']}\t{v.get('folder', '')}/{v['name']}\t{v.get('description', '')}{flag}")
    elif a.cmd == "reel":
        from . import drafts, materials
        req = json.loads(Path(a.request_json).read_text(encoding="utf-8"))
        idx = materials.load_index()
        out = drafts.build_single_reel(date.fromisoformat(req["date"]), req["script"], req["time"], req["id"], idx)
        print(f"完了: {out}")
        folder = req.get("preview_folder_id") or load_account()["google"].get("preview_folder_id")
        if folder:  # 確認用にGoogleドライブ（非公開）へ
            from . import google_api as g
            item = json.loads((out / "post.json").read_text(encoding="utf-8"))
            (out / "caption.txt").write_text(item["caption"], encoding="utf-8")  # スマホでコピーしやすいように
            for f, mime in (("reel.mp4", "video/mp4"), ("caption.txt", "text/plain"), ("cover.jpg", "image/jpeg"),
                            ("REVIEW.md", "text/plain"), ("post.json", "text/plain")):
                r = g.upload(out / f, folder, mime, f"{req['id']}_{f}")
                print(f"アップロード: {f} → {r.get('webViewLink')}")
    elif a.cmd == "check":
        from . import check
        check.run()
    elif a.cmd == "materials":
        from . import materials
        materials.sync()
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
