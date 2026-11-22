from __future__ import annotations

from pathlib import Path

from PIL import Image

from notiziario.copertina import crea_copertina


def test_copertina_1400_valida(tmp_path):
    percorso = crea_copertina(tmp_path / "copertina.png")
    with Image.open(percorso) as img:
        assert img.size == (1400, 1400)
        assert img.mode == "RGB"
        assert img.format == "PNG"
