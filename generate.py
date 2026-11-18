#!/usr/bin/env python3
"""Genera un Reel vertical (1080x1920, mp4) a partir de un JSON de receta.

Uso: python generate.py receta.json salida.mp4

Formato del JSON (ver examples/bizcocho-marmol.json):
{
  "photo_url": "https://.../foto.jpg",
  "titulo": ["Bizcocho", "mármol"],
  "gancho": ["Merienda de dos colores", "¡Con un solo vaso Thermomix!"],
  "ingredientes": ["2 huevos", "180 g de azúcar", ...],
  "pasos": [
    {"titulo": ["La masa", "base"], "texto": ["...", "..."]},
    {"titulo": [...], "texto": [...]},
    {"titulo": [...], "texto": [...]}
  ],
  "cta": "recetasthermomix.net"
}
"""
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.request
import wave

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Montserrat-VF.ttf")
CREAM = (250, 238, 218, 255)
LEMON = (244, 201, 76, 255)
CHOC = (30, 20, 16)
PANEL_H = 700  # alto de la foto en pantalla
PANEL_Y = 150
TEXT_Y = 880  # inicio del texto (deja libre el borde inferior de la interfaz de Facebook)


def font(size, weight="ExtraBold"):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


def wrap(draw, text, fnt, maxw):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


CHIP_RE = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:min(?:utos?)?\b|\')", re.I), lambda m: f"{m.group(1)} MIN"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:s\b|seg(?:undos?)?\b)", re.I), lambda m: f"{m.group(1)} SEG"),
    (re.compile(r"(\d{2,3})\s*(?:°|º|grados)", re.I), lambda m: f"{m.group(1)} °C"),
    (re.compile(r"\bvaroma\b", re.I), lambda m: "VAROMA"),
    (re.compile(r"vel(?:ocidad)?\.?\s*(\d+(?:[.,]\d+)?|cuchara|giro inverso)", re.I), lambda m: f"VEL {m.group(1).upper()}"),
]


def chips_from(lines, limit=4):
    """Extrae tiempo / temperatura / velocidad de las lineas del paso."""
    found, seen = [], set()
    for ln in lines:
        for rx, fmt in CHIP_RE:
            for m in rx.finditer(ln):
                c = fmt(m)
                if c not in seen:
                    seen.add(c)
                    found.append(c)
    return found[:limit]


def text_layer(path, kicker, title_lines, body, body_size=54, title_size=80, extra=None, bullets=True,
               y0=TEXT_Y, chips=None, gradient=False):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if gradient:
        for yy in range(820, H):
            a = int(255 * min(1.0, (yy - 820) / 480))
            d.line((0, yy, W, yy), fill=CHOC + (a,))
    d.text((60, 80), "RECETAS THERMOMIX", font=font(34, "Bold"), fill=LEMON)
    d.rectangle((60, 128, 200, 133), fill=LEMON)
    y = y0
    if kicker:
        d.text((60, y), kicker, font=font(38, "Bold"), fill=LEMON)
        y += 70
    for ln in title_lines:
        d.text((60, y), ln, font=font(title_size), fill=CREAM)
        y += int(title_size * 1.15)
    y += 24
    if chips:
        cf = font(46, "ExtraBold")
        x = 60
        for c in chips:
            tw = d.textlength(c, font=cf)
            d.rounded_rectangle((x, y, x + tw + 56, y + 78), radius=39, fill=LEMON)
            d.text((x + 28, y + 12), c, font=cf, fill=CHOC)
            x += tw + 56 + 18
        y += 78 + 30
    bf = font(body_size, "SemiBold")
    for item in body:
        lines = wrap(d, item, bf, 860)
        if bullets:
            d.ellipse((60, y + 16, 80, y + 36), fill=LEMON)
        for ln in lines:
            d.text((105 if bullets else 60, y), ln, font=bf, fill=CREAM)
            y += int(body_size * 1.3)
        y += 22
    if extra:
        d.text((60, y + 10), extra, font=font(40, "Bold"), fill=LEMON)
    img.save(path)


def as_lines(v):
    if isinstance(v, str):
        return [s for s in v.replace("\\n", "\n").split("\n") if s.strip()]
    return list(v)


def main(src, dst):
    data = json.load(open(src, encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="reel_")

    photo_path = os.path.join(tmp, "foto")
    req = urllib.request.Request(data["photo_url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(photo_path, "wb") as f:
        f.write(r.read())
    photo = Image.open(photo_path).convert("RGB")

    # fondo: foto desenfocada y oscurecida
    scale = max(W / photo.width, H / photo.height)
    bg = photo.resize((int(photo.width * scale) + 1, int(photo.height * scale) + 1), Image.LANCZOS)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), CHOC), 0.78)
    bg_path = os.path.join(tmp, "bg.png")
    bg.save(bg_path)

    # foto para el panel: cubre al menos PANEL_H de alto y W de ancho, con margen para el paneo
    ps = max(900 / photo.height, (W + 120) / photo.width)
    pw, ph = int(photo.width * ps), int(photo.height * ps)
    panel = photo.resize((pw, ph), Image.LANCZOS)
    panel_path = os.path.join(tmp, "panel.jpg")
    panel.save(panel_path, quality=95)
    max_x = pw - W
    max_y = ph - PANEL_H

    pasos = data["pasos"][:3]
    ing = as_lines(data["ingredientes"])[:9]
    cta = data.get("cta", "recetasthermomix.net")

    # portada a pantalla completa (zoom lento): la foto cubre 1080x1920 con margen
    HERO_H = 1300
    hs = max(HERO_H * 1.0 / photo.height, W * 1.0 / photo.width)
    hero = photo.resize((int(photo.width * hs), int(photo.height * hs)), Image.LANCZOS)
    hero_path = os.path.join(tmp, "hero.jpg")
    hero.save(hero_path, quality=95)

    # (nombre, duracion, kicker, titulo, cuerpo, extra, tam titulo, tam cuerpo, vinetas, paneo, chips)
    scenes = [
        ("s1", 2.5, None, as_lines(data["titulo"]), as_lines(data["gancho"]), None, 104, 56, False, None, None),
        ("s2", min(4.5, 1.8 + 0.3 * len(ing)), "INGREDIENTES", [], ing, None, 80, 50, True, (0.9, 0.3), None),
    ]
    for i, p in enumerate(pasos, 1):
        body = as_lines(p["texto"])
        dur = min(4.2, 2.2 + 0.4 * len(body))
        scenes.append((f"s{i+2}", dur, f"PASO {i}", as_lines(p["titulo"]), body, None, 80, 50, True,
                       ((0.4, 0.8) if i % 2 else (0.8, 0.3)), chips_from(body)))
    scenes.append(("s6", 2.5, None, ["Receta", "completa"], [cta, "Paso a paso en el primer comentario"],
                   None, 96, 54, False, (0.2, 0.5), None))
    total = sum(sc[1] for sc in scenes)

    bar_path = os.path.join(tmp, "bar.png")
    Image.new("RGB", (W, 12), LEMON[:3]).save(bar_path)

    files, offset = [], 0.0
    for name, dur, kicker, title, body, extra, tsz, bsz, bul, pan, chips in scenes:
        layer = os.path.join(tmp, f"{name}.png")
        hero_scene = pan is None
        text_layer(layer, kicker, title, body, body_size=bsz, title_size=tsz, extra=extra, bullets=bul,
                   y0=(1090 if hero_scene else TEXT_Y), chips=chips, gradient=hero_scene)
        out = os.path.join(tmp, f"{name}.mp4")
        # el texto entra con un pequeno deslizamiento hacia arriba
        text_fx = (f"[2:v]format=rgba,fade=t=in:st=0.1:d=0.35:alpha=1[t];")
        bar_fx = f"[3:v]format=rgba[b];"
        end = (f"overlay=0:'if(lt(t,0.45),36*(1-t/0.45),0)'[x];"
                f"[x][b]overlay=x='-{W}+{W}*({offset}+t)/{total}':y=0,format=yuv420p,"
                f"fade=t=in:st=0:d=0.2,fade=t=out:st={dur-0.2}:d=0.2[v]")
        if hero_scene:
            fc = (text_fx + bar_fx +
                  f"[1:v]scale=w='iw*(1+0.07*t/{dur})':h=-1:eval=frame,crop={W}:{HERO_H}[h];"
                  f"[0:v][h]overlay=0:0[a];[a][t]" + end)
            inputs = ["-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bg_path]
        else:
            x0, x1 = int(max_x * pan[0]), int(max_x * pan[1])
            y0p = max_y // 2
            fc = (text_fx + bar_fx +
                  f"[1:v]crop={W}:{PANEL_H}:x='{x0}+({x1}-{x0})*t/{dur}':y={y0p}[c];"
                  f"[0:v][c]overlay=0:{PANEL_Y}[a];[a][t]" + end)
            inputs = ["-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bg_path]
        cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", panel_path if not hero_scene else hero_path,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", layer,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bar_path,
               "-filter_complex", fc, "-map", "[v]", "-r", "30",
               "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, check=True)
        files.append(out)
        offset += dur

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for p in files:
            f.write(f"file '{p}'\n")
    silent = os.path.join(tmp, "silent.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", silent], check=True)

    # musica ambiente generada por codigo (sin derechos de autor)
    wav = os.path.join(tmp, "musica.wav")
    make_music(wav, total + 0.5)
    part = dst + ".part.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-af", f"afade=t=in:st=0:d=0.8,afade=t=out:st={total-1.5}:d=1.5",
                    "-t", str(total), "-movflags", "+faststart", part], check=True)
    os.replace(part, dst)
    print(f"ok: {dst} ({total:.1f} s)")


def make_music(path, seconds, sr=32000):
    """Arpegio suave sobre C - Am - F - G con un colchon de acordes. Volumen bajo."""
    chords = [[261.63, 329.63, 392.0], [220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 246.94, 293.66]]
    bpm, n = 96, int(seconds * sr)
    beat = 60.0 / bpm / 2  # corcheas
    frames = bytearray()
    for i in range(n):
        t = i / sr
        ci = int(t / (beat * 8)) % 4
        ch = chords[ci]
        k = int(t / beat)
        f = ch[[0, 1, 2, 1, 0, 1, 2, 1][k % 8]] * 2
        tb = t - k * beat
        env = math.exp(-5.0 * tb)
        pluck = env * (math.sin(2 * math.pi * f * t) + 0.35 * math.sin(4 * math.pi * f * t)) * 0.32
        pad = sum(math.sin(2 * math.pi * fr * t) for fr in ch) * 0.07 * (0.8 + 0.2 * math.sin(2 * math.pi * 0.25 * t))
        v = max(-1.0, min(1.0, (pluck + pad) * 0.8))
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
