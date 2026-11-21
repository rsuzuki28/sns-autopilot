"""設定ファイルとパスの読み込み。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(os.environ.get("AUTOPILOT_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
QUEUE_DIR = ROOT / "queue"
RESEARCH_DIR = ROOT / "research"
REPORTS_DIR = ROOT / "reports"
ASSETS_DIR = ROOT / "assets"

POSTED_LOG = DATA_DIR / "posted.jsonl"
METRICS_LATEST = DATA_DIR / "metrics_latest.json"
ACCOUNT_STATS = DATA_DIR / "account_stats.jsonl"
LEARNINGS = DATA_DIR / "learnings.md"


def load_account() -> dict:
    return yaml.safe_load((CONFIG_DIR / "account.yaml").read_text(encoding="utf-8"))


def load_facts_text() -> str:
    return (CONFIG_DIR / "facts.yaml").read_text(encoding="utf-8")


def load_facts() -> dict:
    return yaml.safe_load(load_facts_text()) or {}


def tz(cfg: dict | None = None) -> ZoneInfo:
    cfg = cfg or load_account()
    return ZoneInfo(cfg["schedule"].get("timezone", "Asia/Tokyo"))


def now(cfg: dict | None = None) -> datetime:
    return datetime.now(tz(cfg))


def target_date(cfg: dict | None = None, offset_days: int = 1):
    """下書きを作る対象日（デフォルトは翌日）。"""
    return (now(cfg) + timedelta(days=offset_days)).date()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def env(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name)
    if required and not v:
        raise RuntimeError(f"環境変数 {name} が設定されていません（GitHubのSecretsに登録してください）")
    return v
