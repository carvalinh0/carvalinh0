"""ASCII art for the left side of the card."""
from __future__ import annotations

import io
from pathlib import Path
from statistics import median
from typing import Callable

import requests

# sparse -> dense
RAMP = " .:-=+*#%@"


def image_to_ascii(
    data: bytes,
    width: int,
    aspect: float,
    contrast: float = 1.4,
    invert: bool = False,
) -> list[str]:
    """Convert image bytes to lines of text.

    ``aspect`` is char_width / line_height (a character is taller than wide).
    The background is detected from the image border and mapped to blank,
    so it works for both light and dark avatars; ``invert`` flips it.
    """
    from PIL import Image, ImageEnhance, ImageOps

    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(base, rgba)
    img = ImageOps.autocontrast(img.convert("L"))
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    height = max(1, round(width * img.height / img.width * aspect))
    img = img.resize((width, height), Image.LANCZOS)
    px = img.load()

    border = [px[x, 0] for x in range(width)] + [px[x, height - 1] for x in range(width)]
    border += [px[0, y] for y in range(height)] + [px[width - 1, y] for y in range(height)]
    background_is_bright = median(border) > 127
    if invert:
        background_is_bright = not background_is_bright

    last = len(RAMP) - 1
    lines = []
    for y in range(height):
        row = []
        for x in range(width):
            density = (255 - px[x, y]) if background_is_bright else px[x, y]
            row.append(RAMP[round(density / 255 * last)])
        lines.append("".join(row).rstrip())
    return lines


def _read_source(source: str, base_dir: Path) -> bytes:
    if source.startswith(("http://", "https://")):
        resp = requests.get(source, timeout=30)
        resp.raise_for_status()
        return resp.content
    return (base_dir / source).read_bytes()


def _read_text_file(name: str, base_dir: Path) -> list[str]:
    path = base_dir / name
    return [line.rstrip("\n").rstrip() for line in path.read_text(encoding="utf-8").splitlines()]


def load_ascii(
    cfg: dict,
    username: str,
    char_aspect: float,
    base_dir: str | Path = ".",
    allow_network: bool = True,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Return the art lines for the configured source ([] for none)."""
    base_dir = Path(base_dir)
    source = cfg["source"]
    if source == "none":
        return []

    if source in ("avatar", "image"):
        try:
            if source == "avatar":
                if not allow_network:
                    raise RuntimeError("offline mode")
                target = f"https://github.com/{username}.png?size=256"
            else:
                if not cfg["image"]:
                    raise RuntimeError("ascii.image is empty")
                target = cfg["image"]
            data = _read_source(target, base_dir)
            return image_to_ascii(data, int(cfg["width"]), char_aspect,
                                  float(cfg["contrast"]), bool(cfg["invert"]))
        except Exception as exc:  # fall back to the text file, never fail the build
            log(f"   warning: could not generate the ASCII from '{source}' ({exc}); using '{cfg['file']}'.")

    try:
        return _read_text_file(cfg["file"], base_dir)
    except FileNotFoundError:
        log(f"   warning: file '{cfg['file']}' not found; card without ASCII art.")
        return []
