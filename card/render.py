"""Build the SVG cards from the config, the values and the ASCII art."""
from __future__ import annotations

import re
from typing import Callable
from xml.sax.saxutils import escape

from .config import Blank, Config, Field, KNOWN_PLACEHOLDERS, PLACEHOLDER_RE, Row

STYLES = ("key", "value", "add", "del", "dim")
TAG_RE = re.compile(r"<(%s)>(.*?)</\1>" % "|".join(STYLES), re.S)

Segment = tuple[str, str]  # (text, style) ; style "text" = default colour


# --- text segments ----------------------------------------------------------
def parse_segments(template: str, default: str = "value") -> list[Segment]:
    """Split ``template`` on <style>..</style> tags (placeholders untouched)."""
    segs: list[Segment] = []
    pos = 0
    for m in TAG_RE.finditer(template):
        if m.start() > pos:
            segs.append((template[pos:m.start()], default))
        segs.append((m.group(2), m.group(1)))
        pos = m.end()
    if pos < len(template):
        segs.append((template[pos:], default))
    return segs


def substitute(segs: list[Segment], values: dict[str, str], warn: Callable[[str], None]) -> list[Segment]:
    def fill(m: re.Match) -> str:
        name = m.group(1)
        if name in values:
            return " ".join(values[name].split())  # collapse newlines/whitespace
        if name in KNOWN_PLACEHOLDERS:
            return ""  # known but unavailable (e.g. {age} without birthday)
        warn(f"unknown placeholder: {{{name}}}")
        return m.group(0)

    return [(PLACEHOLDER_RE.sub(fill, text), style) for text, style in segs]


def seg_len(segs: list[Segment]) -> int:
    return sum(len(t) for t, _ in segs)


def is_blank(segs: list[Segment]) -> bool:
    return not "".join(t for t, _ in segs).strip()


def truncate(segs: list[Segment], limit: int) -> list[Segment]:
    if seg_len(segs) <= limit or limit < 2:
        return segs
    out: list[Segment] = []
    remaining = limit - 1
    for text, style in segs:
        if remaining <= 0:
            break
        out.append((text[:remaining], style))
        remaining -= len(text)
    out.append(("…", out[-1][1] if out else "value"))
    return out


def key_segments(key: str) -> list[Segment]:
    """'Languages.Programming' -> key . key  (dots stay in the default colour)."""
    segs: list[Segment] = []
    for i, part in enumerate(key.split(".")):
        if i:
            segs.append((".", "text"))
        segs.append((part, "key"))
    return segs


# --- layout -----------------------------------------------------------------
def _field_segments(key: str, value: list[Segment], width: int, prefix: bool) -> list[Segment]:
    head = key_segments(key) + [(":", "text")]
    fixed = seg_len(head) + 2 + seg_len(value)  # ' ' before dots, ' ' after
    avail = width - (2 if prefix else 0)
    dots = max(1, avail - fixed)
    segs: list[Segment] = [(". ", "dim")] if prefix else []
    return segs + head + [(" " + "." * dots + " ", "dim")] + value


def _row_segments(columns: list[tuple[str, list[Segment]]], width: int) -> list[Segment]:
    n = len(columns)
    sep = " | "
    avail = width - 2 - len(sep) * (n - 1)
    natural = [len(k) + seg_len(v) + 4 for k, v in columns]
    extra = max(0, avail - sum(natural))
    widths = [w + extra // n for w in natural]
    widths[-1] += extra - (extra // n) * n
    segs: list[Segment] = [(". ", "dim")]
    for i, ((key, value), w) in enumerate(zip(columns, widths)):
        if i:
            segs.append((sep, "text"))
        head = key_segments(key) + [(":", "text")]
        dots = max(1, w - seg_len(head) - 2 - seg_len(value))
        segs += head + [(" " + "." * dots + " ", "dim")] + value
    return segs


def build_lines(cfg: Config, values: dict[str, str], warn: Callable[[str], None] = print) -> list[list[Segment]]:
    width = int(cfg["theme"]["text_columns"])
    rule = cfg["theme"]["rule"] or "-"
    lines: list[list[Segment]] = []

    def value_of(template: str) -> list[Segment]:
        return substitute(parse_segments(template), values, warn)

    for s_idx, section in enumerate(cfg.sections):
        if s_idx and lines and lines[-1]:
            lines.append([])  # blank line between sections
        title = substitute(parse_segments(section.title, "text"), values, warn)
        if seg_len(title):
            fill = max(0, width - seg_len(title) - 1)
            lines.append(title + [(" " + rule * fill, "text")] if fill else title)
        for item in section.items:
            if isinstance(item, Blank):
                lines.append([])
            elif isinstance(item, Field):
                val = value_of(item.value)
                if is_blank(val):
                    continue  # hide fields whose value is empty
                room = width - (2 + len(item.key) + 1 + 2 + 1)
                lines.append(_field_segments(item.key, truncate(val, room), width, True))
            elif isinstance(item, Row):
                cols = [(f.key, value_of(f.value)) for f in item.fields]
                cols = [(k, v) for k, v in cols if not is_blank(v)]
                if cols:
                    lines.append(_row_segments(cols, width))
    while lines and not lines[-1]:
        lines.pop()
    return lines


# --- SVG --------------------------------------------------------------------
FONT_FACE = """@font-face {
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}"""


def _tspans(segs: list[Segment], x: float, y: float) -> str:
    out = []
    for text, style in segs:
        if not text:
            continue
        pos = f' x="{x:g}" y="{y:g}"' if not out else ""
        cls = "" if style == "text" else f' class="{style}"'
        out.append(f"<tspan{pos}{cls}>{escape(text)}</tspan>")
    return "".join(out)


def render_svg(
    text_lines: list[list[Segment]],
    ascii_lines: list[str],
    theme: dict,
    colors: dict[str, str],
) -> str:
    fs, lh = int(theme["font_size"]), int(theme["line_height"])
    cw, pad = float(theme["char_width"]), 15
    text_cols = max(int(theme["text_columns"]), max((seg_len(l) for l in text_lines), default=0))
    ascii_cols = max((len(l) for l in ascii_lines), default=0)

    x_ascii = pad
    x_text = pad + (ascii_cols * cw + 3 * cw if ascii_cols else 0)
    rows = max(len(text_lines), len(ascii_lines))
    width = round(x_text + (text_cols + 2) * cw + pad)  # 2 chars of slack for wider fonts
    height = 2 * pad + rows * lh
    y0 = pad + fs - 1

    def block(lines: list, render: Callable, x: float, offset: int) -> list[str]:
        out = []
        for i, line in enumerate(lines):
            if line:
                out.append(render(line, x, y0 + (i + offset) * lh))
        return out

    ascii_off = (rows - len(ascii_lines)) // 2
    text_off = (rows - len(text_lines)) // 2
    ascii_svg = block(ascii_lines, lambda l, x, y: _tspans([(l, "text")], x, y), x_ascii, ascii_off)
    text_svg = block(text_lines, _tspans, x_text, text_off)

    css = "\n".join([
        FONT_FACE,
        *(f".{name} {{fill: {colors[name]};}}" for name in STYLES),
        "text, tspan {white-space: pre;}",
    ])
    font = "ConsolasFallback,Consolas,'DejaVu Sans Mono','Courier New',monospace"
    # font attributes on root *and* on each <text>: browsers inherit, but
    # simpler renderers (previewers, cairosvg) only honour the latter.
    text_attrs = f'font-family="{font}" font-size="{fs}px" fill="{colors["text"]}" xml:space="preserve"'
    parts = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="{font}" '
        f'width="{width}px" height="{height}px" font-size="{fs}px">',
        f"<style>\n{css}\n</style>",
        f'<rect width="{width}px" height="{height}px" fill="{colors["background"]}" rx="15"/>',
    ]
    if ascii_svg:
        parts.append(f"<text {text_attrs}>\n" + "\n".join(ascii_svg) + "\n</text>")
    parts.append(f"<text {text_attrs}>\n" + "\n".join(text_svg) + "\n</text>")
    parts.append("</svg>\n")
    return "\n".join(parts)
