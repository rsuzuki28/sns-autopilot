"""X API / Instagram Graph API とメディアのホスティング。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

from .config import ROOT, env

TIMEOUT = 60


# ================= X =================
X_API = "https://api.x.com/2"


def _x_auth() -> OAuth1:
    return OAuth1(env("X_API_KEY"), env("X_API_SECRET"), env("X_ACCESS_TOKEN"), env("X_ACCESS_TOKEN_SECRET"))


def x_upload_image(path: Path) -> str:
    """画像をアップロードして media_id を返す（v2、失敗したら v1.1 で再試行）。"""
    with path.open("rb") as fp:
        r = requests.post(f"{X_API}/media/upload", files={"media": (path.name, fp, "image/jpeg")},
                          data={"media_category": "tweet_image", "media_type": "image/jpeg"}, auth=_x_auth(), timeout=TIMEOUT)
    if r.status_code < 300:
        d = r.json().get("data", r.json())
        return str(d.get("id") or d.get("media_id_string") or d.get("media_id"))
    with path.open("rb") as fp:
        r2 = requests.post("https://upload.twitter.com/1.1/media/upload.json", files={"media": fp},
                           auth=_x_auth(), timeout=TIMEOUT)
    if r2.status_code >= 300:
        raise RuntimeError(f"X画像アップロードエラー v2={r.status_code}:{r.text[:200]} v1.1={r2.status_code}:{r2.text[:200]}")
    return r2.json()["media_id_string"]


def x_post(text: str, reply_to: str | None = None, media_ids: list[str] | None = None) -> str:
    body: dict = {"text": text}
    if media_ids:
        body["media"] = {"media_ids": media_ids}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    r = requests.post(f"{X_API}/tweets", json=body, auth=_x_auth(), timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"X投稿エラー {r.status_code}: {r.text[:500]}")
    return r.json()["data"]["id"]


def x_post_thread(text: str, thread: list[str], images: list[Path] | None = None) -> list[str]:
    media_ids = None
    if images:
        try:
            media_ids = [x_upload_image(p) for p in images[:4]]
        except Exception as e:  # 画像で失敗しても文章は投稿する
            print(f"  ⚠ 画像なしで投稿します: {e}")
    ids = [x_post(text, media_ids=media_ids)]
    for t in thread:
        time.sleep(3)
        ids.append(x_post(t, reply_to=ids[-1]))
    return ids


def x_metrics(tweet_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(tweet_ids), 100):
        chunk = tweet_ids[i:i + 100]
        r = requests.get(f"{X_API}/tweets", params={"ids": ",".join(chunk), "tweet.fields": "public_metrics,created_at"},
                         auth=_x_auth(), timeout=TIMEOUT)
        if r.status_code >= 300:
            raise RuntimeError(f"X指標取得エラー {r.status_code}: {r.text[:500]}")
        for t in r.json().get("data", []):
            out[t["id"]] = t.get("public_metrics", {})
    return out


def x_account() -> dict:
    r = requests.get(f"{X_API}/users/me", params={"user.fields": "public_metrics"}, auth=_x_auth(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["data"].get("public_metrics", {})


# ================= Instagram =================
def _ig() -> tuple[str, str, str]:
    """Instagramログイン（IGで始まるトークン）は graph.instagram.com、Facebookログインは graph.facebook.com。"""
    ver = os.environ.get("IG_GRAPH_VERSION", "v23.0")
    token = env("IG_ACCESS_TOKEN")
    host = os.environ.get("IG_GRAPH_HOST") or ("graph.instagram.com" if token.startswith("IG") else "graph.facebook.com")
    return f"https://{host}/{ver}", env("IG_USER_ID"), token


def _ig_req(method: str, path: str, **params) -> dict:
    base, _, token = _ig()
    params["access_token"] = token
    r = requests.request(method, f"{base}/{path}", params=params if method == "GET" else None,
                         data=params if method != "GET" else None, timeout=TIMEOUT)
    if r.status_code >= 300:
        raise RuntimeError(f"Instagram APIエラー {r.status_code}: {r.text[:500]}")
    return r.json()


def _ig_wait(container_id: str, timeout_s: int = 600) -> None:
    start = time.time()
    while time.time() - start < timeout_s:
        st = _ig_req("GET", container_id, fields="status_code,status").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagramのメディア処理に失敗しました: {st}")
        time.sleep(10)
    raise RuntimeError("Instagramのメディア処理がタイムアウトしました")


def _ig_publish(creation_id: str) -> str:
    _, uid, _ = _ig()
    return _ig_req("POST", f"{uid}/media_publish", creation_id=creation_id)["id"]


def ig_post_carousel(image_urls: list[str], caption: str) -> str:
    _, uid, _ = _ig()
    children = []
    for u in image_urls[:10]:
        children.append(_ig_req("POST", f"{uid}/media", image_url=u, is_carousel_item="true")["id"])
    for c in children:
        _ig_wait(c)
    cid = _ig_req("POST", f"{uid}/media", media_type="CAROUSEL", children=",".join(children), caption=caption)["id"]
    _ig_wait(cid)
    return _ig_publish(cid)


def ig_post_reel(video_url: str, caption: str, cover_url: str | None = None) -> str:
    _, uid, _ = _ig()
    params = dict(media_type="REELS", video_url=video_url, caption=caption, share_to_feed="true")
    if cover_url:
        params["cover_url"] = cover_url
    cid = _ig_req("POST", f"{uid}/media", **params)["id"]
    _ig_wait(cid, timeout_s=900)
    return _ig_publish(cid)


IG_METRICS = ["views", "reach", "saved", "likes", "comments", "shares", "total_interactions"]


def ig_insights(media_id: str) -> dict:
    """指標はAPIのバージョンやメディア種別で使えるものが違うので、失敗したら1つずつ取る。"""
    try:
        data = _ig_req("GET", f"{media_id}/insights", metric=",".join(IG_METRICS))["data"]
        return {d["name"]: d["values"][0]["value"] if d.get("values") else d.get("total_value", {}).get("value") for d in data}
    except RuntimeError:
        out = {}
        for m in IG_METRICS:
            try:
                d = _ig_req("GET", f"{media_id}/insights", metric=m)["data"][0]
                out[m] = d["values"][0]["value"] if d.get("values") else d.get("total_value", {}).get("value")
            except Exception:
                pass
        return out


def ig_permalink(media_id: str) -> str:
    try:
        return _ig_req("GET", media_id, fields="permalink").get("permalink", "")
    except Exception:
        return ""


def ig_account() -> dict:
    _, uid, _ = _ig()
    return _ig_req("GET", uid, fields="followers_count,media_count")


# ================= メディアのホスティング =================
def public_url(local: Path) -> str:
    """Instagramに渡す公開URLを返す。"""
    from .config import load_account
    host = load_account().get("media_host", "github_raw")
    rel = local.resolve().relative_to(ROOT.resolve()).as_posix()
    if host == "github_raw":
        repo = env("GITHUB_REPOSITORY")
        branch = os.environ.get("MEDIA_BRANCH", "main")
        return f"https://raw.githubusercontent.com/{repo}/{branch}/{rel}"
    if host == "r2":
        import boto3  # 必要なときだけ読み込む
        s3 = boto3.client("s3", endpoint_url=env("R2_ENDPOINT"), aws_access_key_id=env("R2_ACCESS_KEY_ID"),
                          aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"), region_name="auto")
        bucket = env("R2_BUCKET")
        ctype = "video/mp4" if local.suffix == ".mp4" else "image/jpeg"
        s3.upload_file(str(local), bucket, rel, ExtraArgs={"ContentType": ctype})
        return f"{env('R2_PUBLIC_BASE_URL').rstrip('/')}/{rel}"
    raise RuntimeError(f"未対応の media_host: {host}")
