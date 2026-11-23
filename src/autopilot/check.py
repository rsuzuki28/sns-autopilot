"""接続チェック（X / Instagram / Google / Claude）。キーの値は表示しない。"""
from __future__ import annotations

import os


def run() -> None:
    from . import platforms as pf
    results = []

    def t(name, fn):
        try:
            results.append(f"✅ {name}: {fn()}")
        except Exception as e:
            results.append(f"❌ {name}: {str(e)[:300]}")

    for k in ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
        v = os.environ.get(k, "")
        results.append(f"   {k}: {'設定あり' if v else '未設定'}（{len(v)}文字）")
    t("X（@アカウント確認）", lambda: _x_me())
    t("Instagram", lambda: pf.ig_account())
    t("Google", lambda: _google())
    t("Claude API", lambda: _claude())
    print("\n".join(results))


def _x_me():
    import requests
    from .platforms import X_API, _x_auth
    r = requests.get(f"{X_API}/users/me", params={"user.fields": "public_metrics"}, auth=_x_auth(), timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"{r.status_code} {r.text[:250]}")
    d = r.json()["data"]
    return f"@{d['username']} フォロワー {d.get('public_metrics', {}).get('followers_count')}"


def _google():
    from . import google_api as g
    from .config import load_account
    cfg = load_account()["google"]
    files = g.list_children(cfg["materials_folder_id"], cfg["shared_drive_id"])
    g.sheet_get(cfg["report_spreadsheet_id"], "'ダッシュボード'!A1")
    return f"素材フォルダ {len(files)}件・スプレッドシート読み取りOK"


def _claude():
    import anthropic
    m = anthropic.Anthropic().models.retrieve("claude-opus-5-5")
    return f"OK（{m.id}）"
