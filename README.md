# reels-thermomix

Genera Reels verticales (1080x1920) de recetasthermomix.net con FFmpeg + Pillow, gratis.

- `generate.py receta.json salida.mp4`: crea el vídeo desde un JSON (ver `examples/`).
- `.github/workflows/reel.yml`: acción manual (workflow_dispatch) que genera el vídeo y lo publica como release.
