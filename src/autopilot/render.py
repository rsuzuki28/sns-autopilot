"""カルーセル画像とリール動画の生成（Pillow + ffmpeg）。"""
from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS_DIR

FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        str(ASSETS_DIR / "fonts" / "NotoSansJP-Bold.ttf"),
    ],
    "regular": [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        str(ASSETS_DIR / "fonts" / "NotoSansJP-Regular.ttf"),
    ],
}
JP_INDEX = 0  # NotoSansCJK.ttc 内の Japanese は index 0


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES[weight]:
        if Path(p).exists():
            return ImageFont.truetype(p, size, index=JP_INDEX if p.endswith(".ttc") else 0)
    raise RuntimeError("日本語フォントが見つかりません（apt install fonts-noto-cjk）")


NO_LINE_START = set("、。，．・：；？！ー）」』】〕ゝゞ々ぁぃぅぇぉっゃゅょァィゥェォッャュョ")


def wrap(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=f) <= max_w or not cur:
                cur += ch
            elif ch in NO_LINE_START:  # 禁則処理（行頭に句読点を置かない）
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def fit(draw, text: str, weight: str, sizes: list[int], max_w: int, max_lines: int):
    """文字が収まり、最終行が1〜2文字だけにならない最大サイズを選ぶ。"""
    fallback = None
    for size in sizes:
        f = font(weight, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) > max_lines:
            continue
        if all(len(ln) > 2 for ln in lines if ln):
            return f, lines
        fallback = fallback or (f, lines)
    return fallback or (font(weight, sizes[-1]), wrap(draw, text, font(weight, sizes[-1]), max_w))


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


class Theme:
    def __init__(self, design: dict):
        self.brand = _hex(design["brand_color"])
        self.accent = _hex(design["accent_color"])
        self.bg = _hex(design["background"])
        self.text = _hex(design["text_color"])
        self.handle = design.get("handle", "")


def _draw_lines(d, lines, f, x, y, fill, spacing=1.45):
    lh = int(f.size * spacing)
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill)
        y += lh
    return y


# ---------- カルーセル（1080x1350） ----------
W, H = 1080, 1350


def carousel_cover(t: Theme, title: str, subtitle: str, total: int) -> Image.Image:
    im = Image.new("RGB", (W, H), t.brand)
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 24, W, H], fill=t.accent)
    fs = font("regular", 40)
    d.text((80, 120), subtitle, font=fs, fill=t.accent)
    ft, lines = fit(d, title, "bold", [112, 104, 96, 88, 80, 72], W - 160, 5)
    block_h = int(ft.size * 1.35) * len(lines)
    _draw_lines(d, lines, ft, 80, (H - block_h) // 2, (255, 255, 255), 1.35)
    fh = font("regular", 34)
    d.text((80, H - 120), t.handle, font=fh, fill=(255, 255, 255))
    d.text((W - 80, H - 120), "スワイプ →", font=fh, fill=(255, 255, 255), anchor="ra")
    return im


def carousel_slide(t: Theme, idx: int, total: int, heading: str, points: list[str]) -> Image.Image:
    im = Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 200], fill=t.brand)
    fn = font("bold", 40)
    d.text((80, 60), f"{idx:02d}", font=fn, fill=t.accent)
    fh = font("bold", 56)
    hl = wrap(d, heading, fh, W - 250)
    if len(hl) > 1:
        fh = font("bold", 44)
        hl = wrap(d, heading, fh, W - 250)[:2]
    _draw_lines(d, hl, fh, 170, 100 - (len(hl) - 1) * 28 - fh.size // 2, (255, 255, 255), 1.25)
    fp = font("bold", 56)
    blocks = [wrap(d, p, fp, W - 240) for p in points]
    gap = 70
    total_h = sum(int(fp.size * 1.5) * len(b) for b in blocks) + gap * (len(blocks) - 1)
    y = max(280, 200 + (H - 200 - 120 - total_h) // 2)
    for lines in blocks:
        d.rounded_rectangle([86, y + 14, 116, y + 44], radius=8, fill=t.accent)
        y = _draw_lines(d, lines, fp, 150, y, t.text, 1.5) + gap
    fs = font("regular", 30)
    d.text((80, H - 80), t.handle, font=fs, fill=t.brand)
    d.text((W - 80, H - 80), f"{idx + 1}/{total}", font=fs, fill=t.brand, anchor="ra")
    return im


def carousel_closing(t: Theme, message: str, disclaimer: str) -> Image.Image:
    im = Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(im)
    fb, lines = fit(d, message, "bold", [80, 72, 64, 56], W - 200, 4)
    y = _draw_lines(d, lines, fb, 100, 360, t.brand, 1.4)
    d.rounded_rectangle([100, y + 60, W - 100, y + 200], radius=70, fill=t.accent)
    d.text((W // 2, y + 130), "保存してあとで見返そう", font=font("bold", 50), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, y + 290), f"フォローは {t.handle}", font=font("regular", 42), fill=t.text, anchor="mm")
    fs = font("regular", 26)
    _draw_lines(d, wrap(d, disclaimer, fs, W - 200), fs, 100, H - 160, (120, 120, 120), 1.4)
    return im


def render_carousel(item: dict, design: dict, disclaimer: str, out_dir: Path) -> list[Path]:
    t = Theme(design)
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = item["slides"][:8]
    total = len(slides) + 2
    imgs = [carousel_cover(t, item["cover_title"], item["cover_subtitle"], total)]
    for i, s in enumerate(slides, start=1):
        imgs.append(carousel_slide(t, i, total, s["heading"], s["points"][:4]))
    imgs.append(carousel_closing(t, item["closing_message"], disclaimer))
    paths = []
    for i, im in enumerate(imgs, start=1):
        p = out_dir / f"slide-{i:02d}.jpg"
        im.save(p, "JPEG", quality=92)
        paths.append(p)
    return paths


# ---------- リール（1080x1920） ----------
RW, RH = 1080, 1920


def reel_frame(t: Theme, text: str, idx: int, total: int, is_hook: bool) -> Image.Image:
    im = Image.new("RGB", (RW, RH), t.brand if is_hook else t.bg)
    d = ImageDraw.Draw(im)
    color = (255, 255, 255) if is_hook else t.text
    f, lines = fit(d, text, "bold", [120, 108, 96, 88, 80] if is_hook else [100, 92, 84, 76], RW - 180, 6)
    lh = int(f.size * 1.4)
    y = (RH - lh * len(lines)) // 2 - 80
    for ln in lines:
        d.text((RW // 2, y), ln, font=f, fill=color, anchor="ma")
        y += lh
    # 進捗バー
    d.rectangle([0, RH - 14, int(RW * idx / total), RH], fill=t.accent)
    d.text((RW // 2, RH - 330), t.handle, font=font("regular", 40), fill=t.accent, anchor="mm")
    return im


def render_reel(item: dict, design: dict, out_dir: Path) -> dict:
    """シーンごとの画像をつなげて mp4 を作る。BGMは assets/bgm/*.mp3 からランダム。"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg がインストールされていません")
    t = Theme(design)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [{"text": item["hook"], "seconds": 2.0}] + item["scenes"]
    total = len(scenes)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        concat = []
        for i, s in enumerate(scenes):
            p = tmp / f"f{i:02d}.png"
            reel_frame(t, s["text"], i + 1, total, i == 0).save(p)
            secs = max(1.5, min(float(s.get("seconds", 3)), 6.0))
            concat.append(f"file '{p}'\nduration {secs}")
        concat.append(f"file '{tmp / f'f{total - 1:02d}.png'}'")  # concat demuxerの仕様で最後を重ねる
        (tmp / "list.txt").write_text("\n".join(concat))
        duration = sum(max(1.5, min(float(s.get("seconds", 3)), 6.0)) for s in scenes)
        video = out_dir / "reel.mp4"
        bgms = sorted((ASSETS_DIR / "bgm").glob("*.mp3"))
        audio = ["-i", str(random.choice(bgms))] if bgms else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
            *audio,
            "-t", f"{duration:.2f}",
            "-vf", "fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-af", f"afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5",
            "-movflags", "+faststart", "-shortest", str(video),
        ]
        subprocess.run(cmd, check=True)
        cover = out_dir / "cover.jpg"
        reel_frame(t, item["hook"], 1, total, True).convert("RGB").save(cover, "JPEG", quality=90)
    return {"video": video, "cover": cover, "duration": duration}
