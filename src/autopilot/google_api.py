"""Google ドライブ / スプレッドシートの API（サービスアカウント認証）。"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
DRIVE = "https://www.googleapis.com/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"


def available() -> bool:
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))


@lru_cache(maxsize=1)
def session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return AuthorizedSession(creds)


def _ok(r):
    if r.status_code >= 300:
        raise RuntimeError(f"Google APIエラー {r.status_code}: {r.text[:400]}")
    return r.json() if r.content else {}


# ---------- Drive ----------
def list_children(folder_id: str, drive_id: str) -> list[dict]:
    out, token = [], None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size, imageMediaMetadata(width,height,time), videoMediaMetadata(width,height,durationMillis))",
            "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
            "corpora": "drive", "driveId": drive_id,
        }
        if token:
            params["pageToken"] = token
        data = _ok(session().get(f"{DRIVE}/files", params=params))
        out += data.get("files", [])
        token = data.get("nextPageToken")
        if not token:
            return out


def walk(folder_id: str, drive_id: str, path: str = ""):
    """フォルダ以下のファイルを (フォルダパス, ファイル情報) で返す。"""
    for f in list_children(folder_id, drive_id):
        if f["mimeType"] == "application/vnd.google-apps.folder":
            yield from walk(f["id"], drive_id, f"{path}/{f['name']}" if path else f["name"])
        else:
            yield path, f


def download(file_id: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = session().get(f"{DRIVE}/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, stream=True)
    if r.status_code >= 300:
        raise RuntimeError(f"ダウンロード失敗 {r.status_code}: {r.text[:300]}")
    with dest.open("wb") as fp:
        for chunk in r.iter_content(1 << 20):
            fp.write(chunk)
    return dest


# ---------- Sheets ----------
def sheet_get(spreadsheet_id: str, rng: str) -> list[list]:
    return _ok(session().get(f"{SHEETS}/{spreadsheet_id}/values/{rng}")).get("values", [])


def sheet_update(spreadsheet_id: str, rng: str, rows: list[list]) -> None:
    _ok(session().put(f"{SHEETS}/{spreadsheet_id}/values/{rng}",
                      params={"valueInputOption": "USER_ENTERED"}, json={"values": rows}))


def sheet_clear(spreadsheet_id: str, rng: str) -> None:
    _ok(session().post(f"{SHEETS}/{spreadsheet_id}/values/{rng}:clear", json={}))


def sheet_append(spreadsheet_id: str, rng: str, rows: list[list]) -> None:
    _ok(session().post(f"{SHEETS}/{spreadsheet_id}/values/{rng}:append",
                       params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                       json={"values": rows}))


def upload(path: Path, folder_id: str, mime: str, name: str | None = None) -> dict:
    """共有ドライブのフォルダにファイルをアップロード（同名があれば上書き）。"""
    name = name or path.name
    q = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    found = _ok(session().get(f"{DRIVE}/files", params={"q": q, "supportsAllDrives": "true",
                                                         "includeItemsFromAllDrives": "true", "fields": "files(id)"})).get("files", [])
    meta = {"name": name} if found else {"name": name, "parents": [folder_id]}
    files = {"metadata": ("metadata", json.dumps(meta), "application/json; charset=UTF-8"),
             "file": (name, path.read_bytes(), mime)}
    if found:
        url = f"https://www.googleapis.com/upload/drive/v3/files/{found[0]['id']}"
        r = session().patch(url, params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"}, files=files)
    else:
        url = "https://www.googleapis.com/upload/drive/v3/files"
        r = session().post(url, params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,webViewLink"}, files=files)
    return _ok(r)


def download_by_name(folder_id: str, name: str) -> bytes | None:
    q = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    found = _ok(session().get(f"{DRIVE}/files", params={"q": q, "supportsAllDrives": "true",
                                                         "includeItemsFromAllDrives": "true", "fields": "files(id)"})).get("files", [])
    if not found:
        return None
    r = session().get(f"{DRIVE}/files/{found[0]['id']}", params={"alt": "media", "supportsAllDrives": "true"})
    if r.status_code >= 300:
        raise RuntimeError(f"ダウンロード失敗 {r.status_code}")
    return r.content
