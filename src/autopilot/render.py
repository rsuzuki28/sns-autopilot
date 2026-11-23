"""カルーセル画像とリール動画の生成（Pillow + ffmpeg）。"""
from __future__ import annotations

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from typing import Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

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


try:
    import budoux
    _PARSER = budoux.load_default_japanese_parser()
except ImportError:  # budouxが無ければ1文字ずつ折り返す
    _PARSER = None


def _char_wrap(draw, text: str, f, max_w: int, cur: str = "") -> tuple[list[str], str]:
    lines = []
    for ch in text:
        if draw.textlength(cur + ch, font=f) <= max_w or not cur or ch in NO_LINE_START:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    return lines, cur


def wrap(draw: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    """日本語を文節単位で折り返す（「知っ／ておく」のような不自然な改行を防ぐ）。"""
    lines: list[str] = []
    for para in text.split("\n"):
        chunks = _PARSER.parse(para) if _PARSER and para else list(para)
        cur = ""
        for ch in chunks:
            if draw.textlength(cur + ch, font=f) <= max_w or not cur:
                if draw.textlength(ch, font=f) > max_w:  # 1文節が1行に収まらない
                    more, cur = _char_wrap(draw, ch, f, max_w, cur)
                    lines += more
                else:
                    cur += ch
            elif ch[0] in NO_LINE_START and draw.textlength(cur + ch[0], font=f) <= max_w * 1.05:
                cur += ch[0]
                lines.append(cur)
                cur = ch[1:]
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


# 素材ID → (ファイルパス, "image"|"video", 文字を置く位置) を返す関数。素材が無ければ None
Resolver = Callable[[str], "tuple[Path, str, str] | None"]


def _none(_: str):
    return None


def _draw_lines(d, lines, f, x, y, fill, spacing=1.45, anchor="la", stroke=0, stroke_fill=None):
    lh = int(f.size * spacing)
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=stroke_fill)
        y += lh
    return y


def _photo(path: Path, size: tuple[int, int]) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def _gradient(size: tuple[int, int], top_alpha: int, bottom_alpha: int, start: float = 0.0) -> Image.Image:
    w, h = size
    g = Image.new("L", (1, h))
    for y in range(h):
        r = 0 if y < h * start else (y - h * start) / max(1, h * (1 - start))
        g.putpixel((0, y), int(top_alpha + (bottom_alpha - top_alpha) * r))
    return g.resize((w, h))


def _darken(im: Image.Image, mask: Image.Image, color=(8, 18, 40)) -> Image.Image:
    return Image.composite(Image.new("RGB", im.size, color), im, mask)


# ---------- カルーセル（1080x1350） ----------
W, H = 1080, 1350


def _is_screenshot(path: Path) -> bool:
    """スマホのスクショ（縦長）かどうか。スクショは全面に敷かず、枠つきで見せる。"""
    w, h = ImageOps.exif_transpose(Image.open(path)).size
    return h / max(w, 1) > 1.8


def _phone_inset(path: Path, height: int) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w = int(im.width * height / im.height)
    im = im.resize((w, height), Image.Resampling.LANCZOS)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, height - 1], radius=36, fill=255)
    frame = Image.new("RGBA", (w + 24, height + 24), (255, 255, 255, 255))
    fmask = Image.new("L", frame.size, 0)
    ImageDraw.Draw(fmask).rounded_rectangle([0, 0, frame.width - 1, frame.height - 1], radius=46, fill=255)
    frame.putalpha(fmask)
    frame.paste(im, (12, 12), mask)
    return frame


def carousel_cover_screenshot(t: Theme, title: str, subtitle: str, photo: Path) -> Image.Image:
    im = Image.new("RGB", (W, H), t.brand)
    d = ImageDraw.Draw(im)
    phone = _phone_inset(photo, 640)
    im.paste(phone, ((W - phone.width) // 2, 70), phone)
    d = ImageDraw.Draw(im)
    fs = font("bold", 40)
    sw = int(d.textlength(subtitle, font=fs)) + 56
    y = 70 + phone.height + 60
    d.rounded_rectangle([80, y, 80 + sw, y + 64], radius=32, fill=t.accent)
    d.text((108, y + 32), subtitle, font=fs, fill=(255, 255, 255), anchor="lm")
    ft, lines = fit(d, title, "bold", [96, 88, 80, 72, 64], W - 160, 3)
    _draw_lines(d, lines, ft, 80, y + 100, (255, 255, 255), 1.3)
    d.rectangle([0, H - 24, W, H], fill=t.accent)
    fh = font("regular", 34)
    d.text((80, H - 100), t.handle, font=fh, fill=(255, 255, 255))
    d.text((W - 80, H - 100), "スワイプ →", font=fh, fill=(255, 255, 255), anchor="ra")
    return im


def carousel_cover(t: Theme, title: str, subtitle: str, total: int, photo: Path | None = None) -> Image.Image:
    if photo and _is_screenshot(photo):
        return carousel_cover_screenshot(t, title, subtitle, photo)
    if photo:
        im = _darken(_photo(photo, (W, H)), _gradient((W, H), 40, 225, start=0.25))
    else:
        im = Image.new("RGB", (W, H), t.brand)
    d = ImageDraw.Draw(im)
    d.rectangle([0, H - 24, W, H], fill=t.accent)
    ft, lines = fit(d, title, "bold", [112, 104, 96, 88, 80, 72], W - 160, 5)
    lh = int(ft.size * 1.35)
    block_h = lh * len(lines)
    y = (H - 200 - block_h) if photo else (H - block_h) // 2
    fs = font("bold", 40)
    sw = int(d.textlength(subtitle, font=fs)) + 56
    d.rounded_rectangle([80, y - 100, 80 + sw, y - 36], radius=32, fill=t.accent)
    d.text((108, y - 68), subtitle, font=fs, fill=(255, 255, 255), anchor="lm")
    _draw_lines(d, lines, ft, 80, y, (255, 255, 255), 1.35)
    fh = font("regular", 34)
    d.text((80, H - 100), t.handle, font=fh, fill=(255, 255, 255))
    d.text((W - 80, H - 100), "スワイプ →", font=fh, fill=(255, 255, 255), anchor="ra")
    return im


def carousel_slide(t: Theme, idx: int, total: int, heading: str, points: list[str], photo: Path | None = None) -> Image.Image:
    im = Image.new("RGB", (W, H), t.bg)
    top = 0
    if photo:  # 上半分に写真（スクショは枠つきで中央に）
        ph_h = 560
        if _is_screenshot(photo):
            ImageDraw.Draw(im).rectangle([0, 0, W, ph_h], fill=(226, 232, 243))
            phone = _phone_inset(photo, ph_h - 60)
            im.paste(phone, ((W - phone.width) // 2, 30), phone)
        else:
            im.paste(_photo(photo, (W, ph_h)), (0, 0))
        top = ph_h
    d = ImageDraw.Draw(im)
    band_h = 170
    d.rectangle([0, top, W, top + band_h], fill=t.brand)
    d.text((80, top + band_h // 2), f"{idx:02d}", font=font("bold", 44), fill=t.accent, anchor="lm")
    fh, hl = fit(d, heading, "bold", [56, 50, 44, 40], W - 260, 2)
    lh = int(fh.size * 1.25)
    _draw_lines(d, hl, fh, 180, top + band_h // 2 - (lh * len(hl)) // 2, (255, 255, 255), 1.25)
    fp = font("bold", 48 if photo else 56)
    blocks = [wrap(d, p, fp, W - 240) for p in points]
    gap = 48 if photo else 70
    total_h = sum(int(fp.size * 1.5) * len(b) for b in blocks) + gap * (len(blocks) - 1)
    area_top = top + band_h + 50
    y = max(area_top, area_top + (H - area_top - 120 - total_h) // 2)
    for lines in blocks:
        d.rounded_rectangle([86, y + 12, 114, y + 40], radius=8, fill=t.accent)
        y = _draw_lines(d, lines, fp, 150, y, t.text, 1.5) + gap
    fs = font("regular", 30)
    d.text((80, H - 80), t.handle, font=fs, fill=t.brand)
    d.text((W - 80, H - 80), f"{idx + 1}/{total}", font=fs, fill=t.brand, anchor="ra")
    return im


def carousel_closing(t: Theme, message: str, disclaimer: str, blog_cta: bool = False) -> Image.Image:
    im = Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(im)
    fb, lines = fit(d, message, "bold", [80, 72, 64, 56], W - 200, 4)
    y = _draw_lines(d, lines, fb, 100, 320, t.brand, 1.4)
    d.rounded_rectangle([100, y + 60, W - 100, y + 200], radius=70, fill=t.accent)
    d.text((W // 2, y + 130), "保存してあとで見返そう", font=font("bold", 50), fill=(255, 255, 255), anchor="mm")
    y += 260
    if blog_cta:
        d.rounded_rectangle([100, y, W - 100, y + 130], radius=65, outline=t.brand, width=5)
        d.text((W // 2, y + 65), "詳しくはプロフのリンク（ブログ）へ", font=font("bold", 42), fill=t.brand, anchor="mm")
        y += 170
    d.text((W // 2, y + 40), f"フォローは {t.handle}", font=font("regular", 42), fill=t.text, anchor="mm")
    fs = font("regular", 26)
    _draw_lines(d, wrap(d, disclaimer, fs, W - 200), fs, 100, H - 160, (120, 120, 120), 1.4)
    return im


def render_carousel(item: dict, design: dict, disclaimer: str, out_dir: Path, resolve: Resolver = _none) -> list[Path]:
    t = Theme(design)
    out_dir.mkdir(parents=True, exist_ok=True)

    def img(mid: str):
        r = resolve(mid) if mid else None
        return r[0] if r and r[1] == "image" else None

    slides = item["slides"][:8]
    total = len(slides) + 2
    imgs = [carousel_cover(t, item["cover_title"], item["cover_subtitle"], total, img(item.get("cover_material_id", "")))]
    for i, s in enumerate(slides, start=1):
        imgs.append(carousel_slide(t, i, total, s["heading"], s["points"][:4 if not img(s.get("material_id", "")) else 3],
                                   img(s.get("material_id", ""))))
    imgs.append(carousel_closing(t, item["closing_message"], disclaimer, bool(item.get("blog_url"))))
    paths = []
    for i, im in enumerate(imgs, start=1):
        p = out_dir / f"slide-{i:02d}.jpg"
        im.save(p, "JPEG", quality=92)
        paths.append(p)
    return paths


def x_image(photo: Path, out: Path) -> Path:
    """X添付用に長辺2048pxへ縮小。"""
    im = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    im.thumbnail((2048, 2048))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=90)
    return out


# ---------- リール（1080x1920） ----------
RW, RH = 1080, 1920
FPS = 30


def reel_plain(t: Theme, text: str, is_hook: bool) -> Image.Image:
    """素材が無いシーン用の背景（文字なし）。"""
    return Image.new("RGB", (RW, RH), t.brand if is_hook else t.bg)


def reel_overlay(t: Theme, text: str, idx: int, total: int, is_hook: bool, on_media: bool, area: str = "middle") -> Image.Image:
    """文字・ハンドル・進捗バーを描いた透過PNG。"""
    im = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f, lines = fit(d, text, "bold", [120, 108, 96, 88, 80] if is_hook else [96, 88, 80, 72], RW - 200, 6)
    lh = int(f.size * 1.4)
    block_h = lh * len(lines)
    y = {"top": 330, "middle": (RH - block_h) // 2 - 60, "bottom": RH - 560 - block_h}.get(area, (RH - block_h) // 2)
    if on_media:
        pad = 50
        widest = max(d.textlength(ln, font=f) for ln in lines)
        box = [(RW - widest) // 2 - pad, y - pad + 10, (RW + widest) // 2 + pad, y + block_h + pad - 20]
        d.rounded_rectangle(box, radius=36, fill=(*t.brand, 215) if is_hook else (0, 0, 0, 150))
        color = (255, 255, 255)
    else:
        color = (255, 255, 255) if is_hook else t.text
    for ln in lines:
        d.text((RW // 2, y), ln, font=f, fill=color, anchor="ma")
        y += lh
    d.rectangle([0, RH - 14, int(RW * idx / total), RH], fill=(*t.accent, 255))
    d.text((RW // 2, RH - 300), t.handle, font=font("bold", 40), fill=(255, 255, 255, 230) if on_media else (*t.accent, 255),
           anchor="mm", stroke_width=2 if on_media else 0, stroke_fill=(0, 0, 0, 160))
    return im


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def _segment(bg: tuple[Path, str] | None, overlay: Path, plain: Path, secs: float, out: Path, zoom_in: bool) -> None:
    """1シーン分の無音mp4を作る（背景: 動画/写真/無地 + 文字の重ね合わせ）。"""
    fill = f"scale={RW}:{RH}:force_original_aspect_ratio=increase,crop={RW}:{RH},setsar=1"
    if bg and bg[1] == "video":
        inputs = ["-ss", "0.3", "-t", f"{secs}", "-i", str(bg[0])]
        vf = f"[0:v]{fill},fps={FPS}[b]"
    elif bg and bg[1] == "image":
        frames = int(secs * FPS)
        z = "min(zoom+0.0009,1.12)" if zoom_in else "if(eq(on,0),1.12,max(zoom-0.0009,1.0))"
        inputs = ["-loop", "1", "-t", f"{secs}", "-i", str(bg[0])]
        vf = (f"[0:v]scale={RW * 2}:{RH * 2}:force_original_aspect_ratio=increase,crop={RW * 2}:{RH * 2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={RW}x{RH}:fps={FPS},setsar=1[b]")
    else:
        inputs = ["-loop", "1", "-t", f"{secs}", "-i", str(plain)]
        vf = f"[0:v]{fill},fps={FPS}[b]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-loop", "1", "-t", f"{secs}", "-i", str(overlay),
           "-filter_complex", f"{vf};[b][1:v]overlay=0:0:format=auto[v]", "-map", "[v]", "-t", f"{secs}", "-an", *ENC, str(out)]
    subprocess.run(cmd, check=True)


def render_reel(item: dict, design: dict, out_dir: Path, resolve: Resolver = _none, bgm: Path | None = None) -> dict:
    """シーンごとに 素材（動画/写真）＋文字 を作ってつなげ、BGMを付けて mp4 にする。"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg がインストールされていません")
    t = Theme(design)
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = [{"text": item["hook"], "seconds": 2.0, "material_id": item.get("hook_material_id", "")}] + item["scenes"]
    total = len(scenes)
    durations = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        segs = []
        for i, s in enumerate(scenes):
            secs = max(1.5, min(float(s.get("seconds", 3)), 6.0))
            r = resolve(s.get("material_id", "")) if s.get("material_id") else None
            if r and r[1] == "video":  # 動画が短ければその長さに合わせる
                secs = min(secs, max(1.5, _probe_duration(r[0]) - 0.4))
            durations.append(secs)
            ov = tmp / f"ov{i:02d}.png"
            reel_overlay(t, s["text"], i + 1, total, i == 0, bool(r), r[2] if r else "middle").save(ov)
            plain = tmp / f"bg{i:02d}.png"
            reel_plain(t, s["text"], i == 0).save(plain)
            seg = tmp / f"s{i:02d}.mp4"
            _segment((r[0], r[1]) if r else None, ov, plain, secs, seg, zoom_in=i % 2 == 0)
            segs.append(seg)
        (tmp / "list.txt").write_text("\n".join(f"file '{p}'" for p in segs))
        duration = sum(durations)
        silent = tmp / "silent.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                        "-c", "copy", str(silent)], check=True)
        if bgm is None:
            bgms = sorted((ASSETS_DIR / "bgm").glob("*.mp3"))
            bgm = random.choice(bgms) if bgms else None
        audio = ["-stream_loop", "-1", "-i", str(bgm)] if bgm else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        video = out_dir / "reel.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), *audio, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-af", f"volume=0.8,afade=t=out:st={max(duration - 1.5, 0):.2f}:d=1.5",
                        "-t", f"{duration:.2f}", "-movflags", "+faststart", str(video)], check=True)
        # カバー画像 = 1シーン目の静止画
        cover = out_dir / "cover.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.8", "-i", str(video), "-frames:v", "1",
                        "-q:v", "2", str(cover)], check=True)
    return {"video": video, "cover": cover, "duration": duration}


def _probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 3.0
