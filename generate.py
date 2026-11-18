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
import os
import subprocess
import sys
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Montserrat-VF.ttf")
CREAM = (250, 238, 218, 255)
LEMON = (244, 201, 76, 255)
CHOC = (30, 20, 16)
PANEL_H = 800  # alto de la foto en pantalla
PANEL_Y = 160


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


def text_layer(path, kicker, title_lines, body, body_size=54, title_size=80, extra=None, bullets=True):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((60, 80), "RECETAS THERMOMIX", font=font(34, "Bold"), fill=LEMON)
    d.rectangle((60, 128, 200, 133), fill=LEMON)
    y = 1010
    if kicker:
        d.text((60, y), kicker, font=font(38, "Bold"), fill=LEMON)
        y += 70
    for ln in title_lines:
        d.text((60, y), ln, font=font(title_size), fill=CREAM)
        y += int(title_size * 1.15)
    y += 24
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

    # (nombre, duración, kicker, título, cuerpo, extra, tamaño título, tamaño cuerpo, viñetas, (x0,x1))
    scenes = [
        ("s1", 3.5, None, as_lines(data["titulo"]), as_lines(data["gancho"]), None, 96, 54, False, (0.3, 0.6)),
        ("s2", min(7.0, 3.0 + 0.45 * len(ing)), "INGREDIENTES", [], ing, None, 80, 50, True, (0.9, 0.3)),
    ]
    for i, p in enumerate(pasos, 1):
        body = as_lines(p["texto"])
        scenes.append((f"s{i+2}", min(7.0, 3.0 + 0.45 * sum(max(1, len(b) // 38) for b in body)),
                       f"PASO {i}", as_lines(p["titulo"]), body, None, 80, 54, True,
                       ((0.4, 0.8) if i % 2 else (0.8, 0.3))))
    scenes.append(("s6", 3.5, None, ["Receta", "completa"], [cta, "Más recetas gratis en nuestro canal de WhatsApp"],
                   "Guárdalo y compártelo", 96, 54, False, (0.2, 0.5)))

    files = []
    for name, dur, kicker, title, body, extra, tsz, bsz, bul, (fx0, fx1) in scenes:
        layer = os.path.join(tmp, f"{name}.png")
        text_layer(layer, kicker, title, body, body_size=bsz, title_size=tsz, extra=extra, bullets=bul)
        x0, x1 = int(max_x * fx0), int(max_x * fx1)
        y0 = max_y // 2
        out = os.path.join(tmp, f"{name}.mp4")
        fc = (f"[1:v]crop={W}:{PANEL_H}:x='{x0}+({x1}-{x0})*t/{dur}':y={y0}[c];"
              f"[0:v][c]overlay=0:{PANEL_Y}[a];[a][2:v]overlay=0:0,format=yuv420p,"
              f"fade=t=in:st=0:d=0.3,fade=t=out:st={dur-0.3}:d=0.3[v]")
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bg_path,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", panel_path,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", layer,
               "-filter_complex", fc, "-map", "[v]", "-r", "30",
               "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, check=True)
        files.append(out)

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for p in files:
            f.write(f"file '{p}'\n")
    part = dst + ".part.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", part], check=True)
    os.replace(part, dst)
    print(f"ok: {dst} ({sum(s[1] for s in scenes):.1f} s)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
