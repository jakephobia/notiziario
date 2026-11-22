"""Copertina statica 1400x1400 per il podcast."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(percorsi: list[str], dimensione: int):
    for percorso in percorsi:
        try:
            return ImageFont.truetype(percorso, dimensione)
        except Exception:
            continue
    return ImageFont.load_default()


def crea_copertina(percorso: str | Path, dimensione: int = 1400) -> Path:
    path = Path(percorso)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (dimensione, dimensione), (244, 231, 211))
    draw = ImageDraw.Draw(img)
    bordo = max(40, dimensione // 23)
    draw.rounded_rectangle(
        (bordo, bordo, dimensione - bordo, dimensione - bordo),
        radius=max(28, dimensione // 26),
        outline=(20, 78, 54),
        width=max(3, dimensione // 230),
    )
    raggio = dimensione // 7
    cx = dimensione - raggio - bordo
    cy = bordo + raggio
    draw.ellipse((cx - raggio, cy - raggio, cx + raggio, cy + raggio), fill=(20, 78, 54))
    raggio2 = dimensione // 18
    draw.ellipse((cx - raggio2, cy - raggio2, cx + raggio2, cy + raggio2), fill=(238, 196, 120))

    titolo = _font(
        ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf", "DejaVuSans-Bold.ttf"],
        int(dimensione * 0.136),
    )
    sottotitolo = _font(
        ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf", "DejaVuSans.ttf"],
        int(dimensione * 0.046),
    )
    piccolo = _font(
        ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf", "DejaVuSans.ttf"],
        int(dimensione * 0.03),
    )
    centro = dimensione // 2
    draw.text((centro, int(dimensione * 0.385)), "NOTIZIARIO", font=titolo, fill=(18, 59, 42), anchor="mm")
    draw.text((centro, int(dimensione * 0.532)), "Le notizie del giorno", font=sottotitolo, fill=(18, 59, 42), anchor="mm")
    draw.line(
        (int(dimensione * 0.27), int(dimensione * 0.607), int(dimensione * 0.73), int(dimensione * 0.607)),
        fill=(20, 78, 54),
        width=max(2, dimensione // 350),
    )
    draw.text((centro, int(dimensione * 0.671)), "di Jacopo", font=piccolo, fill=(88, 92, 72), anchor="mm")
    draw.text((centro, int(dimensione * 0.886)), "Ogni mattina, in italiano", font=piccolo, fill=(88, 92, 72), anchor="mm")
    img.save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":  # pragma: no cover
    crea_copertina("docs/copertina.png")
