"""Googleドライブの素材（写真・動画）を取り込み、AIで中身を説明・タグ付けする。

- 素材の一覧と説明は data/materials.json に保存（リポジトリに残る）
- 実ファイルは .cache/materials/ にダウンロード（リポジトリには入れない）
- 搭乗券のQR・カード番号・他人の顔などが写っていそうな素材は使用禁止にする
"""
from __future__ import annotations

import base64
import io
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from . import google_api as g
from . import llm
from .config import ROOT, load_account, now

INDEX = ROOT / ".cache" / "materials.json"
CACHE_DIR = ROOT / ".cache" / "materials"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a", ".wav"}

DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "place_guess": {"type": "string"},
        "privacy_risk": {"type": "boolean"},
        "privacy_reason": {"type": "string"},
        "quality": {"type": "string", "enum": ["good", "ok", "poor"]},
        "text_safe_area": {"type": "string", "enum": ["top", "middle", "bottom"]},
    },
    "required": ["description", "tags", "place_guess", "privacy_risk", "privacy_reason", "quality", "text_safe_area"],
    "additionalProperties": False,
}
DESCRIBE_SYSTEM = """あなたはSNS運用の素材管理担当です。旅行・クレカ・マイル系アカウント（顔出しなし）の投稿素材を確認します。
- description: 何が写っているかを具体的に1〜2文（空港名・ラウンジ名・機材・ホテル名などが読み取れれば書く）
- tags: 検索用タグ 3〜8個（例: 空港, ANAラウンジ, 機内食, ホテル客室, 海, 宮古島, カード券面）
- privacy_risk: 次のどれかが判読できる形で写っていれば true → 搭乗券のQRコード/バーコード/予約番号, カード番号/セキュリティコード, 顔がはっきりわかる他人, 住所や氏名
- text_safe_area: 文字を重ねても被写体を邪魔しにくい位置"""


def _index_on_drive() -> str | None:
    """素材の説明は公開リポジトリに置かず、共有ドライブ（非公開）の作業ログフォルダに保存する。"""
    return load_account()["google"].get("work_folder_id")


def load_index() -> dict:
    folder = _index_on_drive()
    if folder and g.available():
        try:
            data = g.download_by_name(folder, "materials.json")
            if data:
                INDEX.parent.mkdir(parents=True, exist_ok=True)
                INDEX.write_bytes(data)
        except Exception as e:
            print(f"⚠ 素材リストの読み込みに失敗: {e}")
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def save_index(idx: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    folder = _index_on_drive()
    if folder and g.available():
        g.upload(INDEX, folder, "application/json", "materials.json")


def _kind(name: str, mime: str) -> str | None:
    ext = Path(name).suffix.lower()
    if mime.startswith("image/") or ext in IMAGE_EXT:
        return "image"
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if mime.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    return None


def local_path(entry: dict) -> Path:
    ext = Path(entry["name"]).suffix.lower() or ".bin"
    return CACHE_DIR / f"{entry['id']}{ext}"


def ensure_local(entry: dict) -> Path:
    """素材をダウンロードして、使いやすい形式（JPEG / mp4）のパスを返す。"""
    p = local_path(entry)
    if not p.exists():
        g.download(entry["id"], p)
    if entry["kind"] == "image":
        jpg = p.with_suffix(".norm.jpg")
        if not jpg.exists():
            _to_jpeg(p, jpg)
        return jpg
    return p


def _to_jpeg(src: Path, dst: Path) -> None:
    if src.suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif  # iPhoneの写真（HEIC）用
            pillow_heif.register_heif_opener()
        except ImportError:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), str(dst)], check=True)
            return
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.save(dst, "JPEG", quality=92)


def _thumb_b64(path: Path, kind: str) -> str:
    if kind == "video":
        frame = path.with_suffix(".frame.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(path), "-frames:v", "1", str(frame)],
                       check=True)
        path = frame
    im = Image.open(path).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return round(float(out.stdout.strip()), 1)
    except ValueError:
        return 0.0


def sync(max_new: int = 40) -> dict:
    """ドライブの新しい素材を取り込み、AIで説明をつける。"""
    cfg = load_account()["google"]
    idx = load_index()
    seen = set()
    added = 0
    for folder, f in g.walk(cfg["materials_folder_id"], cfg["shared_drive_id"]):
        kind = _kind(f["name"], f["mimeType"])
        if not kind:
            continue
        seen.add(f["id"])
        old = idx.get(f["id"])
        if old and old.get("modifiedTime") == f.get("modifiedTime"):
            old["folder"] = folder
            continue
        entry = {"id": f["id"], "name": f["name"], "folder": folder, "kind": kind,
                 "modifiedTime": f.get("modifiedTime"), "added_at": now().isoformat(),
                 "used_count": old.get("used_count", 0) if old else 0, "used_in": old.get("used_in", []) if old else []}
        if kind == "audio":
            entry.update(description="BGM", tags=["BGM"], privacy_risk=False, quality="good")
            idx[f["id"]] = entry
            continue
        if added >= max_new:
            continue  # 1回に処理する量を制限（残りは翌日）
        try:
            path = ensure_local(entry)
            if kind == "video":
                entry["duration"] = _duration(path)
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _thumb_b64(path, kind)}},
                {"type": "text", "text": f"フォルダ: {folder}\nファイル名: {f['name']}\n種類: {'動画（1秒目のフレーム）' if kind == 'video' else '写真'}"},
            ]
            entry.update(llm.generate_json(DESCRIBE_SYSTEM, content, DESCRIBE_SCHEMA, effort="low"))
        except Exception as e:
            print(f"⚠ 素材の解析に失敗 {f['name']}: {e}")
            continue
        idx[f["id"]] = entry
        added += 1
        print(f"＋ 素材: {folder}/{f['name']} → {entry.get('description', '')[:40]}")
    for k in list(idx):
        if k not in seen:
            idx[k]["deleted"] = True
    save_index(idx)
    print(f"素材: 新規 {added}件 / 合計 {sum(1 for v in idx.values() if not v.get('deleted'))}件")
    return idx


def usable(idx: dict) -> list[dict]:
    return [v for v in idx.values()
            if not v.get("deleted") and not v.get("privacy_risk") and v.get("quality") != "poor" and v["kind"] != "audio"]


def catalog_for_prompt(idx: dict, limit: int = 150) -> str:
    """台本AIに渡す素材カタログ（使用回数が少ないものを優先）。"""
    items = sorted(usable(idx), key=lambda v: (v.get("used_count", 0), v.get("added_at", "")))[:limit]
    lines = []
    for v in items:
        extra = f" {v['duration']}秒" if v["kind"] == "video" else ""
        lines.append(f"- id={v['id']} [{v['kind']}{extra}] {v['folder']} / {v.get('description', '')} "
                     f"tags={','.join(v.get('tags', []))} 使用{v.get('used_count', 0)}回")
    return "\n".join(lines) or "（素材はまだありません。素材なしのデザインで作ってください）"


def bgm_files(idx: dict) -> list[dict]:
    return [v for v in idx.values() if not v.get("deleted") and v["kind"] == "audio"]


def mark_used(idx: dict, ids: list[str], post_key: str) -> None:
    for i in ids:
        if i in idx:
            idx[i]["used_count"] = idx[i].get("used_count", 0) + 1
            idx[i].setdefault("used_in", []).append(post_key)
    save_index(idx)

