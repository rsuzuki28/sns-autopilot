"""PR表記の付与・NGワード・数字の裏取りチェック・文字数チェック。"""
from __future__ import annotations

import re
import unicodedata

NUM_RE = re.compile(
    r"(\d[\d,，.]*)\s*(%|％|円|マイル|ポイント|pt|P|倍|万|泊|日間|ヶ月|か月|カ月)"
)


def x_weighted_length(text: str) -> int:
    """X の文字数カウント（全角=2, 半角=1, URL=23）。上限280。"""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    n = 0
    for ch in text:
        n += 1 if unicodedata.east_asian_width(ch) in ("Na", "H") or ord(ch) < 0x1100 else 2
    return n


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return s.replace(",", "").replace(" ", "")


def unverified_numbers(text: str, reference: str) -> list[str]:
    """本文中の数字のうち、ファクト集・リサーチに出てこないものを返す。"""
    ref = _norm(reference)
    out = []
    for m in NUM_RE.finditer(unicodedata.normalize("NFKC", text)):
        num = _norm(m.group(1)).rstrip(".")
        if num and num not in ref:
            out.append(m.group(0))
    return sorted(set(out))


def ng_hits(text: str, ng_words: list[str]) -> list[str]:
    return [w for w in ng_words if w in text]


def privacy_hits(text: str, cfg: dict) -> list[str]:
    """自分のマイル残高など、出してはいけない情報の表記を返す。"""
    pats = (cfg.get("privacy") or {}).get("forbidden_patterns", [])
    t = unicodedata.normalize("NFKC", text)
    return [m.group(0) for p in pats for m in re.finditer(p, t)]


def blocked_material(entry: dict | None, mid: str, cfg: dict) -> bool:
    pv = cfg.get("privacy") or {}
    if mid in pv.get("blocked_material_ids", []):
        return True
    if not entry:
        return False
    desc = entry.get("description", "") + " " + " ".join(entry.get("tags", []))
    return any(k in desc for k in pv.get("blocked_material_keywords", []))


def add_pr_label_x(text: str, label: str) -> str:
    return text if text.startswith(label) else f"{label}{text}"


def add_pr_label_ig(caption: str, hashtags: list[str], tag: str) -> tuple[str, list[str]]:
    if not caption.startswith("【PR】"):
        caption = "【PR】" + caption
    tags = [t for t in hashtags if t.lstrip("#").upper() != "PR"]
    return caption, [tag] + tags
