#!/usr/bin/env python3
"""Builds the profile README's SVG assets: assets/<name>-dark.svg and -light.svg.

Usage: python tools/build_assets.py --fonts DIR --shots DIR

  --fonts  plex.ttf (IBM Plex Sans variable), mono.ttf (JetBrains Mono variable),
           plexar.ttf (IBM Plex Sans Arabic Medium). All OFL, from github.com/google/fonts.
  --shots  templix.png, split.png, idea.png: 2880x1800 captures of the live sites.

Requires fonttools, uharfbuzz and pillow.

An SVG shown through <img> cannot load web fonts, so all text is outlined into paths.
Animations never hide anything: if one fails to run, the image still shows the final design.
"""
import argparse
import base64
import io
import random
from dataclasses import dataclass
from html import escape
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "assets"


@dataclass(frozen=True)
class Theme:
    ink: str
    muted: str
    accent: str
    on_accent: str
    surface: str
    border: str
    levels: tuple[str, ...]


# Surfaces and text follow GitHub's own themes; the contribution ramps are GitHub's own.
THEMES = {
    "dark": Theme(
        ink="#f0f6fc", muted="#9198a1", accent="#56d364", on_accent="#0d1117",
        surface="#151b23", border="#3d444d",
        levels=("#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364"),
    ),
    "light": Theme(
        ink="#1f2328", muted="#59636e", accent="#116329", on_accent="#ffffff",
        surface="#f6f8fa", border="#d1d9e0",
        levels=("#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329"),
    ),
}

LETTERS = {
    "W": ["1...1", "1...1", "1...1", "1.1.1", "1.1.1", "11.11", "1...1"],
    "A": [".111.", "1...1", "1...1", "11111", "1...1", "1...1", "1...1"],
    "S": [".1111", "1....", "1....", ".111.", "....1", "....1", "1111."],
    "E": ["11111", "1....", "1....", "1111.", "1....", "1....", "11111"],
    "M": ["1...1", "11.11", "1.1.1", "1.1.1", "1...1", "1...1", "1...1"],
}
LETTER_GAP = 2
WEEKS, DAYS, PITCH, CELL = 53, 7, 24, 20
PAGE_W = WEEKS * PITCH - (PITCH - CELL)

# Half cards sit side by side at half the column each: the gutter is transparent canvas
# inside the SVGs, so their outer edges line up with the wide card at every column width.
GUTTER = 34
HALF_CANVAS_W = PAGE_W // 2
HALF_CARD_W = HALF_CANVAS_W - GUTTER // 2

# Horizontal crop of the 2880px captures: drops empty margins so the product reads larger.
CROP_LEFT, CROP_RIGHT = 240, 2640

Slot = tuple[int, int, int, int]


def num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


class Typeface:
    def __init__(self, path: Path) -> None:
        self.face = hb.Face(hb.Blob.from_file_path(str(path)))
        self.fonts: dict[int | None, hb.Font] = {}

    def _font(self, weight: int | None) -> hb.Font:
        if weight not in self.fonts:
            font = hb.Font(self.face)
            if weight:
                font.set_variations({"wght": weight})
            self.fonts[weight] = font
        return self.fonts[weight]

    def _shape(
        self, text: str, size: float, weight: int | None, tracking: float
    ) -> tuple[hb.Font, list[tuple[int, float, float]], float, float]:
        font = self._font(weight)
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(font, buf)
        scale, cursor, glyphs = size / self.face.upem, 0.0, []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            glyphs.append((info.codepoint, cursor + pos.x_offset * scale, pos.y_offset * scale))
            cursor += pos.x_advance * scale + tracking
        return font, glyphs, scale, cursor - tracking

    def width(self, text: str, size: float, weight: int | None = None, tracking: float = 0) -> float:
        return self._shape(text, size, weight, tracking)[3]

    def path(
        self,
        text: str,
        x: float,
        y: float,
        size: float,
        fill: str,
        weight: int | None = None,
        tracking: float = 0,
        anchor: str = "start",
    ) -> str:
        font, glyphs, scale, width = self._shape(text, size, weight, tracking)
        x -= {"start": 0, "middle": width / 2, "end": width}[anchor]
        pen = SVGPathPen(None, ntos=num)
        for gid, gx, gy in glyphs:
            font.draw_glyph_with_pen(gid, TransformPen(pen, (scale, 0, 0, -scale, x + gx, y - gy)))
        return f'<path fill="{fill}" d="{pen.getCommands()}"/>'


def svg(width: int, height: int, title: str, body: str, style: str = "") -> str:
    style_tag = f"<style>{style}</style>" if style else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img"><title>{escape(title)}</title>'
        f"{style_tag}{body}</svg>\n"
    )


def contribution_cells() -> dict[tuple[int, int], int]:
    """Returns {(week, day): level}: the name in bright cells, then rising activity."""
    rng = random.Random(7)
    cells: dict[tuple[int, int], int] = {}
    week = 0
    for letter in "WASEEM":
        for day, row in enumerate(LETTERS[letter]):
            for offset, bit in enumerate(row):
                if bit == "1":
                    cells[(week + offset, day)] = 3 if rng.random() < 0.18 else 4
        week += len(LETTERS[letter][0]) + LETTER_GAP
    for w in range(week, WEEKS):
        density = 0.15 + 0.6 * (w - week) / (WEEKS - week - 1)
        for day in range(DAYS):
            if rng.random() < density:
                cells[(w, day)] = rng.choices([1, 2, 3], [5, 3, 1])[0]
    cells[(WEEKS - 1, DAYS - 1)] = 4
    return cells


def hero(theme: Theme, plex: Typeface, plexar: Typeface) -> str:
    cells = contribution_cells()
    # One sweep plus two pulses, finished in under 5 seconds (WCAG 2.2.2).
    style = "".join(f".l{i}{{fill:{c}}}" for i, c in enumerate(theme.levels)) + (
        "@media (prefers-reduced-motion:no-preference){"
        ".on{animation:wave .7s ease-in-out calc(var(--w)*30ms);"
        "transform-box:fill-box;transform-origin:center}"
        "@keyframes wave{40%{opacity:.2;transform:scale(.7)}}"
        ".today{animation:pulse 1.1s ease-in-out 2.2s 2}"
        "@keyframes pulse{50%{opacity:.3}}}"
    )
    grid = []
    for w in range(WEEKS):
        rects = []
        for d in range(DAYS):
            level = cells.get((w, d), 0)
            is_today = (w, d) == (WEEKS - 1, DAYS - 1)
            state = " today" if is_today else " on" if level else ""
            rects.append(
                f'<rect class="l{level}{state}" x="{w * PITCH}" y="{d * PITCH}" '
                f'width="{CELL}" height="{CELL}" rx="4"/>'
            )
        grid.append(f'<g style="--w:{w}">{"".join(rects)}</g>')

    arabic_w = plexar.width("العربية", 26)
    body = [
        "".join(grid),
        plex.path("Full-stack React developer", 0, 250, 60, theme.ink, 600, -1.2),
        plex.path("building AI-powered web products.", 0, 322, 60, theme.muted, 400, -1.2),
        plex.path("Waseem Abu Fares", 0, 388, 26, theme.ink, 500),
        plexar.path("العربية", PAGE_W, 388, 26, theme.muted, anchor="end"),
        plex.path("English and", PAGE_W - arabic_w - 10, 388, 26, theme.muted, 400, anchor="end"),
    ]
    title = (
        "WASEEM spelled out in a GitHub contribution graph. "
        "Full-stack React developer building AI-powered web products."
    )
    return svg(PAGE_W, 404, title, "".join(body), style)


def encode_shot(path: Path, width: int, height: int) -> str:
    """Crops from the top of the page to the slot's aspect, at 2x, as a JPEG data URI."""
    image = Image.open(path).convert("RGB")
    crop_h = round((CROP_RIGHT - CROP_LEFT) * height / width)
    image = image.crop((CROP_LEFT, 0, CROP_RIGHT, crop_h)).resize((width * 2, height * 2), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=80, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def card(
    theme: Theme,
    shot: Path,
    slot: Slot,
    size: tuple[int, int],
    texts: list[str],
    title: str,
    canvas_w: int | None = None,
    offset: int = 0,
) -> str:
    x, y, w, h = slot
    width, height = size
    radius = 20
    edge = f"M{x} {y + h}V{y + 14}Q{x} {y} {x + 14} {y}H{x + w}"
    body = (
        f'<defs><clipPath id="card"><rect width="{width}" height="{height}" rx="{radius}"/></clipPath>'
        f'<clipPath id="shot"><path d="{edge}V{y + h}Z"/></clipPath></defs>'
        f'<g transform="translate({offset} 0)">'
        f'<rect width="{width}" height="{height}" rx="{radius}" fill="{theme.surface}"/>'
        f'<g clip-path="url(#card)"><image clip-path="url(#shot)" href="{encode_shot(shot, w, h)}" '
        f'x="{x}" y="{y}" width="{w}" height="{h}"/>'
        f'<path d="{edge}" fill="none" stroke="{theme.border}"/></g>'
        f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="{radius - .5}" '
        f'fill="none" stroke="{theme.border}"/>{"".join(texts)}</g>'
    )
    return svg(canvas_w or width, height, title, body)


def wide_card(
    theme: Theme, plex: Typeface, mono: Typeface, shot: Path,
    eyebrow: str, name: str, lines: list[str], title: str,
) -> str:
    texts = [
        mono.path(eyebrow, 48, 78, 20, theme.muted, 400),
        plex.path("Live demo →", 484, 78, 20, theme.accent, 500, anchor="end"),
        plex.path(name, 48, 346, 68, theme.ink, 600, -1.4),
        *[plex.path(line, 48, 408 + i * 40, 28, theme.muted, 400) for i, line in enumerate(lines)],
    ]
    return card(theme, shot, (532, 48, PAGE_W - 532, 452), (PAGE_W, 500), texts, title)


def half_card(
    theme: Theme, plex: Typeface, mono: Typeface, shot: Path,
    eyebrow: str, name: str, lines: list[str], title: str, offset: int,
) -> str:
    texts = [
        mono.path(eyebrow, 44, 66, 20, theme.muted, 400),
        plex.path("Live demo →", HALF_CARD_W - 44, 66, 20, theme.accent, 500, anchor="end"),
        plex.path(name, 44, 126, 52, theme.ink, 600, -1),
        *[plex.path(line, 44, 174 + i * 36, 26, theme.muted, 400) for i, line in enumerate(lines)],
    ]
    slot = (44, 262, HALF_CARD_W - 44, 298)
    return card(theme, shot, slot, (HALF_CARD_W, 560), texts, title, HALF_CANVAS_W, offset)


def button(theme: Theme, plex: Typeface, label: str) -> str:
    width = round(plex.width(label, 20, 600)) + 56
    body = (
        f'<rect width="{width}" height="52" rx="10" fill="{theme.accent}"/>'
        + plex.path(label, width / 2, 33, 20, theme.on_accent, 600, anchor="middle")
    )
    return svg(width, 52, label, body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts", type=Path, required=True)
    parser.add_argument("--shots", type=Path, required=True)
    args = parser.parse_args()

    plex = Typeface(args.fonts / "plex.ttf")
    mono = Typeface(args.fonts / "mono.ttf")
    plexar = Typeface(args.fonts / "plexar.ttf")
    shots = args.shots

    for mode, theme in THEMES.items():
        outputs = {
            "hero": hero(theme, plex, plexar),
            "cta": button(theme, plex, "Start a project →"),
            "templix": wide_card(
                theme, plex, mono, shots / "templix.png", "Template marketplace", "Templix",
                ["61 original website templates.", "Preview each one live, then buy."],
                "Templix, a marketplace of 61 website templates. Open the live demo.",
            ),
            "splitapp": half_card(
                theme, plex, mono, shots / "split.png", "Workout PWA", "SplitApp",
                ["Plan training splits and log every set.", "Installs like an app."],
                "SplitApp, an installable workout planner and tracker. Open the live demo.",
                offset=0,
            ),
            "ideaenhancer": half_card(
                theme, plex, mono, shots / "idea.png", "AI tool", "IDEAenhancer",
                ["Turn one scrappy line into four fully", "developed product concepts."],
                "IDEAenhancer, an AI product concept generator. Open the live demo.",
                offset=GUTTER // 2,
            ),
        }
        for name, content in outputs.items():
            target = ASSETS / f"{name}-{mode}.svg"
            target.write_text(content, encoding="utf-8", newline="\n")
            print(f"{target.name}: {target.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
