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
import os, glob
import re
import subprocess
import sys
import tempfile
import urllib.request
import wave

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "JosefinSans-VF.ttf")
# Marca Recetas Thermomix: negro y dorado del logo (#B88828, aclarado para leerse sobre negro) y tipografia Josefin Sans
CREAM = (250, 247, 240, 255)
LEMON = (214, 164, 58, 255)
CHOC = (10, 10, 10)
PANEL_H = 700  # alto de la foto en pantalla
PANEL_Y = 150
TEXT_Y = 880  # inicio del texto (deja libre el borde inferior de la interfaz de Facebook)


SS = 2  # supersampling del texto: se dibuja al doble y se reduce con Lanczos


def font(size, weight="ExtraBold"):
    f = ImageFont.truetype(FONT, int(size * SS))
    try:
        f.set_variation_by_name("Bold" if weight in ("ExtraBold", "Black", "Bold") else weight)
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


class _SD:
    """Dibujante que escala coordenadas y tamanos por SS."""
    def __init__(self, d):
        self.d = d

    def text(self, xy, t, font=None, fill=None):
        self.d.text((xy[0] * SS, xy[1] * SS), t, font=font, fill=fill)

    def line(self, xy, fill=None):
        self.d.line(tuple(v * SS for v in xy), fill=fill, width=SS)

    def rectangle(self, xy, fill=None):
        self.d.rectangle(tuple(v * SS for v in xy), fill=fill)

    def ellipse(self, xy, fill=None):
        self.d.ellipse(tuple(v * SS for v in xy), fill=fill)

    def rounded_rectangle(self, xy, radius=0, fill=None):
        self.d.rounded_rectangle(tuple(v * SS for v in xy), radius=radius * SS, fill=fill)

    def textlength(self, t, font=None):
        return self.d.textlength(t, font=font) / SS


def text_layer(path, kicker, title_lines, body, body_size=54, title_size=80, extra=None, bullets=True,
               y0=TEXT_Y, chips=None, gradient=False):
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = _SD(ImageDraw.Draw(big))
    if gradient:
        for yy in range(820, H):
            a = int(255 * min(1.0, (yy - 820) / 480))
            d.line((0, yy, W, yy), fill=CHOC + (a,))
    if gradient:  # degradado oscuro arriba para que la marca se lea sobre la foto de la portada
        for yy in range(0, 260):
            d.line((0, yy, W, yy), fill=CHOC + (int(210 * (1 - yy / 260)),))
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
    big.resize((W, H), Image.LANCZOS).save(path)


def as_lines(v):
    if isinstance(v, str):
        return [s for s in v.replace("\\n", "\n").split("\n") if s.strip()]
    return list(v)


def main(src, dst):
    data = json.load(open(src, encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="reel_")

    photo_path = os.path.join(tmp, "foto")
    import re
    url0 = data["photo_url"]
    # WordPress guarda miniaturas "nombre-300x200.jpg": probamos primero el original a maxima resolucion
    cands = [re.sub(r"-\d{2,4}x\d{2,4}(\.[A-Za-z]+)$", r"\1", url0), url0]
    blob = None
    for u in dict.fromkeys(cands):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            break
        except Exception as ex:
            print("foto no disponible:", u, ex)
    open(photo_path, "wb").write(blob)
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
    ps = max(PANEL_H * 2 * 1.12 / photo.height, (W * 2 + 200) / photo.width)  # al doble: se reduce despues
    pw, ph = int(photo.width * ps), int(photo.height * ps)
    panel = photo.resize((pw, ph), Image.LANCZOS)
    panel_path = os.path.join(tmp, "panel.jpg")
    panel.save(panel_path, quality=95)
    max_x = pw - W * 2
    max_y = ph - PANEL_H * 2

    pasos = data["pasos"][:3]
    ing = as_lines(data["ingredientes"])[:9]
    cta = data.get("cta", "recetasthermomix.net")

    # portada a pantalla completa (zoom lento): la foto cubre 1080x1920 con margen
    HERO_H = 960
    hs = max(HERO_H * 2.0 / photo.height, W * 2.0 / photo.width)
    hero = photo.resize((int(photo.width * hs), int(photo.height * hs)), Image.LANCZOS)
    hero_path = os.path.join(tmp, "hero.jpg")
    hero.save(hero_path, quality=95)

    # (nombre, duracion, kicker, titulo, cuerpo, extra, tam titulo, tam cuerpo, vinetas, paneo, chips)
    scenes = [
        ("s1", 2.0, None, as_lines(data["titulo"]), as_lines(data["gancho"]), None, 104, 56, False, None, None),
        ("s2", min(3.4, 1.3 + 0.24 * len(ing)), "INGREDIENTES", [], ing, None, 80, 50, True, (0.9, 0.3), None),
    ]
    for i, p in enumerate(pasos, 1):
        body = as_lines(p["texto"])
        dur = min(3.2, 1.7 + 0.35 * len(body))
        scenes.append((f"s{i+2}", dur, f"PASO {i}", as_lines(p["titulo"]), body, None, 80, 50, True,
                       ((0.4, 0.8) if i % 2 else (0.8, 0.3)), chips_from(body)))
    scenes.append(("s6", 2.4, None, ["Receta", "completa"], [cta, "Paso a paso en el primer comentario"],
                   None, 96, 54, False, (0.2, 0.5), None))
    total = sum(sc[1] for sc in scenes)

    bar_path = os.path.join(tmp, "bar.png")
    Image.new("RGB", (W, 12), LEMON[:3]).save(bar_path)

    files, offset = [], 0.0
    starts = []
    for name, dur, kicker, title, body, extra, tsz, bsz, bul, pan, chips in scenes:
        layer = os.path.join(tmp, f"{name}.png")
        hero_scene = pan is None
        text_layer(layer, kicker, title, body, body_size=bsz, title_size=tsz, extra=extra, bullets=bul,
                   y0=(1040 if hero_scene else TEXT_Y), chips=chips, gradient=hero_scene)
        out = os.path.join(tmp, f"{name}.mp4")
        # el texto entra con un pequeno deslizamiento hacia arriba
        # en la portada (escena 1) el texto ya esta visible desde el primer fotograma: asi Facebook lo usa como miniatura
        text_fx = ("[2:v]format=rgba[t];" if hero_scene else "[2:v]format=rgba,fade=t=in:st=0.1:d=0.35:alpha=1[t];")
        slide = "0" if hero_scene else "if(lt(t,0.45),36*(1-t/0.45),0)"
        fin = "" if hero_scene else "fade=t=in:st=0:d=0.2,"
        bar_fx = f"[3:v]format=rgba[b];"
        end = (f"overlay=0:'{slide}'[x];"
                f"[x][b]overlay=x='-{W}+{W}*({offset}+t)/{total}':y=0,scale=1440:2560:flags=lanczos+accurate_rnd+full_chroma_int:out_color_matrix=bt709,format=yuv420p,"
                f"{fin}fade=t=out:st={dur-0.2}:d=0.2[v]")
        if hero_scene:
            fc = (text_fx + bar_fx +
                  f"[1:v]scale=w='iw*(1+0.04*t/{dur})':h=-1:eval=frame:flags=lanczos,crop={W*2}:{HERO_H*2},scale={W}:{HERO_H}:flags=lanczos+accurate_rnd,eq=saturation=1.15:contrast=1.06,unsharp=5:5:0.8[h];"
                  f"[0:v][h]overlay=0:0[a];[a][t]" + end)
            inputs = ["-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bg_path]
        else:
            x0, x1 = int(max_x * pan[0]), int(max_x * pan[1])
            y0p = max_y // 2
            fc = (text_fx + bar_fx +
                  f"[1:v]crop={W*2}:{PANEL_H*2}:x='{x0}+({x1}-{x0})*t/{dur}':y={y0p},scale={W}:{PANEL_H}:flags=lanczos+accurate_rnd,eq=saturation=1.12:contrast=1.05,unsharp=5:5:0.6[c];"
                  f"[0:v][c]overlay=0:{PANEL_Y}[a];[a][t]" + end)
            inputs = ["-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bg_path]
        cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + [
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", panel_path if not hero_scene else hero_path,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", layer,
               "-framerate", "30", "-loop", "1", "-t", str(dur), "-i", bar_path,
               "-filter_complex", fc, "-map", "[v]", "-r", "30",
               "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-tune", "film", "-g", "60", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", out]
        subprocess.run(cmd, check=True)
        files.append(out)
        starts.append(offset)
        offset += dur

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for p in files:
            f.write(f"file '{p}'\n")
    silent = os.path.join(tmp, "silent.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", silent], check=True)

    # musica: pista CC0 real (carpeta music/) rotando por receta; si falla, musica sintetica
    key = sum(ord(c) for c in str(data.get("name", data["titulo"])))
    tracks = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "music", "*.m4a")))
    wav = os.path.join(tmp, "musica.wav")
    done = False
    if tracks:
        tr = tracks[key % len(tracks)]
        off = 4 + (key * 7) % 50  # segundo de inicio distinto en cada receta
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(off), "-i", tr,
                            "-t", str(total + 0.5), "-ac", "2", "-ar", "44100", wav])
        done = r.returncode == 0 and os.path.exists(wav)
    if not done:
        make_music(wav, total + 0.5, variant=key % len(MUSIC_PRESETS))
    part = dst + ".part.mp4"
    # efectos de sonido sincronizados con las escenas (si fallan, el reel sale solo con musica)
    sfx_wav = os.path.join(tmp, "sfx.wav")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sfx import make_sfx
        make_sfx(sfx_wav, starts, total)
        have_sfx = True
    except Exception as ex:
        print("sin sfx:", ex)
        have_sfx = False
    if have_sfx:
        afc = (f"[1:a]loudnorm=I=-20:TP=-2:LRA=7,afade=t=in:st=0:d=0.8,afade=t=out:st={total-1.5}:d=1.5[m];"
               f"[m][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-i", sfx_wav,
                        "-filter_complex", afc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "192k", "-t", str(total), "-movflags", "+faststart", part], check=True)
        os.replace(part, dst)
        print(f"ok: {dst} ({total:.1f} s)")
        return
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-af", f"loudnorm=I=-18:TP=-2:LRA=7,afade=t=in:st=0:d=0.8,afade=t=out:st={total-1.5}:d=1.5",
                    "-t", str(total), "-movflags", "+faststart", part], check=True)
    os.replace(part, dst)
    print(f"ok: {dst} ({total:.1f} s)")


MUSIC_PRESETS = [
    # (bpm, acordes (4 por ciclo), raices, swing del hi-hat, nombre)
    (84, [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 64]], [36, 33, 29, 31], 0.14),  # Cmaj7 Am7 Fmaj7 G6
    (92, [[62, 65, 69, 72], [58, 62, 65, 69], [55, 58, 62, 65], [57, 61, 64, 67]], [38, 34, 31, 33], 0.10),  # Dm7 Bbmaj7 Gm7 A7
    (78, [[65, 69, 72, 76], [62, 65, 69, 72], [58, 62, 65, 69], [60, 64, 67, 70]], [41, 38, 34, 36], 0.17),  # Fmaj7 Dm7 Bbmaj7 C7
    (88, [[67, 71, 74, 78], [64, 67, 71, 74], [60, 64, 67, 71], [62, 66, 69, 72]], [43, 40, 36, 38], 0.12),  # Gmaj7 Em7 Cmaj7 D7
]


def make_music(path, seconds, sr=32000, variant=0):
    """Base lo-fi tranquila generada por codigo (sin derechos): piano electrico, bajo y percusion suave."""
    import numpy as np

    bpm, chords, roots, swing = MUSIC_PRESETS[variant % len(MUSIC_PRESETS)]
    beat = 60.0 / bpm
    n = int(seconds * sr)
    t = np.arange(n) / sr
    mix = np.zeros(n)
    rng = np.random.default_rng(7)

    def midi(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    # una barra de 4 tiempos por acorde

    def add(start, sig):
        i = int(start * sr)
        if i >= n:
            return
        seg = sig[: n - i]
        mix[i : i + len(seg)] += seg

    def epiano(freq, dur, vel):
        tt = np.arange(int(dur * sr)) / sr
        env = np.exp(-2.6 * tt) * (1 - np.exp(-tt * 90))
        mod = np.sin(2 * np.pi * freq * tt) * 1.4 * np.exp(-5 * tt)
        return vel * env * (np.sin(2 * np.pi * freq * tt + mod) + 0.25 * np.sin(2 * np.pi * freq * 2 * tt) * np.exp(-4 * tt))

    bar = 0
    while bar * 4 * beat < seconds:
        k = bar % 4
        t0 = bar * 4 * beat
        notes = chords[k]
        # acorde en el tiempo 1 y sincopado en el "y" del 2, con rasgueo suave
        for hit, vel in ((0.0, 0.16), (1.5, 0.11), (2.75, 0.09)):
            for j, m in enumerate(notes):
                add(t0 + hit * beat + j * 0.018, epiano(midi(m), 2.2, vel))
        # bajo en 1 y 3
        for hit in (0.0, 2.0):
            d = np.arange(int(1.4 * sr)) / sr
            f = midi(roots[k])
            add(t0 + hit * beat, 0.34 * np.exp(-2.2 * d) * (np.sin(2 * np.pi * f * d) + 0.3 * np.sin(4 * np.pi * f * d)))
        # bombo en 1 y 3
        for hit in (0.0, 2.0):
            d = np.arange(int(0.3 * sr)) / sr
            add(t0 + hit * beat, 0.42 * np.exp(-14 * d) * np.sin(2 * np.pi * (48 + 90 * np.exp(-30 * d)) * d))
        # caja suave en 2 y 4
        for hit in (1.0, 3.0):
            d = np.arange(int(0.22 * sr)) / sr
            noise = rng.standard_normal(len(d))
            noise = np.convolve(noise, np.ones(6) / 6, mode="same")
            add(t0 + hit * beat, 0.16 * np.exp(-18 * d) * noise)
        # hi-hat en corcheas con swing
        for q in range(8):
            off = (q * 0.5) + (swing if q % 2 else 0.0)
            d = np.arange(int(0.06 * sr)) / sr
            noise = rng.standard_normal(len(d))
            noise = noise - np.convolve(noise, np.ones(4) / 4, mode="same")
            add(t0 + off * beat, (0.07 if q % 2 else 0.045) * np.exp(-60 * d) * noise)
        bar += 1

    # filtro paso bajo suave (sonido calido) y normalizacion
    kern = np.ones(3) / 3
    mix = np.convolve(mix, kern, mode="same")
    peak = np.max(np.abs(mix)) or 1.0
    mix = mix / peak * 0.55
    pcm = (mix * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
